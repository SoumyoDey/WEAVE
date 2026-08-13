"""Verification-metric computations for WEAVE.

Pure functions only — no Flask, no database, no rendering. Everything here maps
inputs to numbers, which is what makes the golden-vector suite in
`test_metrics.py` able to cover the science without a database.

The endpoint layer in `flask_api.py` is responsible for fetching rows and
turning them into the plain structures these helpers take.

Grouped as:
  * precipitation record semantics (the per-model accumulation conventions)
  * spread-skill ratio
  * predictive distribution (CRPS / Brier)
  * fractions skill score
  * region aggregation and spatial differencing
"""
import math
from datetime import timedelta

import numpy as np
import scipy.stats


# ── Fractions Skill Score ─────────────────────────────────────────────────────
def _neighbourhood_fractions(binary_by_cell, window):
    """Fraction of event cells in a `window`x`window` box around each cell.

    `binary_by_cell` maps (lat, lon) -> 0.0/1.0 on a regular grid. Returns
    {(lat, lon): fraction}. Cells missing from the grid are excluded from both
    the numerator and the denominator, so a partly-observed neighbourhood is
    scored on what it actually contains rather than being treated as dry.
    """
    if not binary_by_cell:
        return {}
    lats = sorted({lat for lat, _ in binary_by_cell})
    lons = sorted({lon for _, lon in binary_by_cell})
    lat_step = _grid_step(lats)
    lon_step = _grid_step(lons)
    lat_idx = {lat: i for i, lat in enumerate(lats)}
    lon_idx = {lon: j for j, lon in enumerate(lons)}

    grid = np.full((len(lats), len(lons)), np.nan)
    for (lat, lon), v in binary_by_cell.items():
        grid[lat_idx[lat], lon_idx[lon]] = v

    present = ~np.isnan(grid)
    filled  = np.where(present, grid, 0.0)

    # Box sum via a summed-area table — O(cells) regardless of window size.
    def _box_sums(arr):
        pad = np.pad(arr, ((1, 0), (1, 0)), mode='constant')
        sat = pad.cumsum(axis=0).cumsum(axis=1)
        r = window // 2
        n_lat, n_lon = arr.shape
        out = np.empty_like(arr, dtype=float)
        for i in range(n_lat):
            i0, i1 = max(0, i - r), min(n_lat - 1, i + r)
            for j in range(n_lon):
                j0, j1 = max(0, j - r), min(n_lon - 1, j + r)
                out[i, j] = (sat[i1 + 1, j1 + 1] - sat[i0, j1 + 1]
                             - sat[i1 + 1, j0] + sat[i0, j0])
        return out

    event_sums = _box_sums(filled)
    count_sums = _box_sums(present.astype(float))

    return {
        (lats[i], lons[j]): float(event_sums[i, j] / count_sums[i, j])
        for i in range(len(lats)) for j in range(len(lons))
        if present[i, j] and count_sums[i, j] > 0
    }


def _fss_components(fcst_binary_by_cell, obs_binary_by_cell, window):
    """(numerator, denominator, n_cells) behind the FSS over shared cells.

    Returned separately so several cases (lead times) can be aggregated the
    standard way — sum the numerators and denominators, then form the ratio
    once — rather than averaging per-case FSS values.
    """
    if not fcst_binary_by_cell or not obs_binary_by_cell:
        return 0.0, 0.0, 0
    f_frac = _neighbourhood_fractions(fcst_binary_by_cell, window)
    o_frac = _neighbourhood_fractions(obs_binary_by_cell, window)
    shared = set(f_frac) & set(o_frac)
    if not shared:
        return 0.0, 0.0, 0
    num = sum((f_frac[c] - o_frac[c]) ** 2 for c in shared)
    den = sum(f_frac[c] ** 2 + o_frac[c] ** 2 for c in shared)
    return num, den, len(shared)


def _fss_from_components(num, den):
    """FSS from accumulated components; None when the reference is 0 (no events
    in either field), which is undefined rather than a perfect 1.0."""
    if den is None or den <= 1e-10:
        return None
    return round(1.0 - num / den, 4)


def _fractions_skill_score(fcst_binary_by_cell, obs_binary_by_cell, window):
    """Roberts & Lean (2008) FSS over a sliding neighbourhood.

        FSS = 1 - sum((f - o)^2) / sum(f^2 + o^2)

    where f and o are the event fractions in a window x window box around each
    grid point. This is what makes FSS a *placement* score: a single domain-wide
    fraction (what this used to compute) collapses to a comparison of overall
    event frequency, so two fields raining over equal areas in completely
    different places scored a perfect 1.0.

    window=1 degenerates to the grid-point score.
    """
    num, den, n = _fss_components(fcst_binary_by_cell, obs_binary_by_cell, window)
    return _fss_from_components(num, den) if n else None


# ── Predictive distribution for CRPS / Brier ──────────────────────────────────
# Only the ensemble mean and spread are stored on the aggregate tables, so a
# Gaussian predictive distribution is assumed. That is fine for wind speed, but
# a poor fit for precipitation: it is non-negative, zero-inflated and
# right-skewed, and a plain Gaussian puts real probability mass below zero —
# worst exactly where mu is near 0, i.e. most cells.
#
# Both quantities below therefore use the Gaussian CENSORED at zero (X = max(0, Y)),
# which is the physically admissible reading for a non-negative variable.
#
# For a threshold >= 0 the exceedance probability is unchanged by censoring —
# it only moves mass that was already below the threshold — so Brier is
# identical either way. CRPS is not: for y >= 0,
#
#     CRPS_gauss - CRPS_censored = integral over x<0 of Phi((x-mu)/sigma)^2 dx
#
# because the censored CDF is 0 below zero while the Gaussian one is not, and
# the two agree everywhere above zero. That correction is what _censor_correction
# evaluates. It is negligible when mu >> sigma and material when mu ~ 0.
#
# The exact fix would be an empirical/ensemble CRPS, which needs per-member data
# the aggregate tables do not carry.
_CRPS_GL_NODES, _CRPS_GL_WEIGHTS = np.polynomial.legendre.leggauss(24)


def _censor_correction(mean, std):
    """Integral of Phi((x-mu)/sigma)^2 over x < 0, by Gauss-Legendre quadrature."""
    lo = mean - 8.0 * std
    if lo >= 0.0:
        return 0.0                      # no meaningful mass below zero
    half = -lo / 2.0
    mid  = lo / 2.0
    xs   = mid + half * _CRPS_GL_NODES
    vals = scipy.stats.norm.cdf((xs - mean) / std) ** 2
    return float(half * np.dot(_CRPS_GL_WEIGHTS, vals))


def _gaussian_crps(mean, std, obs, censor_at_zero=True):
    """CRPS of the predictive distribution against one observation.

    Closed form for the Gaussian: sigma * [z(2*Phi(z)-1) + 2*phi(z) - 1/sqrt(pi)]
    with z = (obs - mu)/sigma, then the censoring correction above.
    A degenerate spread reduces to the absolute error, which is the correct
    limit (CRPS of a point forecast is |mu - y|).
    """
    if std is None or std <= 1e-10:
        return abs(mean - obs)
    z    = (obs - mean) / std
    crps = float(std * (z * (2.0 * scipy.stats.norm.cdf(z) - 1.0)
                        + 2.0 * scipy.stats.norm.pdf(z)
                        - 1.0 / math.sqrt(math.pi)))
    if censor_at_zero:
        crps -= _censor_correction(mean, std)
    return max(0.0, crps)


def _exceedance_probability(mean, std, threshold):
    """P(X > threshold) under the same predictive distribution.

    Unchanged by censoring for a non-negative threshold, so this is the plain
    Gaussian upper tail; a degenerate spread collapses to a 0/1 indicator.
    """
    if std is None or std <= 1e-10:
        return 1.0 if mean > threshold else 0.0
    return float(1.0 - scipy.stats.norm.cdf(threshold, loc=mean, scale=std))


# ── Spread-skill ratio ────────────────────────────────────────────────────────
# SSR is reported in the conventional form: ensemble spread / error (sigma over
# RMSE), NOT the variance ratio. Both are 1.0 when perfectly calibrated, but the
# interpretation bands the colourbar and the UI use — <0.5 severely
# underdispersive, 0.8-1.2 calibrated, >2.0 severely overdispersive — are the
# standard bands for sigma/RMSE. Reporting a variance ratio against those labels
# mis-stated the wings: a variance ratio of 0.5 is a spread/error ratio of 0.71,
# which is not "severe".
#
# The ratio still explodes toward a near-zero error, so cap it at the top of the
# colourbar and reject non-finite / negative results.
SSR_CAP = 10.0


def _clamp_ssr(value):
    if value is None or not math.isfinite(value) or value < 0:
        return None
    return round(min(value, SSR_CAP), 4)


def _ssr_from_variances(mean_var, mean_sq_err, n_members=None):
    """Spread-skill ratio from a mean variance and a mean squared error.

    Returns sqrt(mean_var / mean_sq_err) — the RMS spread over the RMSE, which
    is the aggregate form of sigma/RMSE. `n_members` applies the finite-ensemble
    correction (see _spread_inflation).
    """
    if mean_sq_err is None or mean_sq_err <= 1e-10 or mean_var is None or mean_var < 0:
        return None
    inflation = _spread_inflation(n_members)
    return _clamp_ssr(math.sqrt(mean_var / mean_sq_err) * inflation)


# A finite ensemble under-estimates the forecast variance; the standard
# correction is Var * (M+1)/M, i.e. spread * sqrt((M+1)/M). Member counts differ
# substantially here (AIFS 50, GEFS 30, UKMO 18 → 1.0%, 1.6%, 2.7% on the
# spread), so leaving it out biases exactly the cross-model SSR ranking this
# tool exists to show.
def _spread_inflation(n_members):
    if not n_members or n_members < 2:
        return 1.0
    return math.sqrt((n_members + 1.0) / n_members)


def _grid_step(sorted_coords, default=0.25):
    """Cell size of a coordinate axis, taken as the median gap between adjacent
    values. Robust to a missing cell in the middle, which a min() would not be.
    """
    gaps = [b - a for a, b in zip(sorted_coords, sorted_coords[1:]) if b > a]
    if not gaps:
        return default
    return float(np.median(gaps))


# ── Precipitation record semantics ───────────────────────────────────────────
# Established from the stored data itself (see METRICS_AUDIT.md findings 1-2):
# the loaders write provider values verbatim, and the three models do NOT share
# a convention.
#
#   AIFS — a running total since initialisation. Its domain mean is monotone in
#          lead time (0.335, 0.787, 1.198, 1.583, ...), which only happens for a
#          cumulative field. Records are 6-hourly, so the increment covering a
#          period is v(h) - v(h-6). That increment is ALREADY a mean rate in
#          mm/h, not an amount in mm — see RATE_CUMULATED_PRECIP_MODELS.
#   GEFS — buckets that reset every 6 h: records at h % 6 == 3 cover 3 h,
#          records at h % 6 == 0 cover 6 h. Over ~100k records the h%6==0 mean
#          is 1.86x the h%6==3 mean, i.e. ~2x, the standard NCEP pattern.
#          Divide each record by its own period; no differencing.
#   UKMO — an hourly mean rate, already mm/h.
#
# Everything downstream works in mm/h, verified against the mean observed rate
# over the *same* period, so models with different cadences stay comparable.
#
# Nominal output cadence per model. This is the emit interval, NOT necessarily
# the period a record covers — use _precip_period_hours() for that.
MODEL_ACCUM_HOURS = {
    'AIFS': 6,
    'GEFS': 3,
    'UKMO': 1,
}


# Models whose stored precipitation value is a running total since init.
CUMULATIVE_PRECIP_MODELS = {'AIFS'}


# Models whose stored precipitation is ALREADY a mean rate in mm/h rather than
# an amount in mm. Their JSON export converted to mm/h before loading — the
# loader folders say so (`json_data_aifs_ensemble_scaled`,
# `json_data_gefs_ensemble_scaled`; UKMO is native mm/h and was never scaled).
# Dividing such a value by its window again understates it by exactly that
# factor.
#
# For a cumulative model (AIFS) it is the *increment* that is already a rate;
# for a bucketed one (GEFS) it is the stored value itself. Either way the
# divisor is 1.
#
# AIFS was established three independent ways from the loaded 2025-09-08 00Z run
# (METRICS_AUDIT.md finding 12):
#
#   1. Cell-level fit of the AIFS 6-h increment against the observed mean rate
#      over the same window: obs = 1.15*incr + 0.07, n=3953, obs/incr = 1.33 —
#      an ordinary model dry bias. Reading the increment as an amount instead
#      gives obs/forecast = 7.98, which is 6 x 1.33.
#   2. Domain-mean rate over 6-18 h, no observations involved: AIFS 0.431
#      against GEFS 0.381 and UKMO 0.559 mm/h. Dividing by 6 puts AIFS at
#      0.072 mm/h, an order of magnitude outside the family.
#   3. 48-h water budget: summing the 6-h mean rates x 6 h gives 17.95 mm
#      against 17.64 mm observed (1.8%). As an amount it would be 2.99 mm.
#
# GEFS reads the same way, confirmed against the same run:
#
#   4. Dividing the stored value by its bucket length gives a domain mean of
#      0.053 mm/h against 0.387 observed — the same ~7x understatement.
#      Read as-is it is 0.235, and in family with UKMO's unscaled 0.418.
#
# The record still COVERS its own window — _precip_period_hours is unchanged, so
# each record is matched against the observed mean rate over the same window.
# Only the divisor that converts the stored value to mm/h changes.
#
RATE_STORED_PRECIP_MODELS = {'AIFS', 'GEFS'}

# Retained under its former name for callers that imported it directly.
RATE_CUMULATED_PRECIP_MODELS = RATE_STORED_PRECIP_MODELS


# Hours the JSON export divided each model's precipitation by on its way to mm/h.
# Straight from Data_convert_weave/"aifs react.py":
#
#     scale_json_files(... scale_factor=6, model_name='AIFS')
#     scale_json_files(... scale_factor=3, model_name='GEFS')
#
# One fixed factor per model, applied to every record regardless of the window
# that record covers. UKMO is absent because it was never scaled — React.py
# converts its native `total_rainfall_rate` (m/s) straight to mm/h with x3.6e6.
#
# The factor is right where it matches the record: AIFS is 6-hourly throughout,
# and GEFS's h%6==3 buckets really are 3 h. It is wrong for GEFS's h%6==0
# buckets, which cover 6 h but were divided by 3, leaving them 2x too high.
SCALED_EXPORT_DIVISOR_HOURS = {'AIFS': 6.0, 'GEFS': 3.0}


def _infer_scaled_export_divisor(ratios, min_samples=100):
    """Which divisor the export used, inferred from the loaded data itself.

    `ratios` are, per cell and per cycle, the stored `h%6==0` record over the
    stored `h%6==3` record before it. The two conventions separate cleanly:

      flat divisor      stored_6h/stored_3h = A(0-6) / A(0-3)       ~ 2.0
      per-window        stored_6h/stored_3h = A(0-6) / (2 * A(0-3)) ~ 1.0

    because the 6 h accumulation contains the 3 h one and runs about twice it.
    Dividing by the record's own window halves that ratio; a flat divisor leaves
    it alone.

    Returns 3.0 (flat — the stored 6 h records need halving), 6.0 (per-window —
    nothing to correct), or None when the sample is too small or the median
    falls between the two, which is a signal to look rather than to guess.

    This exists so the declared SCALED_EXPORT_DIVISOR_HOURS can be checked
    against reality instead of trusted. Re-exporting without updating the
    constant would otherwise apply the correction twice, silently.
    """
    usable = sorted(r for r in ratios if r and r > 0 and math.isfinite(r))
    if len(usable) < min_samples:
        return None
    median = usable[len(usable) // 2]
    if median >= 1.5:
        return 3.0
    if median <= 1.25:
        return 6.0
    return None


def _increment_divisor(model_name, period):
    """Hours to divide a stored precipitation value (or a differenced cumulative
    increment) by to reach mm/h.

    A scaled model was already divided once, by a fixed per-model factor, so what
    remains is the ratio of the record's true window to that factor. GEFS's 3 h
    buckets come out at 1 (already correct) and its 6 h buckets at 2 (halved);
    AIFS is 6/6 = 1 throughout. An unscaled model still stores an amount and
    divides by its own window.
    """
    exported = SCALED_EXPORT_DIVISOR_HOURS.get(model_name)
    if exported:
        return period / exported
    return period


# Every model is verified over this many hours, whatever cadence it emits at.
#
# A threshold only means one thing if the window means one thing. A 1 h mean rate
# keeps peaks that a 6 h mean averages away, so a short-window model crosses a
# high bar more often for no reason but its cadence — on the loaded run, UKMO's
# hourly records exceeded 25 mm/6h 1.64x more often than the identical data
# averaged to 6 h. Comparing its CSI against AIFS's 6-hourly CSI was therefore
# comparing two different questions.
#
# 6 h is the coarsest native window in the set (AIFS throughout, GEFS at
# h%6==0), so it is the only one every model can supply without inventing data.
COMMON_VERIFICATION_WINDOW_HOURS = 6


def _rebin_to_common_window(rates, window=COMMON_VERIFICATION_WINDOW_HOURS):
    """{hour: (rate, std, period)} -> the same series on one common window.

    A record already spanning `window` passes through untouched. Shorter records
    are combined into it, weighted by their own periods, and only when they tile
    the window exactly — a partial cover would understate the mean rate, which is
    the same trap `_obs_window_mean` guards against on the observation side.
    Anything that neither spans nor tiles the window is dropped.

    Spread does not survive the combination: the spread of a mean is not the mean
    of spreads, and the members needed to compute it properly are not in scope
    here. Combined records return None, which SSR/CRPS/Brier already skip.
    """
    if not rates:
        return {}
    out = {}
    for target in sorted(h for h in rates if h > 0 and h % window == 0):
        record = rates.get(target)
        if record is not None and record[2] == window:
            out[target] = record                      # already the right span
            continue
        # Records whose own (h-period, h] lies inside (target-window, target].
        parts = [(rate, period) for hour, (rate, _std, period) in rates.items()
                 if hour <= target and hour - period >= target - window]
        covered = sum(period for _rate, period in parts)
        if parts and covered == window:
            mean = sum(rate * period for rate, period in parts) / window
            out[target] = (mean, None, window)
    return out


def _obs_window_mean(cell_obs, valid_time, period):
    """Mean observed rate over the window (valid_time - period, valid_time].

    Returns (mean, covered_hours, n_samples). `covered_hours` counts how many of
    the `period` one-hour slots in the window contain at least one observation,
    so the caller can reject a partially observed window — scoring a 6 h forecast
    against whatever single observation happens to survive at the end of the
    record is worse than reporting no score at all.

    Every observation inside the window contributes, including sub-hourly ones:
    IMERG is half-hourly, and averaging both samples per hour estimates the
    period mean better than taking the top of each hour alone. So n_samples can
    exceed covered_hours, and the two mean different things.
    """
    if not cell_obs:
        return None, 0, 0
    start  = valid_time - timedelta(hours=period)
    values = []
    slots  = set()
    for obs_time, value in cell_obs.items():
        if not (start < obs_time <= valid_time):
            continue
        values.append(value)
        # Slot 0 is (start, start+1h], slot period-1 ends at valid_time.
        offset = (obs_time - start).total_seconds() / 3600.0
        slots.add(min(period - 1, max(0, math.ceil(offset) - 1)))
    if not values:
        return None, 0, 0
    return sum(values) / len(values), len(slots), len(values)


def _precip_period_hours(model_name, forecast_hour):
    """Hours covered by one precipitation record ending at `forecast_hour`."""
    if model_name == 'GEFS':
        # 0-3 / 0-6 / 6-9 / 6-12 ... — the bucket resets every 6 h.
        return 3 if forecast_hour % 6 == 3 else 6
    if model_name in CUMULATIVE_PRECIP_MODELS:
        return MODEL_ACCUM_HOURS.get(model_name, 1)
    return MODEL_ACCUM_HOURS.get(model_name, 1)


def _precip_lookback_hours(model_name):
    """Extra lead time to fetch below hour_min so the first in-range record of a
    cumulative model still has the predecessor it needs to be differenced."""
    return MODEL_ACCUM_HOURS.get(model_name, 1) if model_name in CUMULATIVE_PRECIP_MODELS else 0


def _precip_member_rate_series(model_name, series, is_wind=False):
    """Scalar sibling of _precip_rate_series, for a single ensemble member.

    {hour: value} -> {hour: (rate, period_h)}. Members carry no spread of their
    own, so nothing is approximated here: differencing a cumulative model
    per-member is EXACT, and the spread of the differenced members is the true
    spread of the increment — which the aggregate mean/std path can only
    estimate (see _precip_rate_series).
    """
    if is_wind:
        return {h: (v, 1) for h, v in series.items()}
    cumulative = model_name in CUMULATIVE_PRECIP_MODELS
    out = {}
    for hour in sorted(series):
        period = _precip_period_hours(model_name, hour)
        value  = series[hour]
        if not cumulative:
            out[hour] = (value / _increment_divisor(model_name, period), period)
            continue
        prev_hour = hour - period
        if prev_hour <= 0:
            amount = value                       # accumulated from init
        elif prev_hour in series:
            amount = value - series[prev_hour]
        else:
            continue                             # can't difference — drop
        out[hour] = (max(0.0, amount) / _increment_divisor(model_name, period), period)
    return out


def _precip_rate_series(model_name, series, is_wind=False):
    """{hour: (mean, std)} -> {hour: (mean_rate, std_rate|None, period_h)}, mm/h.

    Wind is instantaneous and passes through unchanged (period 1).

    Cumulative models are differenced against the record one period earlier;
    bucketed models are divided by their own period. A cumulative record whose
    predecessor is missing is dropped rather than guessed — except at the first
    period of the run, where the predecessor is implicitly zero at init.

    Spread: for a cumulative model the stored std is the spread of the *total*,
    and the increment's spread is not exactly recoverable from it. Under
    independent increments Var(inc) = Var(C_h) - Var(C_h-p), which comes out
    negative for ~13% of AIFS records, so this is an approximation and those
    records get std_rate None. Spread-dependent metrics (SSR, CRPS, Brier) skip
    a None; the deterministic ones (bias/MAE/RMSE/CSI/POD/FAR) are unaffected
    because they never touch the spread.
    """
    if is_wind:
        return {h: (mean, std, 1) for h, (mean, std) in series.items()}

    cumulative = model_name in CUMULATIVE_PRECIP_MODELS
    out = {}
    for hour in sorted(series):
        mean, std = series[hour]
        period    = _precip_period_hours(model_name, hour)
        if not cumulative:
            div = _increment_divisor(model_name, period)
            out[hour] = (mean / div, (std / div) if std is not None else None, period)
            continue

        prev_hour = hour - period
        if prev_hour <= 0:
            amount   = mean                       # accumulated from init; implicit 0 at t=0
            variance = (std ** 2) if std is not None else None
        elif prev_hour in series:
            prev_mean, prev_std = series[prev_hour]
            amount = mean - prev_mean
            if std is None or prev_std is None:
                variance = None
            else:
                variance = std ** 2 - prev_std ** 2
        else:
            continue                              # can't difference — drop the record

        # Cumulative totals are non-decreasing; a small negative is rounding.
        amount    = max(0.0, amount)
        divisor   = _increment_divisor(model_name, period)
        std_rate  = (math.sqrt(variance) / divisor) if (variance is not None and variance > 0) else None
        out[hour] = (amount / divisor, std_rate, period)
    return out


def _categorical_summary(hours_list):
    """Pool per-hour contingency counts into one aggregate score set.

    CSI/POD/FAR come from summed hits/misses/false alarms across every lead
    time (an event-weighted score), not the mean of per-hour ratios. FSS uses
    the same domain-fractions convention as the per-hour path, with the
    forecast/observed event fractions pooled over all points × lead times.
    Returns None-valued fields when a denominator is empty.
    """
    if not hours_list:
        return None
    hits   = sum(h.get('hits',   0) or 0 for h in hours_list)
    misses = sum(h.get('misses', 0) or 0 for h in hours_list)
    fa     = sum(h.get('false_alarms', 0) or 0 for h in hours_list)
    n_pts  = sum(h.get('n_pts',  0) or 0 for h in hours_list)

    csi_den  = hits + misses + fa
    obs_yes  = hits + misses
    fcst_yes = hits + fa

    # FSS aggregates by summing each lead time's numerator and denominator, the
    # standard multi-case form. Pooling the event fractions instead would throw
    # away the neighbourhood structure the per-hour score was built on.
    fss_num = sum(h.get('fss_num') or 0.0 for h in hours_list)
    fss_den = sum(h.get('fss_den') or 0.0 for h in hours_list)

    return {
        'csi':     round(hits / csi_den,  4) if csi_den  > 0 else None,
        'pod':     round(hits / obs_yes,  4) if obs_yes  > 0 else None,
        'far':     round(fa   / fcst_yes, 4) if fcst_yes > 0 else None,
        'fss':     _fss_from_components(fss_num, fss_den),
        'hits':    hits,
        'misses':  misses,
        'false_alarms': fa,
        'n_pts':   n_pts,
        'n_hours': len(hours_list),
    }


def _region_mean(points):
    """Unweighted mean of a metric's per-cell values (None if empty).

    This is what the MAP shows averaged, so it stays available — but it is not
    what the region headline reports; see _region_pooled_metrics.
    """
    if not points:
        return None
    return round(float(np.mean([p['value'] for p in points])), 4)


def _fss_from_pairs(pairs, threshold_rate, window):
    """Aggregated FSS over a region, from matched fcst/obs pairs.

    FSS has no per-cell value — it is a property of a whole field at a lead
    time — so it can't be averaged out of a points list the way the other
    region metrics are. This rebuilds the binary forecast/observed fields for
    each lead time, takes that hour's numerator and denominator, and forms the
    ratio once over all of them (the standard multi-case aggregation).

    Returns None when no lead time has an event in either field.
    """
    by_hour = {}
    for (lat, lon), entries in pairs.items():
        for hour, mean_rate, _std_rate, obs_rate in entries:
            f, o = by_hour.setdefault(hour, ({}, {}))
            f[(lat, lon)] = float(mean_rate > threshold_rate)
            o[(lat, lon)] = float(obs_rate  > threshold_rate)

    total_num = total_den = 0.0
    for f, o in by_hour.values():
        num, den, n = _fss_components(f, o, window)
        if n:
            total_num += num
            total_den += den
    return _fss_from_components(total_num, total_den)


def _region_pooled_metrics(pairs, metrics, threshold_rate, n_members=None,
                           fss_window=3):
    """Region metrics pooled over every (cell, lead time) sample.

    Averaging per-cell scores gives a cell with two samples the same weight as
    one with fifty, and for ratio metrics (CSI/POD/FAR) and RMSE the mean of the
    per-cell values isn't the region score at all — a mean of ratios is not the
    ratio of the pooled counts, and the mean of per-cell RMSE is not the domain
    RMSE because the square root isn't linear. Pooling matches the estimator
    point mode already uses (_categorical_summary).

    `correlation` is absent here on purpose: it is a per-cell correlation across
    lead times, so it has no pooled form and stays a mean over cells.
    """
    errs, sq_errs, abs_errs = [], [], []
    variances, crps_vals, brier_vals = [], [], []
    hits = misses = false_alarms = 0

    for entries in pairs.values():
        for _hour, mean_rate, std_rate, obs_rate in entries:
            err = mean_rate - obs_rate
            errs.append(err)
            abs_errs.append(abs(err))
            sq_errs.append(err ** 2)

            if std_rate is not None:
                variances.append(std_rate ** 2)
                crps_vals.append(_gaussian_crps(mean_rate, std_rate, obs_rate))
                brier_vals.append(
                    (_exceedance_probability(mean_rate, std_rate, threshold_rate)
                     - float(obs_rate > threshold_rate)) ** 2)

            is_fcst = mean_rate > threshold_rate
            is_obs  = obs_rate  > threshold_rate
            if   is_fcst and     is_obs: hits         += 1
            elif is_fcst and not is_obs: false_alarms += 1
            elif not is_fcst and is_obs: misses       += 1

    if not errs:
        return {}

    n            = len(errs)
    csi_den      = hits + misses + false_alarms
    obs_yes      = hits + misses
    fcst_yes     = hits + false_alarms
    mean_sq_err  = sum(sq_errs) / n

    out = {
        'bias':  round(sum(errs) / n, 4),
        'mae':   round(sum(abs_errs) / n, 4),
        'rmse':  round(math.sqrt(mean_sq_err), 4),
        'crps':  round(sum(crps_vals) / len(crps_vals), 4) if crps_vals else None,
        'brier': round(sum(brier_vals) / len(brier_vals), 6) if brier_vals else None,
        'csi':   round(hits / csi_den,  4) if csi_den  else None,
        'pod':   round(hits / obs_yes,  4) if obs_yes  else None,
        'far':   round(false_alarms / fcst_yes, 4) if fcst_yes else None,
        'ssr_agg': (_ssr_from_variances(sum(variances) / len(variances),
                                        mean_sq_err, n_members)
                    if variances else None),
    }
    # FSS is spatial and per-lead-time, so it is built from the fields rather
    # than pooled from the flat sample above. Only compute it when asked, since
    # it walks the pairs a second time.
    if 'fss' in metrics:
        out['fss'] = _fss_from_pairs(pairs, threshold_rate, fss_window)
    return {k: v for k, v in out.items() if k in metrics}


def _spatial_diff_points(pts_a, pts_b):
    """Per-cell A − B over the cells the two models share.

    Cells are keyed by a 0.25° snap — the same key the renderer and the
    correlation path use. Plain 2-dp rounding is not enough: `correlation`
    reports each model's *native* coordinates, which differ between models, so
    a 2-dp key matched zero cells across models even over an identical region.
    Returns (diff_points, n_cells_a, n_cells_b).
    """
    def _cell(p):
        return (round(p['lat'] * 4) / 4, round(p['lon'] * 4) / 4)

    a_by_cell = {_cell(p): float(p['value']) for p in pts_a}
    b_by_cell = {_cell(p): float(p['value']) for p in pts_b}
    common    = sorted(set(a_by_cell) & set(b_by_cell))

    diff_points = [
        {'lat': lat, 'lon': lon,
         'value': round(a_by_cell[(lat, lon)] - b_by_cell[(lat, lon)], 6)}
        for (lat, lon) in common
    ]
    return diff_points, len(a_by_cell), len(b_by_cell)
