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
    CONSTRAINT uq_cyclone_track_member
        UNIQUE (centre, storm_name, init_time, member_id, lead_hours)
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

    `output/` is already signed — measured, BERYL runs −94.0 to −42.9 in the
    North Atlantic. The raw CXML archives each use a *different* convention
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

    # `cyclone_id` is `<init><genesis lat><genesis lon>`, and only the init part
    # is a property of the file. **The genesis part varies by member**, because
    # members disagree about where the storm formed: ALCIDE at 0 h has one id
    # from ECMWF, five from GEFS and eighteen from MOGREPS. An earlier version
    # of this function required a single id per file and refused every MOGREPS
    # file — correctly, in that the assumption was wrong, which is the whole
    # argument for checking rather than assuming.
    stamps = {r['cyclone_id'].split('_', 1)[0] for r in rows}
    if len(stamps) != 1:
        raise SourceError(f'{os.path.basename(path)}: cyclone_id carries more '
                          f'than one initialisation: {sorted(stamps)}')
    stamp = stamps.pop()
    if len(stamp) == 10 and stamp.isdigit():
        from_id = datetime.strptime(stamp, '%Y%m%d%H')
        if from_id != init:
            raise SourceError(
                f'{os.path.basename(path)}: the two statements of the '
                f'initialisation disagree — rows say {init}, cyclone_id '
                f'says {from_id}')
    # How many distinct genesis positions the members found. Not bookkeeping:
    # it is a spread measure in its own right, and one the ensemble mean hides.
    return init, len({r['cyclone_id'] for r in rows})


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
            converted += int(lon_converted) + int(obs_converted)
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

    if not tracks:
        raise SourceError(f'{name}: no rows')

    init, genesis_variants = _init_time_of(tracks, path)
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

    # Expected to be zero for `output/`, which is signed throughout. A non-zero
    # here is the only sign that the upstream processing changed convention —
    # the conversion itself is correct either way, so nothing else would show
    # it. See `_normalise_longitude`.
    converted = sum(r['converted_longitudes'] for r in all_registry)
    if converted:
        print(f'  NOTE {converted:,} longitude(s) arrived in 0-360 form and '
              f'were converted. `output/` is signed throughout, so this means '
              f'the upstream processing changed — the values are right, but '
              f'check what else moved with the convention.')

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
                 source_label_hours, source_cycles, source_generation) VALUES %s
            ON CONFLICT ON CONSTRAINT uq_cyclone_run_registry DO UPDATE SET
                tracked_members = EXCLUDED.tracked_members,
                lead_min = EXCLUDED.lead_min, lead_max = EXCLUDED.lead_max,
                loaded_at = now()
        """, [tuple(r[k] for k in (
                'centre', 'system', 'storm_name', 'init_time',
                'basin', 'basin_source', 'genesis_variants', 'nominal_members', 'tracked_members', 'lead_min',
                'lead_max', 'source_label_hours', 'source_cycles',
                'source_generation')) for r in all_registry])
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
