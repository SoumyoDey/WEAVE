#!/usr/bin/env python
"""Load the ensemble cyclone track CSVs into PostgreSQL.

Why this exists
---------------
`TC_TAB_DESIGN.md` step 2. The source is `output/` from
`/projects/k.aggarwal/Shuochen` on Explorer — 1,181 CSVs, 197 MB, named
`<centre>_<offset>h_<STORM>.csv`, each holding one storm forecast from one
initialisation by one centre, every ensemble member, every lead time.

`TC_DATA_ACCESS.md` is the survey this is built on. Read it before changing a
convention here; every normalisation below exists because the files were
measured and found to disagree with each other.

What this refuses to do
-----------------------
**It does not trust the filename.** The `<offset>h` in the name is wrong for
ECMWF, systematically and by a factor of two. The generating script stepped back
`T` initialisation cycles and labelled the file `T * 6` hours — right for MOGREPS
and GEFS, which run 6-hourly, and wrong for ECMWF, which runs 00Z and 12Z only.
Measured on BERYL, IDA, ETA, LAN and GONI: every ECMWF file labelled `24h` is a
**48-hour** earlier initialisation. `egrr`/LAN is 30 h rather than 24 h for a
different reason — a gap in that archive, so four cycles back landed further
than four cycles should.

So the label is recorded as `source_label_hours` and **never used as a time**.
`init_time` comes from the data, where it is unambiguous and derivable two
independent ways that this loader requires to agree (`_init_time_of`).

**It does not load a column nobody can name.** `T` is loaded — because the
survey established what it is, a count of initialisation cycles — and
`distance_km`, `mean_lat`, `mean_lon` and `dist_to_ens_mean_km` are **not**.
Those four are derived quantities whose derivation is unverified, and
`TC_TAB_DESIGN.md` §7 is explicit: recompute and compare rather than import.
Loading them would make a number true by assertion, which is how
`SCALED_EXPORT_DIVISOR_HOURS` cost days (§13, §22).

**It does not infer the ensemble size from the rows present.** A member that
forecast no cyclone has no track, so counting distinct `member_id` gives the
number that *developed* a storm, not the number that ran. ECMWF files carry
anywhere from 28 to 51. The registry records both, and `NOMINAL_MEMBERS` below
is the declared table — the same bargain `run_registry.DECLARED` strikes, and
for the same reason.

Usage
-----
    python load_cyclone_tracks.py --source /path/to/output --dry-run
    python load_cyclone_tracks.py --source /path/to/output
    python load_cyclone_tracks.py --source /path/to/output --storms BERYL,IDA
"""
import argparse
import csv
import math
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timedelta

import psycopg2
from psycopg2.extras import execute_values
from dotenv import load_dotenv

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env'))

DB_CONFIG = {
    'dbname':   os.environ.get('DB_NAME',     'weave_weather'),
    'user':     os.environ.get('DB_USER',     'k.aggarwal'),
    'password': os.environ.get('DB_PASSWORD', ''),
    'host':     os.environ.get('DB_HOST',     'localhost'),
    'port':     int(os.environ.get('DB_PORT', 5432)),
}

# ── What the centres actually are ─────────────────────────────────────────────
# `centre` is the TIGGE distribution node; `system` is the model that produced
# the forecast. They are not the same thing and the directory layout hides it:
# `kwbc/` carries NCEP's GEFS and GFS *and* Canada's CENS and CMC. `output/` was
# built from GEFS throughout — established by the member count stepping 21 -> 31
# exactly at the GEFS v12 upgrade of 2020-09-23, which a blend of two centres
# would not do. Recording both columns is what stops that distinction being lost
# the next time someone extends this (NEXT_STEPS.md §20, §24).
SYSTEM_OF_CENTRE = {
    'ecmf': 'ECMWF-ENS',
    'egrr': 'MOGREPS',
    'kwbc': 'GEFS',
}

# Declared, not measured — see the module docstring. A value here is the size of
# the ensemble that *ran*, against which members that produced no track are the
# interesting minority rather than missing data.
#
# GEFS is a function of the initialisation: v12 took it from 21 members to 31 on
# 2020-09-23, and the loaded archive straddles that date.
GEFS_V12 = datetime(2020, 9, 23)


def nominal_members(system, init_time):
    if system == 'ECMWF-ENS':
        return 51
    if system == 'MOGREPS':
        return 36
    if system == 'GEFS':
        return 31 if init_time >= GEFS_V12 else 21
    raise ValueError(f'no declared ensemble size for {system!r}; add it to '
                     f'nominal_members() rather than letting the loader guess')


# Basin labels differ by centre, and **not merely in spelling** — the three
# vocabularies have different granularity. Enumerated from every file in
# `output/`, not guessed:
#
#   ecmf   Northwest Pacific, Southwest Pacific, Northeast Pacific,
#          North Atlantic, North Indian
#   egrr   WP, SH, EP, AL, IO, CP
#   kwbc   WP, SI, EP, AL, SP, CP, BB
#
# **`egrr` writes `SH` where `kwbc` writes `SI` or `SP`.** That is not a synonym
# to map away; the Met Office files simply do not say which southern basin, and
# a lookup table that picked one would be inventing a fact. Likewise `IO`
# against `North Indian` and `BB`.
#
# So two columns. `basin_source` keeps what the file said, verbatim and always.
# `basin` is the canonical code **only where the source is precise enough to
# determine one**, and NULL where it is not. An unrecognised code is refused
# rather than passed through — the previous version of this used a dict `.get`
# with the raw value as its default, so `IO` and `SH` sailed into the database
# as if they were canonical, which is the silent-widening this project keeps
# paying for.
#
# For the one case the app currently cares about this is unambiguous: all three
# centres identify the North Atlantic distinctly.
BASIN_CANONICAL = {
    'north atlantic': 'NA', 'al': 'NA',
    'northeast pacific': 'EP', 'ep': 'EP',
    'central pacific': 'CP', 'cp': 'CP',
    'northwest pacific': 'WP', 'wp': 'WP',
    'southwest pacific': 'SP', 'sp': 'SP',
    'south indian': 'SI', 'si': 'SI',
    'north indian': 'NI', 'ni': 'NI',
    'bay of bengal': 'BB', 'bb': 'BB',
    # Genuinely ambiguous: the source is coarser than the vocabulary.
    'sh': None,          # Southern Hemisphere — SI or SP, unstated
    'io': None,          # Indian Ocean — NI or SI, unstated
}


def canonical_basin(raw):
    """(canonical_or_None, verbatim). Refuses a code nobody has declared."""
    verbatim = (raw or '').strip()
    key = verbatim.lower()
    if key not in BASIN_CANONICAL:
        raise SourceError(
            f'unknown basin {verbatim!r}. Add it to BASIN_CANONICAL — mapping '
            f'it to None if the source is coarser than the canonical code — '
            f'rather than letting an undeclared value into the database.')
    return BASIN_CANONICAL[key], verbatim

FILENAME = re.compile(r'^(?P<centre>[a-z]+)_(?P<label>\d+)h_(?P<storm>.+)\.csv$')

SCHEMA = """
CREATE TABLE IF NOT EXISTS cyclone_track_member (
    centre          TEXT      NOT NULL,
    system          TEXT      NOT NULL,
    storm_name      TEXT      NOT NULL,
    cyclone_id      TEXT      NOT NULL,
    init_time       TIMESTAMP NOT NULL,
    member_id       INTEGER   NOT NULL,
    lead_hours      INTEGER   NOT NULL,
    valid_time      TIMESTAMP NOT NULL,
    latitude        REAL      NOT NULL,
    longitude       REAL      NOT NULL,
    pressure_hpa    REAL,
    wind_ms         REAL,
    basin           TEXT,             -- canonical, NULL where the source is coarser
    basin_source    TEXT,             -- what the file actually said
    -- `cyclone_id` is part of the key because it is part of a track point's
    -- identity. Without it the constraint asserts "a member has one position
    -- per lead", which is a modelling claim nobody made: a member that tracked
    -- two candidate cyclones at one lead would have had one of them silently
    -- discarded by the ON CONFLICT below, and nothing would say so.
    --
    -- **No row in this archive exercises that.** Measured across all 1,181
    -- source files: no member ever carries more than one `cyclone_id`, at one
    -- lead or over its whole track — the id is the member's genesis label and
    -- is constant along it. So widening recovers nothing today. It is here so
    -- that an archive where that stops being true loses nothing quietly, which
    -- is the only kind of loss this project keeps being bitten by.
    --
    -- It is emphatically NOT the fix for the 525 rows that `ON CONFLICT` drops
    -- from `kwbc_0h_MATTHEW.csv`. Those are exact duplicates, identical in
    -- every field including `cyclone_id`, and they collide under this
    -- constraint too. `duplicate_rows` below is what reports them.
    CONSTRAINT uq_cyclone_track_member
        UNIQUE (centre, storm_name, init_time, member_id, lead_hours, cyclone_id)
);
CREATE INDEX IF NOT EXISTS cyclone_track_storm
    ON cyclone_track_member (storm_name, centre, init_time);

CREATE TABLE IF NOT EXISTS cyclone_best_track (
    storm_name      TEXT      NOT NULL,
    valid_time      TIMESTAMP NOT NULL,
    latitude        REAL,
    longitude       REAL,
    nature          TEXT,
    wmo_pressure    REAL,
    wmo_wind        REAL,
    dist_to_land_km REAL,
    landfall_km     REAL,
    storm_speed     REAL,
    storm_dir       REAL,
    CONSTRAINT uq_cyclone_best_track UNIQUE (storm_name, valid_time)
);

CREATE TABLE IF NOT EXISTS cyclone_run_registry (
    centre              TEXT      NOT NULL,
    system              TEXT      NOT NULL,
    storm_name          TEXT      NOT NULL,
    init_time           TIMESTAMP NOT NULL,
    basin               TEXT,
    basin_source        TEXT,
    -- Distinct genesis positions the members identified. ECMWF reports one for
    -- ALCIDE; MOGREPS reports eighteen. That disagreement is a result.
    genesis_variants    INTEGER,
    -- Members carried forward from an earlier cycle. MOGREPS is time-lagged:
    -- its 36-member 12Z ensemble is 18 members from 12Z plus 18 from 06Z. Those
    -- 18 are six hours older at the same valid time, so a skill comparison that
    -- treats all 36 as equally fresh is comparing two things.
    lagged_members      INTEGER   DEFAULT 0,
    -- What ran, and what produced a track. The gap is the point: see §5.
    nominal_members     INTEGER   NOT NULL,
    tracked_members     INTEGER   NOT NULL,
    lead_min            INTEGER,
    lead_max            INTEGER,
    -- The filename's claim, kept because it is what the file is called, and
    -- never used as a duration: it is wrong by 2x for ECMWF. See the docstring.
    source_label_hours  INTEGER,
    source_cycles       INTEGER,          -- the `T` column: initialisation cycles back
    source_generation   TEXT,
    loaded_at           TIMESTAMP DEFAULT now(),
    CONSTRAINT uq_cyclone_run_registry UNIQUE (centre, storm_name, init_time)
);
"""


class SourceError(Exception):
    """The files disagree with themselves. Refused rather than reconciled."""


def _f(value):
    """A float, or None for the blanks IBTrACS leaves everywhere."""
    value = (value or '').strip()
    if value in ('', 'NaN', 'nan'):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _normalise_longitude(lon):
    """Signed ±180.

    The *forecast* column is signed — measured across the whole archive, which
    runs -180.000 to 180.000 exactly, not sampled. (An earlier version of this
    docstring cited BERYL alone, at −94.0 to −42.9 in the North Atlantic, which
    cannot reach the dateline and so could not have shown otherwise.)

    **The observed `LON` column is a different matter and is not signed.** It
    reaches 253.6, with 41,159 values above 180 across 85 files — every one a
    storm near the dateline. Both columns pass through here, so the caller
    counts them separately: a conversion on the forecast is a warning, one on
    the observation is a Tuesday. The raw CXML archives each use a *different* convention
    (`TC_DATA_ACCESS.md`), so a 0–360 value arriving here is a real possibility
    rather than a theoretical one, and it would mean the upstream processing
    changed.

    **This converts, and the conversion is unconditionally correct**, which an
    earlier version of this docstring denied by calling it "a guard rather than
    a conversion". It is worth being exact about why it is safe, because the
    reasoning is less obvious than it looks: the two conventions *agree* on
    [0, 180] — 50 means 50°E in both — and differ only above 180, where
    subtracting 360 is exactly right. So there is no input for which guessing
    wrong is possible.

    The cost of that is the thing the old docstring wanted: a convention change
    is **invisible** here. Eastern-hemisphere storms would pass through
    identical, western ones would be silently corrected, and nothing would say
    the upstream had moved. Hence `converted` — the count is reported at load
    time, so a sudden non-zero is a signal rather than a shrug. Only a value
    outside both conventions is refused, because that is the only value this
    function cannot interpret.
    """
    if lon is None:
        return None, False
    if -180.0 <= lon <= 180.0:
        return lon, False
    if 180.0 < lon <= 360.0:
        return lon - 360.0, True
    raise SourceError(f'longitude {lon} is outside any convention this '
                      f'loader recognises')


def _check_latitude(lat):
    """Latitude, guarded.

    Separate from the longitude guard on purpose. In the raw CXML, latitude
    carries `units="deg S"` on an *already signed* value, and applying both the
    sign and the unit flips the hemisphere — a storm in the Coral Sea drawn off
    Japan. `output/` has the sign already applied and the unit dropped, so this
    only has to catch the case where that stops being true.
    """
    if lat is None:
        return None
    if -90.0 <= lat <= 90.0:
        return lat
    raise SourceError(f'latitude {lat} is out of range; if a hemisphere unit '
                      f'has been applied twice this is where it shows')


def _init_time_of(rows, path):
    """The initialisation, derived two ways, which must agree.

    1. `valid_time - lead_hours` on every row.
    2. The `cyclone_id` prefix, which is the CXML disturbance ID and begins
       `YYYYMMDDHH`.

    Requiring both is not belt-and-braces. The AIFS wind stored at 2025-09-08
    was the 2025-09-16 run, and the file's own `time` variable said so in every
    one of those files — nothing read it (§18, §20). Here there are two
    independent statements of the same fact in every row, so checking costs
    nothing and refuses exactly that class of defect.
    """
    from_rows = {r['valid_time'] - timedelta(hours=r['lead_hours']) for r in rows}
    if len(from_rows) != 1:
        raise SourceError(f'{os.path.basename(path)}: valid_time - lead_time is '
                          f'not constant; got {sorted(from_rows)[:3]}')
    init = from_rows.pop()

    # `cyclone_id` is `<cycle><genesis lat><genesis lon>`. **The genesis part
    # varies by member**, because members disagree about where the storm formed:
    # ALCIDE at 0 h has one id from ECMWF, five from GEFS and eighteen from
    # MOGREPS. An earlier version required a single id per file and refused
    # every MOGREPS file.
    #
    # The *cycle* part normally varies too — but not always, and the exception
    # is real rather than corrupt. `egrr_72h_GITA.csv` carries 18 members
    # stamped 2018021206 and 18 stamped 2018021212, because **MOGREPS is a
    # time-lagged ensemble**: its 36-member 12Z ensemble is 18 members from the
    # 12Z cycle plus 18 carried forward from 06Z. The stamp records where a
    # member *came from*; it is not a second initialisation.
    #
    # Requiring the stamp to be constant refused that file — 1 of 1,181, and
    # the only one of 432 MOGREPS files with two stamps. The check was right to
    # fire (the assumption behind it was wrong) and wrong to refuse, which is
    # why it is now the weaker but meaningful condition below.
    #
    # **A member may come from an earlier cycle, never a later one.** A stamp
    # after the init is not lagging, it is the two statements of the
    # initialisation genuinely disagreeing — the §18/§20 defect, where the AIFS
    # wind stored at 2025-09-08 was the 2025-09-16 run and every file said so
    # with nobody reading it. That still refuses.
    lagged = 0
    for stamp in {r['cyclone_id'].split('_', 1)[0] for r in rows}:
        if not (len(stamp) == 10 and stamp.isdigit()):
            continue
        from_id = datetime.strptime(stamp, '%Y%m%d%H')
        if from_id > init:
            raise SourceError(
                f'{os.path.basename(path)}: cyclone_id says this member comes '
                f'from {from_id}, after the initialisation the rows imply '
                f'({init}). A time-lagged member comes from an EARLIER cycle; '
                f'a later one means the two statements disagree.')
        if from_id < init:
            lagged += sum(1 for r in rows
                          if r['cyclone_id'].startswith(stamp + '_'))

    # How many distinct genesis positions the members found. Not bookkeeping:
    # it is a spread measure in its own right, and one the ensemble mean hides.
    return init, len({r['cyclone_id'] for r in rows}), lagged


def generation_of(source):
    """Which generation of the product a directory holds.

    Recorded rather than assumed, because **the generations are scored against
    different best tracks** and mixing them is silent. `output/` was verified
    against the 2026-04-27 IBTrACS download and the April `storm_2016_2024_*`
    set against the 2025-09-17 one; the two disagree for 24 of 138 storms,
    because IBTrACS revises past storms retrospectively (`TC_DATA_ACCESS.md`
    §9). A run from one generation and an observation from the other produce a
    track error that is wrong by whatever the revision moved, with nothing
    downstream able to tell.

    This used to be the literal string `'output'` on every row, which was true
    only for as long as nobody pointed `--source` anywhere else.
    """
    return os.path.basename(os.path.normpath(source)) or 'unknown'


def refuse_mixed_generation(conn, generation):
    """Stop a load that would put two IBTrACS vintages in one table.

    The in-load best-track check catches two files that disagree *in the same
    invocation*. It cannot catch loading `output/` today and the April set
    tomorrow: each is internally consistent, the upserts do not collide, and
    the result is a table where some storms are scored against one vintage and
    some against another. That is `NEXT_STEPS.md` §24's defect exactly — a
    database quietly holding something other than what it claims — so it is
    refused here rather than documented and hoped about.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('cyclone_run_registry')")
        if cur.fetchone()[0] is None:
            return
        cur.execute('SELECT DISTINCT source_generation FROM cyclone_run_registry '
                    'WHERE source_generation IS NOT NULL')
        present = {row[0] for row in cur.fetchall()}
    other = present - {generation}
    if other:
        raise SourceError(
            f'the registry already holds generation(s) {sorted(other)} and this '
            f'load is {generation!r}. These generations are scored against '
            f'different IBTrACS vintages (24 of 138 storms differ), so track '
            f'error computed across them would be wrong by the revision. Load '
            f'one generation, or clear the cyclone tables first.')


def widen_track_constraint(conn):
    """Bring an existing `cyclone_track_member` up to the widened key.

    `CREATE TABLE IF NOT EXISTS` does nothing to a table that already exists,
    so a database loaded before 2026-10-02 keeps the narrow constraint and the
    DDL above silently does not apply to it. That gap — schema source says one
    thing, deployed database says another, nothing compares them — is how
    `NEXT_STEPS.md` §24 happened, so this closes it rather than leaving a note.

    Idempotent, and safe to run on a fresh database: it looks at what is
    actually there rather than at what it expects. Widening a unique constraint
    can never fail on existing rows — every set distinct under the narrow key
    is still distinct under a superset of it — so there is no "this might not
    apply" case to handle.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('cyclone_track_member')")
        if cur.fetchone()[0] is None:
            return 'no table yet'
        cur.execute("""SELECT pg_get_constraintdef(oid) FROM pg_constraint
                       WHERE conrelid = 'cyclone_track_member'::regclass
                         AND conname = 'uq_cyclone_track_member'""")
        row = cur.fetchone()
        if row and 'cyclone_id' in row[0]:
            return 'already widened'
        cur.execute('ALTER TABLE cyclone_track_member '
                    'DROP CONSTRAINT IF EXISTS uq_cyclone_track_member')
        cur.execute('ALTER TABLE cyclone_track_member '
                    'ADD CONSTRAINT uq_cyclone_track_member UNIQUE '
                    '(centre, storm_name, init_time, member_id, lead_hours, '
                    'cyclone_id)')
    conn.commit()
    return 'widened'


def ensure_registry_columns(conn):
    """Add registry columns a pre-existing database does not have yet.

    Same gap as `widen_track_constraint` and the same reason: the DDL above
    describes a fresh table, and a database built from an earlier version of it
    never sees the change. `ADD COLUMN IF NOT EXISTS` is idempotent and cheap \u2014
    a nullable column with a default is a catalogue change in PostgreSQL 11+,
    not a table rewrite, so this stays fast at any size.
    """
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('cyclone_run_registry')")
        if cur.fetchone()[0] is None:
            return 'no table yet'
        cur.execute('ALTER TABLE cyclone_run_registry '
                    'ADD COLUMN IF NOT EXISTS lagged_members INTEGER DEFAULT 0')
    conn.commit()
    return 'registry columns present'


def read_file(path, generation=None):
    """One CSV -> (registry row, track rows, best-track rows). Refuses on doubt."""
    name = os.path.basename(path)
    match = FILENAME.match(name)
    if not match:
        raise SourceError(f'{name}: not <centre>_<label>h_<STORM>.csv')
    centre = match.group('centre')
    # Split from the LEFT on the fixed prefix, never on '_': KYAAR_KYARR carries
    # an underscore inside the storm name and splitting on it loses half.
    storm = match.group('storm')
    if centre not in SYSTEM_OF_CENTRE:
        raise SourceError(f'{name}: unknown centre {centre!r}; add it to '
                          f'SYSTEM_OF_CENTRE rather than guessing its system')
    system = SYSTEM_OF_CENTRE[centre]

    tracks, best, positionless, converted = [], {}, 0, 0
    # (member, lead, cyclone_id) -> the row already seen for it, so an
    # exact repeat can be told apart from a genuine second candidate.
    first_seen, duplicates, contradictions = {}, 0, []
    converted_obs = 0
    with open(path, newline='') as fh:
        for row in csv.DictReader(fh):
            valid = datetime.strptime(row['time'].strip(), '%Y-%m-%d %H:%M:%S')
            lead = int(float(row['lead_time']))
            # A point with only one coordinate is not a position. Six rows in
            # 994,161 are like this, both files EMERAUDE — dropped rather than
            # stored as a NULL that every consumer would then have to guard, and
            # counted so the drop is reported rather than silent.
            if _f(row['lat']) is None or _f(row['lon']) is None:
                positionless += 1
                continue
            lon, lon_converted = _normalise_longitude(_f(row['lon']))
            obs_lon, obs_converted = _normalise_longitude(_f(row['LON']))
            converted += int(lon_converted)         # forecast: never seen
            converted_obs += int(obs_converted)      # observed: 85 files, normal
            key = (int(float(row['member_id'])), lead, row['cyclone_id'].strip())
            position = (_f(row['lat']), lon)
            if key in first_seen:
                if first_seen[key] == position:
                    # Byte-identical repeat. Counted and reported, never stored:
                    # it carries no information and `ON CONFLICT DO NOTHING`
                    # would drop it anyway, silently, which is the part that
                    # cost a day.
                    duplicates += 1
                else:
                    # The same member, lead and cyclone at two *different*
                    # places. Not a duplicate and not reconcilable here.
                    contradictions.append((key, first_seen[key], position))
                continue
            first_seen[key] = position
            tracks.append({
                'member_id':    int(float(row['member_id'])),
                'cyclone_id':   row['cyclone_id'].strip(),
                'basin':        canonical_basin(row['basin'])[0],
                'basin_source': canonical_basin(row['basin'])[1],
                'valid_time':   valid,
                'lead_hours':   lead,
                'latitude':     _check_latitude(_f(row['lat'])),
                'longitude':    lon,
                'pressure_hpa': _f(row['pressure_hPa']),
                'wind_ms':      _f(row['wind_mps']),
                'cycles':       int(float(row['T'])) if row.get('T') else None,
            })
            # The best track is repeated on every member row — 51x redundant,
            # and it makes an observation look like a property of a forecast.
            # Collapsed here, and disagreements are refused rather than
            # last-write-wins: two products built against different IBTrACS
            # vintages would show up exactly here (TC_DATA_ACCESS.md §9).
            obs = (
                _f(row['LAT']), obs_lon,
                row['NATURE'].strip() or None, _f(row['WMO_PRES']),
                _f(row['WMO_WIND']), _f(row['DIST2LAND']), _f(row['LANDFALL']),
                _f(row['STORM_SPEED']), _f(row['STORM_DIR']),
            )
            if valid in best and best[valid] != obs:
                raise SourceError(
                    f'{name}: the best track disagrees with itself at {valid}. '
                    f'Two IBTrACS vintages in one file, or a join that is not '
                    f'one-to-one — either way, not something to average over.')
            best[valid] = obs

    if contradictions:
        k, a, b = contradictions[0]
        raise SourceError(
            f'{name}: {len(contradictions)} row(s) place the same member, lead '
            f'and cyclone at two different positions, first {k} at {a} and {b}. '
            f'A duplicate would be identical; this is a contradiction, and '
            f'picking one of the two would be inventing a track.')

    if not tracks:
        raise SourceError(f'{name}: no rows')

    init, genesis_variants, lagged_rows = _init_time_of(tracks, path)
    members = {t['member_id'] for t in tracks}
    declared = nominal_members(system, init)
    if max(members) >= declared:
        raise SourceError(
            f'{name}: member_id {max(members)} with only {declared} declared '
            f'for {system} at {init}. The declaration in nominal_members() is '
            f'wrong — fix it there, do not widen it here.')

    cycles = {t['cycles'] for t in tracks}
    registry = {
        'centre': centre, 'system': system, 'storm_name': storm,
        'init_time': init, 'genesis_variants': genesis_variants,
        'basin': tracks[0]['basin'],
        'basin_source': tracks[0]['basin_source'],
        'nominal_members': declared,
        'tracked_members': len(members),
        'lead_min': min(t['lead_hours'] for t in tracks),
        'lead_max': max(t['lead_hours'] for t in tracks),
        'source_label_hours': int(match.group('label')),
        'source_cycles': cycles.pop() if len(cycles) == 1 else None,
        'source_generation': generation or generation_of(os.path.dirname(path)),
        'positionless_rows': positionless,
        'converted_longitudes': converted,
        'converted_obs_longitudes': converted_obs,
        'duplicate_rows': duplicates,
        # Rows belonging to members carried forward from an earlier cycle.
        # Non-zero only for MOGREPS GITA in this archive, and worth carrying
        # because those members are genuinely older at the same valid time.
        'lagged_rows': lagged_rows,
        'lagged_members': len({t['member_id'] for t in tracks
                               if datetime.strptime(
                                   t['cyclone_id'].split('_', 1)[0],
                                   '%Y%m%d%H') < init})
                          if lagged_rows else 0,
    }
    return registry, tracks, best


def load(conn, source, storms=None, dry_run=False, skip_bad=False):
    paths = sorted(
        os.path.join(source, f) for f in os.listdir(source)
        if f.endswith('.csv') and FILENAME.match(f)
        and (storms is None or FILENAME.match(f).group('storm') in storms))
    if not paths:
        raise SourceError(f'{source}: no files matching '
                          f'<centre>_<label>h_<STORM>.csv')

    generation = generation_of(source)
    # Checked before any reading, so a load that cannot be committed does not
    # first spend four minutes parsing a thousand files.
    if conn is not None and not dry_run:
        refuse_mixed_generation(conn, generation)
        print(f'  constraint       {widen_track_constraint(conn)}')
        print(f'  registry         {ensure_registry_columns(conn)}')

    all_tracks, all_registry, best_by_storm = [], [], defaultdict(dict)
    short, conflicts, skipped = [], [], []
    for path in paths:
        try:
            registry, tracks, best = read_file(path, generation=generation)
        except SourceError as e:
            # Without --skip-bad a single contradiction stops the load, which is
            # the right default: a partial ingest nobody was told about is how
            # §24's "fixed" runs stayed broken. With it, every skip is named and
            # counted at the end — loudly, never silently.
            if not skip_bad:
                raise
            skipped.append((os.path.basename(path), str(e)))
            continue
        all_registry.append(registry)
        for t in tracks:
            all_tracks.append((
                registry['centre'], registry['system'], registry['storm_name'],
                t['cyclone_id'], registry['init_time'], t['member_id'],
                t['lead_hours'], t['valid_time'], t['latitude'], t['longitude'],
                t['pressure_hpa'], t['wind_ms'], t['basin'], t['basin_source'],
            ))
        if registry['tracked_members'] < registry['nominal_members']:
            short.append(registry)
        # Across files, the same storm's best track must agree. This is the
        # cross-product check the per-file one cannot make.
        store = best_by_storm[registry['storm_name']]
        for valid, obs in best.items():
            if valid in store and store[valid] != obs:
                conflicts.append((registry['storm_name'], valid))
            store[valid] = obs

    if conflicts:
        raise SourceError(
            f'{len(conflicts)} best-track disagreements across files, first '
            f'{conflicts[:3]}. Different products scored against different '
            f'IBTrACS vintages is the cause — confirmed 2026-10-02, the two '
            f'generations differ for 24 of 138 storms — and it is not '
            f'reconcilable here. Load one generation.')

    best_rows = [(storm, valid, *obs)
                 for storm, store in best_by_storm.items()
                 for valid, obs in sorted(store.items())]

    print(f'  generation       {generation}')
    print(f'  files            {len(paths):,}')
    print(f'  track rows       {len(all_tracks):,}')
    print(f'  best-track rows  {len(best_rows):,}')
    print(f'  runs             {len(all_registry):,}')
    print(f'  runs where some members produced no track: {len(short):,} '
          f'of {len(all_registry):,}')
    if short:
        worst = min(short, key=lambda r: r['tracked_members'] / r['nominal_members'])
        print(f"    fewest: {worst['storm_name']} {worst['centre']} "
              f"{worst['tracked_members']}/{worst['nominal_members']} members — "
              f"the other {worst['nominal_members'] - worst['tracked_members']} "
              f"forecast no cyclone, which is a result, not a gap")

    dropped = sum(r['positionless_rows'] for r in all_registry)
    if dropped:
        where = sorted({r['storm_name'] for r in all_registry
                        if r['positionless_rows']})
        print(f'  dropped {dropped} row(s) with only one coordinate, in: '
              f'{", ".join(where)}')

    # Exact repeats. Reported rather than shrugged off: these used to vanish
    # into ON CONFLICT DO NOTHING, and the only trace was that count(*) came
    # back 525 lower than the load said. A doubled source file should name
    # itself at load time, not two months later in a deployment document.
    duplicated = sum(r['duplicate_rows'] for r in all_registry)
    if duplicated:
        worst = sorted(((r['duplicate_rows'], r['storm_name'], r['centre'])
                        for r in all_registry if r['duplicate_rows']),
                       reverse=True)
        print(f'  {duplicated:,} byte-identical duplicate row(s) ignored, in '
              f'{len(worst)} run(s):')
        for n, storm, centre in worst[:5]:
            print(f'    {centre} {storm}: {n:,}')
        print('    these carry no information and were never stored; a run '
              'with many is a sign the generating script emitted it twice')

    # Time-lagged members, which are genuinely older at the same valid time.
    lagged = [r for r in all_registry if r['lagged_members']]
    if lagged:
        print(f'  {len(lagged)} run(s) include time-lagged members carried '
              f'forward from an earlier cycle:')
        for r in lagged:
            print(f"    {r['centre']} {r['storm_name']} {r['init_time']}: "
                  f"{r['lagged_members']} of {r['tracked_members']} members")
        print('    these are older forecasts at the same valid time, which is '
              'what a time-lagged ensemble is, not a defect')

    # **The two longitude columns do not share a convention**, which is worth
    # being exact about because the first version of this message was not.
    #
    # The *forecast* `lon` is signed ±180 in every one of the 1,181 files —
    # measured across the whole archive, which runs -180.000 to 180.000 exactly.
    # So a conversion there means the upstream processing changed, and that
    # deserves a warning.
    #
    # The *observed* `LON`, which is IBTrACS, does not share it: it reaches
    # **253.6**, with 41,159 values above 180 across 85 files, every one a storm
    # near or across the dateline. Normal, and always has been.
    #
    # The first version said `output/` was "signed throughout" and would have
    # fired on all 85, sending someone to hunt a change that never happened.
    # That claim came from measuring BERYL — in the Atlantic, which cannot reach
    # the dateline. The same one-case generalisation as the two longitude
    # retractions in `TC_DATA_ACCESS.md`, for the third time.
    converted = sum(r['converted_longitudes'] for r in all_registry)
    if converted:
        print(f'  WARNING {converted:,} *forecast* longitude(s) arrived in '
              f'0-360 form and were converted. That column is signed ±180 in '
              f'every file of this archive, so the upstream processing has '
              f'changed — the values are right, but check what else moved '
              f'with the convention.')
    converted_obs = sum(r['converted_obs_longitudes'] for r in all_registry)
    if converted_obs:
        print(f'  {converted_obs:,} observed (IBTrACS) longitude(s) converted '
              f'from 0-360 — expected near the dateline, not a problem')

    if skipped:
        print(f'\n  SKIPPED {len(skipped)} file(s) — loaded data is incomplete '
              f'and these are why:')
        for name, why in skipped:
            print(f'    {name}: {why}')

    if dry_run:
        print('\n  --dry-run: nothing written')
        return 0

    with conn.cursor() as cur:
        cur.execute(SCHEMA)
        execute_values(cur, """
            INSERT INTO cyclone_track_member
                (centre, system, storm_name, cyclone_id, init_time, member_id,
                 lead_hours, valid_time, latitude, longitude, pressure_hpa,
                 wind_ms, basin, basin_source) VALUES %s
            ON CONFLICT ON CONSTRAINT uq_cyclone_track_member DO NOTHING
        """, all_tracks, page_size=5000)
        execute_values(cur, """
            INSERT INTO cyclone_best_track
                (storm_name, valid_time, latitude, longitude, nature,
                 wmo_pressure, wmo_wind, dist_to_land_km, landfall_km,
                 storm_speed, storm_dir) VALUES %s
            ON CONFLICT ON CONSTRAINT uq_cyclone_best_track DO NOTHING
        """, best_rows, page_size=5000)
        execute_values(cur, """
            INSERT INTO cyclone_run_registry
                (centre, system, storm_name, init_time, basin, basin_source,
                 genesis_variants, nominal_members, tracked_members, lead_min, lead_max,
                 source_label_hours, source_cycles, source_generation,
                 lagged_members) VALUES %s
            ON CONFLICT ON CONSTRAINT uq_cyclone_run_registry DO UPDATE SET
                tracked_members = EXCLUDED.tracked_members,
                lead_min = EXCLUDED.lead_min, lead_max = EXCLUDED.lead_max,
                loaded_at = now()
        """, [tuple(r[k] for k in (
                'centre', 'system', 'storm_name', 'init_time',
                'basin', 'basin_source', 'genesis_variants', 'nominal_members', 'tracked_members', 'lead_min',
                'lead_max', 'source_label_hours', 'source_cycles',
                'source_generation', 'lagged_members')) for r in all_registry])
    conn.commit()
    print('\n  committed')
    return len(all_tracks)


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--source', required=True,
                    help="directory of <centre>_<label>h_<STORM>.csv files")
    ap.add_argument('--storms', help='comma-separated storm names, for a subset')
    ap.add_argument('--dry-run', action='store_true',
                    help='read, validate and report; write nothing')
    ap.add_argument('--skip-bad', action='store_true',
                    help='skip files that contradict themselves, naming each; '
                         'without this one contradiction stops the whole load')
    args = ap.parse_args()

    if not os.path.isdir(args.source):
        sys.exit(f'not a directory: {args.source}')
    storms = set(s.strip() for s in args.storms.split(',')) if args.storms else None

    conn = None if args.dry_run else psycopg2.connect(**DB_CONFIG)
    try:
        load(conn, args.source, storms=storms, dry_run=args.dry_run,
             skip_bad=args.skip_bad)
    except SourceError as e:
        # Refused, not crashed: the message names the file and the contradiction
        # so it can be checked against the source rather than guessed at.
        sys.exit(f'refusing to load: {e}')
    finally:
        if conn is not None:
            conn.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
