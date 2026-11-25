# Pakistan AirWatch AI

Hourly PM2.5 forecasting for **134 Pakistani cities**, built as an
end-to-end MLOps system: versioned data, tracked experiments, a quality
gate that can say *no*, a containerised API, and an interactive
dashboard.

![tests](https://img.shields.io/badge/tests-127%20passing-brightgreen)
![python](https://img.shields.io/badge/python-3.11-blue)
![licence](https://img.shields.io/badge/licence-MIT-informational)
![status](https://img.shields.io/badge/status-academic%20prototype-orange)

> **Academic prototype.** Not an official public-health warning system.
> It does not provide medical advice. Most cities show *modelled
> estimates*, not sensor readings — every value in the API and the UI
> carries a `source` label saying which it is.

---

## What it does

For any of 134 cities, predict PM2.5 (µg/m³) **1, 6, 12 and 24 hours
ahead**, from free public data, with no API keys.

| | |
|---|---|
| Cities | 134 defined, covering all 7 administrative units |
| Data | 2022-08-05 → today, hourly |
| Model | XGBoost, one global model, `horizon` as a feature |
| **Test MAE** | **8.25 µg/m³** |
| Persistence baseline | 14.04 µg/m³ |
| **Improvement** | **+41.3%** |
| Test R² | 0.800 |
| MAE at +1h / +24h | 2.63 / 10.73 µg/m³ |
| Features | 100 |
| Feature rows | 11.3 M |

The model is trained on the 84 cities backfilled so far but serves all
134, because city identity is encoded continuously (latitude,
longitude, elevation, log-population) rather than as a categorical —
there is no per-city parameter that could be missing. Cities outside
the training set carry additional uncertainty, and the report says so.

---

## Quickstart

**Prerequisites:** [Miniconda](https://docs.conda.io/en/latest/miniconda.html),
Node.js 20+, Git. Docker is optional.

```bash
git clone https://github.com/MuhammadHassanSaboor/Pakistan-AirWatch-AI.git
cd Pakistan-AirWatch-AI

conda create -y -n airwatch python=3.11
conda activate airwatch
pip install -r requirements.txt

cp .env.example .env            # works as-is; fill in for team features
```

### Run it

```bash
# 1. build the city table
python -m src.data.cities

# 2. fetch data — start small, the full backfill takes hours
python -m src.data.ingestion --limit 12

# 3. validate, then build features
python -m src.data.validation
python -m src.features.build_features

# 4. baselines first, then the real model
python -m src.models.train_baselines --model persistence
python -m src.models.train_xgboost

# 5. serve it
python -m src.models.registry export-production
python -m src.serving.app                      # http://localhost:5000
```

```bash
# 6. the dashboard, in a second terminal
cd frontend && npm install && npm run dev      # http://localhost:5173
```

No API key is required at any point. Open-Meteo, our data source,
needs no account.

### Or with Docker

```bash
docker compose up -d --build
curl localhost:5000/health
```

| Service | URL |
|---|---|
| API | http://localhost:5000 |
| Dashboard | http://localhost:5173 |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3001 |
| MLflow (local) | http://localhost:5001 |

---

## API

### `GET /health`
```json
{ "status": "healthy", "model_loaded": true,
  "model_version": "xgboost-d8-lr0.05-n600",
  "upstream_cache": { "age_seconds": 44.3, "stale": false } }
```
Returns **503** when no model is loaded, with the reason — so a monitor
can tell "model failed to load" apart from "process is dead".

### `GET /model-info`
Model version, algorithm, run id, the full feature list and the metrics
it was promoted on.

### `POST /predict`
```bash
curl -X POST http://localhost:5000/predict \
  -H "Content-Type: application/json" \
  -d '{"cities":[{"city_id":"lahore","horizon":24},
                 {"city_id":"karachi","horizon":6}]}'
```
```json
{
  "model_version": "xgboost-d8-lr0.05-n600",
  "count": 2,
  "predictions": [{
    "city_id": "lahore", "horizon": 24,
    "pm2_5_pred": 142.6, "unit": "ug/m3",
    "aqi_us": 196, "aqi_category": "Unhealthy",
    "aqi_standard": "US EPA (2024 PM2.5 revision)",
    "base_time": "2026-11-25T03:00:00+00:00",
    "valid_time": "2026-11-26T03:00:00+00:00",
    "source": "model_prediction"
  }],
  "attribution": "Source data © Open-Meteo.com (CC BY 4.0)",
  "disclaimer": "Academic prototype. Not an official public-health warning system."
}
```

| Status | When |
|---|---|
| 200 | success (an unknown `city_id` is reported per entry, not as a failure) |
| 400 | body is not valid JSON |
| 422 | failed validation — unknown horizon, >200 cities, malformed id |
| 503 | no model loaded, or no upstream data available |

### Dashboard endpoints
`GET /api/cities` · `GET /api/forecast?horizon=24[&format=geojson]` ·
`GET /api/history/<city_id>?days=7` · `GET /api/legend` ·
`GET /api/stats` · `GET /metrics` (Prometheus)

---

## How it is built

```
Open-Meteo (no key) ──► ingestion ──► validation ──► features ──► Feast
                         resumable     Pandera +      100 cols    offline
                         batched       7 rules                    + online
                                           │
                                           ▼
                           train (3 members, one MLflow experiment)
                                           │
                                    QUALITY GATE
                            MAE ≤ 25 and ≥15% better than persistence
                                           │
                              registry: Staging → human → Production
                                           │
                            Flask API (Docker, Gunicorn, non-root)
                                           │
                         React + Leaflet + Plotly dashboard
                                           │
                    Prometheus · Grafana · Evidently drift
```

| Layer | Technology |
|---|---|
| Data | Open-Meteo Air Quality + ERA5 Archive |
| Versioning | Git · DVC · DagsHub |
| Validation | Pandera + custom quality rules |
| Features | pandas · Feast feature store |
| Training | XGBoost · LightGBM · scikit-learn |
| Tracking | MLflow + Model Registry |
| Orchestration | Airflow (schedule) + Kubeflow (ML graph) |
| Serving | Flask + Gunicorn, BentoML as a second path |
| Container | Docker, multi-stage, non-root, read-only rootfs |
| Scaling | Kubernetes — probes, HPA, PDB, NetworkPolicy |
| CI/CD | GitHub Actions, gated on tests |
| Monitoring | Prometheus · Grafana · Evidently |
| Frontend | React 18 · Vite · Leaflet · Plotly · Framer Motion |

---

## Repository layout

```
src/
  config.py            single source of truth for settings
  data/                cities · openmeteo client · ingestion · validation
  features/            preprocessing (leakage rules live here) · splits
  models/              train_base · xgboost · lightgbm · baselines
                       evaluate (quality gate) · registry · tracking · plots
  serving/             app.py (Flask) · model_loader · live_features · aqi
  monitoring/          drift.py (Evidently + PSI fallback)
feature_store/         Feast repo + materialisation demo
pipelines/
  airflow/dags/        hourly_ingest · ml_orchestrator · retraining
  kubeflow/            pipeline_definition.py → compiled_pipeline.yaml
tests/                 127 tests across 6 categories
k8s/                   deployment · service · hpa · pdb · networkpolicy
monitoring/            prometheus.yml · alert_rules.yml · grafana dashboard
frontend/              React dashboard
configs/               data_config.yaml · model_params.yaml
Documents/             planning · workflow · data feasibility · risk · roadmaps
dvc.yaml               reproducible pipeline
```

---

## Environment variables

Names only — never commit values. Copy `.env.example` to `.env`.

| Variable | Purpose | Required? |
|---|---|---|
| `MLFLOW_TRACKING_URI` | DagsHub MLflow server | no — falls back to local `mlruns/` |
| `MLFLOW_TRACKING_USERNAME` | DagsHub username | no |
| `MLFLOW_TRACKING_PASSWORD` | DagsHub token | no |
| `AIRWATCH_MEMBER` | tags your MLflow runs (`hassan`/`mudassar`/`ifraz`) | for the team comparison |
| `DAGSHUB_USER_TOKEN` | DVC remote auth | for `dvc push/pull` |
| `OPENAQ_API_KEY` | optional ground-truth source | **no** — skipped when blank |
| `MODEL_SOURCE` | `local` or `registry` | no (default `local`) |
| `POSTGRES_*`, `GRAFANA_PASSWORD` | Docker stack | only with Docker |

**Open-Meteo needs no key.** The project runs with an empty `.env`.

---

## Testing

```bash
pytest -q                                   # 127 tests
pytest --cov=src --cov-report=term-missing
```

| Category | Covers |
|---|---|
| Unit | lag correctness, cyclical encoding, wind decomposition |
| Data | schema bounds, duplicates, flatlines, coordinates |
| Model | output validity, determinism, beats-baseline |
| API | all endpoints, malformed input, injection, DoS cap |
| Integration | raw → features → train → save → load → predict |
| Regression | MAE threshold, quality-gate behaviour |

The leakage tests matter most: one asserts no feature equals the label,
another fails if *any* feature correlates with the label above 0.999.
A leaking model scores brilliantly and forecasts nothing.

---

## Documentation

| Document | Contents |
|---|---|
| [PLANNING.md](Documents/PLANNING.md) | scope, decisions, ownership, status |
| [WORKFLOW.md](Documents/WORKFLOW.md) | daily loop, data flow, model lifecycle, CI |
| [DATA_FEASIBILITY.md](Documents/DATA_FEASIBILITY.md) | what the APIs actually return, with evidence |
| [SIMPLE_ROADMAP.md](Documents/SIMPLE_ROADMAP.md) | plain-language step-by-step guide |
| [PROJECT_ROADMAP.md](Documents/PROJECT_ROADMAP.md) | detailed reference roadmap |
| [INSTALL.md](Documents/INSTALL.md) | software and accounts setup |

---

## Limitations

Stated plainly, because they affect how the numbers should be read.

1. **The target is a reanalysis product, not a sensor.** We forecast
   CAMS reanalysis PM2.5. A model that matched it perfectly would still
   inherit all of the reanalysis's biases.
2. **No independent ground truth.** OpenAQ registration did not
   complete, so we have no sensor data to validate against.
3. **Uneven accuracy.** Error is lowest where the atmosphere is
   well-observed — large Punjab cities — and highest in Balochistan and
   Gilgit-Baltistan, which is exactly where people have the least air
   quality information already.
4. **3.3 years of history, not 12.** The free archive begins
   2022-08-05.
5. **Coarse spatial resolution.** A city is one grid extraction. The
   map must not be read as street-level.
6. **Non-commercial only** while on the free Open-Meteo tier.

---

## Attribution

Air-quality and weather data © [Open-Meteo.com](https://open-meteo.com)
(CC BY 4.0, non-commercial use). Ground-station observations via
[OpenAQ](https://openaq.org) and their underlying providers. Pakistan
context data © [PAQI](https://pakairquality.hawanama.org) (CC BY 4.0).
City coordinates © [GeoNames](https://www.geonames.org) (CC BY 4.0).
Base map © OpenStreetMap contributors, © CARTO.

---

## Team

| Member | Ownership |
|---|---|
| **Hassan** | data engineering, features, XGBoost, Flask API, React dashboard |
| **Mudassar** | Airflow, Kubeflow, tests, CI/CD, DVC pipeline, registry, LightGBM |
| **Ifraz** | Docker, Kubernetes, monitoring, drift detection, baselines |

All three can explain every component.
