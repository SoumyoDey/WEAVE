"""Golden-vector tests for the WEAVE verification metrics.

These lock in the scientific math (SSR, CRPS, bias/MAE/RMSE, CSI/POD/FAR, FSS)
against hand-computed expected values so future edits can't silently regress it —
in particular the P1 fixes: the SSR clamp and the Roberts-Lean FSS convention
(f^2 + o^2 reference; None when neither field has an event).

No database is used: accuracy metrics run against a monkeypatched
_fetch_fcst_obs_pairs_spatial, and the categorical/FSS path runs against a fake
cursor that returns canned rows. See conftest.py for the DB-pool stub.

Run:  cd Data && ~/miniconda3/envs/afw/bin/python -m pytest -q
"""
import math
from datetime import datetime, timedelta

import pytest

import flask_api as api


# The tuple stored per matched lead time by _fetch_fcst_obs_pairs_spatial:
#   (forecast_hour, mean_rate, std_rate, obs_rate)   — all rates in mm/h.


# ── Pure helpers ──────────────────────────────────────────────────────────────
class TestClampSSR:
    def test_passthrough(self):
        assert api._clamp_ssr(0.4) == 0.4

    def test_zero_is_kept(self):
        assert api._clamp_ssr(0.0) == 0.0

    def test_caps_at_ten(self):
        assert api._clamp_ssr(55.0) == 10.0
        assert api._clamp_ssr(10.0) == 10.0

    def test_none_for_non_finite(self):
        assert api._clamp_ssr(float("inf")) is None
        assert api._clamp_ssr(float("nan")) is None

    def test_none_for_negative(self):
        assert api._clamp_ssr(-1.0) is None

    def test_none_for_none(self):
        assert api._clamp_ssr(None) is None


class TestValidMember:
    @pytest.mark.parametrize("m", ["mean", "std", "0", "5", "49"])
    def test_valid(self, m):
        assert api._valid_member(m) is True

    @pytest.mark.parametrize("m", ["foo", "", "1.5", None, "3abc"])
    def test_invalid(self, m):
        assert api._valid_member(m) is False


# ── Accuracy metrics (bias / MAE / RMSE / CRPS / SSR-agg) ─────────────────────
@pytest.fixture
def patch_pairs(monkeypatch):
    """Make the accuracy compute functions see a fixed set of matched pairs."""
    def _set(pairs):
        monkeypatch.setattr(api, "_fetch_fcst_obs_pairs_spatial",
                            lambda *a, **k: pairs)
    return _set


def _single_value(points):
    assert len(points) == 1, f"expected one grid point, got {points}"
    return points[0]["value"]


# mean errors of +1 and +2 at one grid point.
PAIRS = {(36.0, -79.5): [(6, 2.0, 1.0, 1.0), (12, 3.0, 1.0, 1.0)]}


def test_bias(patch_pairs):
    patch_pairs(PAIRS)
    assert _single_value(
        api._compute_bias_points_rf(None, "AIFS", "precipitation", 0, 1, 0, 1)
    ) == 1.5  # mean(1, 2)


def test_mae(patch_pairs):
    patch_pairs(PAIRS)
    assert _single_value(
        api._compute_mae_points_rf(None, "AIFS", "precipitation", 0, 1, 0, 1)
    ) == 1.5  # mean(|1|, |2|)


def test_rmse(patch_pairs):
    patch_pairs(PAIRS)
    assert _single_value(
        api._compute_rmse_points_rf(None, "AIFS", "precipitation", 0, 1, 0, 1)
    ) == round(math.sqrt((1 + 4) / 2), 4)  # 1.5811


def test_ssr_agg(patch_pairs):
    patch_pairs(PAIRS)
    # mean(sigma^2) = 1 ; mean(err^2) = (1 + 4) / 2 = 2.5 ; SSR = 0.4
    assert _single_value(
        api._compute_ssr_agg_points_rf(None, "AIFS", "precipitation", 0, 1, 0, 1)
    ) == 0.4


def test_ssr_agg_is_capped(patch_pairs):
    # Near-zero error → enormous ratio → clamped to the colourbar ceiling (10).
    patch_pairs({(1.0, 1.0): [(6, 1.001, 1.0, 1.0), (12, 1.001, 1.0, 1.0)]})
    assert _single_value(
        api._compute_ssr_agg_points_rf(None, "AIFS", "precipitation", 0, 1, 0, 1)
    ) == 10.0


def test_ssr_agg_needs_two_pairs(patch_pairs):
    patch_pairs({(1.0, 1.0): [(6, 2.0, 1.0, 1.0)]})  # only one pair
    assert api._compute_ssr_agg_points_rf(None, "AIFS", "precipitation", 0, 1, 0, 1) == []


def test_crps_deterministic(patch_pairs):
    # sigma ~ 0 → CRPS reduces to the absolute error |mean - obs|.
    patch_pairs({(1.0, 1.0): [(6, 5.0, 0.0, 3.0)]})
    assert _single_value(
        api._compute_crps_points_rf(None, "AIFS", "precipitation", 0, 1, 0, 1)
    ) == 2.0


def test_crps_gaussian_at_mean(patch_pairs):
    # obs == mean, sigma = 1 → CRPS = (1/sqrt(pi)) * (sqrt(2) - 1) ≈ 0.2337,
    # the known CRPS of a standard normal evaluated at its mean.
    patch_pairs({(1.0, 1.0): [(6, 5.0, 1.0, 5.0)]})
    assert _single_value(
        api._compute_crps_points_rf(None, "AIFS", "precipitation", 0, 1, 0, 1)
    ) == pytest.approx(0.2337, abs=1e-4)


# ── Categorical metrics (CSI / POD / FAR) with an explicit threshold ──────────
# threshold_rate = 1.5 mm/h. Four lead times: hit, false-alarm, miss, correct-neg.
CAT_PAIRS = {(36.0, -79.5): [
    (6,  2.0, 1.0, 2.0),   # fcst>thr, obs>thr  → hit
    (12, 2.0, 1.0, 1.0),   # fcst>thr, obs<=thr → false alarm
    (18, 1.0, 1.0, 2.0),   # fcst<=thr, obs>thr → miss
    (24, 1.0, 1.0, 1.0),   # both <=thr         → correct negative
]}


def test_csi(patch_pairs):
    patch_pairs(CAT_PAIRS)
    v = _single_value(api._compute_csi_points_rf(
        None, "AIFS", "precipitation", 0, 1, 0, 1, threshold_rate=1.5))
    assert v == round(1 / 3, 4)  # hits / (hits + misses + fa) = 1/3


def test_pod(patch_pairs):
    patch_pairs(CAT_PAIRS)
    v = _single_value(api._compute_pod_points_rf(
        None, "AIFS", "precipitation", 0, 1, 0, 1, threshold_rate=1.5))
    assert v == 0.5  # hits / (hits + misses) = 1/2


def test_far(patch_pairs):
    patch_pairs(CAT_PAIRS)
    v = _single_value(api._compute_far_points_rf(
        None, "AIFS", "precipitation", 0, 1, 0, 1, threshold_rate=1.5))
    assert v == 0.5  # fa / (hits + fa) = 1/2


# ── Per-hour categorical + FSS via the neighbourhood helper ───────────────────
class FakeCursor:
    """Returns queued result sets on successive execute()+fetch calls."""
    def __init__(self, queue):
        self._queue = list(queue)
        self._cur = []

    def execute(self, *args, **kwargs):
        self._cur = self._queue.pop(0) if self._queue else []

    def fetchone(self):
        return self._cur[0] if self._cur else None

    def fetchall(self):
        return list(self._cur)

    def close(self):
        pass


def _run_box(fcst_rows, obs_rows, init):
    """Drive _categorical_hours_for_box with canned rows (UKMO → hourly rates)."""
    cur = FakeCursor([[{"initialization_time": init}], fcst_rows, obs_rows])
    with api.app.app_context():
        return api._categorical_hours_for_box(
            cur, "UKMO", "precipitation", "precipitation", "GPM_IMERG_V07B",
            35.0, 37.0, -80.5, -78.5, 0, 24, threshold_rate=5.0)


def test_categorical_hours_and_fss():
    init = datetime(2025, 9, 8, 0, 0, 0)
    vt = init + timedelta(hours=6)
    fcst_rows = [
        {"forecast_hour": 6, "latitude": 36.0, "longitude": -79.5, "mean_value": 10.0, "std_dev": 1.0},
        {"forecast_hour": 6, "latitude": 36.5, "longitude": -79.5, "mean_value": 0.0,  "std_dev": 1.0},
    ]
    obs_rows = [
        {"obs_time": vt, "latitude": 36.0, "longitude": -79.5, "obs_val": 8.0},
        {"obs_time": vt, "latitude": 36.5, "longitude": -79.5, "obs_val": 8.0},
    ]
    hours = _run_box(fcst_rows, obs_rows, init)
    assert len(hours) == 1
    h = hours[0]
    assert h["hour"] == 6 and h["n_pts"] == 2
    # cell1: fcst 10>5 & obs 8>5 → hit ; cell2: fcst 0 & obs 8>5 → miss
    assert h["csi"] == 0.5   # 1 / (1 hit + 1 miss + 0 fa)
    assert h["pod"] == 0.5   # 1 / (1 hit + 1 miss)
    assert h["far"] == 0.0   # 0 / (1 hit + 0 fa)
    # fcst_frac = 0.5, obs_frac = 1.0 → 1 - (0.5-1)^2 / (0.5^2 + 1^2) = 1 - 0.25/1.25
    assert h["fss"] == 0.8


# ── Precipitation record semantics (METRICS_AUDIT findings 1 & 2) ─────────────
class TestPrecipPeriodHours:
    def test_aifs_is_six_hourly(self):
        assert api._precip_period_hours("AIFS", 6) == 6
        assert api._precip_period_hours("AIFS", 24) == 6

    def test_gefs_alternates_three_and_six(self):
        # 0-3, 0-6, 6-9, 6-12 ... — the bucket resets every 6 h.
        assert api._precip_period_hours("GEFS", 3) == 3
        assert api._precip_period_hours("GEFS", 6) == 6
        assert api._precip_period_hours("GEFS", 9) == 3
        assert api._precip_period_hours("GEFS", 12) == 6

    def test_ukmo_is_hourly(self):
        assert api._precip_period_hours("UKMO", 5) == 1

    def test_lookback_only_for_cumulative_models(self):
        assert api._precip_lookback_hours("AIFS") == 6
        assert api._precip_lookback_hours("GEFS") == 0
        assert api._precip_lookback_hours("UKMO") == 0


class TestPrecipRateSeries:
    def test_aifs_cumulative_is_differenced(self):
        """AIFS stores a running total, so the rate is the increment / 6 —
        not the total / 6, which grows without bound with lead time."""
        series = {6: (0.6, 0.0), 12: (1.2, 0.0), 18: (1.5, 0.0)}
        rates = api._precip_rate_series("AIFS", series)
        assert rates[6][0] == pytest.approx(0.6 / 6)    # from init
        assert rates[12][0] == pytest.approx(0.6 / 6)   # (1.2 - 0.6) / 6
        assert rates[18][0] == pytest.approx(0.3 / 6)   # (1.5 - 1.2) / 6

    def test_aifs_drops_a_record_it_cannot_difference(self):
        series = {24: (3.0, 0.1)}          # no h=18 to difference against
        assert api._precip_rate_series("AIFS", series) == {}

    def test_aifs_negative_increment_is_clamped(self):
        """Cumulative totals are non-decreasing; a small dip is rounding."""
        series = {6: (1.0, 0.0), 12: (0.999, 0.0)}
        assert api._precip_rate_series("AIFS", series)[12][0] == 0.0

    def test_gefs_uses_each_records_own_period(self):
        # equal totals at h=3 (3 h) and h=6 (6 h) are NOT equal rates
        series = {3: (0.9, 0.0), 6: (0.9, 0.0)}
        rates = api._precip_rate_series("GEFS", series)
        assert rates[3][0] == pytest.approx(0.3)   # 0.9 / 3
        assert rates[6][0] == pytest.approx(0.15)  # 0.9 / 6
        assert rates[3][2] == 3 and rates[6][2] == 6

    def test_ukmo_passes_through(self):
        series = {5: (2.0, 0.5)}
        assert api._precip_rate_series("UKMO", series)[5] == (2.0, 0.5, 1)

    def test_wind_is_never_rescaled(self):
        series = {6: (12.0, 3.0), 12: (14.0, 4.0)}
        rates = api._precip_rate_series("AIFS", series, is_wind=True)
        assert rates == {6: (12.0, 3.0, 1), 12: (14.0, 4.0, 1)}

    def test_cumulative_spread_uses_variance_difference(self):
        # sigma 5 -> 13 : sqrt(169 - 25) = 12, then / 6
        series = {6: (1.0, 5.0), 12: (2.0, 13.0)}
        assert api._precip_rate_series("AIFS", series)[12][1] == pytest.approx(12.0 / 6)

    def test_cumulative_spread_is_none_when_variance_shrinks(self):
        """~13% of real AIFS records have a shrinking cumulative variance, where
        the increment spread isn't recoverable — must be None, not fabricated."""
        series = {6: (1.0, 9.0), 12: (2.0, 4.0)}
        rate, std, _ = api._precip_rate_series("AIFS", series)[12]
        assert std is None
        assert rate == pytest.approx(1.0 / 6)   # the amount is still fine

    def test_spread_none_is_skipped_by_spread_metrics(self, monkeypatch):
        """A None spread must drop out of CRPS/Brier/ssr_agg, not crash them."""
        pairs = {(36.0, -79.5): [(6, 2.0, None, 1.0), (12, 3.0, None, 1.0)]}
        monkeypatch.setattr(api, "_fetch_fcst_obs_pairs_spatial", lambda *a, **k: pairs)
        assert api._compute_crps_points_rf(None, "AIFS", "precipitation", 0, 1, 0, 1) == []
        assert api._compute_brier_points_rf(None, "AIFS", "precipitation", 0, 1, 0, 1) == []
        assert api._compute_ssr_agg_points_rf(None, "AIFS", "precipitation", 0, 1, 0, 1) == []
        # deterministic metrics are unaffected — they never touch the spread
        assert _single_value(
            api._compute_bias_points_rf(None, "AIFS", "precipitation", 0, 1, 0, 1)) == 1.5


# ── Region aggregation (compare/region-metrics) ───────────────────────────────
class TestRegionMetrics:
    def test_region_mean_averages_cells(self):
        assert api._region_mean([{"value": 1.0}, {"value": 2.0}, {"value": 6.0}]) == 3.0

    def test_region_mean_none_when_empty(self):
        assert api._region_mean([]) is None
        assert api._region_mean(None) is None

    def test_one_fetch_shared_by_every_pairs_metric(self, monkeypatch):
        """The fcst↔obs match is fetched once per model, not once per metric."""
        calls = []
        monkeypatch.setattr(api, "_fetch_fcst_obs_pairs_spatial",
                            lambda *a, **k: (calls.append(a), PAIRS)[1])
        points, n_cells = api._region_metric_points(
            None, "AIFS", "precipitation",
            ["bias", "mae", "rmse", "correlation"],
            0, 1, 0, 1, 0, 24, threshold_rate=1.5)
        assert len(calls) == 1
        assert n_cells == 1
        # correlation runs the ensemble path, so it isn't in the pairs table
        assert set(points) == {"bias", "mae", "rmse"}
        assert api._region_mean(points["bias"]) == 1.5   # mean(+1, +2)
        assert api._region_mean(points["mae"]) == 1.5
        assert api._region_mean(points["rmse"]) == round(math.sqrt(2.5), 4)

    def test_threshold_reaches_categorical_metrics(self, monkeypatch):
        monkeypatch.setattr(api, "_fetch_fcst_obs_pairs_spatial",
                            lambda *a, **k: CAT_PAIRS)
        points, _ = api._region_metric_points(
            None, "AIFS", "precipitation", ["csi", "pod", "far"],
            0, 1, 0, 1, 0, 24, threshold_rate=1.5)
        assert api._region_mean(points["csi"]) == round(1 / 3, 4)
        assert api._region_mean(points["pod"]) == 0.5
        assert api._region_mean(points["far"]) == 0.5

    def test_mean_is_over_cells_not_lead_times(self, monkeypatch):
        """Two cells with different sample counts still weigh equally — the
        region value is the mean of per-cell metrics, matching the maps."""
        monkeypatch.setattr(api, "_fetch_fcst_obs_pairs_spatial", lambda *a, **k: {
            (36.0, -79.5): [(6, 2.0, 1.0, 1.0)],                       # bias +1
            (36.5, -79.5): [(6, 4.0, 1.0, 1.0), (12, 4.0, 1.0, 1.0)],  # bias +3
        })
        points, n_cells = api._region_metric_points(
            None, "AIFS", "precipitation", ["bias"],
            0, 1, 0, 1, 0, 24, threshold_rate=1.5)
        assert n_cells == 2
        assert api._region_mean(points["bias"]) == 2.0   # mean(1, 3), not 7/3

    def test_no_pairs_metrics_skips_the_fetch(self, monkeypatch):
        monkeypatch.setattr(api, "_fetch_fcst_obs_pairs_spatial",
                            lambda *a, **k: pytest.fail("should not query"))
        assert api._region_metric_points(
            None, "AIFS", "precipitation", ["correlation"],
            0, 1, 0, 1, 0, 24, threshold_rate=1.5) == ({}, 0)


# ── Spatial difference (compare/spatial-diff) ─────────────────────────────────
class TestSpatialDiffPoints:
    def test_subtracts_at_matching_cells(self):
        a = [{"lat": 36.0, "lon": -75.5, "value": 2.0},
             {"lat": 36.25, "lon": -75.5, "value": 1.0}]
        b = [{"lat": 36.0, "lon": -75.5, "value": 0.5},
             {"lat": 36.25, "lon": -75.5, "value": 4.0}]
        diff, n_a, n_b = api._spatial_diff_points(a, b)
        assert (n_a, n_b) == (2, 2)
        assert [d["value"] for d in diff] == [1.5, -3.0]

    def test_keeps_only_shared_cells(self):
        a = [{"lat": 36.0, "lon": -75.5, "value": 2.0},
             {"lat": 40.0, "lon": -70.0, "value": 9.0}]   # A only
        b = [{"lat": 36.0, "lon": -75.5, "value": 0.5},
             {"lat": 30.0, "lon": -80.0, "value": 9.0}]   # B only
        diff, n_a, n_b = api._spatial_diff_points(a, b)
        assert (n_a, n_b) == (2, 2)
        assert len(diff) == 1
        assert diff[0]["lat"] == 36.0 and diff[0]["value"] == 1.5

    def test_snaps_native_coords_to_the_quarter_degree_grid(self):
        """Models report slightly different native coordinates for the same
        cell (the `correlation` path does), so the key has to snap."""
        a = [{"lat": 36.01, "lon": -75.49, "value": 2.0}]
        b = [{"lat": 35.98, "lon": -75.52, "value": 0.5}]
        diff, _, _ = api._spatial_diff_points(a, b)
        assert len(diff) == 1
        assert diff[0]["value"] == 1.5

    def test_empty_when_nothing_overlaps(self):
        a = [{"lat": 36.0, "lon": -75.5, "value": 2.0}]
        b = [{"lat": 10.0, "lon": -150.0, "value": 2.0}]
        diff, n_a, n_b = api._spatial_diff_points(a, b)
        assert diff == [] and (n_a, n_b) == (1, 1)

    def test_empty_inputs(self):
        assert api._spatial_diff_points([], []) == ([], 0, 0)

    def test_mean_diff_matches_the_region_means(self):
        """The map's mean equals (region mean A) - (region mean B) when both
        models cover the same cells — so the diff map and the bars agree."""
        a = [{"lat": 36.0, "lon": -75.5, "value": 2.0},
             {"lat": 36.25, "lon": -75.5, "value": 4.0}]
        b = [{"lat": 36.0, "lon": -75.5, "value": 1.0},
             {"lat": 36.25, "lon": -75.5, "value": 1.0}]
        diff, _, _ = api._spatial_diff_points(a, b)
        mean_diff = sum(d["value"] for d in diff) / len(diff)
        assert mean_diff == api._region_mean(a) - api._region_mean(b)


# ── Pooled categorical summary (compare/categorical `summaries`) ──────────────
class TestCategoricalSummary:
    def test_none_for_empty(self):
        assert api._categorical_summary([]) is None

    def test_pools_counts_not_ratios(self):
        """Scores come from summed counts, so a sparse hour can't outweigh a
        dense one the way a mean of per-hour ratios would."""
        hours = [
            # 9 hits, 1 miss, 0 fa over 20 pts → per-hour POD 0.9
            {"hour": 6,  "n_pts": 20, "hits": 9, "misses": 1,
             "false_alarms": 0, "correct_neg": 10},
            # 0 hits, 1 miss, 1 fa over 2 pts  → per-hour POD 0.0
            {"hour": 12, "n_pts": 2,  "hits": 0, "misses": 1,
             "false_alarms": 1, "correct_neg": 0},
        ]
        s = api._categorical_summary(hours)
        assert s["pod"] == round(9 / 11, 4)          # not mean(0.9, 0.0) = 0.45
        assert s["csi"] == round(9 / (9 + 2 + 1), 4)
        assert s["far"] == round(1 / (9 + 1), 4)
        assert s["n_pts"] == 22 and s["n_hours"] == 2

    def test_fss_uses_pooled_fractions(self):
        hours = [{"hour": 6, "n_pts": 4, "hits": 1, "misses": 1,
                  "false_alarms": 0, "correct_neg": 2}]
        # f = (1+0)/4 = 0.25, o = (1+1)/4 = 0.5
        # FSS = 1 - (0.25-0.5)^2 / (0.25^2 + 0.5^2) = 1 - 0.0625/0.3125 = 0.8
        assert api._categorical_summary(hours)["fss"] == 0.8

    def test_fss_none_when_no_events(self):
        hours = [{"hour": 6, "n_pts": 4, "hits": 0, "misses": 0,
                  "false_alarms": 0, "correct_neg": 4}]
        s = api._categorical_summary(hours)
        assert s["fss"] is None
        assert s["csi"] is None and s["pod"] is None and s["far"] is None

    def test_matches_single_hour_per_hour_values(self):
        """One lead time → the pooled summary equals that hour's own scores."""
        init = datetime(2025, 9, 8, 0, 0, 0)
        vt = init + timedelta(hours=6)
        fcst_rows = [
            {"forecast_hour": 6, "latitude": 36.0, "longitude": -79.5, "mean_value": 10.0, "std_dev": 1.0},
            {"forecast_hour": 6, "latitude": 36.5, "longitude": -79.5, "mean_value": 0.0,  "std_dev": 1.0},
        ]
        obs_rows = [
            {"obs_time": vt, "latitude": 36.0, "longitude": -79.5, "obs_val": 8.0},
            {"obs_time": vt, "latitude": 36.5, "longitude": -79.5, "obs_val": 8.0},
        ]
        hours = _run_box(fcst_rows, obs_rows, init)
        s = api._categorical_summary(hours)
        for k in ("csi", "pod", "far", "fss"):
            assert s[k] == hours[0][k]


def test_fss_none_when_no_events():
    """Both fields event-free → FSS is undefined (None), not a misleading 1.0."""
    init = datetime(2025, 9, 8, 0, 0, 0)
    vt = init + timedelta(hours=6)
    fcst_rows = [
        {"forecast_hour": 6, "latitude": 36.0, "longitude": -79.5, "mean_value": 0.0, "std_dev": 1.0},
    ]
    obs_rows = [
        {"obs_time": vt, "latitude": 36.0, "longitude": -79.5, "obs_val": 0.0},
    ]
    hours = _run_box(fcst_rows, obs_rows, init)
    assert len(hours) == 1
    assert hours[0]["fss"] is None
