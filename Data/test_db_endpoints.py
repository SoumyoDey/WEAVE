"""Endpoint tests against a real PostgreSQL database.

`test_metrics.py` covers the science as pure functions; `test_endpoints.py`
covers request validation and the response contract against a fake cursor.
Neither runs a query. This file does: `fixture_db.py` builds a throwaway
database whose field has a known answer, and these tests drive the endpoints
against it.

That matters because every correctness fix in METRICS_AUDIT.md was found by
hand-querying the database rather than by a test. Findings 12, 16 and 17 were all
invisible to a green suite, and the reason is structural — a fake cursor returns
the rows a test hands it, so it can never disagree with the SQL about a JOIN, a
parameter order, a `BETWEEN` boundary or a `GROUP BY`.

The load-bearing property of the fixture is that **all three models are given the
same true field in their own storage convention**, so they must produce identical
scores. A regression in the unit or window layer breaks exactly one of them.

These tests skip themselves when no PostgreSQL server is reachable; see
`conftest.py`. Read `fixture_db.py` first — it derives every expected number.

Run:  ~/miniconda3/envs/afw/bin/python -m pytest Data -q
"""
import base64

import pytest

import fixture_db as fx

BOX = {'min_lat': 35, 'max_lat': 37, 'min_lon': -76, 'max_lon': -74}
BOX_QS = '&'.join(f'{k}={v}' for k, v in BOX.items())

# A wet cell and a dry one, for the point endpoints.
WET_CELL = (35.0, -76.0)      # forecast 3.0, observed 2.0 -> bias +1
DRY_CELL = (36.5, -76.0)      # forecast 0.5, observed 2.0 -> bias -1.5

APPROX = {'abs': 1e-3}        # the regridded tables are REAL (float4)


def region_metrics(client, model, metrics, variable='precipitation', **kw):
    body = {'models': [model], 'variable': variable, 'metrics': metrics,
            'hour_min': 0, 'hour_max': 36, **BOX, **kw}
    if variable == 'precipitation':
        body.setdefault('threshold_mm_6h', fx.EXPECT_PRECIP['threshold_mm_6h'])
    r = client.post('/api/compare/region-metrics', json=body)
    assert r.status_code == 200, r.get_json()
    return r.get_json()


# ── The fixture itself ────────────────────────────────────────────────────────

class TestFixtureShape:
    """If these fail, later failures are about the fixture, not the API."""

    def test_the_endpoints_see_all_three_models(self, db_client):
        names = [m['name'] for m in db_client.get('/api/models').get_json()]
        assert names == list(fx.MODELS)

    def test_one_run_per_model(self, db_client):
        """Every regridded query resolves valid time from "the latest run", so a
        second run per model would silently reattribute rows (DATA_EXPANSION_
        DESIGN.md). The fixture must not smuggle one in."""
        d = db_client.get('/api/health').get_json()
        assert d['status'] == 'healthy'
        assert d['total_forecast_points'] > 0


# ── The headline: one field, three storage conventions ────────────────────────

class TestUnitConventionParity:
    """AIFS cumulates, GEFS buckets and pre-divides by a flat 3 h, UKMO stores an
    hourly rate. The fixture gives all three the same true field, so every scored
    number must match across them — findings 1, 2 and 12 were each a case of one
    model's convention being applied to another's rows."""

    METRICS = ['bias', 'mae', 'rmse', 'csi', 'pod', 'far']

    @pytest.mark.parametrize('metric', METRICS)
    def test_every_model_reports_the_expected_score(self, db_client, metric):
        for model in fx.MODELS:
            d = region_metrics(db_client, model, self.METRICS)
            assert d['models'][model][metric] == pytest.approx(
                fx.EXPECT_PRECIP[metric], **APPROX), f'{model} {metric}'

    def test_wind_scores_match_across_models(self, db_client):
        for model in fx.MODELS:
            d = region_metrics(db_client, model, ['bias', 'mae', 'rmse'],
                               variable='wind', hour_max=18, threshold_ms=4.5)
            for metric in ('bias', 'mae', 'rmse'):
                assert d['models'][model][metric] == pytest.approx(
                    fx.EXPECT_WIND[metric], **APPROX), f'{model} {metric}'

    def test_the_map_shows_a_rate_for_every_model(self, db_client):
        """/api/forecast-data is labelled mm/h, so it has to BE mm/h. AIFS's raw
        value is a running total and GEFS's 6 h buckets are 2x too high; both must
        come back as the same 3.0 mm/h UKMO stores natively.

        The display path serves each model's NATIVE grid, so the point count is per
        model (AIFS 81, GEFS 25, UKMO 70) and cells are matched by the analysis band
        their latitude falls in rather than by an exact latitude — UKMO's grid has
        no cell at 35.0 at all."""
        for model in fx.MODELS:
            pts = db_client.get(
                f'/api/forecast-data?model={model}&hour=6&member=mean').get_json()
            assert len(pts) == fx.n_native_cells(model), model
            wet = [p['value'] for p in pts if fx.outcome(p['lat']) != 'miss']
            assert wet, f'{model}: no wet cells matched — check the band mapping'
            assert wet == pytest.approx([fx.EXPECT_PRECIP['rate']] * len(wet), **APPROX)

    def test_the_member_path_converts_the_same_way(self, db_client):
        """Per-member de-accumulation is exact where the mean/spread path can only
        approximate, so the two must still agree on the member value itself."""
        expected = fx.EXPECT_PRECIP['rate'] - fx.PRECIP_SPREAD   # member 0 offset
        for model in fx.MODELS:
            pts = db_client.get(
                f'/api/forecast-data?model={model}&hour=6&member=0').get_json()
            wet = [p['value'] for p in pts if fx.outcome(p['lat']) != 'miss']
            assert wet, model
            assert wet == pytest.approx([expected] * len(wet), **APPROX), model

    def test_the_spread_is_reported_as_a_rate_too(self, db_client):
        """The display path reads the aggregate `ensemble_statistics` spread, which
        the fixture seeds inflated on purpose (see NATIVE_SPREAD_INFLATION) — so
        this value also pins which table the display path reads."""
        pts = db_client.get(
            '/api/forecast-data?model=AIFS&hour=12&member=std').get_json()
        expected = fx.PRECIP_SPREAD * fx.NATIVE_SPREAD_INFLATION
        assert [p['value'] for p in pts] == pytest.approx(
            [expected] * fx.n_native_cells('AIFS'), **APPROX)

    def test_timeseries_shows_the_rate_beside_the_raw_total(self, db_client):
        """AIFS looked wetter the further out you scrubbed because the raw value
        accumulates. `mean` must be flat and `raw_mean` must climb."""
        d = db_client.post('/api/compare/timeseries', json={
            'models': list(fx.MODELS), 'lat': WET_CELL[0], 'lon': WET_CELL[1],
            'variable': 'precipitation', 'hour_min': 0, 'hour_max': 36}).get_json()

        for model in fx.MODELS:
            rates = [h['mean'] for h in d[model]]
            assert rates == pytest.approx([fx.EXPECT_PRECIP['rate']] * len(rates),
                                          **APPROX), model
        aifs_raw = [h['raw_mean'] for h in d['AIFS']]
        assert aifs_raw == sorted(aifs_raw) and aifs_raw[-1] > aifs_raw[0]

    def test_point_scores_agree_across_models(self, db_client):
        d = db_client.post('/api/compare/skill', json={
            'models': list(fx.MODELS), 'lat': WET_CELL[0], 'lon': WET_CELL[1],
            'variable': 'precipitation', 'hour_min': 0, 'hour_max': 36}).get_json()
        for model in fx.MODELS:
            summary = d['models'][model]['summary']
            assert summary['bias'] == pytest.approx(
                fx.EXPECT_PRECIP_CELL_BIAS['hit'], **APPROX), model
            assert [h['hour'] for h in d['models'][model]['hours']] == \
                list(fx.SCORED_PRECIP_HOURS)


# ── Region metrics ────────────────────────────────────────────────────────────

class TestRegionMetrics:
    def test_pooled_and_per_cell_agree_where_the_estimator_is_linear(self, db_client):
        d = region_metrics(db_client, 'AIFS', ['bias', 'mae'])
        for metric in ('bias', 'mae'):
            assert d['models']['AIFS'][metric] == pytest.approx(
                d['cell_means']['AIFS'][metric], **APPROX)

    def test_pooled_rmse_is_not_the_mean_of_per_cell_rmse(self, db_client):
        """Finding 8. sqrt isn't linear, so the domain RMSE (1.5166) and the mean
        of the per-cell RMSEs the map shows (1.4) are different numbers. Both are
        reported, and confusing them is how a headline stops matching its map."""
        d = region_metrics(db_client, 'AIFS', ['rmse'])
        assert d['models']['AIFS']['rmse'] == pytest.approx(
            fx.EXPECT_PRECIP['rmse'], **APPROX)
        assert d['cell_means']['AIFS']['rmse'] == pytest.approx(
            fx.EXPECT_PRECIP['mae'], **APPROX)      # per-cell |error| == per-cell RMSE
        assert d['models']['AIFS']['rmse'] > d['cell_means']['AIFS']['rmse']

    @pytest.mark.parametrize('metric,expected', [
        ('bias', fx.EXPECT_PRECIP_CELL_BIAS),
        ('mae',  fx.EXPECT_PRECIP_CELL_MAE),
    ])
    @pytest.mark.parametrize('model', fx.MODELS)
    def test_the_map_is_right_cell_by_cell(self, db_client, model, metric, expected):
        """A region mean can be right while the field behind it is wrong — two
        cells with equal and opposite errors average away. This checks the map the
        Analysis region view draws, cell by cell, against the outcome each
        latitude was seeded with, for each storage convention."""
        d = db_client.get(f'/api/spatial-metric?metric={metric}&model={model}'
                          f'&variable=precipitation&hour_min=0&hour_max=36'
                          f"&threshold_mm_6h={fx.EXPECT_PRECIP['threshold_mm_6h']}"
                          f'&{BOX_QS}').get_json()
        assert len(d['points']) == fx.N_CELLS
        for p in d['points']:
            assert p['value'] == pytest.approx(
                expected[fx.outcome(p['lat'])], **APPROX), (model, p)

    def test_categorical_counts_come_from_the_pooled_table(self, db_client):
        d = db_client.post('/api/region-categorical-metrics', json={
            'model': 'AIFS', 'variable': 'precipitation', 'hour_min': 0,
            'hour_max': 36, 'threshold_mm_6h': fx.EXPECT_PRECIP['threshold_mm_6h'],
            **BOX}).get_json()
        s = d['summary']
        assert s['hits']         == fx.EXPECT_PRECIP['hits']
        assert s['misses']       == fx.EXPECT_PRECIP['misses']
        assert s['false_alarms'] == fx.EXPECT_PRECIP['false_alarms']
        assert s['csi'] == pytest.approx(fx.EXPECT_PRECIP['csi'], **APPROX)
        assert s['pod'] == pytest.approx(fx.EXPECT_PRECIP['pod'], **APPROX)
        assert s['far'] == pytest.approx(fx.EXPECT_PRECIP['far'], **APPROX)
        assert d['obs_hours'] == list(fx.SCORED_PRECIP_HOURS)

    def test_every_endpoint_labels_wind_in_metres_per_second(self, db_client):
        """compare/skill used to hard-code `units: 'mm/h'` for every variable, so
        the Comparison point chart labelled an m/s wind speed in mm/h."""
        for variable, unit in (('wind', 'm/s'), ('precipitation', 'mm/h')):
            skill = db_client.post('/api/compare/skill', json={
                'models': ['UKMO'], 'lat': WET_CELL[0], 'lon': WET_CELL[1],
                'variable': variable, 'hour_min': 0, 'hour_max': 18}).get_json()
            spread = db_client.get(f'/api/spread-skill?model=UKMO&variable={variable}'
                                   f'&lat={WET_CELL[0]}&lon={WET_CELL[1]}').get_json()
            assert skill['units'] == spread['units'] == unit, variable

    def test_the_threshold_unit_follows_the_variable(self, db_client):
        precip = region_metrics(db_client, 'AIFS', ['csi'])
        assert precip['threshold_info']['unit'] == 'mm/6h'
        assert precip['threshold_info']['threshold_rate'] == pytest.approx(1.5)
        wind = region_metrics(db_client, 'AIFS', ['bias'], variable='wind',
                              hour_max=18, threshold_ms=4.5)
        assert wind['threshold_info']['unit'] == 'm/s'
        assert wind['threshold_info']['threshold_rate'] == pytest.approx(4.5)

    def test_correlation_reaches_the_region_view_through_the_ensemble_path(self, db_client):
        """`correlation` is the one region metric that does not come from the
        regridded pairs — it runs the native ensemble path and has no pooled form,
        so its region value is the mean over cells."""
        d = region_metrics(db_client, 'AIFS', ['correlation', 'bias'],
                           variable='wind', hour_max=18)
        assert d['models']['AIFS']['correlation'] == pytest.approx(
            fx.EXPECT_WIND['correlation'], **APPROX)
        assert d['cell_means']['AIFS']['correlation'] == \
            d['models']['AIFS']['correlation']
        assert d['n_points']['AIFS']['correlation'] == fx.N_CELLS

    def test_ukmo_precipitation_has_no_probabilistic_scores(self, db_client):
        """Not a bug, but a parity gap worth pinning: re-binning an hourly model
        onto the common 6 h window combines records, and the spread of a mean is
        not the mean of spreads, so CRPS/Brier/SSR are dropped rather than
        guessed. AIFS and GEFS emit 6 h records natively and keep theirs."""
        for model in ('AIFS', 'GEFS'):
            d = region_metrics(db_client, model, ['crps', 'brier', 'ssr_agg'])
            assert all(v is not None for v in d['models'][model].values()), model
        d = region_metrics(db_client, 'UKMO', ['crps', 'brier', 'ssr_agg'])
        assert d['models']['UKMO'] == {'crps': None, 'brier': None, 'ssr_agg': None}


# ── The end of the observation record ─────────────────────────────────────────

class TestObservationCoverage:
    """Truth runs out before the forecast does. The fixture stops observations at
    +12 h with forecast records out to +36 h, which is the loaded run's real
    shape (NEXT_STEPS item 4)."""

    def test_lead_times_past_the_record_score_nothing_and_say_so(self, db_client):
        d = region_metrics(db_client, 'AIFS', ['mae'], hour_min=18, hour_max=36)
        assert d['n_cells']['AIFS'] == 0
        assert d['models']['AIFS']['mae'] is None
        assert 'observation record' in d['warnings']['AIFS']

    def test_a_range_spanning_the_edge_scores_only_the_covered_part(self, db_client):
        d = db_client.post('/api/compare/skill', json={
            'models': ['AIFS'], 'lat': WET_CELL[0], 'lon': WET_CELL[1],
            'variable': 'precipitation', 'hour_min': 0, 'hour_max': 36}).get_json()
        assert d['obs_hours'] == list(fx.SCORED_PRECIP_HOURS)
        assert '12h' in d['obs_warning']

    def test_a_partly_observed_window_is_rejected_not_averaged(self, db_client):
        """+18 h covers (12, 18], of which only nothing is observed; +12 h covers
        (6, 12] and is fully observed. Averaging the survivors would score a 6 h
        forecast against whatever observation happens to sit at the edge."""
        d = region_metrics(db_client, 'AIFS', ['mae'], hour_min=12, hour_max=18)
        assert d['n_cells']['AIFS'] == fx.N_CELLS      # +12 h scores
        d = region_metrics(db_client, 'AIFS', ['mae'], hour_min=13, hour_max=18)
        assert d['n_cells']['AIFS'] == 0               # +18 h does not

    @pytest.mark.parametrize('hour,expect_points', [(6, True), (12, True),
                                                    (24, False), (36, False)])
    def test_the_ssr_map_stops_at_the_observation_record(self, db_client,
                                                         hour, expect_points):
        """Lead times past the truth are pruned before the forecast is even
        queried (_observation_record_end) — the member grid is members x cells x
        hours, so fetching records that can never be scored is the difference
        between a 1 s map and a 55 s one."""
        d = db_client.get(f'/api/spatial-metric?metric=ssr&model=AIFS'
                          f'&variable=precipitation&hour={hour}&{BOX_QS}').get_json()
        assert bool(d['points']) is expect_points

    def test_hour_zero_precipitation_is_empty_for_every_model(self, db_client):
        """A 6 h window ending at +0 h would start before initialisation. Two
        models returned nothing here and the hourly one returned a full map scored
        against a single instantaneous observation — so the same lead time was
        blank or full depending only on the model's cadence."""
        for model in fx.MODELS:
            d = db_client.get(f'/api/spatial-metric?metric=ssr&model={model}'
                              f'&variable=precipitation&hour=0&{BOX_QS}').get_json()
            assert d['points'] == [], model

    def test_hour_zero_wind_is_scored(self, db_client):
        """Wind is instantaneous, so it is exempt from the window and +0 h is a
        real lead time — the asymmetry above is physical, not a gap."""
        d = db_client.get('/api/spatial-metric?metric=ssr&model=AIFS'
                          f'&variable=wind&hour=0&{BOX_QS}').get_json()
        assert len(d['points']) == fx.N_CELLS

    @pytest.mark.parametrize('variable,window,scored', [
        ('precipitation', 6, fx.SCORED_PRECIP_HOURS),
        ('wind',          1, fx.SCORED_WIND_HOURS),
    ])
    def test_the_coverage_endpoint_promises_what_the_scores_deliver(
            self, db_client, variable, window, scored):
        """/api/observation-coverage exists so the UI can state where verification
        stops rather than showing an empty panel. Its promise is only worth making
        if it matches what the scored endpoints actually return, so this pins the
        two together: `last_verifiable_hour` must be the last lead time that really
        does get scored."""
        d = db_client.get('/api/observation-coverage?model=AIFS'
                          f'&variable={variable}').get_json()
        assert d['window_hours'] == window
        assert d['obs_end'].startswith('2025-09-08T12:00')
        assert d['record_end_lead_hours'] == pytest.approx(fx.OBS_HOUR_MAX)
        assert d['last_verifiable_hour'] == max(scored)

        # And nothing beyond it is scored, in the endpoint the UI actually reads.
        skill = db_client.post('/api/compare/skill', json={
            'models': ['AIFS'], 'lat': WET_CELL[0], 'lon': WET_CELL[1],
            'variable': variable, 'hour_min': 0, 'hour_max': 36}).get_json()
        assert max(skill['obs_hours']) == d['last_verifiable_hour']

    def test_coverage_reports_the_run_it_is_relative_to(self, db_client):
        """The lead times only mean something against an initialisation time, and
        the frontend had that date hard-coded."""
        d = db_client.get('/api/observation-coverage').get_json()
        assert d['init_time'].startswith('2025-09-08T00:00')
        assert d['source'] == fx.PRECIP_OBS_SOURCE

    def test_wind_stops_at_the_wind_record(self, db_client):
        d = db_client.post('/api/compare/skill', json={
            'models': ['UKMO'], 'lat': WET_CELL[0], 'lon': WET_CELL[1],
            'variable': 'wind', 'hour_min': 0, 'hour_max': 18}).get_json()
        assert d['obs_hours'] == list(fx.SCORED_WIND_HOURS)

    def test_the_earliest_window_uses_every_observation_in_it(self, db_client):
        """The point path used to fetch from `min(valid_time) - (max_period - 1)`,
        one hour short of the window the earliest record covers. That is enough for
        observations on the hour and not for half-hourly IMERG, so the +6 h window
        averaged 11 of its 12 samples — weighted toward the end of the window. The
        two paths must agree, and both must see the whole window."""
        point = db_client.post('/api/compare/skill', json={
            'models': ['AIFS'], 'lat': WET_CELL[0], 'lon': WET_CELL[1],
            'variable': 'precipitation', 'hour_min': 0, 'hour_max': 36}).get_json()
        spread = db_client.get('/api/spread-skill?model=AIFS&variable=precipitation'
                               f'&lat={WET_CELL[0]}&lon={WET_CELL[1]}').get_json()
        n_point  = [h['n_obs_in_window'] for h in point['models']['AIFS']['hours']]
        n_spread = [h['n_obs_in_window'] for h in spread['hours']]
        assert n_point == n_spread == [12, 12]


# ── The native (pre-regrid) tables ────────────────────────────────────────────

class TestNativeEnsemblePaths:
    """The spread-dependent maps — `ssr` and `correlation` — read the regridded
    MEMBER grid, the same source /api/spread-skill uses (METRICS_AUDIT.md finding
    11). The fixture seeds the aggregate `ensemble_statistics` spread inflated by
    NATIVE_SPREAD_INFLATION, so these values would be visibly wrong if anything
    here fell back to the aggregate table."""

    def test_ssr_is_computed_per_cell_from_the_member_grid(self, db_client):
        d = db_client.get('/api/spatial-metric?metric=ssr&model=AIFS'
                          f'&variable=precipitation&hour=6&{BOX_QS}').get_json()
        assert d['metric'] == 'ssr' and d['hour'] == 6
        assert len(d['points']) == fx.N_CELLS
        # Spread is uniform, so SSR ranks purely by |error|: the false-alarm row
        # (error 2.5) must score lowest and the hit rows (error 1.0) highest.
        by_lat = {}
        for p in d['points']:
            by_lat.setdefault(p['lat'], set()).add(p['value'])
        assert all(len(v) == 1 for v in by_lat.values())   # uniform along a row
        hit = next(iter(by_lat[35.0]))
        fa  = next(iter(by_lat[36.0]))
        mis = next(iter(by_lat[36.5]))
        assert hit > mis > fa

    @pytest.mark.parametrize('model', fx.MODELS)
    @pytest.mark.parametrize('variable', ['precipitation', 'wind'])
    def test_the_map_and_the_point_panel_report_the_same_ssr(self, db_client,
                                                            model, variable):
        """Finding 11's actual requirement. The Analysis map and the Analysis point
        panel answered this question from two different tables — the map from the
        aggregate spread (which carries within-cell spatial variance) and the panel
        from the members — so the same cell reported two SSRs. One implementation
        now serves both, and the inflated aggregate spread in the fixture means a
        regression to it could not go unnoticed."""
        hour = 6
        panel = db_client.get(f'/api/spread-skill?model={model}&variable={variable}'
                              f'&lat={WET_CELL[0]}&lon={WET_CELL[1]}').get_json()
        at_hour = [h for h in panel['hours'] if h['hour'] == hour]
        assert at_hour, f'{model}/{variable} scored no +{hour}h case'

        m = db_client.get(f'/api/spatial-metric?metric=ssr&model={model}'
                          f'&variable={variable}&hour={hour}&{BOX_QS}').get_json()
        cell = [p for p in m['points']
                if (p['lat'], p['lon']) == WET_CELL]
        assert cell, 'the map has no value at the cell the panel scored'
        assert cell[0]['value'] == pytest.approx(at_hour[0]['ssr'], **APPROX)

    @pytest.mark.parametrize('model', fx.MODELS)
    @pytest.mark.parametrize('variable', ['precipitation', 'wind'])
    def test_both_point_panels_report_the_same_spread_and_ssr(self, db_client,
                                                             model, variable):
        """/api/compare/skill was the last scored path still reading the aggregate
        spread, so the Comparison point panel and the Analysis point panel gave
        different SSRs for the same cell and lead time — up to 31% apart on the
        loaded run. Same defect as finding 11, one endpoint behind. Both now go
        through _member_cases_by_cell, and the fixture's deliberately inflated
        aggregate spread means a regression could not pass unnoticed."""
        panel = db_client.get(f'/api/spread-skill?model={model}&variable={variable}'
                              f'&lat={WET_CELL[0]}&lon={WET_CELL[1]}').get_json()
        skill = db_client.post('/api/compare/skill', json={
            'models': [model], 'lat': WET_CELL[0], 'lon': WET_CELL[1],
            'variable': variable, 'hour_min': 0, 'hour_max': 36}).get_json()
        by_hour = {h['hour']: h for h in skill['models'][model]['hours']}

        assert panel['hours'], f'{model}/{variable}: nothing scored'
        for h in panel['hours']:
            other = by_hour.get(h['hour'])
            assert other is not None, f"{model}/{variable} +{h['hour']}h missing"
            assert other['spread'] == pytest.approx(h['spread'], **APPROX)
            assert other['ssr'] == pytest.approx(h['ssr'], **APPROX)
            assert other['obs'] == pytest.approx(h['obs'], **APPROX)

    def test_an_hourly_model_can_produce_point_spread_metrics(self, db_client):
        """UKMO precipitation had no SSR or CRPS in the Comparison point panel at
        all — the aggregate path re-bins to the common window and the spread does
        not survive. Re-binning members first does."""
        d = db_client.post('/api/compare/skill', json={
            'models': ['UKMO'], 'lat': WET_CELL[0], 'lon': WET_CELL[1],
            'variable': 'precipitation', 'hour_min': 0, 'hour_max': 36}).get_json()
        hours = d['models']['UKMO']['hours']
        assert hours
        assert all(h['ssr'] is not None and h['crps'] is not None for h in hours)
        assert d['models']['UKMO']['summary']['ssr_agg'] is not None

    def test_an_hourly_model_can_correlate_its_precipitation(self, db_client):
        """Was structurally impossible: the old path read the aggregate table, and
        re-binning a mean/spread pair onto the common window has to discard the
        spread, so UKMO had none and every spread metric came back empty. Re-binning
        each MEMBER and pooling afterwards gives the exact spread of the 6 h means,
        so an hourly model now reaches the same lead times as a 6-hourly one."""
        n_hours = {}
        for model in fx.MODELS:
            d = db_client.get(f'/api/spatial-metric?metric=correlation&model={model}'
                              f'&variable=precipitation&{BOX_QS}').get_json()
            n_hours[model] = d['n_hours']
        assert n_hours['UKMO'] >= 2
        assert len(set(n_hours.values())) == 1, n_hours

    def test_an_hourly_model_gets_a_precipitation_spread_at_all(self, db_client):
        """The other half of the same fix, where the value is checkable: UKMO's
        re-binned 6 h spread must be the seeded ensemble spread, not None and not
        the inflated aggregate."""
        d = db_client.get('/api/spread-skill?model=UKMO&variable=precipitation'
                          f'&lat={WET_CELL[0]}&lon={WET_CELL[1]}').get_json()
        assert [h['hour'] for h in d['hours']] == list(fx.SCORED_PRECIP_HOURS)
        for h in d['hours']:
            assert h['spread'] == pytest.approx(fx.PRECIP_SPREAD, **APPROX)
            assert h['n_members'] == len(fx.MEMBER_OFFSETS)

    def test_correlation_is_plus_one_when_spread_tracks_error(self, db_client):
        """The fixture grows the wind spread on exactly the schedule the error
        grows on, so a correct implementation returns +1 in every cell. A sign
        error or a mispaired hour cannot produce that."""
        d = db_client.get('/api/spatial-metric?metric=correlation&model=AIFS'
                          f'&variable=wind&{BOX_QS}').get_json()
        assert d['n_hours'] >= 2
        assert len(d['points']) == fx.N_CELLS
        assert all(p['value'] == pytest.approx(fx.EXPECT_WIND['correlation'], **APPROX)
                   for p in d['points'])

    def test_a_constant_spread_yields_no_correlation_rather_than_a_wrong_one(self, db_client):
        """Precipitation spread is flat in the fixture, so the denominator is zero
        and there is no correlation to report. It must come back empty with the
        lead-time count intact, not as 0 (which would read as "no skill")."""
        d = db_client.get('/api/spatial-metric?metric=correlation&model=AIFS'
                          f'&variable=precipitation&{BOX_QS}').get_json()
        assert d['n_hours'] >= 2
        assert d['points'] == []


class TestSpreadSkillMemberGrid:
    """/api/spread-skill reads the regridded MEMBER grid (finding 11): the pooled
    member x native-cell spread in the aggregate table carries within-cell spatial
    variance, which is not ensemble spread."""

    def test_spread_equals_error_gives_a_unit_correlation(self, db_client):
        d = db_client.get('/api/spread-skill?model=AIFS&variable=wind'
                          f'&lat={WET_CELL[0]}&lon={WET_CELL[1]}').get_json()
        assert d['units'] == 'm/s' and d['grid'] == '0.5deg'
        assert [h['hour'] for h in d['hours']] == list(fx.SCORED_WIND_HOURS)
        for h in d['hours']:
            assert h['spread'] == pytest.approx(h['error'], **APPROX)
            assert h['ens_mean'] == pytest.approx(fx.EXPECT_WIND['speed'], **APPROX)
        assert d['correlation'] == pytest.approx(fx.EXPECT_WIND['correlation'], **APPROX)

    def test_spread_is_across_members_only(self, db_client):
        d = db_client.get('/api/spread-skill?model=AIFS&variable=precipitation'
                          f'&lat={WET_CELL[0]}&lon={WET_CELL[1]}').get_json()
        assert d['hours']
        for h in d['hours']:
            assert h['n_members'] == len(fx.MEMBER_OFFSETS)
            assert h['spread'] == pytest.approx(fx.PRECIP_SPREAD, **APPROX)

    def test_it_scores_the_common_window_and_says_which(self, db_client):
        d = db_client.get('/api/spread-skill?model=UKMO&variable=precipitation'
                          f'&lat={WET_CELL[0]}&lon={WET_CELL[1]}').get_json()
        assert [h['hour'] for h in d['hours']] == list(fx.SCORED_PRECIP_HOURS)
        for h in d['hours']:
            assert h['period_h'] == 6
            # Every half-hourly IMERG sample in the window contributes.
            assert h['n_obs_in_window'] == 12

    def test_an_off_grid_click_snaps_to_the_cell_it_scored(self, db_client):
        d = db_client.get('/api/spread-skill?model=AIFS&variable=precipitation'
                          '&lat=35.11&lon=-76.13').get_json()
        assert d['cell'] == [35.0, -76.0]

    def test_a_cell_outside_the_grid_is_empty_not_an_error(self, db_client):
        d = db_client.get('/api/spread-skill?model=AIFS&variable=precipitation'
                          '&lat=10.0&lon=10.0').get_json()
        assert d['n_cases'] == 0 and d['hours'] == []
        assert 'error' not in d


class TestPointCategoricalMetrics:
    """The Analysis point path. Its contingency table describes the clicked cell
    only (`box_cells` = 1), so each seeded outcome must come back cleanly — a
    neighbourhood leaking into the count is exactly how "at this point" stops
    being true."""

    @pytest.mark.parametrize('lat,expected', [
        (35.0, {'hits': 2, 'misses': 0, 'false_alarms': 0,
                'csi': 1.0, 'pod': 1.0, 'far': 0.0}),
        (36.0, {'hits': 0, 'misses': 0, 'false_alarms': 2,
                'csi': 0.0, 'pod': None, 'far': 1.0}),
        (36.5, {'hits': 0, 'misses': 2, 'false_alarms': 0,
                'csi': 0.0, 'pod': 0.0, 'far': None}),
    ])
    def test_each_outcome_is_counted_at_the_clicked_cell(self, db_client, lat, expected):
        d = db_client.post('/api/categorical-metrics', json={
            'model': 'AIFS', 'variable': 'precipitation', 'lat': lat, 'lon': -76.0,
            'threshold_mm_6h': fx.EXPECT_PRECIP['threshold_mm_6h'],
            'hour_min': 0, 'hour_max': 36}).get_json()
        assert d['scored_area']['n_cells'] == 1
        assert d['obs_hours'] == list(fx.SCORED_PRECIP_HOURS)
        for key, want in expected.items():
            got = d['summary'][key]
            assert got == pytest.approx(want, **APPROX) if want is not None else got is None

    def test_a_wider_box_gives_fss_something_to_work_with(self, db_client):
        """`box_cells` and `fss_window` are separate parameters because widening
        the neighbourhood used to move CSI/POD/FAR too. The point metrics must
        stay on the centre cell while FSS appears."""
        args = {'model': 'AIFS', 'variable': 'precipitation',
                'lat': 36.0, 'lon': -75.0, 'hour_min': 0, 'hour_max': 36,
                'threshold_mm_6h': fx.EXPECT_PRECIP['threshold_mm_6h']}
        point = db_client.post('/api/categorical-metrics', json=args).get_json()
        boxed = db_client.post('/api/categorical-metrics',
                               json={**args, 'box_cells': 3}).get_json()
        assert point['summary']['fss'] is None
        assert boxed['summary']['fss'] is not None
        assert boxed['scored_area']['n_cells'] > 1
        assert boxed['summary']['csi'] == pytest.approx(point['summary']['csi'])
        assert boxed['summary']['false_alarms'] == point['summary']['false_alarms']

    def test_wind_uses_a_metres_per_second_threshold(self, db_client):
        d = db_client.post('/api/categorical-metrics', json={
            'model': 'AIFS', 'variable': 'wind', 'lat': 35.0, 'lon': -76.0,
            'threshold_ms': 4.5, 'hour_min': 0, 'hour_max': 18}).get_json()
        assert d['threshold_info']['unit'] == 'm/s'
        assert d['obs_hours'] == list(fx.SCORED_WIND_HOURS)
        # Forecast speed is always 5.0 and observed never exceeds 4.0, so every
        # lead time is a false alarm.
        assert d['summary']['false_alarms'] == len(fx.SCORED_WIND_HOURS)
        assert d['summary']['far'] == pytest.approx(1.0)


class TestNativeGrids:
    """The three models are ingested on three different native grids, and the
    fixture now reproduces that: AIFS 0.25 degrees, GEFS 0.5, UKMO 0.1875 x 0.28125
    aligned to neither (see NATIVE_GRIDS).

    It used to put every table on the shared 0.5 degree analysis grid, which made a
    whole class of bug invisible — a 0.25 degree snap key can only collapse two
    cells if two cells are closer together than the key, and nothing was. That is
    NEXT_STEPS.md defect 6, and audit finding 3 and the cross-model join bug lived
    in the same place. The scored paths no longer key on native coordinates, so
    these are guards rather than a live bug hunt: they fail if anyone puts a snap
    back."""

    def test_the_fixture_can_actually_see_a_collapse(self):
        """The property that was missing. UKMO's native latitudes are 0.1875 apart,
        so a 0.25 degree snap maps distinct cells onto a shared key — which is how
        110 native cells became 77, with one cell's value reported at another's
        coordinates. No database needed: this is about the seed."""
        lats, _lons = fx.native_cells('UKMO')
        snapped = {round(v * 4) / 4 for v in lats}
        assert len(snapped) < len(lats), 'UKMO latitudes no longer collapse — ' \
                                        'the fixture has stopped modelling defect 6'
        # 35.15625 and 35.34375 are different cells and share the key 35.25.
        assert round(lats[0] * 4) / 4 == round(lats[1] * 4) / 4

        # Longitude must NOT collapse: 0.28125 is wider than the key.
        _lats, lons = fx.native_cells('UKMO')
        assert len({round(v * 4) / 4 for v in lons}) == len(lons)

        # And the aligned models are unaffected, so a failure points at one model.
        for model in ('AIFS', 'GEFS'):
            m_lats, _ = fx.native_cells(model)
            assert len({round(v * 4) / 4 for v in m_lats}) == len(m_lats), model

    def test_wind_and_precipitation_coordinates_differ_for_ukmo(self):
        """Two loaders wrote UKMO's rows and one passed coordinates through a
        six-significant-digit conversion, so the same physical cell is 35.1562 for
        wind and 35.15625 for precipitation. Nothing joins across variables today;
        if anything starts to, it will match zero rows rather than fail loudly, so
        the difference is pinned here."""
        precip_lats, _ = fx.native_cells('UKMO', 'precipitation')
        wind_lats, _   = fx.native_cells('UKMO', 'wind_u_10m')
        assert precip_lats[0] != wind_lats[0]
        assert set(precip_lats).isdisjoint(wind_lats)
        # AIFS and GEFS sit on round numbers, so their two variables agree.
        for model in ('AIFS', 'GEFS'):
            assert fx.native_cells(model, 'precipitation') == \
                   fx.native_cells(model, 'wind_u_10m'), model

    @pytest.mark.parametrize('model', fx.MODELS)
    def test_the_display_path_serves_the_native_grid_unchanged(self, db_client, model):
        """No snapping, no regridding, no precision lost through the API — the
        coordinates that come back are the ones in the table."""
        pts = db_client.get(
            f'/api/forecast-data?model={model}&hour=6&member=mean').get_json()
        expected_lats, expected_lons = fx.native_cells(model)
        assert sorted({p['lat'] for p in pts}) == pytest.approx(expected_lats)
        assert sorted({p['lon'] for p in pts}) == pytest.approx(expected_lons)

    @pytest.mark.parametrize('model', fx.MODELS)
    def test_scores_are_on_the_analysis_grid_whatever_the_native_one(
            self, db_client, model):
        """The reason the three models are comparable at all. Their native grids
        differ by a factor of nearly three in cell count (AIFS 81, GEFS 25, UKMO
        70), and every score still comes back on the 25-cell analysis grid — so a
        cell count that follows the native grid means something has started keying
        on native coordinates again."""
        d = region_metrics(db_client, model, ['mae', 'bias'])
        assert d['n_cells'][model] == fx.N_CELLS
        assert d['n_points'][model]['mae'] == fx.N_CELLS
        assert fx.n_native_cells(model) != fx.N_CELLS or model == 'GEFS'

    def test_a_finer_grid_does_not_change_the_score(self, db_client):
        """UKMO is on the finest native grid and GEFS's is identical to the analysis
        grid, and they must still agree exactly — the field is the same, so only the
        resolution differs."""
        ukmo = region_metrics(db_client, 'UKMO', ['mae', 'bias', 'rmse'])['models']['UKMO']
        gefs = region_metrics(db_client, 'GEFS', ['mae', 'bias', 'rmse'])['models']['GEFS']
        assert ukmo == gefs

    # The nearest-cell choice in /api/point-timeseries only has more than one
    # candidate when the native grid is finer than the radius — so before this
    # fixture change, `min(cells, key=distance)` was never actually exercised.
    # UKMO's cells at 36.09375 and 36.28125 straddle the analysis band boundary at
    # 36.25, so they carry different forecast rates: 3.0 and 0.5. The midpoint is
    # 36.1875, and the answer must flip either side of it.
    @pytest.mark.parametrize('lat,expected_cell,expected_rate', [
        (36.18, 36.09375, 3.0),
        (36.20, 36.28125, 0.5),
    ])
    def test_the_timeseries_picks_the_nearest_native_cell(
            self, db_client, lat, expected_cell, expected_rate):
        pts = db_client.get('/api/point-timeseries?model=UKMO&variable=precipitation'
                            f'&lat={lat}&lon=-75.515625&radius=0.2').get_json()
        assert pts, 'expected the two straddling cells to be in range'
        assert pts[0]['cell'][0] == pytest.approx(expected_cell, abs=1e-4)
        assert pts[0]['mean'] == pytest.approx(expected_rate, **APPROX)


class TestPointAndDisplayEndpoints:
    @pytest.mark.parametrize('model', fx.MODELS)
    def test_wind_data_reports_speed_and_direction(self, db_client, model):
        """Also pins the u/v self-join across all three native grids, including
        UKMO's reduced-precision coordinates: the join is on exact latitude and
        longitude equality, so if the two components ever disagreed about a cell's
        coordinates it would return nothing at all."""
        pts = db_client.get(f'/api/wind-data?model={model}&hour=6').get_json()
        assert len(pts) == fx.n_native_cells(model, 'wind_u_10m'), model
        for p in pts:
            assert p['u'] == pytest.approx(fx.WIND_U, **APPROX)
            assert p['v'] == pytest.approx(fx.WIND_V, **APPROX)
            assert p['speed'] == pytest.approx(fx.WIND_SPEED, **APPROX)
            assert p['direction'] == pytest.approx(216.9, abs=0.1)

    @pytest.mark.parametrize('member,expected_speed', [
        # The aggregate spread is seeded inflated; the members are exact.
        ('std', fx.wind_spread(0) * fx.NATIVE_SPREAD_INFLATION),
        ('0',   fx.WIND_SPEED - fx.wind_spread(0)),     # member 0 is -1 spread
        ('3',   fx.WIND_SPEED + fx.wind_spread(0)),
    ])
    def test_wind_data_serves_the_spread_and_single_members(self, db_client,
                                                            member, expected_speed):
        """Three different self-joins over two tables — the u/v pairing is the
        part that broke before (a raw u-component was compared against observed
        scalar speed)."""
        pts = db_client.get(
            f'/api/wind-data?model=AIFS&hour=0&member={member}').get_json()
        assert len(pts) == fx.n_native_cells('AIFS', 'wind_u_10m')
        assert pts[0]['speed'] == pytest.approx(expected_speed, **APPROX)

    def test_forecast_data_delegates_wind_to_the_wind_endpoint(self, db_client):
        pts = db_client.get('/api/forecast-data?model=AIFS&hour=6&variable=wind').get_json()
        assert 'speed' in pts[0] and 'direction' in pts[0]

    def test_timeseries_spread_is_the_spread_of_the_increments(self, db_client):
        """De-accumulating per member is exact, so the band around a cumulative
        model's rate must be the seeded 0.25 mm/h — not the spread of the running
        total, which grows with lead time."""
        pts = db_client.get('/api/point-timeseries?model=AIFS&variable=precipitation'
                            f'&lat={WET_CELL[0]}&lon={WET_CELL[1]}&radius=0.1').get_json()
        scored = [p for p in pts if p['hour'] > 0]
        assert scored
        for p in scored:
            assert p['n_members'] == len(fx.MEMBER_OFFSETS)
            assert p['mean'] == pytest.approx(fx.EXPECT_PRECIP['rate'], **APPROX)
            assert p['std'] == pytest.approx(fx.PRECIP_SPREAD, **APPROX)

    def test_an_unknown_model_is_a_404_not_a_500(self, db_client):
        assert db_client.get('/api/forecast-data?model=NOPE&hour=6').status_code == 404
        assert db_client.get('/api/wind-data?model=NOPE&hour=6').status_code == 404

    def test_variables_lists_what_the_schema_declares(self, db_client):
        names = db_client.get('/api/variables').get_json()
        assert {'precipitation', 'wind_u_10m', 'wind_v_10m'} <= set(names)


class TestHealth:
    def test_the_export_convention_is_verified_against_the_data(self, db_client):
        """Finding 16. SCALED_EXPORT_DIVISOR_HOURS describes the DATA, not the
        code, so /api/health infers it back from the stored ratio rather than
        trusting the constant. The fixture stores GEFS the way the export left it
        — a flat 3 h divisor — so the check must read `ok`."""
        d = db_client.get('/api/health').get_json()
        conv = d['precip_export_convention']
        assert conv['status'] == 'ok', conv
        assert conv['declared_divisor_h'] == conv['inferred_divisor_h'] == 3.0
        assert conv['n_samples'] >= 100      # _infer_scaled_export_divisor's floor


# ── Rendering ─────────────────────────────────────────────────────────────────

class TestRendering:
    """The Cartopy paths are the other half of the untested 59%. They are
    CPU-bound, run under a threaded server, and build figures through the
    object-oriented API precisely because pyplot's global registry is not
    thread-safe — so "it returns a PNG at all" is worth asserting."""

    def _png(self, response):
        assert response.status_code == 200, response.get_json()
        raw = base64.b64decode(response.get_json()['image'])
        assert raw[:8] == b'\x89PNG\r\n\x1a\n'
        return raw

    def test_metric_map_renders(self, db_client):
        self._png(db_client.post('/api/spatial-metric-plot', json={
            'metric': 'mae', 'model': 'AIFS', 'variable': 'precipitation',
            'points': [{'lat': lat, 'lon': lon, 'value': 1.25}
                       for lat in fx.LATS for lon in fx.LONS]}))

    def test_difference_map_renders_and_is_flat_for_identical_fields(self, db_client):
        r = db_client.post('/api/compare/spatial-diff', json={
            'model_a': 'AIFS', 'model_b': 'GEFS', 'metric': 'mae',
            'variable': 'precipitation', 'hour_min': 0, 'hour_max': 36, **BOX})
        self._png(r)
        d = r.get_json()
        assert d['n_common'] == fx.N_CELLS
        assert d['mean_diff'] == pytest.approx(0.0, **APPROX)
        assert d['max_abs_diff'] == pytest.approx(0.0, **APPROX)

    @pytest.mark.parametrize('models,variable', [
        (['AIFS', 'UKMO'],         'precipitation'),
        (list(fx.MODELS),          'precipitation'),
        (['AIFS', 'GEFS'],         'wind'),
    ])
    def test_agreement_map_renders(self, db_client, models, variable):
        r = db_client.post('/api/compare/spatial-agreement', json={
            'models': models, 'variable': variable, 'hour': 6, **BOX})
        self._png(r)
        assert r.get_json()['n_models'] == len(models)

    def test_a_categorical_metric_renders_on_its_own_scale(self, db_client):
        """CSI/POD/FAR are bounded in [0,1] and get a discrete norm, a different
        branch of the renderer from the diverging one bias uses."""
        self._png(db_client.post('/api/spatial-metric-plot', json={
            'metric': 'csi', 'model': 'UKMO', 'variable': 'precipitation',
            'threshold_mm_6h': fx.EXPECT_PRECIP['threshold_mm_6h'],
            'points': [{'lat': lat, 'lon': lon, 'value': 0.6}
                       for lat in fx.LATS for lon in fx.LONS]}))

    def test_a_wind_map_labels_its_threshold_in_metres_per_second(self, db_client):
        self._png(db_client.post('/api/spatial-metric-plot', json={
            'metric': 'pod', 'model': 'AIFS', 'variable': 'wind',
            'threshold_ms': 4.5,
            'points': [{'lat': 36.0, 'lon': -75.0, 'value': 0.75}]}))

    def test_an_identical_request_is_served_from_cache(self, db_client):
        body = {'metric': 'bias', 'model': 'AIFS', 'variable': 'precipitation',
                'points': [{'lat': 35.5, 'lon': -75.5, 'value': 0.8}]}
        first  = self._png(db_client.post('/api/spatial-metric-plot', json=body))
        second = self._png(db_client.post('/api/spatial-metric-plot', json=body))
        assert first == second


# ── The connection pool ───────────────────────────────────────────────────────

class TestConnectionPool:
    """Pool behaviour is invisible to a fake cursor by construction."""

    def test_a_failed_statement_does_not_poison_the_pool(self, db_client):
        """Without autocommit, psycopg2 opens an implicit transaction on the
        first statement; a failure leaves the connection in an aborted state and
        the NEXT request to reuse it dies with "current transaction is aborted".
        One bad request would take out every later one."""
        import flask_api as api

        conn = api.get_db_connection()
        cursor = conn.cursor()
        with pytest.raises(Exception):
            cursor.execute('SELECT * FROM a_table_that_does_not_exist')
        cursor.close()
        api.return_db_connection(conn)

        assert db_client.get('/api/models').status_code == 200
        assert db_client.get('/api/health').get_json()['status'] == 'healthy'

    def test_sequential_requests_do_not_exhaust_the_pool(self, db_client):
        """More requests than the pool has connections: each must be returned.
        A missing `return_db_connection` in a `finally` shows up here and nowhere
        else."""
        for _ in range(12):
            assert db_client.get(
                f'/api/spatial-metric?metric=ssr&model=AIFS&variable=precipitation'
                f'&hour=6&{BOX_QS}').status_code == 200


# ── Regressions for the defects this layer found ──────────────────────────────
# All six are fixed. These are the tests that were written first, as strict
# xfails, and unmarked as each fix landed — see NEXT_STEPS.md for the diagnoses.

class TestFormerDefects:
    def test_wind_timeseries_spread_is_ensemble_only(self, db_client):
        """The cone of uncertainty took the nearest cell for precipitation but let
        the wind branch aggregate in SQL over every cell within `radius`, so wind's
        band was widened by spatial variance that is not ensemble spread — finding
        11 on the display side. It also reported a sample standard deviation where
        precipitation reported the population one, and omitted n_members."""
        wide   = db_client.get('/api/point-timeseries?model=AIFS&variable=wind'
                               f'&lat={WET_CELL[0]}&lon={WET_CELL[1]}&radius=0.5').get_json()
        narrow = db_client.get('/api/point-timeseries?model=AIFS&variable=wind'
                               f'&lat={WET_CELL[0]}&lon={WET_CELL[1]}&radius=0.1').get_json()
        # The field is spatially uniform, so widening the radius must not change
        # the ensemble spread.
        assert [p['std'] for p in wide] == pytest.approx([p['std'] for p in narrow])
        for p in wide:
            # Population spread of four members at +/- s(h) is exactly s(h); the
            # sample spread would be s * sqrt(4/3), and pooling four cells as well
            # would give s * sqrt(16/15).
            assert p['std'] == pytest.approx(fx.wind_spread(p['hour']), **APPROX)
            assert p['n_members'] == len(fx.MEMBER_OFFSETS)
            assert p['cell'] == list(WET_CELL)

    def test_both_variables_report_the_same_timeseries_keys(self, db_client):
        """One code path now, so the two must not differ in shape."""
        args = f'&lat={WET_CELL[0]}&lon={WET_CELL[1]}&radius=0.1'
        wind   = db_client.get(f'/api/point-timeseries?model=AIFS&variable=wind{args}').get_json()
        precip = db_client.get(f'/api/point-timeseries?model=AIFS&variable=precipitation{args}').get_json()
        assert wind and precip
        assert set(wind[0]) == set(precip[0])

    def test_fss_reports_the_sample_count_behind_it(self, db_client):
        """n_points['fss'] was 0 beside a real score, because FSS has no per-cell
        map to count. A caller using the count to decide whether a value is
        populated hid a perfectly good FSS."""
        d = region_metrics(db_client, 'AIFS', ['fss', 'mae'])
        assert d['models']['AIFS']['fss'] is not None
        assert d['n_points']['AIFS']['fss'] == d['n_cells']['AIFS'] == fx.N_CELLS
        # Still no per-cell value, which is the thing that made the count 0.
        assert d['cell_means']['AIFS']['fss'] is None

    @pytest.mark.parametrize('metric', ['ssr_agg', 'bias', 'mae', 'rmse', 'crps',
                                        'csi', 'pod', 'far', 'brier', 'fss'])
    def test_every_pairs_metric_works_when_asked_for_alone(self, db_client, metric):
        """Found while fact-checking the reviewer's guide, and the general form of
        the gap: `fss` alone returned no value, zero cells, and a warning that the
        grids did not overlap — none of it true, since `mae` over the same box
        returned every cell. The fcst-obs fetch was skipped because FSS has no
        per-cell function of its own, being a property of the whole field.

        A caller should never have to co-request a second metric to get a first one,
        so each is asked for on its own. Nine of these ten always passed; only the
        combination was broken, which is the kind of gap a per-metric loop catches
        and a hand-picked pair does not."""
        d = region_metrics(db_client, 'AIFS', [metric])
        assert d['models']['AIFS'][metric] is not None, metric
        assert d['n_cells']['AIFS'] == fx.N_CELLS, metric
        assert d['n_points']['AIFS'][metric] > 0, metric
        assert not d['warnings'], f'{metric}: spurious warning {d["warnings"]}'

    def test_correlation_alone_does_not_claim_the_grids_do_not_overlap(self, db_client):
        """`correlation` comes from the member path and needs no fcst-obs pairs, so
        requesting it alone legitimately matches no pairs — but it was then told the
        grids did not overlap while returning a perfectly good correlation. Uses
        wind, where the fixture makes spread track error so the value is exactly
        +1; precipitation spread is flat by design and has nothing to correlate."""
        d = region_metrics(db_client, 'AIFS', ['correlation'],
                           variable='wind', hour_max=18)
        assert d['models']['AIFS']['correlation'] == pytest.approx(
            fx.EXPECT_WIND['correlation'], **APPROX)
        assert not d['warnings'], d['warnings']

    def test_a_metric_with_no_value_still_counts_zero(self, db_client):
        """The count has to stay honest in the other direction: UKMO precipitation
        has no CRPS, so its count must be 0 rather than the cell total."""
        d = region_metrics(db_client, 'UKMO', ['crps', 'fss'])
        assert d['models']['UKMO']['crps'] is None
        assert d['n_points']['UKMO']['crps'] == 0
        assert d['n_points']['UKMO']['fss'] > 0
