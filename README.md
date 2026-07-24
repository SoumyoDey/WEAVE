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
- **Spatial Metric overlay (MetricPanel)** — Live per-grid-point dot overlay for any of 10 verification metrics with configurable threshold and legend
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
| **Spread-Skill Analysis** | Per-lead-time SSR bar chart, spread vs. \|error\| comparison chart, mean SSR and Pearson correlation badges, and a plain-language calibration readout (severely overconfident → overconfident → well calibrated → underconfident → severely underconfident) |
| **Verification Metrics** | Run CSI, POD, FAR, FBI, Brier Score, and Composite Confidence at a configurable precipitation threshold and hour range; point or region sub-mode with charts |

#### 🗺 Region Mode
Computes all 10 spatial metrics in parallel for a drawn bounding box and renders each as a server-side Cartopy/Matplotlib PNG map. Controls: hour range, categorical threshold. Each card has individual ⬇ (download) and share buttons.

| Group | Metrics |
|-------|---------|
| **Calibration** | Spread-Skill Ratio (time-aggregated), Spread-Skill Correlation |
| **Accuracy vs Observations** | Bias (Mean Error), MAE, RMSE, CRPS |
| **Categorical** | CSI, POD, FAR, Brier Score |

---

### ⚖️ Comparison Tab
Side-by-side multi-model verification at a point or region. Location, model selection, and lead-time range sit in a responsive grid (side by side on wide screens, stacked on narrow ones).

- **Time-series comparison** — Ensemble mean (± σ envelope) per model on a shared axis, with a friendly "Normalise" toggle when models report at very different magnitudes
- **Skill score comparison** — MAE and RMSE per model per lead time as grouped bar/line charts
- **Spatial agreement** — Per-grid-point agreement fraction map across selected models (requires ≥ 2 models)
- Accumulation-period normalization (AIFS ÷ 6, GEFS ÷ 3, UKMO ÷ 1 → mm/h) applied before all cross-model comparisons

---

## Spatial Verification Metrics

All metrics are computed from `regridded_forecast` + `regridded_observation` tables and returned as `{lat, lon, value}` point lists, then rendered server-side by Cartopy.

| Key | Full name | Direction |
|-----|-----------|-----------|
| `ssr_agg` | Spread-Skill Ratio (time-aggregated) | Ideal ≈ 1 |
| `correlation` | Spread-Skill Correlation | Higher = better |
| `bias` | Bias / Mean Error | Ideal = 0 |
| `mae` | Mean Absolute Error | Lower = better |
| `rmse` | Root Mean Square Error | Lower = better |
| `crps` | Continuous Ranked Probability Score | Lower = better |
| `csi` | Critical Success Index | Higher = better |
| `pod` | Probability of Detection | Higher = better |
| `far` | False Alarm Ratio | Lower = better |
| `brier` | Brier Score | Lower = better |

> **Note:** `ssr` (single lead-time SSR) is also registered for use in the MetricPanel live overlay. Region mode uses `ssr_agg`, which aggregates across all verified lead times using the regridded tables.

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
    ├── schema.sql                # PostgreSQL schema
    ├── add_indexes.sql           # Index migrations
    ├── requirements.txt          # Python dependencies
    ├── load_to_postgres.py       # Forecast data ingestion
    ├── load_wind.py              # Wind data ingestion
    └── load_gefs_ukmo_wind.py    # GEFS/UKMO wind ingestion
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
| `POST` | `/api/compare/skill` | MAE/RMSE per model per lead time — `{models, lat, lon, hour_min, hour_max, variable}` |
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
