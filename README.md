# WEAVE — Weather Ensemble Analysis & Visualization Environment

WEAVE is an interactive web application for visualizing probabilistic weather forecast data from multiple ensemble models. It supports spatial uncertainty visualization, time-series analysis, and ensemble spread diagnostics over a Leaflet map base.

---

## Features

### Forecast Visualization
- **Multi-model support** — AIFS (50 members), GEFS (30 members), UKMO (18 members)
- **Variables** — Precipitation (mm/hr) and Wind Speed (m/s)
- **Ensemble members** — Switch between ensemble mean, individual members, or uncertainty overlays
- **IDW interpolation** — Smooth spatial field rendering via inverse-distance weighting
- **Wind overlays** — Arrow glyphs and animated streamlines

### Uncertainty Visualization (3 modes, mutually exclusive)
| Mode | Description |
|------|-------------|
| **VSUP Boxes** | Box size encodes ensemble spread; color encodes forecast value |
| **Bivariate** | 4×4 color matrix: hue = forecast value, saturation = uncertainty |
| **VSUP Fan** | Polar fan chart; arc width encodes value range, ring depth encodes uncertainty |

All three modes support an **Invert Uncertainty** toggle — flipping which color encoding represents high vs. low uncertainty without changing the underlying color scheme.

### Spatial Diagnostics
- **Spread-Skill Ratio (SSR)** — Per-gridpoint ratio of ensemble variance to squared forecast error
- **Spread-Skill Correlation** — Pearson correlation of spread and error across lead times
- Region selection tool for spatial subsetting

### Time-Series & Analysis
- Point and region time-series extraction
- Ensemble spaghetti plots with mean/spread envelopes
- Spread-skill diagnostic plots per selected region

### UI
- Left panel: model, variable, member, colormap, wind controls
- Right panel: uncertainty mode selector, colormap preview, invert toggle
- Timeline scrubber with 6-hourly steps up to +360h (15 days)
- Click-away sidebar collapse
- About modal

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | React 18 |
| Map | Leaflet.js |
| Charts | Recharts |
| Styling | Inline CSS (no framework) |
| Backend API | Flask (Python) |
| Icons | Lucide React |

---

## Project Structure

```
WEAVE/
├── src/
│   ├── App.js                  # Root component, map init, layer orchestration
│   ├── constants.js            # Model registry, colormaps, buildColorMatrix
│   ├── api/
│   │   ├── forecastApi.js      # Forecast data, timeseries, spread-skill fetch
│   │   └── spatialApi.js       # Spatial metric fetch
│   ├── layers/
│   │   ├── idwLayer.js         # IDW interpolation renderer
│   │   ├── windLayer.js        # Wind arrows & streamlines
│   │   ├── vsupLayer.js        # VSUP boxes uncertainty overlay
│   │   ├── bivariateLayer.js   # Bivariate color overlay
│   │   └── metricLayer.js      # Spatial metric canvas layer
│   ├── components/
│   │   ├── LeftPanel.jsx       # Model/variable/member controls
│   │   ├── RightPanel.jsx      # Uncertainty & colormap settings
│   │   ├── Timeline.jsx        # Bottom time scrubber
│   │   ├── AnalysisTab.jsx     # Time-series & spread-skill plots
│   │   ├── MetricPanel.jsx     # Spatial diagnostics panel
│   │   ├── SelectionToolbar.jsx
│   │   ├── AboutModal.jsx
│   │   └── legends/
│   │       ├── IDWLegend.jsx
│   │       ├── BivariateLegend.jsx
│   │       ├── VSUPFanLegend.jsx
│   │       └── VSUPBoxesLegend.jsx
│   └── utils/
│       ├── colorUtils.js
│       └── geoUtils.js
└── Data/
    └── flask_api.py            # Flask REST API
```

---

## Getting Started

### Prerequisites
- Node.js ≥ 18
- Python ≥ 3.9 (for the Flask API)

### Install & Run

```bash
# Install frontend dependencies
npm install

# Start the React dev server
npm start
```

The app runs at [http://localhost:3000](http://localhost:3000).

```bash
# Start the Flask API (in a separate terminal)
cd Data
python flask_api.py
```

---

## Colormaps

WEAVE ships with 9 colormaps: `Default`, `Viridis`, `Plasma`, `Inferno`, `Turbo`, `Cool`, `Warm`, `RdYlBu`, `Spectral`. Sequential maps are recommended for precipitation and wind speed. Diverging maps (`RdYlBu`, `Spectral`) work well for anomaly views.

The `buildColorMatrix(colormapName, vsup, invertUncertainty)` utility in `constants.js` generates the 4×4 color matrix used by both the bivariate overlay and the VSUP fan legend. Passing `vsup=true` compresses the value axis at high uncertainty; `invertUncertainty=true` flips which rows are vivid vs. muted on the map.

---

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Commit your changes
4. Push and open a Pull Request

---

## License

© 2025 Northeastern University. All rights reserved.
