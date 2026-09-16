"""Tests for `load_observations.py`.

These cover the pure functions -- the coordinate canonicalisation, the bbox
clip, the longitude convention and the granule timestamp. Deliberately no
source files: IMERG granules are 8 MB each and ERA5 subsets are hundreds of
MB, so neither belongs in the repository, and the end-to-end check is
`--verify` against `observation_data` rather than a fixture.

What is pinned here is the set of things that were *wrong on the first run* and
would be silent if they regressed. Each one produced a table that loaded
cleanly and matched nothing.
"""
import numpy as np
import pytest

import load_observations as lo


class TestCoordinateCanonicalisation:
    """2dp, because that is the precision the stored table holds."""

    def test_float32_coordinates_round_to_the_lattice(self):
        """IMERG ships float32, where 24.05 is really 24.049999237060547.

        The first version of the loader rounded to 6dp and built 2,190,144
        rows that matched nothing, against a table whose row count was already
        exactly right -- the failure looked like missing data rather than a
        rounding choice.
        """
        assert lo._coord(np.float32(24.05)) == 24.05
        assert lo._coord(np.float32(-85.95)) == -85.95
        assert lo._coord(np.float32(36.05)) == 36.05

    def test_quarter_degree_coordinates_are_exact(self):
        """ERA5's 0.25 lattice also lands on 2dp, so one rule serves both."""
        for value in (25.0, 25.25, 36.5, 44.75, -85.0, -64.25):
            assert lo._coord(np.float32(value)) == value

    def test_the_two_native_grids_do_not_collide_at_this_precision(self):
        """0.1 and 0.25 spacing both need 2dp and neither needs more."""
        imerg = [lo._coord(24.05 + 0.1 * i) for i in range(20)]
        era5 = [lo._coord(25.0 + 0.25 * i) for i in range(20)]
        assert len(set(imerg)) == 20
        assert len(set(era5)) == 20


class TestLongitudeConvention:
    def test_era5_zero_to_360_becomes_negative(self):
        """ERA5 arrives at 275..295; the table stores -85..-65."""
        assert lo._to_negative_lon(275.0) == -85.0
        assert lo._to_negative_lon(295.0) == -65.0

    def test_already_negative_longitudes_are_left_alone(self):
        """IMERG ships -180..180 and must not be converted twice."""
        assert lo._to_negative_lon(-85.95) == -85.95
        assert lo._to_negative_lon(0.0) == 0.0
        assert lo._to_negative_lon(180.0) == 180.0


def _imerg_lattice(start, count):
    """IMERG's coordinate array: each centre computed in float64, then stored
    as float32 -- which is what the granules hold.

    Not `np.arange(start, stop, 0.1, dtype=np.float32)`. That accumulates the
    step in float32 and drifts ~2e-3 by index 1800, which is larger than
    `COORD_TOL` and made this test fail against code that is correct on real
    granules. A synthetic grid that is noisier than the real one tests the
    tolerance rather than the clip.
    """
    return np.array([start + 0.1 * i for i in range(count)], dtype=np.float32)


class TestClip:
    def test_a_bbox_on_cell_centres_keeps_those_cells(self):
        """The loaded run's hull quotes centres (24.05, 45.95), not edges.

        An exclusive comparison drops a row and a column, which is 220 -> 219
        and reads as a slightly smaller domain rather than as a bug.
        """
        lats = _imerg_lattice(-89.95, 1800)
        lons = _imerg_lattice(-179.95, 3600)
        ai, oi = lo._clip(lats, lons, (24.05, 45.95, -85.95, -64.05))
        assert ai.size == 220
        assert oi.size == 220
        assert lo._coord(lats[ai[0]]) == 24.05
        assert lo._coord(lats[ai[-1]]) == 45.95
        assert lo._coord(lons[oi[0]]) == -85.95
        assert lo._coord(lons[oi[-1]]) == -64.05

    def test_no_bbox_keeps_everything(self):
        lats = _imerg_lattice(-89.95, 1800)
        lons = _imerg_lattice(-179.95, 3600)
        ai, oi = lo._clip(lats, lons, None)
        assert ai.size == lats.size
        assert oi.size == lons.size


class TestGranuleTimestamp:
    """IMERG's epoch is 1980-01-06 and its units string ends in ` UTC`."""

    class _FakeTimeDataset:
        def __init__(self, units):
            self.attrs = {'units': units}

    def test_the_epoch_is_1980_not_unix(self):
        """1441346400 seconds past 1980-01-06 is 2025-09-08 06:00.

        Against the Unix epoch the same integer is 2015-09-04, which is a
        plausible-looking timestamp for a completely different day.
        """
        dataset = self._FakeTimeDataset(b'seconds since 1980-01-06 00:00:00 UTC')
        stamp = lo._imerg_stamp(dataset, 1441346400)
        assert stamp.year == 2025 and stamp.month == 9 and stamp.day == 8
        assert stamp.hour == 6 and stamp.minute == 0

    def test_the_utc_suffix_is_stripped(self):
        """`np.datetime64` raises on a trailing ` UTC` rather than ignoring it."""
        for units in (b'seconds since 1980-01-06 00:00:00 UTC',
                      'seconds since 1980-01-06 00:00:00',
                      b'seconds since 1980-01-06 00:00:00Z'):
            assert lo._imerg_stamp(self._FakeTimeDataset(units), 0).year == 1980

    def test_half_hourly_granules_land_on_the_half_hour(self):
        dataset = self._FakeTimeDataset(b'seconds since 1980-01-06 00:00:00 UTC')
        assert lo._imerg_stamp(dataset, 1441346400 + 1800).minute == 30


class TestTheLegacyShiftIsNotTheDefault:
    """UTC is the default; -4h only reproduces the legacy table.

    The stored IMERG timestamps are 4 hours behind the granules they hold (see
    the module docstring, where exact field matching establishes it). A loader
    that defaulted to the legacy behaviour would propagate the defect into
    every future run, silently, since nothing downstream checks.
    """

    def test_the_column_order_is_one_definition(self):
        """`precipitation` and `wind_u` are both floats, so a reordered tuple
        would COPY cleanly into the wrong columns."""
        assert lo.COLUMNS.index('precipitation') == 3
        assert lo.COLUMNS.index('wind_u') == 7
        assert lo.COLUMNS[:3] == ('obs_time', 'latitude', 'longitude')

    def test_load_defaults_away_from_the_live_table(self):
        """A first run must not be able to destroy the truth field."""
        assert lo.DEFAULT_TABLE != lo.LIVE_TABLE
        assert lo.LIVE_TABLE == 'observation_data'
