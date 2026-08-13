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


class TestSSRConvention:
    """SSR is reported as spread/error (sigma over RMSE), which is what the
    colourbar bands and the UI wording describe."""

    def test_perfect_calibration_is_one(self):
        assert api._ssr_from_variances(4.0, 4.0) == 1.0

    def test_is_the_ratio_of_roots_not_of_variances(self):
        # sigma^2 = 1, err^2 = 4  ->  sigma/err = 0.5, not the variance ratio 0.25
        assert api._ssr_from_variances(1.0, 4.0) == 0.5

    def test_none_when_error_is_degenerate(self):
        assert api._ssr_from_variances(1.0, 0.0) is None

    def test_capped_at_the_colourbar_ceiling(self):
        assert api._ssr_from_variances(1e6, 1e-6) == 10.0

    def test_ensemble_correction_inflates_spread(self):
        # 18 members -> sqrt(19/18) = 1.0274 on the spread
        assert api._spread_inflation(18) == pytest.approx(math.sqrt(19 / 18))
        assert api._spread_inflation(50) == pytest.approx(math.sqrt(51 / 50))
        assert api._spread_inflation(None) == 1.0
        assert api._spread_inflation(1) == 1.0

    def test_correction_is_applied_to_the_ratio(self):
        plain     = api._ssr_from_variances(1.0, 1.0)
        corrected = api._ssr_from_variances(1.0, 1.0, n_members=18)
        assert plain == 1.0
        assert corrected == round(math.sqrt(19 / 18), 4)

    def test_smaller_ensembles_get_a_larger_correction(self):
        """The whole point: without this, an 18-member model looks less
        dispersive than a 50-member one purely because of ensemble size."""
        assert api._spread_inflation(18) > api._spread_inflation(50) > 1.0


class TestNeighbourhoodFSS:
    """FSS must measure spatial PLACEMENT. The previous implementation used a
    single domain-wide fraction, which only compared how much area each field
    rained over — these tests pin the difference."""

    @staticmethod
    def _row(values, lat=36.0, lon0=-80.0, step=0.5):
        """One row of grid cells from a list of 0/1 values."""
        return {(lat, round(lon0 + i * step, 2)): float(v)
                for i, v in enumerate(values)}

    def test_perfect_overlap_is_one(self):
        f = self._row([0, 1, 1, 0, 0])
        assert api._fractions_skill_score(f, dict(f), window=1) == 1.0

    def test_displaced_events_are_not_perfect(self):
        """Equal event counts, completely different places. The old
        domain-fraction score returned 1.0 here; a real FSS must not."""
        f = self._row([1, 1, 0, 0, 0, 0])
        o = self._row([0, 0, 0, 0, 1, 1])
        assert api._fractions_skill_score(f, o, window=1) == 0.0

    def test_larger_neighbourhood_forgives_small_displacement(self):
        """The defining behaviour of FSS: a near miss scores better as the
        neighbourhood grows."""
        f = self._row([0, 1, 0, 0, 0, 0, 0])
        o = self._row([0, 0, 1, 0, 0, 0, 0])       # one cell away
        narrow = api._fractions_skill_score(f, o, window=1)
        wide   = api._fractions_skill_score(f, o, window=5)
        assert narrow == 0.0
        assert wide > narrow

    def test_none_when_neither_field_has_an_event(self):
        f = self._row([0, 0, 0])
        assert api._fractions_skill_score(f, dict(f), window=3) is None

    def test_frequency_agreement_alone_does_not_score_well(self):
        """Two fields with identical event frequency but disjoint placement —
        the exact case the old implementation scored as perfect."""
        f = self._row([1, 0, 1, 0, 1, 0, 0, 0])
        o = self._row([0, 0, 0, 0, 0, 1, 1, 1])
        assert api._fractions_skill_score(f, o, window=1) < 0.5

    def test_empty_inputs_are_handled(self):
        assert api._neighbourhood_fractions({}, window=3) == {}
        assert api._fss_components({}, {(36.0, -80.0): 1.0}, 3) == (0.0, 0.0, 0)
        assert api._fractions_skill_score({}, {}, 3) is None

    def test_disjoint_grids_share_no_cells(self):
        """Two models on non-overlapping grids must yield no components rather
        than a score computed from nothing."""
        f = {(36.0, -80.0): 1.0}
        o = {(10.0, -150.0): 1.0}
        assert api._fss_components(f, o, 3) == (0.0, 0.0, 0)
        assert api._fractions_skill_score(f, o, 3) is None

    def test_fractions_ignore_missing_cells(self):
        """A cell absent from the grid is excluded from the neighbourhood
        rather than counted as dry."""
        cells = {(36.0, -80.0): 1.0, (36.0, -79.5): 1.0}   # -79.0 absent
        fr = api._neighbourhood_fractions(cells, window=3)
        assert fr[(36.0, -80.0)] == 1.0
        assert fr[(36.0, -79.5)] == 1.0


class TestGridStep:
    def test_median_gap(self):
        assert api._grid_step([25.0, 25.5, 26.0, 26.5]) == 0.5

    def test_survives_a_missing_cell(self):
        # a gap of 1.0 in the middle must not become the cell size
        assert api._grid_step([25.0, 25.5, 26.5, 27.0]) == 0.5

    def test_falls_back_when_indeterminate(self):
        assert api._grid_step([25.0]) == 0.25
        assert api._grid_step([]) == 0.25


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
    # mean(sigma^2) = 1 ; mean(err^2) = (1 + 4) / 2 = 2.5
    # SSR is the RMS spread over the RMSE, i.e. sqrt(1 / 2.5) = 0.6325 —
    # NOT the variance ratio 0.4 (see _ssr_from_variances).
    assert _single_value(
        api._compute_ssr_agg_points_rf(None, "AIFS", "precipitation", 0, 1, 0, 1)
    ) == round(math.sqrt(0.4), 4)


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


class TestObsWindowMean:
    """The forecast↔observation window. A record covering `period` hours must
    verify against observations spanning that whole period — see audit finding
    13, where a 6 h AIFS record at the edge of the observation record was being
    scored against a single observation 5 h from its valid time."""

    VT = datetime(2025, 9, 8, 12, 0)

    def _hourly(self, n, start_offset, value=1.0):
        """Observations on the hour, `n` of them, ending at VT - start_offset."""
        return {self.VT - timedelta(hours=start_offset + i): value for i in range(n)}

    def test_full_window_is_accepted(self):
        obs = self._hourly(6, 0)                       # VT, VT-1 ... VT-5
        mean, covered, n = api._obs_window_mean(obs, self.VT, 6)
        assert covered == 6 and n == 6
        assert mean == pytest.approx(1.0)

    def test_partial_window_reports_short_coverage(self):
        """The exact shape of the bug: one observation survives at the far edge
        of a 6 h window. The mean is computable, but coverage says 1 of 6."""
        obs = {self.VT - timedelta(hours=5): 4.0}
        mean, covered, n = api._obs_window_mean(obs, self.VT, 6)
        assert mean == 4.0 and n == 1
        assert covered == 1                            # caller must reject this

    def test_window_is_left_open_right_closed(self):
        """(vt - period, vt] — the observation exactly one period back belongs
        to the previous record's window, not this one."""
        obs = {self.VT - timedelta(hours=6): 9.0, self.VT: 1.0}
        mean, covered, _n = api._obs_window_mean(obs, self.VT, 6)
        assert mean == 1.0                             # the 9.0 is excluded
        assert covered == 1

    def test_observations_outside_the_window_are_ignored(self):
        obs = {self.VT + timedelta(hours=1): 99.0, self.VT - timedelta(hours=99): 99.0}
        assert api._obs_window_mean(obs, self.VT, 6) == (None, 0, 0)

    def test_sub_hourly_samples_all_contribute(self):
        """IMERG is half-hourly. Both samples in an hour count toward the mean,
        but they occupy the same one-hour coverage slot."""
        obs = {self.VT: 2.0, self.VT - timedelta(minutes=30): 4.0}
        mean, covered, n = api._obs_window_mean(obs, self.VT, 1)
        assert mean == pytest.approx(3.0)              # not just the top of hour
        assert (covered, n) == (1, 2)

    def test_hourly_record_needs_one_slot(self):
        obs = {self.VT: 5.0}
        assert api._obs_window_mean(obs, self.VT, 1) == (5.0, 1, 1)

    def test_empty_or_missing_cell(self):
        assert api._obs_window_mean(None, self.VT, 6) == (None, 0, 0)
        assert api._obs_window_mean({}, self.VT, 6) == (None, 0, 0)

    def test_coverage_counts_slots_not_samples(self):
        """Twelve half-hourly samples crammed into two hours still cover only
        two of the six slots — a dense burst is not a covered window."""
        obs = {self.VT - timedelta(minutes=30 * i): 1.0 for i in range(4)}
        _mean, covered, n = api._obs_window_mean(obs, self.VT, 6)
        assert n == 4 and covered == 2


class TestPrecipRateSeries:
    def test_aifs_cumulative_is_differenced(self):
        """AIFS stores a running total, so the rate comes from the increment —
        not the total, which grows without bound with lead time.

        The increment is NOT divided by the 6 h window: what AIFS accumulates
        is a mean rate in mm/h, so differencing already lands in mm/h (see
        RATE_CUMULATED_PRECIP_MODELS)."""
        series = {6: (0.6, 0.0), 12: (1.2, 0.0), 18: (1.5, 0.0)}
        rates = api._precip_rate_series("AIFS", series)
        assert rates[6][0] == pytest.approx(0.6)    # from init
        assert rates[12][0] == pytest.approx(0.6)   # 1.2 - 0.6
        assert rates[18][0] == pytest.approx(0.3)   # 1.5 - 1.2
        # the record still covers 6 h — that's what obs are matched over
        assert rates[12][2] == 6

    def test_aifs_increment_is_a_rate_not_an_amount(self):
        """Regression guard for the factor-of-6 dry bias (audit finding 12).

        Dividing the increment by the window made every AIFS precipitation
        number 6x too low: verification against the 2025-09-08 00Z run put
        obs/forecast at 7.98 instead of 1.33, and the 48 h domain total at
        2.99 mm against 17.64 mm observed."""
        series = {6: (0.5, 0.0), 12: (1.0, 0.0)}
        rate = api._precip_rate_series("AIFS", series)[12][0]
        assert rate == pytest.approx(0.5)          # not 0.5 / 6
        assert api._increment_divisor("AIFS", 6) == 1
        # a cumulative model that banked amounts would still divide
        assert api._increment_divisor("SOME_AMOUNT_MODEL", 6) == 6

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
        # sigma 5 -> 13 : sqrt(169 - 25) = 12, and the increment is already mm/h
        series = {6: (1.0, 5.0), 12: (2.0, 13.0)}
        assert api._precip_rate_series("AIFS", series)[12][1] == pytest.approx(12.0)

    def test_cumulative_spread_is_none_when_variance_shrinks(self):
        """~13% of real AIFS records have a shrinking cumulative variance, where
        the increment spread isn't recoverable — must be None, not fabricated."""
        series = {6: (1.0, 9.0), 12: (2.0, 4.0)}
        rate, std, _ = api._precip_rate_series("AIFS", series)[12]
        assert std is None
        assert rate == pytest.approx(1.0)   # the increment is still fine

    def test_missing_std_on_either_record_yields_no_spread(self):
        """Differencing a cumulative model needs both records' spreads; if
        either is absent the increment spread is unrecoverable."""
        assert api._precip_rate_series("AIFS", {6: (1.0, 1.0), 12: (2.0, None)})[12][1] is None
        assert api._precip_rate_series("AIFS", {6: (1.0, None), 12: (2.0, 1.0)})[12][1] is None

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


class TestPrecipMemberRateSeries:
    """Per-member differencing is exact — it's what makes the ensemble spread of
    a cumulative model recoverable, unlike the aggregate mean/std path."""

    def test_member_cumulative_is_differenced(self):
        series = {6: 0.6, 12: 1.2, 18: 1.5}
        rates = api._precip_member_rate_series("AIFS", series)
        # increments are already mm/h — not divided by the 6 h window
        assert rates[6][0] == pytest.approx(0.6)
        assert rates[12][0] == pytest.approx(0.6)
        assert rates[18][0] == pytest.approx(0.3)

    def test_member_and_aggregate_paths_use_the_same_divisor(self):
        """The two rate paths must agree, or the ensemble mean would sit at a
        different scale from the members it is drawn from."""
        series = {6: 1.0, 12: 2.5, 18: 3.0}
        member = api._precip_member_rate_series("AIFS", series)
        agg = api._precip_rate_series("AIFS", {h: (v, 0.0) for h, v in series.items()})
        for hour in series:
            assert member[hour][0] == pytest.approx(agg[hour][0])

    def test_member_gefs_uses_own_bucket(self):
        rates = api._precip_member_rate_series("GEFS", {3: 0.9, 6: 0.9})
        assert rates[3][0] == pytest.approx(0.3)
        assert rates[6][0] == pytest.approx(0.15)

    def test_member_wind_passes_through(self):
        assert api._precip_member_rate_series("AIFS", {6: 12.0}, is_wind=True) == {6: (12.0, 1)}

    def test_member_drops_undifferenceable_record(self):
        assert api._precip_member_rate_series("AIFS", {24: 3.0}) == {}

    def test_spread_of_differenced_members_is_exact(self):
        """Two members whose cumulative totals differ by a constant have zero
        increment spread — the aggregate variance-difference path cannot see
        this, but per-member differencing gets it exactly right."""
        m1 = api._precip_member_rate_series("AIFS", {6: 1.0, 12: 2.0})
        m2 = api._precip_member_rate_series("AIFS", {6: 5.0, 12: 6.0})
        at12 = [m1[12][0], m2[12][0]]
        assert at12[0] == at12[1]                      # identical increments
        mean = sum(at12) / 2
        assert sum((x - mean) ** 2 for x in at12) == 0.0


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
        points, _pairs, n_cells = api._region_metric_points(
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
        points, _pairs, _n = api._region_metric_points(
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
        points, _pairs, n_cells = api._region_metric_points(
            None, "AIFS", "precipitation", ["bias"],
            0, 1, 0, 1, 0, 24, threshold_rate=1.5)
        assert n_cells == 2
        assert api._region_mean(points["bias"]) == 2.0   # mean(1, 3), not 7/3

    def test_no_pairs_metrics_skips_the_fetch(self, monkeypatch):
        monkeypatch.setattr(api, "_fetch_fcst_obs_pairs_spatial",
                            lambda *a, **k: pytest.fail("should not query"))
        assert api._region_metric_points(
            None, "AIFS", "precipitation", ["correlation"],
            0, 1, 0, 1, 0, 24, threshold_rate=1.5) == ({}, {}, 0)


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


# ── Pooled region metrics (the region headline numbers) ───────────────────────
class TestRegionPooledMetrics:
    """Every region bar comes from here, so the estimator each metric uses is
    worth pinning explicitly."""

    ALL = ["bias", "mae", "rmse", "crps", "brier", "csi", "pod", "far", "ssr_agg"]

    def test_empty_pairs(self):
        assert api._region_pooled_metrics({}, self.ALL, 1.5) == {}

    def test_only_returns_requested_metrics(self):
        out = api._region_pooled_metrics(PAIRS, ["mae"], 1.5)
        assert set(out) == {"mae"}

    def test_accuracy_metrics_pool_over_all_samples(self):
        # errors +1 and +2 at one cell
        out = api._region_pooled_metrics(PAIRS, self.ALL, 1.5)
        assert out["bias"] == 1.5
        assert out["mae"] == 1.5
        assert out["rmse"] == round(math.sqrt((1 + 4) / 2), 4)

    def test_rmse_is_the_domain_rmse_not_a_mean_of_cell_rmse(self):
        """sqrt is not linear, so pooling and averaging genuinely differ — this
        is the discrepancy finding 8 was about."""
        pairs = {
            (36.0, -79.5): [(6, 1.0, None, 0.0)],   # err 1
            (36.5, -79.5): [(6, 4.0, None, 0.0)],   # err 4
        }
        pooled = api._region_pooled_metrics(pairs, ["rmse"], 1.5)["rmse"]
        per_cell_mean = (1.0 + 4.0) / 2                  # what a cell mean gives
        assert pooled == round(math.sqrt((1 + 16) / 2), 4)
        assert pooled != per_cell_mean

    def test_categorical_metrics_pool_counts(self):
        out = api._region_pooled_metrics(CAT_PAIRS, self.ALL, 1.5)
        assert out["csi"] == round(1 / 3, 4)      # 1 hit / (1 hit + 1 miss + 1 fa)
        assert out["pod"] == 0.5
        assert out["far"] == 0.5

    def test_counts_are_event_weighted_across_cells(self):
        """A cell with many samples must count more than a sparse one — the
        failure mode of averaging per-cell ratios."""
        dense  = [(h, 2.0, None, 2.0) for h in range(10)]      # 10 hits
        sparse = [(6, 2.0, None, 1.0)]                         # 1 false alarm
        pairs  = {(36.0, -79.5): dense, (36.5, -79.5): sparse}
        out = api._region_pooled_metrics(pairs, ["far"], 1.5)
        assert out["far"] == round(1 / 11, 4)      # not the mean of 0.0 and 1.0

    def test_spread_metrics_skip_records_without_a_spread(self):
        pairs = {(36.0, -79.5): [(6, 2.0, None, 1.0), (12, 3.0, None, 1.0)]}
        out = api._region_pooled_metrics(pairs, self.ALL, 1.5)
        assert out["crps"] is None
        assert out["brier"] is None
        assert out["ssr_agg"] is None
        assert out["mae"] == 1.5          # deterministic metrics unaffected

    def test_ssr_uses_the_pooled_variance_and_error(self):
        out = api._region_pooled_metrics(PAIRS, ["ssr_agg"], 1.5)
        # mean(sigma^2) = 1, mean(err^2) = 2.5 -> sqrt(0.4)
        assert out["ssr_agg"] == round(math.sqrt(0.4), 4)

    def test_ensemble_correction_reaches_the_region_ssr(self):
        plain     = api._region_pooled_metrics(PAIRS, ["ssr_agg"], 1.5)["ssr_agg"]
        corrected = api._region_pooled_metrics(PAIRS, ["ssr_agg"], 1.5,
                                               n_members=18)["ssr_agg"]
        assert corrected > plain


class TestFSSFromPairs:
    """FSS over a region is built from the fields per lead time, not averaged
    out of a points list — it has no per-cell value."""

    @staticmethod
    def _pairs(rows):
        """rows: {(lat, lon): [(hour, fcst_rate, obs_rate), ...]}"""
        return {cell: [(h, f, None, o) for h, f, o in entries]
                for cell, entries in rows.items()}

    def test_perfect_overlap(self):
        pairs = self._pairs({
            (36.0, -80.0): [(6, 5.0, 5.0)],
            (36.0, -79.5): [(6, 0.0, 0.0)],
        })
        assert api._fss_from_pairs(pairs, threshold_rate=1.0, window=1) == 1.0

    def test_displaced_events_score_zero(self):
        pairs = self._pairs({
            (36.0, -80.0): [(6, 5.0, 0.0)],
            (36.0, -79.5): [(6, 0.0, 5.0)],
        })
        assert api._fss_from_pairs(pairs, threshold_rate=1.0, window=1) == 0.0

    def test_wider_neighbourhood_forgives_displacement(self):
        pairs = self._pairs({
            (36.0, -80.0 + 0.5 * i): [(6, 5.0 if i == 1 else 0.0,
                                       5.0 if i == 2 else 0.0)]
            for i in range(7)
        })
        narrow = api._fss_from_pairs(pairs, threshold_rate=1.0, window=1)
        wide   = api._fss_from_pairs(pairs, threshold_rate=1.0, window=5)
        assert narrow == 0.0
        assert wide > narrow

    def test_none_when_no_events(self):
        pairs = self._pairs({(36.0, -80.0): [(6, 0.0, 0.0)]})
        assert api._fss_from_pairs(pairs, threshold_rate=1.0, window=3) is None

    def test_aggregates_across_lead_times(self):
        """Two lead times, one matching and one displaced — the combined score
        sits between the two, since components sum rather than scores averaging."""
        pairs = self._pairs({
            (36.0, -80.0): [(6, 5.0, 5.0), (12, 5.0, 0.0)],
            (36.0, -79.5): [(6, 0.0, 0.0), (12, 0.0, 5.0)],
        })
        combined = api._fss_from_pairs(pairs, threshold_rate=1.0, window=1)
        assert 0.0 < combined < 1.0

    def test_only_computed_when_requested(self):
        """It walks the pairs a second time, so it must not run unasked."""
        pairs = self._pairs({(36.0, -80.0): [(6, 5.0, 5.0)]})
        assert 'fss' not in api._region_pooled_metrics(pairs, ['mae'], 1.0)
        assert 'fss' in api._region_pooled_metrics(pairs, ['mae', 'fss'], 1.0)

    def test_region_metrics_honour_the_window(self):
        pairs = self._pairs({
            (36.0, -80.0 + 0.5 * i): [(6, 5.0 if i == 1 else 0.0,
                                       5.0 if i == 2 else 0.0)]
            for i in range(7)
        })
        narrow = api._region_pooled_metrics(pairs, ['fss'], 1.0, fss_window=1)['fss']
        wide   = api._region_pooled_metrics(pairs, ['fss'], 1.0, fss_window=5)['fss']
        assert wide > narrow


class TestExceedanceProbability:
    def test_degenerate_spread_is_an_indicator(self):
        assert api._exceedance_probability(5.0, 0.0, 1.0) == 1.0
        assert api._exceedance_probability(0.5, 0.0, 1.0) == 0.0
        assert api._exceedance_probability(5.0, None, 1.0) == 1.0

    def test_at_the_threshold_is_a_half(self):
        assert api._exceedance_probability(1.0, 2.0, 1.0) == pytest.approx(0.5)

    def test_increases_with_the_mean(self):
        lo = api._exceedance_probability(0.5, 1.0, 2.0)
        hi = api._exceedance_probability(1.5, 1.0, 2.0)
        assert 0.0 < lo < hi < 1.0


class TestCensoredCRPS:
    """CRPS uses a Gaussian censored at zero, since precipitation cannot be
    negative. The correction is the sub-zero mass the plain Gaussian carries."""

    def test_negligible_when_the_mean_is_far_from_zero(self):
        # mu = 5, sigma = 1 -> essentially no mass below zero
        assert api._censor_correction(5.0, 1.0) == pytest.approx(0.0, abs=1e-9)

    def test_material_when_the_mean_is_near_zero(self):
        assert api._censor_correction(0.0, 1.0) > 0.01

    def test_zero_when_the_distribution_cannot_reach_zero(self):
        assert api._censor_correction(100.0, 1.0) == 0.0

    def test_censoring_lowers_crps_near_zero(self):
        """The censored forecast is sharper — it does not waste probability on
        impossible negative values."""
        plain    = api._gaussian_crps(0.1, 1.0, 0.2, censor_at_zero=False)
        censored = api._gaussian_crps(0.1, 1.0, 0.2, censor_at_zero=True)
        assert censored < plain

    def test_crps_is_never_negative(self):
        for mean in (0.0, 0.05, 0.5, 5.0):
            for std in (0.01, 0.5, 3.0):
                assert api._gaussian_crps(mean, std, 0.0) >= 0.0

    def test_perfect_deterministic_forecast_is_zero(self):
        assert api._gaussian_crps(2.0, 0.0, 2.0) == 0.0


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

    def test_fss_aggregates_components_not_scores(self):
        """FSS over several lead times sums numerators and denominators, the
        standard multi-case form — it is not the mean of per-hour FSS."""
        hours = [
            {"hour": 6,  "n_pts": 4, "hits": 1, "misses": 1,
             "false_alarms": 0, "correct_neg": 2, "fss_num": 0.5, "fss_den": 2.5},
            {"hour": 12, "n_pts": 4, "hits": 1, "misses": 0,
             "false_alarms": 1, "correct_neg": 2, "fss_num": 1.5, "fss_den": 2.5},
        ]
        # 1 - (0.5 + 1.5) / (2.5 + 2.5) = 0.6
        # (the mean of the per-hour scores 0.8 and 0.4 is also 0.6 here only
        #  because the denominators happen to match)
        assert api._categorical_summary(hours)["fss"] == 0.6

    def test_fss_none_without_components(self):
        hours = [{"hour": 6, "n_pts": 4, "hits": 1, "misses": 1,
                  "false_alarms": 0, "correct_neg": 2}]
        assert api._categorical_summary(hours)["fss"] is None

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
