"""A load test for the WEAVE API — `SYSTEM_DESIGN_PLAN.md` S3.

S3 asks for "Redis, async jobs and a load test" and nothing had been measured.
The load test comes first on purpose: §50's 217-second region request was one
unindexable `COUNT(DISTINCT)` found by profiling, and adding a cache in front
of it would have hidden the defect rather than fixed it. **Decide whether
Redis and async are warranted from numbers, not from the shape of the stack.**

What this exercises, stated so the result is not over-read (§66 — a negative
result is only evidence about what you actually ran):

  * The **dev server**, `app.run(threaded=True)`, one process, one connection
    pool of `DB_POOL_MAX` (8). Production is 4 gunicorn workers with a pool
    each. So pool-saturation numbers here are the *per-worker* picture, and
    per-worker is exactly where saturation happens.
  * The **real 129 GB database**, not a fixture. The timings are therefore the
    real ones.
  * `RATE_LIMIT` is raised for the run. Leaving the 300/min default in place
    would measure flask-limiter rejecting requests rather than the API
    serving them.

It does NOT exercise multi-worker behaviour, so it says nothing directly about
the per-worker rate limiter or a cache shared between instances. Those are
read off the code instead and reported separately.
"""
import argparse
import json
import random
import statistics
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

BASE = 'http://127.0.0.1:5000/api'
RUN = '2025-09-16T00:00:00'

# The mix a reviewer actually generates, from what the tabs call on load and
# on interaction. Weighted so the cheap, frequent calls dominate — a flat mix
# across endpoints would over-represent the render path and report a latency
# nobody experiences.
REQUESTS = [
    ('runs',        6, 'GET',  '/runs', None),
    ('models',      4, 'GET',  '/models', None),
    ('config',      4, 'GET',  '/config', None),
    ('forecast',    8, 'GET',  f'/forecast-data?model=AIFS&variable=precipitation'
                               f'&hour=6&member=mean&init_time={RUN}', None),
    ('timeseries',  5, 'GET',  f'/point-timeseries?model=AIFS&variable=precipitation'
                               f'&lat=35.0&lon=-75.0&init_time={RUN}', None),
    ('spread',      3, 'GET',  f'/spread-skill?model=AIFS&variable=precipitation'
                               f'&lat=35.0&lon=-75.0&init_time={RUN}', None),
    ('cyclones',    3, 'GET',  '/cyclones', None),
    ('health',      1, 'GET',  '/health', None),
    ('region',      2, 'POST', '/region-categorical-metrics',
     {'model': 'AIFS', 'variable': 'precipitation',
      'min_lat': 30, 'max_lat': 40, 'min_lon': -80, 'max_lon': -70,
      'threshold_mm_6h': 1.0, 'hour_min': 6, 'hour_max': 168,
      'init_time': RUN}),
]

# **Shuffled, deterministically.** Built in declaration order and indexed
# `i % len`, a run shorter than the list only ever fires the endpoints at the
# front of it — the first probe did 20 requests and never touched `region`,
# `spread` or `timeseries`, which are the expensive ones the test exists to
# measure. It reported 3 ms p50 and looked excellent. A fixed seed keeps runs
# comparable without keeping them unrepresentative.
WEIGHTED = [r for r in REQUESTS for _ in range(r[1])]
random.Random(20261016).shuffle(WEIGHTED)


def fire(spec):
    name, _w, method, path, body = spec
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={'Content-Type': 'application/json'} if data else {})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=300) as r:
            r.read()
            return name, (time.perf_counter() - t0) * 1000, r.status
    except urllib.error.HTTPError as e:
        return name, (time.perf_counter() - t0) * 1000, e.code
    except Exception as e:                      # connection refused, timeout
        return name, (time.perf_counter() - t0) * 1000, type(e).__name__


def pct(xs, p):
    if not xs:
        return float('nan')
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(round((p / 100) * (len(xs) - 1))))]


def run(concurrency, total):
    specs = [WEIGHTED[i % len(WEIGHTED)] for i in range(total)]
    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        results = list(ex.map(fire, specs))
    wall = time.perf_counter() - t0

    by_name, codes = {}, {}
    for name, ms, status in results:
        by_name.setdefault(name, []).append(ms)
        codes[status] = codes.get(status, 0) + 1

    ok = sum(n for c, n in codes.items() if c == 200)
    print(f'\n=== concurrency {concurrency}, {total} requests, '
          f'{wall:.1f}s wall, {total / wall:.1f} req/s ===')
    print(f'    statuses: {codes}')
    print(f'    {"endpoint":<12}{"n":>5}{"p50":>9}{"p95":>9}{"max":>9}')
    for name in sorted(by_name, key=lambda k: -pct(by_name[k], 95)):
        v = by_name[name]
        print(f'    {name:<12}{len(v):>5}{pct(v,50):>9.0f}{pct(v,95):>9.0f}'
              f'{max(v):>9.0f}')
    allms = [m for v in by_name.values() for m in v]
    print(f'    {"ALL":<12}{len(allms):>5}{pct(allms,50):>9.0f}'
          f'{pct(allms,95):>9.0f}{max(allms):>9.0f}   ok={ok}/{total}')
    return {'concurrency': concurrency, 'rps': total / wall,
            'p50': pct(allms, 50), 'p95': pct(allms, 95),
            'max': max(allms), 'ok': ok, 'total': total, 'codes': codes}


def preflight():
    """Refuse to run against a server that is not there.

    **§82a: a 25-minute run was spent firing at a server that had died 25
    minutes earlier.** Every request failed instantly with connection-refused,
    the harness dutifully recorded them, and the run looked like it was
    queueing hard under the new retry budget — a slow clock read as the fix
    working. A load generator that cannot tell "busy" from "absent" will
    report the second as the first.
    """
    try:
        with urllib.request.urlopen(BASE + '/ready', timeout=20) as r:
            if r.status != 200:
                raise SystemExit(f'preflight: /ready returned {r.status}')
    except Exception as e:
        raise SystemExit(
            f'preflight: cannot reach {BASE}/ready ({type(e).__name__}: {e}).\n'
            'Start the API first. Refusing to measure a server that is not '
            'answering — see NEXT_STEPS.md §82a.')
    print(f'preflight: {BASE} is answering')


def guard(results_summary):
    """Say loudly when a level was dominated by transport failures.

    A status of `URLError` is not a latency measurement, and a table full of
    them still renders as a table.
    """
    for s in results_summary:
        bad = sum(n for c, n in s['codes'].items() if not isinstance(c, int))
        if bad:
            print(f'  ⚠️  concurrency {s["concurrency"]}: {bad}/{s["total"]} '
                  f'requests never reached the server — these are transport '
                  f'failures, not latencies. {s["codes"]}')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--levels', default='1,2,4,8,16,32')
    ap.add_argument('--requests', type=int, default=60)
    a = ap.parse_args()

    preflight()

    summary = []
    for c in [int(x) for x in a.levels.split(',')]:
        summary.append(run(c, a.requests))
        # Re-check between levels: if the server dies partway through, the
        # remaining levels would otherwise be measured against nothing.
        preflight()

    print('\n=== summary ===')
    print(f'{"conc":>5}{"req/s":>9}{"p50 ms":>9}{"p95 ms":>9}{"max ms":>9}{"ok":>9}')
    for s in summary:
        print(f'{s["concurrency"]:>5}{s["rps"]:>9.1f}{s["p50"]:>9.0f}'
              f'{s["p95"]:>9.0f}{s["max"]:>9.0f}{s["ok"]:>5}/{s["total"]}')
    guard(summary)
