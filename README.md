# Pakistan AirWatch AI

Hourly PM2.5 forecasting for **134 Pakistani cities**, built as an
end-to-end MLOps system: versioned data, tracked experiments, a quality
gate that can say *no*, a containerised API, and an interactive
dashboard.

![tests](https://img.shields.io/badge/tests-262%20passing-brightgreen)
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

### Already on the team? Pull the data instead of re-fetching it

The dataset is versioned with DVC and stored on DagsHub, so you do not
need to re-download four years of hourly data — and you should not,
because a fresh fetch gives you a *different* dataset and makes your
model incomparable with everyone else's. See
[TEAM_SETUP.md](Documents/TEAM_SETUP.md) for the token setup, then:

```bash
dvc pull            # ~1.4 GB, byte-identical to what the models trained on
dvc status          # "Data and pipelines are up to date."
dvc status -c       # "Cache and remote 'origin' are in sync."
```

### Run it from scratch

Only needed if you are not using the shared data.

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
tests/                 262 tests across 6 categories
k8s/                   deployment · service · hpa · pdb · networkpolicy
monitoring/            prometheus.yml · alert_rules.yml · grafana dashboard
frontend/              React dashboard
configs/               data_config.yaml · model_params.yaml
Documents/             planning · workflow · team setup · feasibility · roadmaps
notebooks/             EDA · model comparison · drift (committed with outputs)
scripts/               boundary builder · MLflow run migration · demo shells
dvc.yaml               pipeline definition: cities → ingest → validate
                       → features → train
dvc.lock               the hashes that pin each stage's inputs and outputs
.dvc/config            DagsHub remote (credentials live in config.local,
                       which is gitignored)
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
pytest -q                                   # 262 tests, 72% coverage
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
| [REPORT.md](REPORT.md) | **the project report** — data, features, model, results, MLOps, limitations, status against every acceptance criterion |
| [PLANNING.md](Documents/PLANNING.md) | scope, decisions, ownership, status |
| [WORKFLOW.md](Documents/WORKFLOW.md) | daily loop, data flow, model lifecycle, CI |
| [DATA_FEASIBILITY.md](Documents/DATA_FEASIBILITY.md) | what the APIs actually return, with evidence |
| [TEAM_SETUP.md](Documents/TEAM_SETUP.md) | **start here if you are Mudassar or Ifraz** — DagsHub token, `dvc pull`, training, troubleshooting |
| [SIMPLE_ROADMAP.md](Documents/SIMPLE_ROADMAP.md) | plain-language step-by-step guide |
| [PROJECT_ROADMAP.md](Documents/PROJECT_ROADMAP.md) | detailed reference roadmap |
| [INSTALL.md](Documents/INSTALL.md) | software and accounts setup |

### Notebooks

Analysis only — all logic lives in `src/`, and the notebooks import it
rather than reimplementing it. They are committed **with their outputs**,
so they can be read without being run.

| Notebook | What it establishes |
|---|---|
| [01_exploratory_data_analysis.ipynb](notebooks/01_exploratory_data_analysis.ipynb) | coverage, missingness, skew, seasonality, autocorrelation, altitude — each section ends with the modelling decision it justifies |
| [02_model_comparison.ipynb](notebooks/02_model_comparison.ipynb) | reads the shared MLflow server, checks that runs are comparable *before* ranking them, then builds the per-member leaderboard |
| [03_drift_and_monitoring.ipynb](notebooks/03_drift_and_monitoring.ipynb) | drift detection against a control window, a real seasonal shift and a simulated smog event — and a measured defect in our own threshold |

```bash
jupyter lab notebooks/          # or open them in VS Code
```

### Experiment tracking and data versioning

Both run on one free DagsHub repo — no AWS account, no paid tier.

| | Where |
|---|---|
| MLflow UI | [DagsHub → Experiments](https://dagshub.com/MuhammadHassanSaboor/Pakistan-AirWatch-AI/experiments) |
| Tracking URI | `https://dagshub.com/MuhammadHassanSaboor/Pakistan-AirWatch-AI.mlflow` |
| DVC remote | `s3://dvc` via the same repo's S3-compatible endpoint |
| Experiment | `pm25-forecasting` — every member's runs land here |

```bash
python -m src.models.registry compare            # per-member table
python -m src.models.registry best               # lowest test MAE
python scripts/migrate_mlflow_runs.py --dry-run  # move local runs to the server
```

Three governance demos, each runnable and each verified:

```bash
./scripts/demo_dvc_rollback.sh    # corrupt the dataset, recover it byte-for-byte
./scripts/demo_quality_gate.sh    # train a bad model, watch the gate refuse it
./scripts/rollback.sh             # roll the deployed model back a version
```

Every run is tagged with `member`, `model_family`, `git_commit` and
`dataset_version` — the md5 DVC recorded for the feature table it
trained on. That last tag is what makes "we compared these fairly" a
checkable claim rather than an assertion.

---

## Limitations

Stated plainly, because they affect how the numbers should be read.

1. **The target is a reanalysis product, and it reads low.** We
   forecast CAMS reanalysis PM2.5. Validated against 19,327 hours from
   reference-grade instruments (US Diplomatic Posts, Islamabad and
   Lahore), the reanalysis has **MAE 27.4 µg/m³ and a −12.5 µg/m³
   bias** — it tracks the shape of Pakistani air quality (r ≈ 0.67)
   but understates its magnitude, and the gap widens in dirtier air
   (−8.9 in Islamabad, −25.5 in Lahore).

   **The dominant error is the target, not the model:** our model
   forecasts the reanalysis to 8.2 µg/m³, while the reanalysis itself
   sits 27.4 µg/m³ from the instruments. Read the numbers on this map
   as "reanalysis scale"; real air is likely dirtier.
2. **Ground truth exists but is sparse and uneven.** 493 OpenAQ
   stations match 61 of our 134 cities, but only 2 are reference-grade
   and they stopped reporting in March 2025. The rest are low-cost
   sensors, which over-report. We use them for validation only, never
   for training.
3. **Uneven accuracy.** Error is lowest where the atmosphere is
   well-observed — large Punjab cities — and highest in Balochistan and
   Gilgit-Baltistan, which is exactly where people have the least air
   quality information already.
4. **3.3 years of history, not 12.** The free archive begins
   2022-08-05.
5. **Coarse spatial resolution.** A city is one grid extraction. The
   map must not be read as street-level.
6. **Non-commercial only** while on the free Open-Meteo tier.

### Known issues

Open problems, named rather than left to be discovered.

1. **The drift detector's retrain flag is wired to the wrong number.**
   `run_drift_check` sets `retrain_recommended` from `drift_share`,
   which is Evidently's count of statistically significant columns.
   At our sample sizes (tens of thousands of rows per window) a
   Kolmogorov–Smirnov test rejects the null on differences far too
   small to matter, so that share saturates at 100% and the flag is
   effectively always `True` — it fires even on a control window of two
   adjacent weeks. The PSI values the same function computes *are*
   sound and do separate the cases cleanly (control 1/8 features above
   0.25, seasonal shift 2/8, simulated smog event 6/8), so the fix is
   to threshold on PSI. Measured in
   [03_drift_and_monitoring.ipynb](notebooks/03_drift_and_monitoring.ipynb).
   Owner: Ifraz.
2. **The model comparison is currently one family deep.** XGBoost and
   the reference baselines are logged; LightGBM, RandomForest and the
   remaining baselines are not yet run on the versioned dataset, so the
   per-member table has rows for one member. The infrastructure is in
   place and shared — see [TEAM_SETUP.md](Documents/TEAM_SETUP.md).
   Owners: Mudassar, Ifraz.
3. **Two historical runs are not comparable with the current ones.**
   They predate DVC tracking and were trained on a superseded feature
   table; they carry `dataset_provenance: pre-dvc-tracking` and a
   different `dataset_cohort` on the MLflow server. They are kept
   rather than deleted because the discrepancy is the clearest
   available demonstration of why the dataset needed versioning at all.
4. **Not deployed publicly yet.** The API is containerised with
   Kubernetes manifests, an HPA and a NetworkPolicy, and runs locally;
   no cloud resource exists. The intended target is Oracle Cloud Always
   Free as an approved equivalent to AWS, which needs the teacher's
   written sign-off first (`SIMPLE_ROADMAP.md`, step 17).

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
