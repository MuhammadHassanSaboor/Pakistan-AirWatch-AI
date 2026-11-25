# Pakistan-AirWatch-AI — Simple Step-by-Step Roadmap

**Team:** Hassan · Mudassar · Ifraz
**What we are building:** A website showing air pollution (PM2.5) for 100+ Pakistani cities, with AI predictions for the next 24 hours.

**How we work:**
- **All 3 of us** do ML work (collect data, train models) and compare results on MLflow.
- **Hassan** additionally builds the React frontend and the backend API.
- **Everything free.** No paid APIs, no paid hosting.

---

## Quick answers first

| Question | Answer |
|---|---|
| Backend: Laravel or Flask? | **Flask.** The teacher's PDF requires Flask by name. Laravel gives us 0 marks and doubles the work. |
| Frontend? | **React + Leaflet** (map library). Free. |
| Where do we deploy if not AWS? | **Oracle Cloud Always Free** (recommended) or **Hugging Face Spaces**. Both 100% free. See Step 17. |
| Do we really get 10–15 years of data? | Yes — about **12 years** (2013 to today) free from Open-Meteo. |
| Where do we compare models for free? | **DagsHub** gives us a free MLflow server we all share. |

---

## The big picture (read this once)

```
1. Get data from free APIs  (100+ cities, ~12 years, hourly)
2. Clean it and make features
3. All 3 of us train different models
4. Compare everything on one MLflow page → pick the winner
5. Put the winner inside a Flask API
6. React map shows the predictions
7. Put it in Docker, deploy it free on the cloud
8. Add automation + monitoring on top
```

---

## STEP 1 — Install software (all 3, same day)

Install on each laptop:
- Python 3.11 (tick "Add to PATH")
- Git
- VS Code
- Docker Desktop
- Node.js (only Hassan needs this, for React)

Check it worked:
```bash
python --version
git --version
docker --version
```

---

## STEP 2 — Make free accounts

| Account | Who | Why |
|---|---|---|
| GitHub | all 3 | store code |
| DagsHub | all 3 | free MLflow server + free data storage |
| OpenAQ API key | Hassan | real sensor data |
| Oracle Cloud Free | Hassan | free deployment (needs a card for ID check, but never charges) |

Open-Meteo needs **no account and no key**. That is our main data source.

---

## STEP 3 — Create the project on GitHub

Hassan creates the repo, adds Mudassar and Ifraz as collaborators.

Folders we need:
```
data/          → the datasets
src/           → all our Python code
  data/        → downloading + checking data
  features/    → making features
  models/      → training models
  serving/     → the Flask API
  monitoring/  → drift checking
tests/         → pytest tests
pipelines/     → Airflow + Kubeflow
frontend/      → React app
docker/        → Dockerfiles
k8s/           → Kubernetes files
configs/       → settings files
Documents/     → reports and this roadmap
```

**Rule:** nobody pushes to `main` directly. Always make a branch, then a Pull Request, then someone else approves it. The teacher gives marks for this.

```bash
git checkout -b feature/my-work
# ...do work...
git add .
git commit -m "feat: what I did"
git push origin feature/my-work
# then open a Pull Request on GitHub
```

---

## STEP 4 — Set up DVC + DagsHub (this is our shared server)

**Why:** GitHub cannot store big data files. DVC stores them on DagsHub instead, for free. DagsHub also gives us a free **MLflow server** that all three of us log into — this is exactly what we wanted.

```bash
dvc init
dvc remote add -d origin s3://dvc
dvc remote modify origin endpointurl https://dagshub.com/<owner>/Pakistan-AirWatch-AI.s3
dvc remote modify --local origin access_key_id <your-dagshub-token>
dvc remote modify --local origin secret_access_key <your-dagshub-token>
```

Each person makes their **own** DagsHub token (Settings → Tokens). Put it in a file called `.env`:

```
MLFLOW_TRACKING_URI=https://dagshub.com/<owner>/Pakistan-AirWatch-AI.mlflow
MLFLOW_TRACKING_USERNAME=<your username>
MLFLOW_TRACKING_PASSWORD=<your token>
OPENAQ_API_KEY=<your key>
```

**`.env` must be in `.gitignore`. Never push it to GitHub.**

How DVC works day to day:
```bash
dvc add data/raw/airquality.parquet   # tell DVC to track the file
dvc push                              # upload the real file to DagsHub
git add data/raw/airquality.parquet.dvc && git commit -m "data: ..."
```
Your teammate then runs `git pull` and `dvc pull` and gets the same data.

---

## STEP 5 — Make the city list

Make a file `data/reference/pakistan_cities.csv` with 120+ cities:

```csv
city_id,city_name,province,latitude,longitude,population,elevation_m
lahore,Lahore,Punjab,31.5204,74.3587,11126000,217
karachi,Karachi,Sindh,24.8607,67.0011,14910000,10
islamabad,Islamabad,ICT,33.6844,73.0479,1015000,540
```

Get the coordinates free from **GeoNames** (`download.geonames.org/export/dump/PK.zip`). Filter for populated places with population > 25,000 and take the top 130.

Make sure all provinces are covered — Punjab, Sindh, KPK, Balochistan, GB, AJK, ICT. The teacher will ask.

---

## STEP 6 — Check the data actually exists (do this BEFORE anything else)

Run this one command:

```bash
curl "https://air-quality-api.open-meteo.com/v1/air-quality?latitude=31.5204&longitude=74.3587&hourly=pm2_5&start_date=2013-01-01&end_date=2013-01-02&timezone=UTC"
```

- Numbers come back → we have ~12 years of data. 
- Error about the date → try 2016, then 2019, then 2022 until it works.

**Write the answer in `Documents/DATA_FEASIBILITY.md`.** Whatever date works is the date we use everywhere.

**One honest thing we must say in our report:** Open-Meteo data is from a weather/pollution *model*, not a real sensor in every city. Real sensors in Pakistan exist only in a few cities (Lahore, Karachi, Islamabad, Peshawar). We will use those few as our "ground truth" check. Admitting this **gains** marks. Hiding it loses marks.

---

## STEP 7 — Download the data

**Who:** all 3 split the cities (40 cities each) so it's faster.

We download two things per city:
- **Air quality** (PM2.5, PM10, NO₂, SO₂, CO, ozone) from `air-quality-api.open-meteo.com`
- **Weather** (temperature, humidity, wind, pressure, rain) from `archive-api.open-meteo.com`

Loop: for each city, for each year → one API call → save a small parquet file. Then join them all together.

```python
# src/data/historical.py  (simplified idea)
for city in cities:
    for year in range(2013, 2027):
        aq = get_air_quality(city.lat, city.lon, f"{year}-01-01", f"{year}-12-31")
        wx = get_weather(city.lat, city.lon, f"{year}-01-01", f"{year}-12-31")
        df = aq.merge(wx, on="time")
        df["city_id"] = city.city_id
        df.to_parquet(f"data/raw/by_city_year/{city.city_id}_{year}.parquet")
        time.sleep(1.5)          # be polite, don't get blocked
```

Tips:
- **Skip files that already exist** so you can stop and restart safely.
- `time.sleep(1.5)` between calls. If you get error 429, wait 60 seconds and retry.
- Run it overnight. 130 cities × 13 years = ~1700 calls.

Result: about **14 million rows**. Then:
```bash
dvc add data/raw/airquality_hourly.parquet
dvc push
```

Also grab real sensor data from OpenAQ for the few Pakistani cities that have it — this is our validation set.

---

## STEP 8 — Check the data is clean

**Who:** one person writes it, everyone uses it.

Use **Pandera** — you describe what good data looks like, and it complains if the data is bad.

```python
import pandera.pandas as pa

schema = pa.DataFrameSchema({
    "city_id":   pa.Column(str),
    "timestamp": pa.Column("datetime64[ns, UTC]"),
    "pm2_5":     pa.Column(float, pa.Check.in_range(0, 2000), nullable=True),
    "latitude":  pa.Column(float, pa.Check.in_range(23.0, 37.5)),   # Pakistan only
    "longitude": pa.Column(float, pa.Check.in_range(60.0, 78.0)),
})
schema.validate(df, lazy=True)
```

Also check: no duplicate rows, PM2.5 is not more than PM10, not more than 30% missing, data is fresh.

---

## STEP 9 — Make features

**Who:** all 3 agree on this together, one person writes the code. **This file must be identical for everyone** or our comparison is meaningless.

Features we create:

| Type | Examples |
|---|---|
| **Lags** (past values) | PM2.5 1h ago, 3h ago, 24h ago, 1 week ago |
| **Rolling** | average/max PM2.5 over last 24h, 72h |
| **Calendar** | hour, day of week, month, is weekend, is smog season (Oct–Jan) |
| **Weather** | temperature, humidity, wind speed, wind direction |
| **Location** | latitude, longitude, elevation |

**The most important rule — no cheating (leakage):**
To predict pollution at 5pm, we may only use pollution values from **before now**, plus the **weather forecast** for 5pm. We must NEVER use the pollution value at 5pm as an input. If we do, our model looks amazing and is completely useless.

**Splitting the data — by time, never randomly:**
```
Train:      oldest data → end of 2024
Validation: 2025
Test:       2026 → today
```
Put these dates in `configs/model_params.yaml` and everyone reads them from there.

**What we predict:** PM2.5 in µg/m³ at +1h, +6h, +12h and +24h ahead, for any city. One single model for all cities (the city's latitude/longitude are just features).

---

## STEP 10 — All 3 train models and compare on MLflow ⭐

**This is the core of our project.**

### Rules (agree before anyone starts)

| Rule | Value |
|---|---|
| Everyone uses | the exact same `features.parquet` (run `dvc pull` first) |
| Everyone uses | the same train/val/test split dates |
| Experiment name | `pm25-forecasting` — **same for all 3** |
| Metrics to log | `test_mae`, `test_rmse`, `test_r2`, `mae_h1`, `mae_h24`, `baseline_mae` |
| Everyone tags | `member` = your name, `model_family` = your model |
| Runs per person | at least 10 (different settings) |
| Winner is | lowest `test_mae` |

### Who trains what

| Member | Models |
|---|---|
| **Ifraz** | Baselines first: `persistence` (tomorrow = today), `seasonal naive` (same hour yesterday), `Linear Regression`, `Ridge`. Then LSTM if time allows. |
| **Hassan** | `XGBoost` — try different depth, learning rate, number of trees |
| **Mudassar** | `LightGBM`, `RandomForest`, `HistGradientBoosting` |

**Why baselines matter:** if XGBoost cannot beat "same hour yesterday", we have a bug, not a model. Every single run must log the baseline score next to its own score.

### The code pattern everyone copies

```python
import mlflow, os
from dotenv import load_dotenv
load_dotenv()

mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
mlflow.set_experiment("pm25-forecasting")       # SAME for all 3

with mlflow.start_run(run_name="xgboost-depth8"):
    mlflow.set_tags({"member": "hassan", "model_family": "xgboost"})
    mlflow.log_params({"max_depth": 8, "learning_rate": 0.05})

    model.fit(X_train, y_train)

    mlflow.log_metrics({
        "test_mae": test_mae,
        "test_rmse": test_rmse,
        "test_r2": test_r2,
        "baseline_mae": baseline_mae,
    })
    mlflow.sklearn.log_model(model, "model", registered_model_name="pm25-forecaster")
```

Run many settings in a loop:
```bash
for d in 4 6 8 10; do
  for lr in 0.01 0.05 0.1; do
    python -m src.models.train_xgboost --max-depth $d --lr $lr
  done
done
```

### Making the comparison table

Open the DagsHub MLflow page → sort by `test_mae`. Or run a small script to pull everything into a table:

| Member | Model | test MAE | test RMSE | R² | vs baseline |
|---|---|---|---|---|---|
| Hassan | XGBoost | **11.8** | 19.4 | 0.81 | +38% |
| Mudassar | LightGBM | 12.1 | 19.9 | 0.80 | +36% |
| Mudassar | RandomForest | 14.7 | 23.8 | 0.72 | +22% |
| Ifraz | Ridge | 17.9 | 28.1 | 0.61 | +5% |
| Ifraz | Persistence | 18.9 | 31.2 | 0.52 | — |

Save it in `Documents/MODEL_COMPARISON.md` and write 1 paragraph explaining **why** we picked the winner (not just "lowest number" — also speed, size, stability).

---

## STEP 11 — Register the winning model

MLflow has a **Model Registry** — like a shelf with labels.

```
Version 7 → Staging → (we test it) → Production
Old version → Archived
```

```python
from mlflow.tracking import MlflowClient
c = MlflowClient()
c.transition_model_version_stage("pm25-forecaster", 7, "Staging")
c.transition_model_version_stage("pm25-forecaster", 7, "Production",
                                 archive_existing_versions=True)
```

**Quality gate** — a rule that can say NO:
```python
if test_mae > 20.0:
    raise ValueError("Model too bad — not deploying")
if improvement_over_baseline < 15:
    raise ValueError("Not better than baseline — not deploying")
```

The teacher specifically wants to see a **bad model being rejected**. So train one on purpose with `n_estimators=1`, let the gate block it, and screenshot it.

**Rollback** = move the old version back to Production and restart. Takes 10 seconds. Demo this.

---

## STEP 12 — Feature Store (Feast)

**Why:** so the features used in training and the features used in the live app are calculated by the **same code**. Otherwise live predictions go silently wrong.

Setup is small:
```bash
cd feature_store && feast init -m feature_repo
```

Define: entity = `city_id`, offline store = parquet file, online store = SQLite (both free, no servers).

Then demonstrate 3 commands:
```bash
feast apply                  # register the features
feast materialize-incremental <now>   # copy offline → online
feast ui                     # screenshot this
```

That's 6 marks for about half a day of work.

---

## STEP 13 — Flask API (Hassan)

One Flask app does everything. Required endpoints:

| Endpoint | What it does |
|---|---|
| `GET /health` | "am I alive?" |
| `GET /model-info` | which model version is running |
| `POST /predict` | give it cities, get predictions back |
| `GET /metrics` | numbers for Prometheus (1 line of code) |
| `GET /api/cities` | city list for the map |
| `GET /api/forecast` | all predictions for the map |

Example:
```bash
curl -X POST http://localhost:5000/predict \
  -H "Content-Type: application/json" \
  -d '{"cities":[{"city_id":"lahore","horizon":24}]}'
```
```json
{"model_version":"7","predictions":[
  {"city_id":"lahore","horizon":24,"pm2_5_pred":142.6,"unit":"ug/m3",
   "aqi_category":"Unhealthy","source":"model_prediction"}]}
```

Must-dos:
- Check the input. Bad input → return 422, not a crash.
- Limit how many cities per request (e.g. max 200).
- Don't log the full request body.
- Get Prometheus metrics with 2 lines:
  ```python
  from prometheus_flask_exporter import PrometheusMetrics
  metrics = PrometheusMetrics(app)
  ```

---

## STEP 14 — BentoML (quick extra)

The teacher also wants a BentoML demo. Half a day max — Flask stays the main API.

```bash
bentoml serve src/serving/bentoml_service.py:svc --port 3000
bentoml build
bentoml containerize airwatch_bento:latest
```
Record a 2-minute video. Done.

---

## STEP 15 — Tests (pytest)

Six kinds of tests are required. Aim for 25+ tests total.

| Kind | Example test |
|---|---|
| **Unit** | the 1-hour lag column really equals the previous row |
| **Data** | negative PM2.5 is rejected; coordinates outside Pakistan are rejected |
| **Model** | predictions are never negative, never NaN, right shape |
| **API** | `/health` returns 200; bad JSON returns 400; bad horizon returns 422 |
| **Integration** | raw data → features → train → save → load → predict all works |
| **Regression** | model MAE is still below our threshold and still beats the baseline |

The most important test:
```python
def test_no_leakage(df):
    """No feature column may be identical to the answer column."""
    for col in feature_columns:
        assert not df[col].equals(df["y"])
```

Run:
```bash
pytest -v --cov=src
```

---

## STEP 16 — Docker

**Docker** = put the app in a box that runs the same everywhere.

`docker/Dockerfile.api` — key points:
- Start from `python:3.11-slim`
- Install only what the API needs (not Airflow!)
- Run as a non-root user
- Use **Gunicorn**, not `flask run`
- Add a `HEALTHCHECK`

`docker-compose.yml` runs everything together:
```
api         → our Flask app
db          → PostgreSQL + PostGIS
mlflow      → local MLflow (backup)
prometheus  → collects metrics
grafana     → draws the graphs
```

```bash
docker compose up -d --build
curl localhost:5000/health
```

**Proof needed:** one person builds it, another person runs it on their laptop and screenshots `/health` working.

---

## STEP 17 — Deploy for FREE (no AWS needed)

The teacher allows "AWS **or an approved equivalent architecture**." Here are the 100% free options. **Ask the teacher to approve your choice first.**

### Option A — Oracle Cloud Always Free ⭐ Recommended

Truly free forever (not a 12-month trial). You get a real Linux server.

| What we need | AWS name | Oracle free equivalent |
|---|---|---|
| Server | EC2 | **Compute VM** (up to 4 ARM cores + 24 GB RAM, free forever) |
| File storage | S3 | **Object Storage** (20 GB free) |
| Logs/monitoring | CloudWatch | **OCI Logging + Monitoring** (free) |
| Container registry | ECR | **OCI Container Registry** (free) |
| Permissions | IAM | **OCI IAM** (free) |

This maps 1-to-1 onto the AWS architecture in the requirements, which is exactly what "equivalent architecture" means. It needs a card for identity verification but **never charges** on the Always Free tier.

Steps:
1. Create an Always Free ARM VM with Ubuntu
2. Install Docker
3. Open ports 80 and 22 in the security list (SSH from your IP only)
4. `docker compose up -d`
5. Note down the public IP → that's your live endpoint

### Option B — Hugging Face Spaces (easiest, no card at all)

Free Docker hosting, no credit card, always on.
1. Create a Space → choose **Docker** → free CPU tier
2. Push your Dockerfile + code
3. You get a public URL like `https://hassan-airwatch.hf.space`

Great backup. Less "cloud architecture" to show, so use Oracle if you can.

### Option C — Render / Railway / Fly.io free tiers

Easy, but the free tier sleeps after inactivity and storage is limited. Fine as a third backup.

**Whatever we choose, we must document:** the architecture diagram, which service replaces which AWS service, how to reproduce the deployment, and how to shut it down.

---

## STEP 18 — Kubernetes (runs on our own laptop, free)

We do NOT need a cloud Kubernetes cluster (those cost money). **Minikube** runs Kubernetes on a laptop for free, and the requirements allow this.

```bash
minikube start --cpus=4 --memory=8192
minikube image load airwatch-api:latest
kubectl apply -f k8s/
```

Then demonstrate these 4 things (record your screen):
```bash
kubectl get pods                    # 3 copies running
kubectl delete pod <one-name>       # kill one...
kubectl get pods -w                 # ...watch Kubernetes bring it back
kubectl scale deployment airwatch-api --replicas=5   # scale up
kubectl rollout undo deployment/airwatch-api         # rollback
```

Our `k8s/api-deployment.yaml` needs **readiness and liveness probes** pointing at `/health`.

---

## STEP 19 — Airflow (automatic scheduling)

**Airflow** runs jobs on a timetable and shows a nice graph of what ran and what failed.

Run it with Docker:
```bash
docker compose -f docker-compose.airflow.yml up -d
# open localhost:8080
```

We need 3 DAGs (a DAG is just a Python file listing tasks in order):

| DAG | When | What |
|---|---|---|
| `hourly_ingest_dag` | every hour | fetch new data → check it → save to database |
| `ml_orchestrator_dag` | manual | validate data → trigger the Kubeflow pipeline → wait |
| `retraining_dag` | weekly or when drift found | check drift → retrain → compare → promote |

Always set retries (the teacher checks this):
```python
default_args = {"retries": 3, "retry_delay": timedelta(minutes=5)}
```

Screenshots to take: the DAG graph, a successful run, a **failed task showing retries**.

---

## STEP 20 — Kubeflow Pipelines

Airflow **schedules**. Kubeflow **runs each ML step in its own container**. The teacher wants both.

Install on Minikube (same cluster as Step 18):
```bash
export PIPELINE_VERSION=2.2.0
kubectl apply -k "github.com/kubeflow/pipelines/manifests/kustomize/cluster-scoped-resources?ref=$PIPELINE_VERSION"
kubectl apply -k "github.com/kubeflow/pipelines/manifests/kustomize/env/platform-agnostic?ref=$PIPELINE_VERSION"
kubectl port-forward -n kubeflow svc/ml-pipeline-ui 8080:80
```

Write the pipeline in Python, compile it to YAML:
```python
@dsl.pipeline(name="pm25-training-pipeline")
def pipeline(mae_threshold: float = 20.0):
    v = validate_data(...)
    with dsl.If(v.output == True):
        f = engineer_features(...)
        t = train_model(features=f.output)
        e = evaluate_model(model=t.output, threshold=mae_threshold)
        with dsl.If(e.output == True):       # only register if it's good enough
            register_model(...)

compiler.Compiler().compile(pipeline, "pipelines/kubeflow/compiled_pipeline.yaml")
```

Upload the YAML in the Kubeflow UI → Create Run → screenshot the graph.

**If Kubeflow won't install** (it's heavy), still produce the compiled YAML, run the same steps with `kfp.local` or `kind`, and write down what happened. The YAML file itself is the deliverable.

---

## STEP 21 — GitHub Actions (automatic testing)

A file `.github/workflows/ci.yml`. Every time anyone pushes code, GitHub automatically:
1. Checks code style (Ruff)
2. Scans for secrets and vulnerable packages
3. Runs all the pytest tests
4. Builds the Docker image — **only if tests passed**
5. Starts the container and checks `/health`

```yaml
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.11"}
      - run: pip install -r requirements.txt
      - run: ruff check src tests
      - run: pytest -v --cov=src --cov-fail-under=70

  build:
    needs: test        # ← this line IS the quality gate
    runs-on: ubuntu-latest
    steps:
      - run: docker build -f docker/Dockerfile.api -t airwatch-api .
```

**Important deliverable:** we must show a **FAILING** build blocking a merge. So:
1. Make a branch, break a test on purpose
2. Open a PR → screenshot the red ❌ and the blocked Merge button
3. Fix it → screenshot the green ✅
4. Save both images in `Documents/evidence/`

Secrets (tokens, keys) go in GitHub → Settings → Secrets. **Never in the code.**

---

## STEP 22 — DVC pipeline

`dvc.yaml` chains our scripts together so one command rebuilds everything that changed:

```yaml
stages:
  ingest:    {cmd: python -m src.data.historical,      outs: [data/raw/airquality_hourly.parquet]}
  validate:  {cmd: python -m src.data.validation,      metrics: [reports/data_quality.json]}
  features:  {cmd: python -m src.features.build_features, outs: [data/processed/features.parquet]}
  train:     {cmd: python -m src.models.train_xgboost, outs: [models/model.pkl], metrics: [reports/metrics.json]}
  evaluate:  {cmd: python -m src.models.evaluate,      metrics: [reports/evaluation.json]}
```

```bash
dvc repro          # runs only what changed
dvc dag            # shows the diagram — screenshot it
dvc metrics show   # shows the scores
```

**Time-travel demo (worth marks, practise it):**
```bash
git checkout <old-commit>
dvc checkout            # the DATA goes back in time too
# show the old row count — proof that code and data move together
git checkout main && dvc checkout
```

---

## STEP 23 — React frontend (Hassan)

```bash
npm create vite@latest frontend -- --template react
cd frontend
npm install leaflet react-leaflet recharts axios
```

Pages:
1. **Map of Pakistan** — a coloured circle per city, colour = pollution level
2. **Time slider** — drag through the next 24 hours
3. **Click a city** — side panel with a 7-day chart + 24h forecast
4. **Layer toggles** — our prediction / provider forecast / real sensor
5. **Legend** — say clearly it's the **US EPA AQI** standard
6. **Footer** — data credits + "academic prototype, not a health warning"

Colours (US EPA PM2.5):
```js
const BANDS = [
  {max: 12.0,  color:"#00e400", label:"Good"},
  {max: 35.4,  color:"#ffff00", label:"Moderate"},
  {max: 55.4,  color:"#ff7e00", label:"Unhealthy for Sensitive Groups"},
  {max: 150.4, color:"#ff0000", label:"Unhealthy"},
  {max: 250.4, color:"#8f3f97", label:"Very Unhealthy"},
  {max: Infinity, color:"#7e0023", label:"Hazardous"},
];
```

**Important:** every popup must say where the number came from — `model_prediction`, `provider_forecast`, or `ground_station` — plus the time and the model version. This is an ethics requirement.

The browser talks only to **our** Flask API, never to Open-Meteo directly.

---

## STEP 24 — Monitoring (Prometheus + Grafana)

Both free, both run in `docker-compose`.

- **Prometheus** reads `http://api:5000/metrics` every 15 seconds and stores the numbers
- **Grafana** draws them as graphs — open at `localhost:3001`

Grafana panels to make:
1. Requests per second
2. Error rate %
3. Prediction speed (p95 latency)
4. Predictions per city
5. Distribution of predicted PM2.5
6. Which model version is running
7. Data quality failures

**Alerts** — we need at least one, and we must show it actually firing:
```yaml
- alert: HighAPIErrorRate
  expr: error_rate > 0.05
  for: 2m
```
To make it fire, just stop the API container or spam it with bad requests, then screenshot the red FIRING state.

---

## STEP 25 — Drift detection (Evidently)

**Drift** = the live data no longer looks like the training data, so the model gets worse.

```python
from evidently import Report
from evidently.presets import DataDriftPreset

report = Report(metrics=[DataDriftPreset()])
result = report.run(reference_data=training_data, current_data=last_7_days)
result.save_html("reports/drift_report.html")
```

If more than 30% of features drifted → Airflow triggers retraining.

**Easy demo (allowed by the requirements):** fake the drift.
```python
current = reference.copy()
current["pm2_5"] = current["pm2_5"] * 3.5        # pretend smog season
current["temperature_2m"] = current["temperature_2m"] - 12
```
Run the report → drift detected → Airflow retrains. Record this.

---

## STEP 26 — Automatic retraining + rollback

The full story to show the teacher:

```
Airflow checks drift
   ↓ drift found
Re-validate the data
   ↓
Trigger Kubeflow → retrain the model
   ↓
Compare the new model against the CURRENT production model
   ↓ new one is at least 2% better?
   ├── NO  → stop, keep the old model (DAG turns red)
   └── YES → move to Staging → a human approves → Production
                 ↓
            restart the app → check /model-info shows the new version
                 ↓ something broke?
            rollback to the previous version
```

The key point the teacher wants: **we do not blindly deploy every new model.** There is a comparison and a human approval.

Rollback script:
```bash
python -m src.models.registry rollback
kubectl rollout restart deployment/airwatch-api
curl $API/model-info     # shows the old version is back
```

---

## STEP 27 — Security & ethics

**Security checklist:**
- [ ] `.env` is in `.gitignore`, never pushed
- [ ] All tokens in GitHub Secrets
- [ ] Each person has their own tokens (never share one)
- [ ] SSH open only to our own IP; database not exposed to the internet
- [ ] Container runs as non-root
- [ ] `pip-audit` runs in CI
- [ ] API validates all input
- [ ] We don't log full request bodies

**Ethics — write these honestly in the report:**
1. This is a **student prototype**, not an official health warning system.
2. Most cities get **model estimates**, not real sensor readings — we label them differently.
3. The model is **less accurate in Balochistan and GB** because there's less data there. Say it plainly.
4. We show feature importance so people can see *why* a prediction is high.
5. All data sources are credited (Open-Meteo, OpenAQ, PAQI, GeoNames — all CC BY 4.0).
6. We collect **no personal data** at all.

**Risk table (need at least 3, give 5):**

| Risk | What we do about it |
|---|---|
| API goes down or rate-limits us | cache everything in our database, retry with backoff, keep a second source |
| Very few real sensors in Pakistan | validate where we can, report coverage honestly, call it a prototype |
| Model gets worse in smog season | drift monitoring + automatic retraining + seasonal features |
| One member blocked by another | agree the file formats and API shape in week 1, use fake data to work alone |
| Kubeflow too heavy for our laptops | use `kind` or `kfp.local`, still deliver the compiled YAML |

---

## STEP 28 — Documentation & final demo

**`README.md` must have:** what the project is, the live URL, how to run it in 3 commands, environment variable names (not values!), API examples, data credits, team contributions, how to shut everything down.

**`REPORT.md` must have:** problem, data sources + coverage, data quality findings, features + why no leakage, the model comparison table + justification, error analysis by season/region, the MLOps architecture, CI/CD evidence, deployment, monitoring, security, ethics, risks, individual contributions.

**2 diagrams** (draw.io, free): architecture diagram + workflow diagram.

### Demo order (rehearse it twice, record backup videos of everything)

| # | Show | Who |
|---|---|---|
| 1 | Architecture diagram + problem | Hassan |
| 2 | GitHub repo, branches, Pull Requests | all |
| 3 | DVC time travel (old code → old data) | all |
| 4 | **MLflow: 50+ runs, filter by member, the comparison table** | all 3 |
| 5 | Feast apply + materialize | one |
| 6 | `dvc repro` + `dvc dag` | one |
| 7 | Airflow DAG running + a failed task with retries | one |
| 8 | Kubeflow pipeline graph | one |
| 9 | **CI: the red PR that cannot merge, then the green one** | one |
| 10 | Docker Compose up, curl the 3 endpoints | Hassan |
| 11 | BentoML serving | one |
| 12 | **Kubernetes: kill a pod, it heals, scale to 5, rollback** | one |
| 13 | **Live cloud URL working** + logs | Hassan |
| 14 | React map with the time slider | Hassan |
| 15 | **Grafana dashboard + make an alert fire live** | one |
| 16 | **Fake drift → retraining → bad model REJECTED → good one promoted → rollback** | one |
| 17 | Limitations and ethics | Hassan |

**All three of us must be able to explain any part.** The examiner will deliberately ask Hassan about Kubernetes and ask Ifraz about the React map.

---

## Order to build things in

Do NOT perfect one step before starting the next. Get a tiny version of the whole thing working first, then improve each layer.

```
Setup → GitHub → DVC/DagsHub → check data exists
   → download 5 cities only → clean → features → baseline model → 1 MLflow run
   → Flask /health + /predict returning a fake number → Docker → a few tests → GitHub Actions
   ════════ now the whole thing works end-to-end ════════
   → scale to 130 cities + 12 years → real models → the 3-way comparison
   → Feast → dvc.yaml → Airflow → Kubeflow → Kubernetes
   → deploy to Oracle Cloud → React map → Grafana → Evidently
   → retraining + rollback → BentoML → report + diagrams → rehearse
```

---

## 10 mistakes that will cost us marks

1. **Doing the real work in a Jupyter notebook.** The teacher's PDF forbids it. Notebooks for exploring only; real code in `src/`.
2. **Splitting the data randomly.** It's time-series. Split by date only.
3. **Leakage** — using the future value as an input. Keep the leakage test.
4. **No baseline.** "MAE is 12" means nothing without "baseline was 18.9".
5. **Different MLflow experiment names.** Our comparison silently becomes impossible. Use `pm25-forecasting` for all 3.
6. **Pushing `.env` or a token to GitHub.** Install `pre-commit` before the first real commit.
7. **Only showing green CI.** We must show a failed gate blocking a merge.
8. **Using paid cloud by accident** (EKS, Fargate, RDS). Stick to Oracle Always Free / HF Spaces / Minikube.
9. **Saying every city has a sensor.** Label the source of every number.
10. **Leaving integration to the last week.** Get the tiny end-to-end version working early.

---

## Commands we'll use every day

```bash
# start work
git checkout main && git pull && dvc pull

# do work
git checkout -b feature/xyz
pytest -q
git add -A && git commit -m "feat: ..." && git push origin feature/xyz

# data
dvc add data/processed/features.parquet && dvc push
dvc repro

# train
python -m src.models.train_xgboost --max-depth 8 --lr 0.05

# run the app
docker compose up -d --build
curl localhost:5000/health

# kubernetes
minikube start && kubectl apply -f k8s/ && kubectl get pods -w
```

---

**Data credits:** Air quality and weather © Open-Meteo.com (CC BY 4.0) · Sensor data via OpenAQ · Pakistan data © PAQI (CC BY 4.0) · City coordinates © GeoNames (CC BY 4.0). Pakistan AirWatch AI is a free, academic, non-commercial student project and is not an official public-health warning system.
