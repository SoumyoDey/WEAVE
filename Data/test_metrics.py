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
    """Drive _categorical_hours_for_box with canned rows (UKMO → accum_h=1)."""
    cur = FakeCursor([[{"initialization_time": init}], fcst_rows, obs_rows])
    with api.app.app_context():
        return api._categorical_hours_for_box(
            cur, "UKMO", "precipitation", "precipitation", "GPM_IMERG_V07B",
            35.0, 37.0, -80.5, -78.5, 0, 24, threshold_rate=5.0, accum_h=1)


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
