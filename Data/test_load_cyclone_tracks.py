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

    def test_forecast_and_observed_conversions_are_counted_apart(self, tmp_path):
        """They do not share a convention, so one count would hide the signal.

        The forecast column is signed +-180 in all 1,181 files; the observed
        IBTrACS column reaches 253.6 in 85 of them. Counted together, the 85
        dateline storms would drown a forecast conversion, which is the only
        one that means anything has gone wrong.
        """
        rows = [_row(0, 0, '2024-07-01 00:00:00', lon=310.0, obs_lon=309.0)]
        path = write(tmp_path, 'kwbc_120h_BERYL.csv', rows)
        registry, _t, _b = loader.read_file(path)
        assert registry['converted_longitudes'] == 1       # forecast
        assert registry['converted_obs_longitudes'] == 1   # observed

    def test_an_observed_conversion_alone_does_not_flag_the_forecast(self, tmp_path):
        # The normal dateline case: 85 real files look like this.
        rows = [_row(0, 0, '2024-07-01 00:00:00', lon=179.0, obs_lon=185.0)]
        path = write(tmp_path, 'kwbc_120h_GITA.csv', rows)
        registry, tracks, _b = loader.read_file(path)
        assert registry['converted_longitudes'] == 0
        assert registry['converted_obs_longitudes'] == 1
        assert tracks[0]['longitude'] == 179.0

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


class TestExactDuplicatesAreCountedNotSwallowed:
    """525 rows used to disappear into `ON CONFLICT DO NOTHING`.

    They were all in one file, `kwbc_0h_MATTHEW.csv`, which holds 1,050 rows
    that are 525 records each written twice — identical in every field,
    `cyclone_id` included. Nothing reported them. The only symptom was that
    `count(*)` came back 525 lower than the load had said, and that was noticed
    two months later while writing a deployment document.

    Dropping them is right; dropping them silently is not. A doubled source
    file should name itself at load time.
    """

    def test_an_identical_repeat_is_counted_and_not_stored(self, tmp_path):
        row = _row(0, 0, '2024-07-01 00:00:00')
        path = write(tmp_path, 'kwbc_120h_MATTHEW.csv', [row, dict(row)])
        registry, tracks, _b = loader.read_file(path)
        assert len(tracks) == 1
        assert registry['duplicate_rows'] == 1

    def test_a_clean_file_reports_none(self, tmp_path):
        registry, _t, _b = loader.read_file(a_good_file(tmp_path))
        assert registry['duplicate_rows'] == 0

    def test_the_whole_file_doubled_keeps_exactly_half(self, tmp_path):
        """The shape of the real defect, in miniature."""
        rows = [_row(m, lead, f'2024-07-01 {lead:02d}:00:00')
                for m in (0, 1) for lead in (0, 6)]
        path = write(tmp_path, 'kwbc_120h_MATTHEW.csv', rows + [dict(r) for r in rows])
        registry, tracks, _b = loader.read_file(path)
        assert len(tracks) == len(rows)
        assert registry['duplicate_rows'] == len(rows)


class TestTwoPositionsForOneCandidateAreRefused:
    """A repeat that is *not* identical is a contradiction, not a duplicate.

    The same member, lead and cyclone cannot be in two places. Picking one
    would be inventing a track, and averaging them would invent a different
    one — so the file is refused and names what it disagreed about.
    """

    def test_the_same_key_at_two_positions_refuses(self, tmp_path):
        rows = [_row(0, 0, '2024-07-01 00:00:00', lat=15.0),
                _row(0, 0, '2024-07-01 00:00:00', lat=25.0)]
        path = write(tmp_path, 'kwbc_120h_BERYL.csv', rows)
        with pytest.raises(SourceError, match='two different positions'):
            loader.read_file(path)

    def test_two_candidates_at_one_lead_are_kept_not_refused(self, tmp_path):
        """Different `cyclone_id` is the case the widened constraint admits.

        This is the whole reason the key gained `cyclone_id`: before, the
        second row collided and was dropped with nothing said. It must now
        survive the loader — choosing between the two is the views' job.
        """
        # Both ids must carry the same init stamp: the genesis part of a
        # cyclone_id varies by member, the init part does not, and the loader
        # refuses a file where it does.
        a, b = '2024070100_150N_0500W', '2024070100_250N_0500W'
        rows = [_row(0, 0, '2024-07-01 00:00:00', lat=15.0, cyclone_id=a),
                _row(0, 0, '2024-07-01 00:00:00', lat=25.0, cyclone_id=b)]
        path = write(tmp_path, 'kwbc_120h_BERYL.csv', rows)
        registry, tracks, _b = loader.read_file(path)
        assert len(tracks) == 2
        assert {t['cyclone_id'] for t in tracks} == {a, b}
        assert registry['duplicate_rows'] == 0


class TestTheConstraintMigration:
    """`CREATE TABLE IF NOT EXISTS` does nothing to a table that exists.

    So a database loaded before 2026-10-02 keeps the narrow key while the DDL
    in this file says otherwise — schema source and deployed database quietly
    disagreeing, which is the shape of §24.
    """

    class _Cursor:
        def __init__(self, table, constraint):
            self._table, self._constraint, self._r = table, constraint, None
            self.executed = []

        def execute(self, sql, *_a):
            self.executed.append(sql)
            if 'to_regclass' in sql:
                self._r = [(self._table,)]
            elif 'pg_get_constraintdef' in sql:
                self._r = [(self._constraint,)] if self._constraint else []
            else:
                self._r = []

        def fetchone(self):
            return self._r[0] if self._r else None

        def __enter__(self):
            return self

        def __exit__(self, *_e):
            return False

    class _Conn:
        def __init__(self, cur):
            self._cur = cur
            self.commits = 0

        def cursor(self):
            return self._cur

        def commit(self):
            self.commits += 1

    def test_a_narrow_constraint_is_widened(self):
        cur = self._Cursor('cyclone_track_member',
                           'UNIQUE (centre, storm_name, init_time, member_id, lead_hours)')
        conn = self._Conn(cur)
        assert loader.widen_track_constraint(conn) == 'widened'
        added = [s for s in cur.executed if 'ADD CONSTRAINT' in s]
        assert len(added) == 1 and 'cyclone_id' in added[0]
        assert conn.commits == 1

    def test_an_already_wide_constraint_is_left_alone(self):
        cur = self._Cursor(
            'cyclone_track_member',
            'UNIQUE (centre, storm_name, init_time, member_id, lead_hours, cyclone_id)')
        conn = self._Conn(cur)
        assert loader.widen_track_constraint(conn) == 'already widened'
        assert not [s for s in cur.executed if 'ALTER TABLE' in s]
        assert conn.commits == 0

    def test_no_table_yet_is_not_an_error(self):
        conn = self._Conn(self._Cursor(None, None))
        assert loader.widen_track_constraint(conn) == 'no table yet'


class TestTimeLaggedMembers:
    """`egrr_72h_GITA.csv` — the one file of 1,181 the loader used to refuse.

    MOGREPS is a **time-lagged ensemble**: its 36-member 12Z ensemble is 18
    members from the 12Z cycle plus 18 carried forward from 06Z. The tracker
    stamps each member's `cyclone_id` with the cycle it came from, so that file
    carries two stamps where every other file carries one.

    The old rule — "the cyclone_id stamp must be constant" — refused it. The
    rule was not arbitrary: two independent statements of the initialisation
    guard the §18/§20 defect, where AIFS wind stored at 2025-09-08 was the
    2025-09-16 run and every file said so with nobody reading it. But constancy
    was the wrong form of the check, and it cost a whole file.

    Measured before changing it: all 36 members agree that `valid - lead` is
    2018-02-12 12:00, and 431 of the 432 MOGREPS files carry a single stamp.
    So the file is internally coherent on a 12Z basis and the stamp is
    provenance, not a second initialisation.

    The rule now is **causal**: a member may come from an earlier cycle, never
    a later one.

    The loader does **not** count the lagged members. It did briefly, and the
    count was removed: only 1 of the 432 MOGREPS files discloses a lag, so a
    zero meant "this file did not say" rather than "not lagged", and a field
    that reads as a measurement but is really a disclosure quirk is worse than
    no field. What matters is that the file loads and that a stamp from the
    future still refuses.
    """

    def _lagged_file(self, tmp_path, lag_stamp='2024063018', init_stamp='2024070100'):
        rows = []
        for member, stamp in ((0, init_stamp), (1, lag_stamp)):
            for lead, valid in ((0, '2024-07-01 00:00:00'),
                                (6, '2024-07-01 06:00:00')):
                rows.append(_row(member, lead, valid,
                                 cyclone_id=f'{stamp}_150N_0500W'))
        return write(tmp_path, 'egrr_72h_GITA.csv', rows)

    def test_a_member_from_an_earlier_cycle_is_accepted(self, tmp_path):
        from datetime import datetime
        registry, tracks, _b = loader.read_file(self._lagged_file(tmp_path))
        assert len(tracks) == 4
        # The init is what the rows say, not what either stamp says.
        assert registry['init_time'] == datetime(2024, 7, 1, 0, 0)

    def test_a_member_from_a_LATER_cycle_still_refuses(self, tmp_path):
        """The check that matters, and the reason this is not just a relaxation.

        A stamp after the init is not lagging — it is the two statements of the
        initialisation genuinely disagreeing, which is the defect the original
        rule existed to catch. Keeping that while admitting GITA is the whole
        point of the change.
        """
        path = self._lagged_file(tmp_path, lag_stamp='2024070112')
        with pytest.raises(SourceError, match='after the initialisation'):
            loader.read_file(path)

    def test_the_rows_still_have_to_agree_with_themselves(self, tmp_path):
        # Relaxing the stamp rule must not relax this one: valid - lead is the
        # statement the init is actually taken from.
        rows = [_row(0, 0, '2024-07-01 00:00:00'),
                _row(0, 6, '2024-07-01 18:00:00')]       # implies a later init
        path = write(tmp_path, 'egrr_72h_GITA.csv', rows)
        with pytest.raises(SourceError, match='not constant'):
            loader.read_file(path)
