"""The target grid `regrid_members.py` interpolates onto.

Every scored endpoint reads cells that this grid defined, so a change to it moves
numbers everywhere at once and moves them silently — an interpolation onto the
wrong cells produces a full, plausible map. These tests pin the grid itself, and
pin the property that made the old version fragile: it is a constant, not a
query. Deriving it from a table meant the coordinates depended on which rows
happened to be in that table at the time.

No database and no PostgreSQL: that is the point of the change under test.
"""
import inspect

import numpy as np
import pytest

import regrid_members as rm


class TestTheGridConstant:
    """41x41 at 0.5 degrees over 25..45 N, -85..-65 W."""

    def test_the_grid_has_the_shape_the_stored_data_has(self):
        lats, lons = rm.target_grid()
        assert (len(lats), len(lons)) == (41, 41)

    def test_the_endpoints_are_included_and_exact(self):
        # arange's stop is exclusive, so an endpoint is exactly where a grid
        # definition goes wrong: 45.0 must be a cell, not one step past the end.
        lats, lons = rm.target_grid()
        assert (lats[0], lats[-1]) == (25.0, 45.0)
        assert (lons[0], lons[-1]) == (-85.0, -65.0)

    def test_every_cell_is_exactly_on_the_half_degree(self):
        # Exact equality on purpose. 0.5 is a binary fraction, so the stored
        # coordinates are reproducible bit-for-bit and any drift here would mean
        # a query for latitude = 35.5 stops matching its own row.
        for axis in rm.target_grid():
            assert list(np.diff(axis)) == [0.5] * (len(axis) - 1)
            assert [v for v in axis if v * 2 != round(v * 2)] == []

    def test_the_resolution_constant_is_the_spacing_actually_produced(self):
        lats, _ = rm.target_grid()
        assert lats[1] - lats[0] == rm.TARGET_RESOLUTION


class TestTheGridIsNotRead:
    """The regression guard. The bug was the source, not the values."""

    def test_target_grid_takes_no_cursor(self):
        # It used to take one and run two SELECTs against `regridded_forecast`,
        # which nothing in this repository writes — so the script could not run
        # at all on a fresh database. If a parameter comes back, so has that.
        assert list(inspect.signature(rm.target_grid).parameters) == []

    def test_the_module_no_longer_queries_the_superseded_table(self):
        # `regridded_forecast` is documented as droppable on the grounds that
        # nothing reads it. This module was the last reader; keep it that way.
        source = inspect.getsource(rm)
        statements = [
            line for line in source.splitlines()
            if 'FROM regridded_forecast ' in line or 'FROM regridded_forecast"' in line
        ]
        assert statements == [], f'still reading the superseded table: {statements}'


class FakeCursor:
    """Answers the two query shapes `verify_grid` issues, and nothing else."""

    def __init__(self, tables):
        self._tables = tables          # {table: {column: [values]}}
        self._result = None

    def execute(self, sql, params=None):
        if 'to_regclass' in sql:
            self._result = [(params[0] in self._tables,)]
            return
        table = sql.split(' FROM ')[1].split()[0]
        column = sql.split('DISTINCT ')[1].split()[0]
        self._result = [(v,) for v in sorted(self._tables[table][column])]

    def fetchone(self):
        return self._result[0]

    def fetchall(self):
        return self._result


class TestVerifyGrid:
    """What makes dropping `regridded_forecast` safe rather than hopeful."""

    def test_it_accepts_coordinates_that_are_on_the_grid(self, capsys):
        lats, lons = rm.target_grid()
        cur = FakeCursor({'regridded_forecast_ens': {
            'latitude':  [float(v) for v in lats],
            'longitude': [float(v) for v in lons],
        }})
        rm.verify_grid(cur, lats, lons)
        assert '41 of 41 cells' in capsys.readouterr().out

    def test_it_accepts_a_subset_because_a_native_hull_can_be_narrower(self, capsys):
        # UKMO's native grid does not reach the domain edge, so its rows cover
        # 39x39 of the 41x41. That is correct data, not a mismatch.
        lats, lons = rm.target_grid()
        cur = FakeCursor({'regridded_forecast_ens': {
            'latitude':  [float(v) for v in lats[1:-1]],
            'longitude': [float(v) for v in lons[1:-1]],
        }})
        rm.verify_grid(cur, lats, lons)
        assert '39 of 41 cells' in capsys.readouterr().out

    def test_it_rejects_a_coordinate_that_is_off_the_grid(self):
        # The failure it exists for: the constant and the stored data disagreeing,
        # which would mean the drop silently redefines every scored cell.
        lats, lons = rm.target_grid()
        cur = FakeCursor({'regridded_forecast_ens': {
            'latitude':  [35.1562] + [float(v) for v in lats],
            'longitude': [float(v) for v in lons],
        }})
        with pytest.raises(AssertionError, match=r'35\.1562'):
            rm.verify_grid(cur, lats, lons)

    def test_an_absent_table_is_skipped_not_failed(self, capsys):
        # Runnable on a partly built database, which is the state this whole
        # change exists to support.
        lats, lons = rm.target_grid()
        rm.verify_grid(FakeCursor({}), lats, lons)
        out = capsys.readouterr().out
        assert out.count('absent, skipped') == 3

    def test_an_empty_table_is_skipped_not_failed(self, capsys):
        lats, lons = rm.target_grid()
        cur = FakeCursor({'regridded_forecast': {'latitude': [], 'longitude': []}})
        rm.verify_grid(cur, lats, lons)
        out = capsys.readouterr().out
        assert out.count('empty, skipped') == 2
