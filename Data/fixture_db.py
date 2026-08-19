"""A small real PostgreSQL database for the endpoint tests.

`test_metrics.py` covers the science as pure functions and `test_endpoints.py`
covers the request/response contract against a fake cursor. Neither touches SQL.
That is the gap this module fills: every correctness fix in METRICS_AUDIT.md was
found by hand-querying the database, and findings 12, 16 and 17 were invisible to
a green test suite. A fake cursor cannot catch a wrong JOIN, a wrong `%s` order,
an `obs_time BETWEEN` that misses the edge of the record, or a `GROUP BY` that
silently pools two runs — because it never runs the query.

So this builds a throwaway database, loads the real schema, and seeds it with a
field whose true answer is known by construction.

Run it standalone to get an inspectable copy:

    python fixture_db.py            # build (drops any previous copy first)
    python fixture_db.py --drop     # remove it
    psql -d weave_fixture_test

── The design ────────────────────────────────────────────────────────────────

One 5x5 patch of the 0.5 degree analysis grid, one initialisation (2025-09-08
00Z, the real one), three models, two variables.

**Two levels of grid, as in the real database.** The regridded tables — and so
every score — are on the shared 0.5 degree analysis grid. The pre-regrid tables
are on each model's own native grid: AIFS 0.25 degrees, GEFS 0.5, UKMO
0.1875 x 0.28125 and aligned to neither. See NATIVE_GRIDS; the numbers are
measured from the loaded run, not invented.

That difference is load-bearing. A 0.25 degree snap key can only collapse two
cells if two cells are closer together than the key, so while every table sat on
one clean grid the fixture could not see a collapse at all — which is exactly how
NEXT_STEPS.md defect 6 escaped it, and audit finding 3 and the cross-model join
bug lived in the same place. It also gives the nearest-cell choice in
/api/point-timeseries more than one candidate, so that `min()` is finally
exercised.

**Every model is given the same true field, expressed in its own storage
convention.** AIFS gets a running total since init, GEFS gets 3 h and 6 h buckets
pre-divided by a flat 3 h, UKMO gets a native hourly rate. So all three must
produce *identical* scores. Any regression in the unit or window layer breaks
exactly one model and the parity test says which — which is the failure mode the
audit spent most of its time on, and the one a fake cursor cannot reproduce
because the fake never applies the conversion to real rows.

The storage conventions are restated here from the documented convention rather
than imported from `metrics.py`, deliberately: seeding with the code under test
would let a wrong divisor cancel itself out and the test would still pass.

Precipitation, by latitude band, chosen so the contingency table has all three
outcomes at a threshold of 9 mm/6h (a rate of 1.5 mm/h):

    band 35.0, 35.5, 37.0  forecast 3.0   observed 2.0   both exceed  -> hit
    band 36.0              forecast 3.0   observed 0.5   fcst only    -> false alarm
    band 36.5              forecast 0.5   observed 2.0   obs only     -> miss

Piecewise constant over those bands, so a native cell takes the value of the
analysis cell it falls in (`precip_scene`). That is what lets the two grid levels
above disagree about resolution without introducing a second truth: a constant
field regrids to itself whatever the grids.

Flat in lead time, and every cell carries the same 0.25 mm/h ensemble spread —
including the dry ones, so no cell drops out of a spread-dependent metric for a
reason the test did not intend.

Wind is uniform in space and varies in lead time instead: forecast speed is
always 5.0 m/s (u=3, v=4) while the observed speed decays from 4.0 m/s at init by
1/6 m/s per hour, and the forecast spread grows on exactly the same schedule. So
spread == error at every lead time and the spread-skill correlation is exactly
+1 — a signed anchor, which a constant field cannot give.

Observations stop at +12 h on purpose. The loaded run's real observations end at
+19.5 h, and "the forecast outruns the truth" is a live behaviour of this API
(NEXT_STEPS item 4), so the fixture reproduces it: forecast records exist out to
+36 h and everything past +12 h must go unscored rather than be scored against a
partially observed window.

── What the endpoints must therefore report ──────────────────────────────────

Precipitation, over the whole patch, for each of the three models (25 cells x the
two scored lead times +6 h and +12 h = 50 samples):

    bias  = (15*(3-2) + 5*(3-0.5) + 5*(0.5-2)) / 25 = (15 + 12.5 - 7.5) / 25 = 0.8
    mae   = (15*1 + 5*2.5 + 5*1.5) / 25             = 35 / 25              = 1.4
    rmse  = sqrt((15*1 + 5*6.25 + 5*2.25) / 25)     = sqrt(57.5 / 25)      = 1.51658
    csi   = 15 / (15 + 5 + 5) = 0.6     pod = 15/20 = 0.75     far = 5/20 = 0.25

Wind, over the whole patch (25 cells x five scored lead times 0, 3, 6, 9, 12 h):

    per-hour error = 1, 1.5, 2, 2.5, 3 m/s
    bias  = mean = 2.0        mae = 2.0        rmse = sqrt(4.5) = 2.12132
"""
import math
import os
import sys
from datetime import datetime, timedelta

import psycopg2
from psycopg2.extras import execute_values

HERE = os.path.dirname(os.path.abspath(__file__))

# Named so it cannot be confused with the real database, and guarded below.
FIXTURE_DB_NAME = os.environ.get('WEAVE_FIXTURE_DB', 'weave_fixture_test')
PROTECTED_DB_NAMES = {'weave_weather', 'postgres', 'template0', 'template1'}


def db_config(dbname=None):
    """Connection settings for the fixture database.

    Deliberately re-read from the environment rather than imported from
    flask_api, so building the fixture does not import the module under test
    (and does not need Cartopy).
    """
    return {
        'dbname':   dbname or FIXTURE_DB_NAME,
        'user':     os.environ.get('DB_USER',     os.environ.get('USER', '')),
        'password': os.environ.get('DB_PASSWORD', ''),
        'host':     os.environ.get('DB_HOST',     'localhost'),
        'port':     int(os.environ.get('DB_PORT', 5432)),
    }


# ── The field ─────────────────────────────────────────────────────────────────

INIT_TIME = datetime(2025, 9, 8, 0, 0, 0)
MODELS    = ('AIFS', 'GEFS', 'UKMO')

LATS = (35.0, 35.5, 36.0, 36.5, 37.0)
LONS = (-76.0, -75.5, -75.0, -74.5, -74.0)

# ── The grids ─────────────────────────────────────────────────────────────────
# LATS x LONS above is the shared 0.5 degree ANALYSIS grid. Every regridded table
# is on it, so every score is on it, which is what makes the three models
# comparable at all.
#
# The pre-regrid tables are NOT. Each model was ingested on its own native grid,
# measured from the loaded run over 35-37 N / 76-74 W:
#
#   AIFS  0.25 x 0.25       from 35.0,       -76.0        aligned (every 2nd cell)
#   GEFS  0.5  x 0.5        from 35.0,       -76.0        aligned (identical)
#   UKMO  0.1875 x 0.28125  from 35.15625,   -75.796875   NOT aligned to either
#
# The fixture used to put every table on the analysis grid, which made a whole
# class of bug invisible: there was nothing for two cells to collapse *onto*. On
# UKMO's real grid a 0.25 degree snap sends 35.15625 and 35.34375 — different
# cells — to the same key, which is how 110 native cells became 77 keys and one
# cell's value ended up reported at another's coordinates (NEXT_STEPS.md defect
# 6). Latitude collapses because 0.1875 < 0.25; longitude does not because
# 0.28125 > 0.25. Both are reproduced here.
NATIVE_GRIDS = {
    'AIFS': {'d_lat': 0.25,   'd_lon': 0.25,    'lat0': 35.0,     'lon0': -76.0},
    'GEFS': {'d_lat': 0.5,    'd_lon': 0.5,     'lat0': 35.0,     'lon0': -76.0},
    'UKMO': {'d_lat': 0.1875, 'd_lon': 0.28125, 'lat0': 35.15625, 'lon0': -75.796875},
}

# (model, variable) pairs whose loader wrote coordinates through a
# six-significant-digit text conversion. UKMO's wind rows did and its
# precipitation rows did not, so in `ensemble_statistics` the same physical cell
# is 35.1562 for wind and 35.15625 for precipitation. Nothing joins across
# variables today, so nothing is broken — but such a join would match zero rows,
# silently, and the fixture should be able to show that.
COORD_6SIG_VARIABLES = {('UKMO', 'wind_u_10m'), ('UKMO', 'wind_v_10m')}


def _axis(start, step, limit):
    """Grid coordinates from `start` in `step`s, up to `limit` inclusive.

    Indexed rather than accumulated, so the 40th cell is not `start + 40` rounding
    errors — the coordinates have to survive an equality join.
    """
    n = int(math.floor((limit - start) / step + 1e-9)) + 1
    return [round(start + i * step, 8) for i in range(max(0, n))]


def native_cells(model, variable='precipitation'):
    """(lats, lons) of one model's native grid inside the fixture's box."""
    g = NATIVE_GRIDS[model]
    lats = _axis(g['lat0'], g['d_lat'], max(LATS))
    lons = _axis(g['lon0'], g['d_lon'], max(LONS))
    if (model, variable) in COORD_6SIG_VARIABLES:
        lats = [float(f'{v:.6g}') for v in lats]
        lons = [float(f'{v:.6g}') for v in lons]
    return lats, lons


def n_native_cells(model, variable='precipitation'):
    lats, lons = native_cells(model, variable)
    return len(lats) * len(lons)


def analysis_cell(lat):
    """The 0.5 degree analysis cell a native latitude belongs to."""
    return min(LATS, key=lambda c: abs(c - lat))


# Analysis cell -> (forecast rate mm/h, observed rate mm/h, outcome at 1.5 mm/h).
# The field is piecewise constant over these bands, which is what lets the native
# and regridded tables disagree about RESOLUTION while agreeing about the field: a
# constant field regrids to itself whatever the grids, so no second truth is
# introduced. It also makes nearest-cell selection observable, because the value
# changes across a band boundary.
PRECIP_BANDS = {
    35.0: (3.0, 2.0, 'hit'),
    35.5: (3.0, 2.0, 'hit'),
    36.0: (3.0, 0.5, 'false_alarm'),
    36.5: (0.5, 2.0, 'miss'),
    37.0: (3.0, 2.0, 'hit'),
}


def precip_scene(lat):
    """(forecast rate, observed rate, outcome) at any latitude, native or not."""
    return PRECIP_BANDS[analysis_cell(lat)]
PRECIP_SPREAD = 0.25          # mm/h, every cell, every model, every lead time

# The native aggregate table (`ensemble_statistics`) is seeded with a spread this
# many times the true ensemble spread — the member values stay exact.
#
# That is not an arbitrary trick. METRICS_AUDIT.md finding 11 established that the
# stored aggregate std_dev is the spread of the pooled (member x native-cell)
# population, so it carries within-cell spatial variance that is not ensemble
# spread at all (~23% high on the loaded run). Seeding it deliberately wrong, by
# an unmistakable factor, is what lets a test tell WHICH table an endpoint read —
# which the fixture could not do while the two agreed.
NATIVE_SPREAD_INFLATION = 2.0

WIND_U, WIND_V = 3.0, 4.0     # -> forecast speed exactly 5.0 m/s
WIND_SPEED     = 5.0


def wind_spread(hour):
    """Forecast spread in m/s. Grows so that spread == error at every hour."""
    return 1.0 + hour / 6.0


def wind_obs_speed(hour):
    """Observed speed in m/s, decaying away from the forecast at 1/6 per hour."""
    return WIND_SPEED - wind_spread(hour)


# Four members, offset symmetrically so the mean is exact and the population
# spread is exactly the declared spread: std([-s, -s, +s, +s]) == s.
MEMBER_OFFSETS = (-1.0, -1.0, 1.0, 1.0)

# The observation record stops here. Forecast records run to PRECIP_HOUR_MAX, so
# everything beyond this must go unscored.
OBS_HOUR_MAX     = 12
PRECIP_HOUR_MAX  = 36
WIND_HOUR_MAX    = 18

# Native output cadence, restated from the documented convention (see the module
# docstring) rather than imported from metrics.py.
PRECIP_HOURS = {
    'AIFS': list(range(6, PRECIP_HOUR_MAX + 1, 6)),    # 6-hourly, cumulative
    'GEFS': list(range(3, PRECIP_HOUR_MAX + 1, 3)),    # 3 h and 6 h buckets
    'UKMO': list(range(0, PRECIP_HOUR_MAX + 1)),       # hourly rate
}
WIND_HOURS = {m: list(range(0, WIND_HOUR_MAX + 1, 3)) for m in MODELS}

# The native (per-member, pre-regrid) tables carry a shorter record: the spatial
# SSR and correlation paths only ever query multiples of 6, and UKMO is seeded
# hourly anyway so a test can tell "the query did not ask" from "the row is not
# there".
NATIVE_PRECIP_HOURS = {
    'AIFS': [0, 6, 12, 18, 24],
    'GEFS': [0, 6, 12, 18, 24],
    'UKMO': list(range(0, 25)),
}
NATIVE_WIND_HOURS = {m: [0, 6, 12, 18, 24] for m in MODELS}

PRECIP_OBS_SOURCE = 'GPM_IMERG_V07B'
WIND_OBS_SOURCE   = 'ERA5_WIND'


# ── Expected results, for the tests to assert against ─────────────────────────
# Hand-derived in the module docstring. Written as literals on purpose: deriving
# them from the pipeline would re-implement the thing under test.

SCORED_PRECIP_HOURS = (6, 12)
SCORED_WIND_HOURS   = (0, 3, 6, 9, 12)
N_CELLS             = len(LATS) * len(LONS)

EXPECT_PRECIP = {
    'bias':     0.8,
    'mae':      1.4,
    'rmse':     math.sqrt(2.3),
    'csi':      0.6,
    'pod':      0.75,
    'far':      0.25,
    'hits':     15 * len(SCORED_PRECIP_HOURS),
    'misses':   5  * len(SCORED_PRECIP_HOURS),
    'false_alarms': 5 * len(SCORED_PRECIP_HOURS),
    'n_points': N_CELLS * len(SCORED_PRECIP_HOURS),
    'threshold_mm_6h': 9.0,           # -> a rate of 1.5 mm/h
    'rate':     3.0,                  # wet-cell forecast rate, mm/h
    'spread':   PRECIP_SPREAD,
}

# Per-cell values, by outcome — what a spatial map must show cell by cell.
EXPECT_PRECIP_CELL_BIAS = {'hit': 1.0, 'false_alarm': 2.5, 'miss': -1.5}
EXPECT_PRECIP_CELL_MAE  = {'hit': 1.0, 'false_alarm': 2.5, 'miss': 1.5}

EXPECT_WIND = {
    'bias':     2.0,
    'mae':      2.0,
    'rmse':     math.sqrt(4.5),
    'n_points': N_CELLS * len(SCORED_WIND_HOURS),
    'speed':    WIND_SPEED,
    'correlation': 1.0,               # spread == error by construction
}


def outcome(lat):
    """Which contingency outcome the cells at this latitude produce."""
    return precip_scene(lat)[2]


def cells_with_outcome(name):
    return [(lat, lon) for lat in LATS for lon in LONS if outcome(lat) == name]


# ── Storage conventions ───────────────────────────────────────────────────────
# What each model's loader would have written for a given true rate. Restated
# from METRICS_AUDIT.md findings 1, 2 and 12 — NOT imported from metrics.py, so a
# wrong divisor there cannot cancel itself against the fixture.

def stored_precip(model, hour, rate):
    if model == 'AIFS':
        # A running total since init, already in mm/h (the export divided by 6
        # and the records are 6-hourly, so the increment IS the rate).
        return rate * hour / 6.0
    if model == 'GEFS':
        # Buckets pre-divided by a flat 3 h: the 3 h buckets came out right, the
        # 6 h ones came out 2x too high.
        return rate * (2.0 if hour % 6 == 0 else 1.0)
    return rate                        # UKMO: native hourly mm/h, never scaled


def stored_precip_std(model, hour, spread=PRECIP_SPREAD):
    if model == 'AIFS':
        # Spread of the running total. Independent increments accumulate in
        # variance, so std grows as sqrt(hour) and each increment's spread comes
        # back out as `spread` exactly.
        return spread * math.sqrt(hour / 6.0)
    if model == 'GEFS':
        return spread * (2.0 if hour % 6 == 0 else 1.0)
    return spread


def _rows_precip_ens(model):
    for hour in PRECIP_HOURS[model]:
        for lat in LATS:
            rate = precip_scene(lat)[0]
            for lon in LONS:
                yield (model, 'precipitation', hour, lat, lon,
                       stored_precip(model, hour, rate),
                       stored_precip_std(model, hour),
                       len(MEMBER_OFFSETS), '0.5deg')


def _rows_wind_ens(model):
    for hour in WIND_HOURS[model]:
        s = wind_spread(hour)
        for var, mean, std in (('wind_u_10m', WIND_U, 0.6 * s),
                               ('wind_v_10m', WIND_V, 0.8 * s)):
            for lat in LATS:
                for lon in LONS:
                    yield (model, var, hour, lat, lon, mean, std,
                           len(MEMBER_OFFSETS), '0.5deg')


def _rows_precip_member(model):
    for hour in PRECIP_HOURS[model]:
        for lat in LATS:
            rate = precip_scene(lat)[0]
            for member, off in enumerate(MEMBER_OFFSETS):
                value = stored_precip(model, hour, rate + off * PRECIP_SPREAD)
                for lon in LONS:
                    yield (model, 'precipitation', hour, member, lat, lon, value)


def _rows_wind_member(model):
    for hour in WIND_HOURS[model]:
        s = wind_spread(hour)
        for member, off in enumerate(MEMBER_OFFSETS):
            e = off * s
            # u = 3 + 0.6e and v = 4 + 0.8e give speed exactly 5 + e, so the
            # member spread of the SPEED is exactly s — consistent with the
            # component std_devs above.
            for var, value in (('wind_u_10m', WIND_U + 0.6 * e),
                               ('wind_v_10m', WIND_V + 0.8 * e)):
                for lat in LATS:
                    for lon in LONS:
                        yield (model, var, hour, member, lat, lon, value)


def _obs_times_precip():
    """Half-hourly, like IMERG, from +0.5 h to the end of the record."""
    n = OBS_HOUR_MAX * 2
    return [INIT_TIME + timedelta(minutes=30 * (i + 1)) for i in range(n)]


def _obs_times_wind():
    """Hourly, like ERA5, from init to the end of the record."""
    return [INIT_TIME + timedelta(hours=h) for h in range(OBS_HOUR_MAX + 1)]


def _rows_regridded_obs():
    for t in _obs_times_precip():
        for lat in LATS:
            obs = precip_scene(lat)[1]
            for lon in LONS:
                yield (PRECIP_OBS_SOURCE, 'precipitation', t, lat, lon, obs, 1, '0.5deg')
    for t in _obs_times_wind():
        hour = (t - INIT_TIME).total_seconds() / 3600.0
        speed = wind_obs_speed(hour)
        for lat in LATS:
            for lon in LONS:
                yield (WIND_OBS_SOURCE, 'wind_speed', t, lat, lon, speed, 1, '0.5deg')


def _rows_point_obs():
    """Sparse point observations, on the hour, for the SSR/correlation paths.

    Those queries match `obs_time` exactly, so only whole hours are useful here.
    """
    for hour in range(0, OBS_HOUR_MAX + 1, 6):
        t = INIT_TIME + timedelta(hours=hour)
        speed = wind_obs_speed(hour)
        for lat in LATS:
            obs = precip_scene(lat)[1]
            for lon in LONS:
                yield (t, lat, lon, obs, 0.1, 1.0, PRECIP_OBS_SOURCE,
                       WIND_U, WIND_V, speed)


# ── Build / teardown ──────────────────────────────────────────────────────────

def unavailable_reason():
    """None if a fixture database can be built here, else why not."""
    if os.environ.get('WEAVE_SKIP_DB_TESTS'):
        return 'WEAVE_SKIP_DB_TESTS is set'
    try:
        conn = psycopg2.connect(connect_timeout=3, **db_config('postgres'))
    except Exception as e:
        return f'cannot reach PostgreSQL ({type(e).__name__}: {e})'
    conn.close()
    return None


def _maintenance_connection():
    conn = psycopg2.connect(**db_config('postgres'))
    conn.autocommit = True             # CREATE/DROP DATABASE cannot run in a txn
    return conn


def _assert_safe_name():
    if FIXTURE_DB_NAME in PROTECTED_DB_NAMES or not FIXTURE_DB_NAME.startswith('weave_fixture'):
        raise RuntimeError(
            f'refusing to create or drop {FIXTURE_DB_NAME!r} — the fixture '
            f'database name must start with "weave_fixture"')


def _schema_sql():
    """The real schema, from the two files that create the real database.

    `schema.sql` predates the ensemble regrid, so the member and mean/spread
    tables live in `regrid_members.py`. Reading both keeps the fixture honest: if
    a column is added to either one and the endpoints start using it, the fixture
    picks it up without anyone remembering to.
    """
    with open(os.path.join(HERE, 'schema.sql')) as fh:
        base = fh.read()
    ddl = [base]
    with open(os.path.join(HERE, 'regrid_members.py')) as fh:
        source = fh.read()
    for name in ('SCHEMA', 'INDEXES'):
        marker = f'{name} = """'
        start  = source.index(marker) + len(marker)
        ddl.append(source[start:source.index('"""', start)])
    return '\n'.join(ddl)


def create_database():
    _assert_safe_name()
    conn = _maintenance_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{FIXTURE_DB_NAME}"')
            cur.execute(f'CREATE DATABASE "{FIXTURE_DB_NAME}"')
    finally:
        conn.close()


def drop_database():
    _assert_safe_name()
    conn = _maintenance_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(f'DROP DATABASE IF EXISTS "{FIXTURE_DB_NAME}"')
    finally:
        conn.close()


def seed(conn):
    """Load the schema and the field into an empty fixture database."""
    ens = mem = 0
    with conn.cursor() as cur:
        cur.execute(_schema_sql())

        for model in MODELS:
            cur.execute("""
                INSERT INTO forecast_runs (model_id, initialization_time)
                SELECT model_id, %s FROM models WHERE model_name = %s
            """, (INIT_TIME, model))

        for model in MODELS:
            rows = list(_rows_precip_ens(model)) + list(_rows_wind_ens(model))
            execute_values(cur, """
                INSERT INTO regridded_forecast_ens
                    (model_name, variable_name, forecast_hour, latitude, longitude,
                     mean_value, std_dev, n_members, resolution) VALUES %s
            """, rows)
            ens += len(rows)

            rows = list(_rows_precip_member(model)) + list(_rows_wind_member(model))
            execute_values(cur, """
                INSERT INTO regridded_forecast_member
                    (model_name, variable_name, forecast_hour, ensemble_member,
                     latitude, longitude, value) VALUES %s
            """, rows)
            mem += len(rows)

        execute_values(cur, """
            INSERT INTO regridded_observation
                (source, variable_name, obs_time, latitude, longitude,
                 value, source_points, resolution) VALUES %s
        """, list(_rows_regridded_obs()))

        execute_values(cur, """
            INSERT INTO observation_data
                (obs_time, latitude, longitude, precipitation, random_error,
                 quality_index, source, wind_u, wind_v, wind_speed) VALUES %s
        """, list(_rows_point_obs()))

        _seed_native(cur)

    conn.commit()
    return {'regridded_forecast_ens': ens, 'regridded_forecast_member': mem}


def _seed_native(cur):
    """The pre-regrid tables: ensemble_statistics and per-member forecast_data.

    Same field and same storage conventions as the regridded tables, but **each
    model on its own native grid** (see NATIVE_GRIDS): AIFS at 0.25 degrees, GEFS
    at 0.5, UKMO at 0.1875 x 0.28125 and aligned to neither. UKMO's wind rows also
    carry the reduced-precision coordinates its loader wrote.

    No second truth is introduced by the finer grids, because the field is
    piecewise constant over the analysis bands (see PRECIP_BANDS) and a constant
    field regrids to itself whatever the grids. What the resolution difference does
    buy is a fixture that can see a cell collapse, and a nearest-cell choice with
    more than one candidate.

    The aggregate spread here is inflated by NATIVE_SPREAD_INFLATION while the
    per-member values stay exact, so an endpoint's numbers say which table it read.
    """
    infl = NATIVE_SPREAD_INFLATION
    cur.execute("SELECT variable_name, variable_id FROM variables")
    var_id = dict(cur.fetchall())
    cur.execute("""
        SELECT m.model_name, fr.run_id FROM forecast_runs fr
        JOIN models m ON m.model_id = fr.model_id
    """)
    run_id = dict(cur.fetchall())

    stats, members = [], []
    for model in MODELS:
        rid = run_id[model]

        lats, lons = native_cells(model, 'precipitation')
        vid = var_id['precipitation']
        for hour in NATIVE_PRECIP_HOURS[model]:
            for lat in lats:
                rate = precip_scene(lat)[0]
                mean = stored_precip(model, hour, rate)
                std  = stored_precip_std(model, hour) * infl
                for lon in lons:
                    stats.append((rid, vid, hour, lat, lon, mean, std,
                                  mean - std, mean + std, mean, mean, mean))
                    for member, off in enumerate(MEMBER_OFFSETS):
                        members.append((rid, vid, hour, member, lat, lon,
                                        stored_precip(model, hour,
                                                      rate + off * PRECIP_SPREAD)))

        for hour in NATIVE_WIND_HOURS[model]:
            s = wind_spread(hour)
            for var, mean, std in (('wind_u_10m', WIND_U, 0.6 * s * infl),
                                   ('wind_v_10m', WIND_V, 0.8 * s * infl)):
                vid = var_id[var]
                comp = 0.6 if var == 'wind_u_10m' else 0.8
                # Wind may sit on different coordinates from precipitation for the
                # same model — that is the point of COORD_6SIG_VARIABLES. Both
                # components share them, so the u/v join still works.
                w_lats, w_lons = native_cells(model, var)
                for lat in w_lats:
                    for lon in w_lons:
                        stats.append((rid, vid, hour, lat, lon, mean, std,
                                      mean - std, mean + std, mean, mean, mean))
                        for member, off in enumerate(MEMBER_OFFSETS):
                            members.append((rid, vid, hour, member, lat, lon,
                                            mean + comp * off * s))

    execute_values(cur, """
        INSERT INTO ensemble_statistics
            (run_id, variable_id, forecast_hour, latitude, longitude,
             mean_value, std_dev, min_value, max_value,
             percentile_25, percentile_50, percentile_75) VALUES %s
    """, stats)
    execute_values(cur, """
        INSERT INTO forecast_data
            (run_id, variable_id, forecast_hour, ensemble_member,
             latitude, longitude, value) VALUES %s
    """, members)


def build():
    """Create the fixture database from scratch and seed it."""
    create_database()
    conn = psycopg2.connect(**db_config())
    try:
        return seed(conn)
    finally:
        conn.close()


if __name__ == '__main__':
    if '--drop' in sys.argv:
        drop_database()
        print(f'dropped {FIXTURE_DB_NAME}')
    else:
        reason = unavailable_reason()
        if reason:
            sys.exit(f'cannot build fixture database: {reason}')
        counts = build()
        print(f'built {FIXTURE_DB_NAME}: ' +
              ', '.join(f'{k}={v}' for k, v in counts.items()))
