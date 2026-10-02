#!/usr/bin/env python
"""Recompute the cyclone CSVs' derived columns and measure the difference.

Why this exists
---------------
`TC_TAB_DESIGN.md` §7. `output/` ships four derived quantities —
`distance_km`, `mean_lat`, `mean_lon`, `dist_to_ens_mean_km` — **and every input
to them**. A number whose derivation is unknown is not a measurement, and this
project has twice paid for trusting one: `SCALED_EXPORT_DIVISOR_HOURS` took days
to reconstruct (§13, §22) and the 4-hour IMERG shift moved every precipitation
figure in the app and changed which model looked better (§12).

So `load_cyclone_tracks.py` deliberately does not load those four columns, and
this script is how they get checked instead. It is the same bargain
`regrid_observations.py --compare` strikes: when a stored value can be
recomputed, recompute it and report the difference rather than adopting it.

**It needs no database.** The forecast position, the best-track position and the
claimed distance are all on the same CSV row, so this is a self-contained check
that can run before anything is loaded.

Diagnosis, not just measurement
-------------------------------
"They differ by 0.1%" is not a finding; it is the start of one. A great-circle
distance differs by about 0.1% between the common Earth radii, and by more
between formulae, so the script tries the plausible alternatives and reports
**which one explains the residual**. If none does, that is worth knowing too,
and much more interesting.

The mean-longitude check is the one with teeth. An arithmetic mean of longitudes
is wrong across the antimeridian — members at +179 and −179 average to 0, which
is the wrong side of the planet. A circular mean is right. If their column was
computed arithmetically the two agree everywhere except near the dateline, which
is exactly the signature this reports separately.

Usage
-----
    python compare_cyclone_derived.py --source /path/to/output
    python compare_cyclone_derived.py --source /path/to/output --storms BERYL
"""
import argparse
import csv
import math
import os
import sys
from collections import defaultdict

# The radii worth testing. 6371.0088 is the IUGG mean radius, 6371.0 the usual
# round number, 6378.137 the WGS-84 equatorial radius — which is what a script
# reaching for "the radius of the Earth" in a geodesy library often gets, and is
# 0.11% larger than the mean.
RADII = {
    'R=6371.0 (common mean)':     6371.0,
    'R=6371.0088 (IUGG mean)':    6371.0088,
    'R=6378.137 (WGS-84 equat.)': 6378.137,
    'R=6372.8 (haversine lore)':  6372.8,
}

# A longitude pair is "near the antimeridian" if the members straddle it. Used
# to separate the dateline signature from everything else.
DATELINE_SPAN_DEG = 180.0


def haversine(lat1, lon1, lat2, lon2, radius):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))


def great_circle_cosines(lat1, lon1, lat2, lon2, radius):
    """The spherical law of cosines. Included because it is the other thing
    people write, and it differs from haversine at small separations where
    floating point eats the result — which is most cyclone track errors."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    c = math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(dl)
    return radius * math.acos(max(-1.0, min(1.0, c)))


def arithmetic_mean_lon(lons):
    return sum(lons) / len(lons)


def circular_mean_lon(lons):
    """The correct mean for an angle. Differs from the arithmetic one only when
    the values straddle the antimeridian — and there it differs by about 360."""
    x = sum(math.cos(math.radians(v)) for v in lons)
    y = sum(math.sin(math.radians(v)) for v in lons)
    if abs(x) < 1e-12 and abs(y) < 1e-12:
        return None                       # antipodal spread; no mean direction
    return math.degrees(math.atan2(y, x))


def _f(value):
    value = (value or '').strip()
    if value in ('', 'NaN', 'nan'):
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _stats(diffs):
    """(n, exact, median, p95, max) over absolute differences."""
    if not diffs:
        return 0, 0, None, None, None
    ordered = sorted(diffs)
    exact = sum(1 for d in ordered if d == 0.0)
    def at(p):
        return ordered[min(int(p * len(ordered)), len(ordered) - 1)]
    return len(ordered), exact, at(0.5), at(0.95), ordered[-1]


def _report(label, diffs, unit='km'):
    n, exact, med, p95, mx = _stats(diffs)
    if not n:
        print(f'  {label}: nothing to compare')
        return
    print(f'  {label}: {n:,} compared, {exact:,} identical '
          f'({100 * exact / n:.1f}%)')
    print(f'    |diff| median {med:.6g} {unit}, p95 {p95:.6g}, max {mx:.6g}')


def compare_file(path, radius, distance_fn, mean_fn):
    """Recompute one file. Returns per-quantity lists of absolute differences."""
    out = {'distance': [], 'mean_lat': [], 'mean_lon': [], 'to_mean': [],
           'dateline_mean_lon': []}
    rows = []
    with open(path, newline='') as fh:
        for r in csv.DictReader(fh):
            rows.append(r)

    # distance_km: forecast position against the best track on the same row.
    for r in rows:
        lat, lon = _f(r['lat']), _f(r['lon'])
        olat, olon = _f(r['LAT']), _f(r['LON'])
        claimed = _f(r['distance_km'])
        if None in (lat, lon, olat, olon, claimed):
            continue
        out['distance'].append(abs(distance_fn(lat, lon, olat, olon, radius) - claimed))

    # The ensemble mean is per (lead_time); every member at that lead contributes.
    by_lead = defaultdict(list)
    for r in rows:
        lat, lon = _f(r['lat']), _f(r['lon'])
        if lat is not None and lon is not None:
            by_lead[r['lead_time']].append((lat, lon, r))

    for lead, members in by_lead.items():
        lats = [m[0] for m in members]
        lons = [m[1] for m in members]
        mlat = sum(lats) / len(lats)
        mlon = mean_fn(lons)
        if mlon is None:
            continue
        straddles = (max(lons) - min(lons)) > DATELINE_SPAN_DEG
        for lat, lon, r in members:
            claimed_lat, claimed_lon = _f(r['mean_lat']), _f(r['mean_lon'])
            if claimed_lat is not None:
                out['mean_lat'].append(abs(mlat - claimed_lat))
            if claimed_lon is not None:
                d = abs(mlon - claimed_lon)
                (out['dateline_mean_lon'] if straddles else out['mean_lon']).append(d)
            claimed_to_mean = _f(r['dist_to_ens_mean_km'])
            if claimed_to_mean is not None:
                out['to_mean'].append(
                    abs(distance_fn(lat, lon, mlat, mlon, radius) - claimed_to_mean))
    return out


def run(source, storms=None):
    paths = sorted(os.path.join(source, f) for f in os.listdir(source)
                   if f.endswith('.csv')
                   and (storms is None or any(f'_{s}.csv' in f for s in storms)))
    if not paths:
        sys.exit(f'{source}: no CSVs')

    print(f'comparing {len(paths):,} files; writing nothing\n')

    # ── Which formula and radius explains distance_km? ───────────────────────
    print('distance_km — which great-circle convention was used?\n')
    best = None
    for fn_name, fn in (('haversine', haversine),
                        ('law of cosines', great_circle_cosines)):
        for rad_name, rad in RADII.items():
            diffs = []
            for path in paths:
                diffs += compare_file(path, rad, fn, circular_mean_lon)['distance']
            n, exact, med, p95, mx = _stats(diffs)
            if not n:
                continue
            print(f'  {fn_name:<15} {rad_name:<28} '
                  f'median |diff| {med:.6g} km, max {mx:.6g}')
            if best is None or med < best[0]:
                best = (med, fn_name, rad_name, fn, rad)

    if best is None:
        sys.exit('no comparable rows — is this the right directory?')
    med, fn_name, rad_name, fn, rad = best
    print(f'\n  best fit: {fn_name}, {rad_name} — median |diff| {med:.6g} km')
    if med < 0.001:
        print('  -> their distance_km is reproducible. It can be trusted, and '
              'this is why.')
    elif med < 1.0:
        print('  -> close but not exact. Sub-kilometre on a track error of '
              'hundreds of km is immaterial for display, and still means the '
              'convention is not quite the one tried here.')
    else:
        print('  -> NOT reproduced. Do not quote their distance_km as a '
              'measurement until this is explained.')

    # ── Was the ensemble mean longitude arithmetic or circular? ──────────────
    print('\nmean_lon — arithmetic or circular?\n')
    for mean_name, mean_fn in (('circular (correct)', circular_mean_lon),
                               ('arithmetic', arithmetic_mean_lon)):
        plain, dateline = [], []
        for path in paths:
            res = compare_file(path, rad, fn, mean_fn)
            plain += res['mean_lon']
            dateline += res['dateline_mean_lon']
        n, exact, pm, _, pmx = _stats(plain)
        dn, dexact, dm, _, dmx = _stats(dateline)
        print(f'  {mean_name:<20} away from the dateline: median '
              f'{pm if pm is not None else float("nan"):.6g}°, max '
              f'{pmx if pmx is not None else float("nan"):.6g}°')
        if dn:
            print(f'  {"":20} straddling it ({dn:,} rows): median '
                  f'{dm:.6g}°, max {dmx:.6g}°')
        else:
            print(f'  {"":20} no member set straddles the antimeridian in this '
                  f'sample — the case that separates the two is absent')

    # ── And the rest, under the best-fitting convention ──────────────────────
    print('\nthe other derived columns, under the best-fitting convention\n')
    agg = defaultdict(list)
    for path in paths:
        for key, values in compare_file(path, rad, fn, circular_mean_lon).items():
            agg[key] += values
    _report('mean_lat           ', agg['mean_lat'], 'deg')
    _report('mean_lon           ', agg['mean_lon'], 'deg')
    _report('dist_to_ens_mean_km', agg['to_mean'])
    return 0


def provenance(source, storms=None):
    """Does track error grow with lead time? The gate before trusting anything.

    §24's method lesson 10, in track space. Row counts, grids, member counts and
    lead ranges were identical between two different forecast runs and told them
    apart not at all; what did was that **a forecast scored against its own
    valid times loses skill monotonically with lead, and the wrong week gives a
    flat curve at a higher level.**

    The same test works here and is cheaper, because `distance_km` is already
    the error and `compare_cyclone_derived` has shown it is reproducible.

    Spearman rather than Pearson, per this project's first method lesson: the
    question is whether error *rises* with lead, not whether it rises linearly,
    and track error against lead is not a straight line.
    """
    from scipy.stats import spearmanr

    paths = sorted(os.path.join(source, f) for f in os.listdir(source)
                   if f.endswith('.csv')
                   and (storms is None or any(f'_{s}.csv' in f for s in storms)))
    if not paths:
        sys.exit(f'{source}: no CSVs')

    by_centre = defaultdict(lambda: defaultdict(list))
    by_storm = defaultdict(lambda: defaultdict(list))
    for path in paths:
        centre = os.path.basename(path).split('_', 1)[0]
        storm = os.path.basename(path).rsplit('h_', 1)[-1][:-4]
        with open(path, newline='') as fh:
            for r in csv.DictReader(fh):
                d = _f(r['distance_km'])
                if d is None:
                    continue
                lead = int(float(r['lead_time']))
                by_centre[centre][lead].append(d)
                by_storm[(centre, storm)][lead].append(d)

    print(f'provenance check over {len(paths):,} files\n')
    print('track error against lead time, by centre\n')
    failures = []
    for centre in sorted(by_centre):
        leads = sorted(by_centre[centre])
        means = [sum(by_centre[centre][l]) / len(by_centre[centre][l]) for l in leads]
        rho, _ = spearmanr(leads, means)
        growth = means[-1] - means[0]
        rate = growth / (leads[-1] - leads[0]) * 24 if leads[-1] != leads[0] else 0
        verdict = 'rises' if rho > 0.9 else 'FLAT OR FALLING'
        if rho <= 0.9:
            failures.append(centre)
        print(f'  {centre}:  rho={rho:+.4f}  {verdict}')
        print(f'     +{leads[0]}h {means[0]:7.1f} km  ->  '
              f'+{leads[-1]}h {means[-1]:7.1f} km   '
              f'({rate:.0f} km/day)')
        sparse = [f'+{l}h {m:.0f}' for l, m in zip(leads, means)
                  if l % 24 == 0]
        print(f'     {"  ".join(sparse)}')

    # Per storm, because one mispaired storm inside a healthy aggregate is
    # exactly what an aggregate hides.
    #
    # **This is a flag, not a gate.** A single storm's error-vs-lead curve has
    # no reason to be monotone: an ensemble can be lucky at day 5 and unlucky at
    # day 2, and a storm only some members tracked is scored on a biased subset
    # of them. Run over 400 pairs it flagged two — LESTER and GAEMI, both from
    # MOGREPS, both still rising overall and both clean at another centre. That
    # is sampling, not provenance. Read these as "worth a look", and let the
    # aggregate decide.
    bad = []
    for (centre, storm), leads_map in by_storm.items():
        leads = sorted(leads_map)
        if len(leads) < 5:
            continue
        means = [sum(leads_map[l]) / len(leads_map[l]) for l in leads]
        rho, _ = spearmanr(leads, means)
        if rho <= 0.5:
            bad.append((rho, centre, storm, means[0], means[-1]))
    print(f'\n  per storm-centre pairs checked: {len(by_storm):,}')
    if bad:
        print(f'  {len(bad)} with rho <= 0.5 — noisy rather than suspect, '
              f'unless one is flat at a HIGH level, which is the mispaired '
              f'signature. Worth a look:')
        for rho, centre, storm, first, last in sorted(bad)[:10]:
            print(f'     {storm:<14} {centre}  rho={rho:+.3f}  '
                  f'{first:.0f} -> {last:.0f} km')
    else:
        print('  none with rho <= 0.5 — every storm-centre pair loses skill '
              'with lead, which is what correctly paired forecasts do')

    if failures:
        print(f'\n  GATE FAILED for {failures}. Do not trust these tracks.')
        return 1
    print('\n  gate passed')
    return 0


def main():
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--source', required=True, help='directory of output/ CSVs')
    ap.add_argument('--storms', help='comma-separated storm names, for a subset')
    ap.add_argument('--provenance', action='store_true',
                    help='check that track error grows with lead, and stop there')
    args = ap.parse_args()
    if not os.path.isdir(args.source):
        sys.exit(f'not a directory: {args.source}')
    storms = [s.strip() for s in args.storms.split(',')] if args.storms else None
    if args.provenance:
        return provenance(args.source, storms)
    return run(args.source, storms)


if __name__ == '__main__':
    sys.exit(main())
