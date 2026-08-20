# WEAVE — Weather Ensemble Analysis & Visualization Environment

WEAVE is an interactive web application for exploring, verifying, and comparing probabilistic weather forecasts from multiple ensemble models. It combines a Leaflet map with three analysis panels — Visualization, Analysis, and Comparison — and a Flask/PostgreSQL backend that serves regridded forecast and observation data.

---

## Application Tabs

### 🌍 Visualization Tab
The main map view for real-time forecast exploration. Controls live in a single left-hand **Controls** sidebar, grouped by decision (Data → Display → Advanced) so the three choices that matter most — model, variable, time — are always up front, with power-user settings tucked behind an "Advanced" disclosure.

- **Multi-model support** — AIFS (50 members), GEFS (30 members), UKMO (18 members)
- **Variables** — Precipitation (mm/h) and Wind Speed (m/s) in the UI; the database also holds Temperature 2 m (K) and MSLP (hPa) for future exposure
- **Ensemble members** — Switch between ensemble mean, individual members, or an uncertainty overlay (member selection is disabled while an uncertainty style is active, since those overlays always read from the ensemble mean/spread)
- **IDW interpolation** — Smooth spatial field rendering via inverse-distance weighting
- **Wind overlays** — Arrow glyphs and animated streamlines
- **Timeline** — Transport controls (step/play/pause), a scrubber from +0 h to +360 h (15 days), and a persistent valid-time + lead-time readout
- **Spatial Metric overlay (MetricPanel)** — Live per-grid-point dot overlay for any of 11 verification metrics with configurable threshold and legend
- **Onboarding tour** — First-run 3-step walkthrough (pick data → read the map → explore uncertainty), replayable any time from the About modal
- **Accessibility** — Viridis (colorblind-safe, perceptually uniform) is the default colormap; keyboard-operable controls, visible focus rings, and `prefers-reduced-motion` support throughout
- **Responsive** — Sidebar and tab bar reflow to a mobile-friendly layout below ~760px wide

#### Uncertainty Style (5 modes, mutually exclusive)
Each mode is picked from a thumbnail-preview grid using a plain name; the underlying technique is noted below for reference.

| Mode | Technique | Description |
|------|-----------|-------------|
| **None** | — | Ensemble mean/member only, no uncertainty encoding |
| **Boxes** | VSUP boxes | Box size encodes ensemble spread; color encodes forecast value |
| **Grid** | Bivariate matrix | N×N color matrix: hue = forecast value, saturation = uncertainty |
| **Fan** | VSUP polar fan | Polar fan chart; arc width encodes value range, ring depth encodes uncertainty |
| **Texture** | Hatching | Value shown as color, uncertainty shown as hatch density |

All modes support **Flip colours**, **Invert uncertainty**, **Grid opacity**, and a **Number of buckets** control (0 = continuous, up to 20 discrete steps), plus 9 selectable colormaps.

---

### 📊 Analysis Tab
Deep-dive analysis for a clicked point or a drawn region, with plain-language readouts alongside the raw numbers (e.g. "the forecast looks overconfident here").

#### 📍 Point Mode
| Section | Description |
|---------|-------------|
| **Cone of Uncertainty** | Ensemble mean ± 1σ / ± 2σ (or empirical P10–P90) shaded area chart across the full lead-time range |
| **Spread-Skill Analysis** | Per-lead-time SSR bar chart, spread vs. \|error\| comparison chart, aggregated-SSR and Pearson-correlation badges, and a plain-language calibration readout (severely overconfident → overconfident → well calibrated → underconfident → severely underconfident) |
| **Accuracy vs observations** | Bias, MAE, RMSE and CRPS at the clicked cell, pooled over the verified lead times. Same request and the same matched cases as the spread numbers above, so the two rows cannot disagree — and the same values the Comparison point panel reports for that cell |
| **Verification Metrics** | Run CSI, POD, FAR, FBI, Brier Score, FSS and Composite Confidence at a configurable threshold and hour range; a "Score over: This cell | Drawn region" control chooses the scoring area. A **Scored area** control widens the box so FSS has a neighbourhood to work with, while the contingency table keeps reading the centre cell only — so the point metrics do not move |

#### 🗺 Region Mode
Computes all 10 spatial metrics in parallel for a drawn bounding box and renders each as a server-side Cartopy/Matplotlib PNG map. Controls: hour range, categorical threshold. Each card has individual ⬇ (download) and share buttons.

| Group | Metrics |
|-------|---------|
| **Calibration** | Spread-Skill Ratio (time-aggregated), Spread-Skill Correlation |
| **Accuracy vs Observations** | Bias (Mean Error), MAE, RMSE, CRPS |
| **Categorical** | CSI, POD, FAR, Brier Score |

---

### ⚖️ Comparison Tab
Side-by-side multi-model verification, with a **Point | Region** toggle. Location, model selection, and lead-time range sit in a responsive grid (side by side on wide screens, stacked on narrow ones).

#### 📍 Point Mode
| Section | Description |
|---------|-------------|
| **Time series** | Ensemble mean (± σ envelope) per model on a shared axis, with a "Normalise" toggle when models report at very different magnitudes |
| **Skill over lead time** | Bias, MAE, RMSE, CRPS and SSR per model per lead time, plus aggregate cards |
| **Categorical skill** | CSI / POD / FAR / FSS per model at a configurable threshold, over a verification box whose size is set independently of the FSS neighbourhood |

#### 🗺 Region Mode
| Section | Description |
|---------|-------------|
| **Region metrics** | All 11 metrics per model over a drawn bbox, as grouped bars — pooled over samples, not averaged over per-cell ratios |
| **Spatial small-multiples** | One Cartopy map per model for a chosen metric, on a shared colour scale so the panels are directly comparable |
| **A − B difference map** | Per-cell difference between two models on a diverging scale centred at zero; swapping A/B flips sign and colour, leaving magnitude intact |
| **Spatial agreement** | Per-grid-point agreement fraction across selected models (requires ≥ 2 models) |

Both modes show a **scored-area badge** stating the cells and neighbourhood a number was computed over, because "point" means a box rather than a single cell.

#### Verification conventions
These matter for reading any cross-model number, and are the subject of `METRICS_AUDIT.md`:

- **Everything is compared in mm/h.** The three models do not share a record convention — AIFS stores a running total since initialisation, GEFS alternates 3 h and 6 h accumulation buckets, UKMO is already an hourly rate — so each is converted with its own semantics rather than one divisor. AIFS and GEFS were additionally pre-scaled by the JSON export, which the metric layer accounts for; `/api/health` verifies that assumption against the loaded data and reports a mismatch.
- **Every model is scored over a common 6-hour window.** A threshold only asks one question if the window means one thing: a 1 h mean keeps peaks a 6 h mean averages away, so an hourly model would otherwise cross a high bar more often for no reason but its cadence. Shorter records are combined only when they tile the window exactly.
- **Observations are averaged over the same window a forecast record spans**, and a partially observed window is rejected rather than averaged — so lead times past the end of the observation record return no score instead of a misleading one.
- **FSS needs more than one cell.** With a single cell an event fraction can only be 0 or 1, so FSS degenerates into CSI; it is reported as `null` and the UI says why.

---

## Spatial Verification Metrics

Metrics are returned as `{lat, lon, value}` point lists on the shared 0.5° grid and rendered server-side by Cartopy. Truth is always `regridded_observation`, averaged over the window each forecast record spans.

Two forecast sources, by whether the metric needs the ensemble spread:

- **Spread-dependent** (`ssr`, `ssr_agg`, `correlation`, and the point panels) read `regridded_forecast_member` and pool the members in Python. A cumulative model's increment spread cannot be recovered from stored totals — the approximation √(σ(h)² − σ(h−p)²) assumes independent increments and goes negative for ~13% of AIFS records — and re-binning onto the common verification window discards the spread outright, which left hourly models with no spread-dependent scores at all. Differencing each member first is exact and fixes both.
- **Everything else** reads `regridded_forecast_ens` (ensemble mean and spread over the regridded members, sample `ddof=1`), which is enough when only the mean is needed.

| Key | Full name | Direction | Map? |
|-----|-----------|-----------|------|
| `ssr` | Spread-Skill Ratio (single lead time) | Ideal ≈ 1 | ✓ |
| `ssr_agg` | Spread-Skill Ratio (time-aggregated) | Ideal ≈ 1 | ✓ |
| `correlation` | Spread-Skill Correlation | Higher = better | ✓ |
| `bias` | Bias / Mean Error | Ideal = 0 | ✓ |
| `mae` | Mean Absolute Error | Lower = better | ✓ |
| `rmse` | Root Mean Square Error | Lower = better | ✓ |
| `crps` | Continuous Ranked Probability Score | Lower = better | ✓ |
| `csi` | Critical Success Index | Higher = better | ✓ |
| `pod` | Probability of Detection | Higher = better | ✓ |
| `far` | False Alarm Ratio | Lower = better | ✓ |
| `brier` | Brier Score | Lower = better | ✓ |
| `fss` | Fractions Skill Score | Higher = better | **no** |
| `fbi` | Frequency Bias Index | Ideal = 1 | no |
| `composite_confidence` | Weighted CSI/POD/FAR blend | Higher = better | no |

> **`fss` has no map, on purpose.** It compares the *fraction* of exceedances in a neighbourhood against the observed fraction, so its value belongs to a whole field at a lead time rather than to a cell; drawing it per cell would map a number that is not a property of that cell. It is reported as a region number in both tabs and mapped in neither. In Analysis it arrives through the categorical panel rather than the region metric explorer, which is why it can look absent there.

> **`fbi` and `composite_confidence` are Analysis-only.** No reason for that was recorded and it looks incidental; both are ordinary per-model scores. Worth noting before adding them to Comparison: a composite's weights are a judgement call, so ranking models by it is a different kind of claim from ranking them by CSI. See `CONSISTENCY_AUDIT.md` 1d.

> **`ssr` vs `ssr_agg`:** `ssr` scores one lead time and drives the MetricPanel live overlay; region and point summaries use `ssr_agg`, which pools as **√(mean(σ²) / mean(ε²))** across verified lead times — deliberately *not* the mean of the per-case ratios, since E[X/Y] ≠ E[X]/E[Y] and one near-zero error drags a mean to the clamp. Note the square root: both are reported as spread over error (σ/RMSE), not as a variance ratio, because the calibration bands the colourbar and the UI use are the σ/RMSE ones (`METRICS_AUDIT.md` finding 7).

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 19 |
| Map | Leaflet 1.9 + react-leaflet 5 |
| Charts | Recharts 3 |
| Map rendering | Cartopy + Matplotlib (server-side PNG) |
| Styling | Inline CSS + a small shared design-token/component layer (`theme.js`, `components/ui/`) |
| Backend API | Flask (Python) |
| Rate limiting | Flask-Limiter (best-effort, no-op if not installed) |
| Database | PostgreSQL |
| Icons | Lucide React |

---

## Project Structure

```
WEAVE_v3/
├── src/
│   ├── App.js                    # Root component, map init, layer orchestration, tab routing
│   ├── theme.js                  # Design tokens — color, spacing, radius, type scale
│   ├── constants.js              # MODELS, COLORMAPS, METRIC_CONFIG, buildColorMatrix
│   ├── api/
│   │   ├── forecastApi.js        # Forecast data, point timeseries, spread-skill
│   │   ├── spatialApi.js         # Spatial metric point fetch + Cartopy plot fetch
│   │   ├── analysisApi.js        # Categorical metrics (point + region)
│   │   └── comparisonApi.js      # Multi-model comparison endpoints
│   ├── layers/
│   │   ├── idwLayer.js           # IDW interpolation renderer
│   │   ├── windLayer.js          # Wind arrows & streamlines
│   │   ├── vsupLayer.js          # Boxes uncertainty overlay
│   │   ├── bivariateLayer.js     # Grid (bivariate) color overlay
│   │   └── metricLayer.js        # Spatial metric canvas layer (dot overlay)
│   ├── components/
│   │   ├── ControlsSidebar.jsx   # Unified Data / Display / Advanced controls panel
│   │   ├── Timeline.jsx          # Bottom transport controls + time scrubber
│   │   ├── MetricPanel.jsx       # Live spatial metric overlay + metric selector
│   │   ├── AnalysisTab.jsx       # Point & Region analysis (cone, SSR, verification, maps)
│   │   ├── ComparisonTab.jsx     # Multi-model time-series, skill, spatial agreement
│   │   ├── SelectionToolbar.jsx  # Rectangle/polygon region draw tool
│   │   ├── OnboardingTour.jsx    # First-run coach-mark tour
│   │   ├── AboutModal.jsx
│   │   ├── ui/                   # Shared primitives: Button, Toggle, Select, IconButton,
│   │   │                         #   SectionHeader, Hint (tooltip)
│   │   └── legends/
│   │       ├── IDWLegend.jsx
│   │       ├── BivariateLegend.jsx
│   │       ├── VSUPFanLegend.jsx
│   │       ├── VSUPBoxesLegend.jsx
│   │       └── TextureLegend.jsx
│   └── utils/
│       ├── colorUtils.js
│       └── geoUtils.js
└── Data/
    ├── flask_api.py              # Flask REST API (all endpoints)
    ├── metrics.py                # The science, as pure functions — units, windows, scores
    ├── schema.sql                # PostgreSQL schema
    ├── add_indexes.sql           # Index migrations
    ├── requirements.txt          # Python dependencies
    ├── requirements-dev.txt      # Test-only dependencies
    ├── load_to_postgres.py       # Forecast data ingestion
    ├── load_wind.py              # Wind data ingestion
    ├── load_gefs_ukmo_wind.py    # GEFS/UKMO wind ingestion
    ├── regrid_members.py         # Per-member regrid → regridded_forecast_ens / _member
    ├── conftest.py               # Test setup: pool stub + fixture-database fixtures
    ├── fixture_db.py             # Builds a throwaway PostgreSQL DB with a known answer
    ├── test_metrics.py           # The science, against golden vectors (no DB)
    ├── test_endpoints.py         # Request validation + response contract (fake cursor)
    └── test_db_endpoints.py      # The endpoints against real SQL (fixture database)
```

---

## Flask API Endpoints

### Forecast data
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/forecast-data` | Gridded forecast field — `?model=&variable=&hour=&member=` |
| `GET` | `/api/wind-data` | U/V wind components — `?model=&hour=&member=` |
| `GET` | `/api/point-timeseries` | Ensemble stats time-series at a lat/lon — `?model=&variable=&lat=&lon=` |
| `GET` | `/api/spread-skill` | Point-level SSR + correlation — `?model=&variable=&lat=&lon=` |
| `GET` | `/api/models` | List available models |
| `GET` | `/api/variables` | List available variables |
| `GET` | `/api/observation-coverage` | How far the truth reaches — `?model=&variable=` → `{init_time, obs_end, record_end_lead_hours, last_verifiable_hour, window_hours}` |
| `GET` | `/api/health` | Health check |

### Spatial metrics
| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/spatial-metric` | Per-grid-point metric values — `?metric=&model=&variable=&min_lat=&max_lat=&min_lon=&max_lon=[&hour=][&hour_min=][&hour_max=][&threshold_mm_6h=]` |
| `POST` | `/api/spatial-metric-plot` | Cartopy PNG map from point list — `{metric, model, variable, hour, n_hours, points, threshold_mm_6h?}` |

### Verification (categorical)
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/categorical-metrics` | CSI/POD/FAR/FBI/Brier/Composite at a single point — `{model, variable, lat, lon, threshold_mm_6h, hour_min, hour_max}` |
| `POST` | `/api/region-categorical-metrics` | Same metrics + FSS aggregated over a bounding box — `{model, variable, min_lat, max_lat, min_lon, max_lon, threshold_mm_6h, hour_min, hour_max}` |

### Multi-model comparison
| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/compare/timeseries` | Ensemble mean/spread per model at a point — `{models, lat, lon, hour_min, hour_max, variable}` |
| `POST` | `/api/compare/skill` | Bias/MAE/RMSE/CRPS/SSR per model per lead time — `{models, lat, lon, hour_min, hour_max, variable}` |
| `POST` | `/api/compare/categorical` | CSI/POD/FAR/FSS per model over a verification box — `{models, lat, lon, hour_min, hour_max, variable, threshold_mm_6h \| threshold_ms, box_cells, fss_window}` |
| `POST` | `/api/compare/region-metrics` | All region metrics per model over a bbox — `{models, variable, min_lat, max_lat, min_lon, max_lon, hour_min, hour_max, metrics[], threshold_mm_6h \| threshold_ms, fss_window}` |
| `POST` | `/api/compare/spatial-diff` | Per-cell A − B difference map for one metric — `{model_a, model_b, metric, variable, bbox, hour_min, hour_max, threshold}` |
| `POST` | `/api/compare/spatial-agreement` | Model agreement fraction per grid point — `{models, min_lat, max_lat, min_lon, max_lon, hour, variable}` |

### Robustness
Every endpoint above validates its model/variable tokens against an allowlist and its numeric parameters (lat/lon/hour/bbox) before querying, returning a clean `400` rather than a server error on malformed input. POST bodies must be a JSON object. A configurable rate limit (default 300 requests/minute, `RATE_LIMIT` env var) applies globally, and request bodies are capped at 16 MB (`MAX_CONTENT_LENGTH`).

---

## Getting Started

### Prerequisites
- Node.js ≥ 18
- Python ≥ 3.9 with the `afw` conda environment (Cartopy, psycopg2, Flask, NumPy, SciPy) — see `Data/requirements.txt`
- PostgreSQL with the WEAVE schema loaded (`Data/schema.sql`)

### Frontend

```bash
# Install dependencies
npm install

# Development server (http://localhost:3000)
npm start

# Production build
CI=false npm run build
```

### Flask API

```bash
# From the Data/ directory, using the afw conda environment
cd Data
/path/to/miniconda3/envs/afw/bin/python flask_api.py
```

The API runs at `http://localhost:5000`. If port 5000 is occupied on macOS, disable **AirPlay Receiver** in System Settings → General → AirDrop & Handoff. Local dev enables the interactive debugger via `FLASK_DEBUG=true` in `Data/.env`; leave it unset (or `false`) for anything beyond local dev, since the debugger allows remote code execution.

### Tests

```bash
cd Data
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest -q                                    # everything
python -m pytest -q --cov=flask_api --cov-report=term-missing
```

Three layers, deliberately separate:

| File | What it covers | Database |
|---|---|---|
| `test_metrics.py` | The science as pure functions — unit conversions, verification windows, every score, against golden vectors | none |
| `test_endpoints.py` | Request validation and the response keys the React components read, driven by a query-routing fake cursor | none |
| `test_db_endpoints.py` | The endpoints against real SQL: joins, parameter order, `BETWEEN` boundaries, `GROUP BY`, and the Cartopy renders | a throwaway one, built by `fixture_db.py` |

The third layer exists because a fake cursor returns whatever the test hands it, so it can never disagree with the SQL. `fixture_db.py` creates `weave_fixture_test`, loads the real schema, and seeds one 5×5 patch of grid whose answer is known by construction — **the same true field given to all three models in each one's own storage convention**, so any regression in the unit or window layer breaks exactly one model and the test names it. Read that module's docstring before changing an expected number; every one of them is derived there.

Those tests skip themselves when PostgreSQL is unreachable (or with `WEAVE_SKIP_DB_TESTS=1`), so the suite still runs anywhere. To inspect the fixture by hand:

```bash
python fixture_db.py && psql -d weave_fixture_test
```

---

## Colormaps

WEAVE ships with 9 colormaps: `Default`, `Viridis`, `Plasma`, `Inferno`, `Turbo`, `Cool`, `Warm`, `RdYlBu`, `Spectral`. **Viridis is the default** — it's perceptually uniform and colorblind-safe. Sequential maps suit precipitation and wind speed; diverging maps (`RdYlBu`, `Spectral`) are appropriate for bias and anomaly views.

`buildColorMatrix(colormapName, vsup, invertUncertainty)` in `constants.js` generates the color matrix used by the Grid overlay and Fan legend. `vsup=true` compresses the value axis at high uncertainty; `invertUncertainty=true` flips which cells are vivid vs. muted.

---

## Adding a New Spatial Metric

1. **Backend** — add a `_compute_<key>_points_rf()` function in `flask_api.py`, a `_dispatch_<key>()` wrapper, register both in `SPATIAL_METRIC_REGISTRY` and `PLOT_STYLE_REGISTRY`.
2. **Frontend constants** — add an entry to `METRIC_CONFIG` in `constants.js` with `key`, `label`, `shortLabel`, `requiresHour`, `requiresThreshold`, `colorFn`, and `legend`.
3. **Analysis tab** — add the key to `REGION_METRICS` in `AnalysisTab.jsx` and to the relevant group's `keys` array.
4. **MetricPanel** — the dropdown and overlay update automatically from `METRIC_CONFIG`.

---

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Commit your changes
4. Push and open a Pull Request against `main`

---

## License

© 2026 Northeastern University. All rights reserved.
