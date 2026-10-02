#!/usr/bin/env python
"""The cyclone loader's refusals.

`load_cyclone_tracks.py` is almost entirely refusals, and until now had no tests
at all. That is the wrong way round: an ingest script's value is precisely that
it stops when the files contradict themselves, and an untested refusal is
indistinguishable from no refusal until the day it matters. `NEXT_STEPS.md` §24
is what that day looks like — a database holding something other than what it
claimed, with three commits' worth of "fixed" sitting on top.

Every case here is a file the loader **must not** accept, written as a real CSV
in a temp directory. No database, no HPC, no fixtures: these run anywhere, which
is the point, because the mistakes they guard against were all found by reading
cluster files nobody else can open.

The one positive test is deliberate — a refusal suite that never accepts
anything would pass with `raise SourceError` as the whole function body.
"""
import csv
import os

import pytest

import load_cyclone_tracks as loader
from load_cyclone_tracks import SourceError


COLUMNS = [
    'member_id', 'cyclone_id', 'basin', 'time', 'lead_time', 'lat', 'lon',
    'pressure_hPa', 'wind_mps', 'T',
    'LAT', 'LON', 'NATURE', 'WMO_PRES', 'WMO_WIND', 'DIST2LAND', 'LANDFALL',
    'STORM_SPEED', 'STORM_DIR',
]


def _row(member, lead, valid, lat=15.0, lon=-50.0, basin='AL',
         cyclone_id='2019W_0', obs_lat=15.1, obs_lon=-50.1, nature='TS'):
    return {
        'member_id': member, 'cyclone_id': cyclone_id, 'basin': basin,
        'time': valid, 'lead_time': lead, 'lat': lat, 'lon': lon,
        'pressure_hPa': 990.0, 'wind_mps': 30.0, 'T': 0,
        'LAT': obs_lat, 'LON': obs_lon, 'NATURE': nature, 'WMO_PRES': 985.0,
        'WMO_WIND': 55.0, 'DIST2LAND': 400.0, 'LANDFALL': 400.0,
        'STORM_SPEED': 10.0, 'STORM_DIR': 290.0,
    }


def write(tmp_path, name, rows, subdir='output'):
    directory = tmp_path / subdir
    directory.mkdir(exist_ok=True)
    path = directory / name
    with open(path, 'w', newline='') as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow(r)
    return str(path)


def a_good_file(tmp_path, name='kwbc_120h_BERYL.csv', subdir='output'):
    """Two members, three leads, one initialisation. Accepted."""
    rows = []
    for member in (0, 1):
        for lead, valid in ((0, '2024-07-01 00:00:00'),
                            (6, '2024-07-01 06:00:00'),
                            (12, '2024-07-01 12:00:00')):
            rows.append(_row(member, lead, valid, lat=15.0 + lead / 6,
                             lon=-50.0 - lead / 6))
    return write(tmp_path, name, rows, subdir=subdir)


class TestTheGenerationIsRecordedNotAssumed:
    """`source_generation` was the literal string 'output' on every row.

    True only while nobody pointed `--source` anywhere else — and the April
    `storm_2016_2024_*` generation is sitting right beside it on the cluster,
    scored against a *different* IBTrACS vintage (`TC_DATA_ACCESS.md` §9). A
    mislabelled row is worse than an unlabelled one: it is the evidence someone
    would later use to decide the two were safe to mix.
    """

    def test_it_comes_from_the_directory(self, tmp_path):
        path = a_good_file(tmp_path, subdir='storm_2016_2024_0h')
        registry, _tracks, _best = loader.read_file(path)
        assert registry['source_generation'] == 'storm_2016_2024_0h'

    def test_the_already_loaded_generation_still_reads_as_output(self, tmp_path):
        # The 1,180 runs in the database carry 'output'. If this changed, a
        # re-load would collide with its own previous load.
        registry, _t, _b = loader.read_file(a_good_file(tmp_path))
        assert registry['source_generation'] == 'output'

    def test_a_trailing_slash_does_not_become_the_generation(self):
        assert loader.generation_of('/projects/x/output/') == 'output'
        assert loader.generation_of('/projects/x/output') == 'output'

    def test_an_explicit_generation_wins(self, tmp_path):
        registry, _t, _b = loader.read_file(a_good_file(tmp_path),
                                            generation='april')
        assert registry['source_generation'] == 'april'


class TestMixingGenerationsIsRefused:
    """The cross-*load* check, which the in-load best-track check cannot make.

    Loading `output/` today and the April set tomorrow produces two internally
    consistent loads whose upserts never collide, and a table where some storms
    are scored against the 2026-04-27 best track and some against the
    2025-09-17 one. 24 of 138 storms differ between those vintages, so a track
    error computed across them is wrong by whatever the revision moved.
    """

    class _Cursor:
        def __init__(self, present, table='cyclone_run_registry'):
            self._present, self._table, self._result = present, table, None

        def execute(self, sql, *_args):
            if 'to_regclass' in sql:
                self._result = [(self._table,)]
            else:
                self._result = [(g,) for g in self._present]

        def fetchone(self):
            return self._result[0]

        def fetchall(self):
            return self._result

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    class _Conn:
        def __init__(self, cursor):
            self._cursor = cursor

        def cursor(self):
            return self._cursor

    def test_a_different_generation_present_refuses(self):
        conn = self._Conn(self._Cursor({'storm_2016_2024_0h'}))
        with pytest.raises(SourceError) as e:
            loader.refuse_mixed_generation(conn, 'output')
        assert 'storm_2016_2024_0h' in str(e.value)
        assert 'IBTrACS' in str(e.value)

    def test_the_same_generation_again_is_fine(self):
        conn = self._Conn(self._Cursor({'output'}))
        loader.refuse_mixed_generation(conn, 'output')   # a re-load must work

    def test_an_empty_registry_is_fine(self):
        conn = self._Conn(self._Cursor(set()))
        loader.refuse_mixed_generation(conn, 'output')

    def test_no_table_yet_is_fine(self):
        # First load of all: the schema has not been created.
        conn = self._Conn(self._Cursor(set(), table=None))
        loader.refuse_mixed_generation(conn, 'output')

    def test_it_runs_before_the_files_are_read(self, tmp_path):
        """A load that cannot commit must not first parse a thousand files."""
        a_good_file(tmp_path)
        conn = self._Conn(self._Cursor({'storm_2016_2024_0h'}))
        with pytest.raises(SourceError, match='IBTrACS'):
            loader.load(conn, str(tmp_path / 'output'))


class TestTheBestTrackMustAgreeWithItself:
    """Two IBTrACS vintages in one file, caught where they first appear.

    The best track is repeated on every member row. Collapsing it with
    last-write-wins would silently keep whichever row came last.
    """

    def test_disagreeing_observations_at_one_valid_time_refuse(self, tmp_path):
        rows = [_row(0, 0, '2024-07-01 00:00:00', obs_lat=15.1),
                _row(1, 0, '2024-07-01 00:00:00', obs_lat=15.4)]
        path = write(tmp_path, 'kwbc_120h_BERYL.csv', rows)
        with pytest.raises(SourceError, match='disagrees with itself'):
            loader.read_file(path)

    def test_agreeing_observations_collapse_to_one(self, tmp_path):
        registry, _tracks, best = loader.read_file(a_good_file(tmp_path))
        assert len(best) == 3           # three valid times, not six member-rows
        assert registry['tracked_members'] == 2


class TestTheDeclaredEnsembleSizeIsNotWidenedToFit:
    """`nominal_members` is the denominator of every strike probability.

    A member id above the declaration means the declaration is wrong, and the
    tempting fix — take the observed maximum instead — would make the
    denominator a property of whichever members happened to develop a storm.
    That is the export-divisor defect (§13, §22) rebuilt in a new table.
    """

    def test_a_member_id_above_the_declaration_refuses(self, tmp_path):
        rows = [_row(m, 0, '2024-07-01 00:00:00') for m in (0, 31)]
        path = write(tmp_path, 'kwbc_120h_BERYL.csv', rows)
        with pytest.raises(SourceError, match='member_id 31'):
            loader.read_file(path)

    def test_gefs_switches_at_the_v12_upgrade(self):
        from datetime import datetime
        assert loader.nominal_members('GEFS', datetime(2020, 9, 22)) == 21
        assert loader.nominal_members('GEFS', datetime(2020, 9, 23)) == 31

    def test_an_undeclared_system_refuses(self):
        from datetime import datetime
        with pytest.raises(ValueError, match='no declared ensemble size'):
            loader.nominal_members('ICON-EPS', datetime(2024, 7, 1))


class TestBasinsAreRefusedRatherThanPassedThrough:
    """An earlier version used `dict.get(raw, raw)`.

    So `IO` and `SH` entered the database as though they were canonical codes.
    The Met Office files genuinely do not say *which* southern basin; a lookup
    that picked one would be inventing a fact, so these map to None with the
    raw label kept beside them.
    """

    def test_an_ambiguous_code_is_null_and_keeps_its_source(self):
        assert loader.canonical_basin('SH') == (None, 'SH')
        assert loader.canonical_basin('IO') == (None, 'IO')

    def test_an_unknown_code_refuses(self):
        with pytest.raises(SourceError):
            loader.canonical_basin('ZZ')

    def test_a_precise_code_resolves_to_the_canonical_name(self):
        # `AL` is the file's label; `NA` is this application's canonical code.
        # Both are kept, because the first is what the file said.
        assert loader.canonical_basin('AL') == ('NA', 'AL')


class TestFilenamesAndCentres:
    def test_a_storm_name_containing_an_underscore_survives(self, tmp_path):
        # KYAAR_KYARR is why the split is from the left on a fixed prefix.
        path = a_good_file(tmp_path, name='kwbc_120h_KYAAR_KYARR.csv')
        registry, _t, _b = loader.read_file(path)
        assert registry['storm_name'] == 'KYAAR_KYARR'

    def test_an_unknown_centre_refuses(self, tmp_path):
        path = a_good_file(tmp_path, name='rjtd_120h_BERYL.csv')
        with pytest.raises(SourceError, match='unknown centre'):
            loader.read_file(path)

    def test_the_label_hours_are_recorded_but_not_used_as_a_duration(self, tmp_path):
        """The filename's claim is kept verbatim and never believed.

        `ecmf_72h_*` files run to +144 h: the label is the init *cadence*, not
        the forecast length, and reading it as a duration is wrong by 2x.
        """
        path = a_good_file(tmp_path, name='kwbc_120h_BERYL.csv')
        registry, _t, _b = loader.read_file(path)
        assert registry['source_label_hours'] == 120
        assert registry['lead_max'] == 12          # what the rows actually say


class TestPositionlessRowsAreDroppedAndCounted:
    """Six rows of 994,161, both files EMERAUDE.

    Stored as NULL they would become a guard in every consumer; dropped
    silently they would be a hole nobody could find.
    """

    def test_a_row_with_no_longitude_is_not_a_position(self, tmp_path):
        rows = [_row(0, 0, '2024-07-01 00:00:00'),
                _row(0, 6, '2024-07-01 06:00:00', lon='')]
        path = write(tmp_path, 'kwbc_120h_EMERAUDE.csv', rows)
        registry, tracks, _b = loader.read_file(path)
        assert len(tracks) == 1
        assert registry['positionless_rows'] == 1


class TestLongitudeConversionIsCorrectAndCounted:
    """`output/` is signed ±180 — measured, not assumed.

    The raw CXML archives each use a *different* convention, so a 0–360 value
    arriving here is possible and would mean the upstream processing changed.

    Writing these tests is what showed the docstring and the code disagreed:
    it claimed to be "a guard rather than a conversion" while converting. The
    conversion turns out to be unconditionally correct — the conventions agree
    below 180 and differ only above it — so the fix was to the docstring, plus
    a count, because a correct silent conversion still hides the fact that the
    upstream moved.
    """

    def test_a_0_to_360_longitude_is_converted_correctly(self, tmp_path):
        rows = [_row(0, 0, '2024-07-01 00:00:00', lon=310.0)]
        path = write(tmp_path, 'kwbc_120h_BERYL.csv', rows)
        _registry, tracks, _b = loader.read_file(path)
        assert tracks[0]['longitude'] == -50.0     # 310°E is 50°W

    def test_the_conversion_is_counted_so_it_is_not_silent(self, tmp_path):
        rows = [_row(0, 0, '2024-07-01 00:00:00', lon=310.0, obs_lon=309.0)]
        path = write(tmp_path, 'kwbc_120h_BERYL.csv', rows)
        registry, _t, _b = loader.read_file(path)
        assert registry['converted_longitudes'] == 2   # forecast and observed

    def test_signed_input_is_not_counted(self, tmp_path):
        registry, tracks, _b = loader.read_file(a_good_file(tmp_path))
        assert tracks[0]['longitude'] == -50.0
        assert registry['converted_longitudes'] == 0

    def test_the_two_conventions_agree_below_180_so_nothing_is_guessed(self):
        """Why the conversion cannot be wrong: there is no ambiguous input."""
        for lon in (0.0, 50.0, 120.0, 180.0):
            assert loader._normalise_longitude(lon) == (lon, False)

    def test_a_value_outside_both_conventions_refuses(self, tmp_path):
        rows = [_row(0, 0, '2024-07-01 00:00:00', lon=400.0)]
        path = write(tmp_path, 'kwbc_120h_BERYL.csv', rows)
        with pytest.raises(SourceError, match='outside any convention'):
            loader.read_file(path)


class TestAGoodFileIsActuallyAccepted:
    """Without this, `raise SourceError` would pass every test above."""

    def test_the_registry_row_describes_the_file(self, tmp_path):
        from datetime import datetime
        registry, tracks, best = loader.read_file(a_good_file(tmp_path))
        assert registry['centre'] == 'kwbc'
        assert registry['system'] == 'GEFS'
        assert registry['storm_name'] == 'BERYL'
        assert registry['init_time'] == datetime(2024, 7, 1, 0, 0)
        assert registry['nominal_members'] == 31     # declared, not observed
        assert registry['tracked_members'] == 2      # observed, and lower
        assert registry['lead_min'] == 0 and registry['lead_max'] == 12
        assert len(tracks) == 6 and len(best) == 3

    def test_the_two_member_counts_are_kept_apart(self, tmp_path):
        """The whole denominator argument in one assertion."""
        registry, _t, _b = loader.read_file(a_good_file(tmp_path))
        assert registry['tracked_members'] < registry['nominal_members']
