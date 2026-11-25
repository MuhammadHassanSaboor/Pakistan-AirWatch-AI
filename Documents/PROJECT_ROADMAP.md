# Pakistan-AirWatch-AI — Complete A–Z Roadmap

**Team:** Hassan · Mudassar · Ifraz
**Course:** MLOps Semester Project
**Rule we follow everywhere:** free tools only. No paid APIs, no paid hosting beyond cloud free tiers.
**Scope:** 100+ cities of Pakistan, hourly PM2.5 forecasting.

> **How to read this document.** Work top to bottom. Every phase tells you *who* does it, *why* it exists, and the *exact commands*. Do not skip Phase 0 — if the three of you don't have identical environments, you will lose days to "it works on my machine".

---

## Table of Contents

1. [Decisions made up front (read this first)](#1-decisions-made-up-front)
2. [What the teacher actually grades](#2-what-the-teacher-actually-grades)
3. [Final architecture](#3-final-architecture)
4. [Every tool explained in plain English](#4-every-tool-explained-in-plain-english)
5. [Who does what — Hassan, Mudassar, Ifraz](#5-who-does-what)
6. [Phase 0 — Setup (all three members, same day)](#phase-0--setup)
7. [Phase 1 — Repository skeleton](#phase-1--repository-skeleton)
8. [Phase 2 — Git, DVC and DagsHub](#phase-2--git-dvc-and-dagshub)
9. [Phase 3 — Data collection (100+ cities, 10+ years)](#phase-3--data-collection)
10. [Phase 4 — Data validation](#phase-4--data-validation)
11. [Phase 5 — Feature engineering](#phase-5--feature-engineering)
12. [Phase 6 — Feature Store with Feast](#phase-6--feature-store-with-feast)
13. [Phase 7 — The 3-member model competition on shared MLflow](#phase-7--the-3-member-model-competition)
14. [Phase 8 — Model selection, registry and promotion](#phase-8--model-selection-registry-and-promotion)
15. [Phase 9 — The Flask API](#phase-9--the-flask-api)
16. [Phase 10 — BentoML (second serving path)](#phase-10--bentoml)
17. [Phase 11 — Testing with pytest](#phase-11--testing-with-pytest)
18. [Phase 12 — Docker and Docker Compose](#phase-12--docker-and-docker-compose)
19. [Phase 13 — GitHub Actions CI/CD](#phase-13--github-actions-cicd)
20. [Phase 14 — DVC pipeline (dvc.yaml)](#phase-14--dvc-pipeline)
21. [Phase 15 — Airflow orchestration](#phase-15--airflow-orchestration)
22. [Phase 16 — Kubeflow Pipelines](#phase-16--kubeflow-pipelines)
23. [Phase 17 — Kubernetes scaling](#phase-17--kubernetes-scaling)
24. [Phase 18 — React frontend](#phase-18--react-frontend)
25. [Phase 19 — AWS deployment on free tier](#phase-19--aws-deployment-on-free-tier)
26. [Phase 20 — Monitoring: Prometheus, Grafana, Evidently](#phase-20--monitoring)
27. [Phase 21 — Automated retraining and rollback](#phase-21--automated-retraining-and-rollback)
28. [Phase 22 — Security, ethics, risk assessment](#phase-22--security-ethics-risk-assessment)
29. [Phase 23 — Documentation, report and demo](#phase-23--documentation-report-and-demo)
30. [Final deliverables checklist](#30-final-deliverables-checklist)
31. [Mistakes that will cost you marks](#31-mistakes-that-will-cost-you-marks)

---

## 1. Decisions made up front

These are settled. Don't re-argue them mid-semester.

### 1.1 Backend framework: **Flask**, not Laravel

| Option | Verdict |
|---|---|
| **Laravel (PHP)** | ❌ **Do not use.** It earns zero marks. The rubric never mentions PHP. It forces you to maintain two languages, two Dockerfiles, two dependency systems, and an HTTP hop between PHP and Python for every prediction. For a beginner team this is the single biggest avoidable risk in the project. |
| **FastAPI** | ⚠️ Technically nicer than Flask, but the requirements document says **"Flask REST API"** five separate times and the rubric line reads *"Docker, Flask REST API and BentoML"*. Using FastAPI instead risks losing marks for no benefit. |
| **Flask** | ✅ **Use this.** Mandated by the spec. Simple enough for beginners (a working API is ~100 lines). Runs in production behind Gunicorn. Has `prometheus-flask-exporter` for the monitoring requirement in one line. |

**Final stack decision:**

```
React (frontend)  →  Flask (ONE backend: app APIs + ML serving)  →  PostgreSQL + PostGIS
                                      ↑
                        loads model from MLflow Registry
```

One Flask app serves both the graded ML endpoints (`/health`, `/model-info`, `/predict`) and the app endpoints the React map needs (`/api/cities`, `/api/forecast`, `/api/history`). One language, one repo, one container. This is strictly better for your situation.

> **Whoever suggested Flask over Laravel was right, and for the right reason:** your ML code is Python, so your serving layer should be Python.

### 1.2 Honest correction on "10–15 years of data"

You asked for 10–15 years. Here is the truth about what is free:

| Data | How far back, free | Source |
|---|---|---|
| **Hourly weather** (temp, humidity, wind, pressure, rain, boundary layer height) | **1940 → today** | Open-Meteo **Archive API** (ERA5 reanalysis). Free, no API key. |
| **Hourly air quality** (PM2.5, PM10, NO₂, SO₂, CO, O₃, dust) | **~2013 → today** (verify on day 1) | Open-Meteo **Air Quality API** (CAMS reanalysis). Free, no API key. |
| **Real ground-sensor readings in Pakistan** | Mostly **2017/2019 → today**, and only for a handful of cities (US Embassy/Consulate monitors in Islamabad, Lahore, Karachi, Peshawar + some PAQI monitors) | OpenAQ v3 (free API key) and PAQI/Hawanama |

**So: ~12 years of hourly air-quality data for 100+ cities is achievable and free.** That satisfies your "10–15 years" goal.

**But you must be honest about what it is.** The Open-Meteo air-quality archive is a *reanalysis model output*, not a sensor in every city. It is perfectly valid training data (every weather-forecasting system on earth trains on reanalysis), but in your report you must write:

> "Our primary training target is CAMS reanalysis PM2.5. We additionally validate against independent OpenAQ ground-station observations for the four Pakistani cities where they exist. We do not claim sensor-verified accuracy for cities without monitors."

Saying this *gains* you marks under "Discuss model limitations" (§3.13) and "data provenance". Hiding it and claiming a sensor in every city loses marks and is the first thing an examiner will attack in the oral defense.

**Action:** On day 1, Hassan runs the verification call in [Phase 3](#phase-3--data-collection) and records the actual earliest available date in `Documents/DATA_FEASIBILITY.md`. Whatever number comes back is the number you use everywhere.

### 1.3 Cities, not a grid

Your proposal said "grid". You've decided on **100+ cities**. That is a *better* choice for this project:

- A city list is a clean **entity key** for Feast (`city_id`) — a grid is messier.
- 120 cities × hourly is a dataset you can actually train on a laptop.
- The map still looks great: render coloured circle markers sized by population, not grid squares.
- Fewer API calls, so you stay inside free limits.

Keep one sentence in the report: *"We model named population centres rather than a uniform spatial grid, because the free data sources provide point extraction and because a city list gives a stable entity key for the feature store."*

### 1.4 Prediction task (pin this down now)

> **For a given city, at a given hour, predict PM2.5 (µg/m³) at +1h, +6h, +12h and +24h.**

- One **global** model for all cities (city identity enters as `latitude`, `longitude`, `elevation`, `city_type`). **Not** 120 separate models.
- `horizon` (1, 6, 12, 24) is a *feature*, so one model handles all four lead times.
- **Leakage rule:** to predict hour `t+h`, you may only use PM2.5 values up to hour `t` (lags), plus **weather forecast** values for `t+h` (legitimately known in advance). Never use the pollutant value at `t+h` as an input.
- **Splits are chronological**, never random:
  - Train: earliest → 2024-12-31
  - Validation: 2025-01-01 → 2025-12-31
  - Test: 2026-01-01 → today
- **Quality gate for deployment:** test-set MAE must beat the persistence baseline by ≥ 15%, **and** MAE must be < 20 µg/m³. Write these two numbers in `configs/model_params.yaml` — CI enforces them.

---

## 2. What the teacher actually grades

The rubric, translated into "what must exist in your repo", sorted by marks. **Build in this order of priority if you run short of time.**

| Marks | Component | What must physically exist |
|---|---|---|
| 12 | Airflow + Kubeflow pipelines | `pipelines/airflow/dags/*.py`, `pipelines/kubeflow/pipeline_definition.py`, screenshots of both running |
| 12 | Testing + CI/CD | `tests/` (6 categories), `.github/workflows/ci.yml`, a screenshot of a **failed** run blocking a merge |
| 12 | AWS deployment | Live `http://<ip>/health`, ECR image, S3 bucket, CloudWatch logs, budget alert screenshot |
| 10 | Docker + Flask + BentoML | `Dockerfile.api`, `docker-compose.yml`, `src/serving/app.py`, `src/serving/bentoml_service.py` |
| 10 | Documentation + demo + defense | `README.md`, `REPORT.md`, architecture diagram, all 3 can explain everything |
| 9 | Git + DVC + DagsHub | commit history, PRs, `.dvc/config`, data version rollback demo |
| 9 | MLflow tracking + registry | 50+ runs on shared DagsHub MLflow, registered model with Staging/Production stages |
| 6 | Feast feature store | `feature_store/feature_repo/`, materialize demo |
| 6 | Modular ML code | `src/` with real modules — **no notebooks doing the actual work** |
| 6 | Kubernetes | `k8s/*.yaml`, 3 replicas running, pod-kill demo |
| 6 | Monitoring + retraining | Grafana dashboard, Prometheus, one alert firing, Evidently drift report |
| 2 | Security | no secrets in git, IAM least privilege, `pip-audit`/Trivy in CI |

**Minimum acceptance criteria (§9 of the requirements) — all must be YES or the project fails regardless of marks:**

- [ ] Model trains via a reproducible pipeline (`dvc repro`)
- [ ] Data + code versions recoverable (`git checkout <old> && dvc checkout`)
- [ ] Experiments in MLflow
- [ ] Tests run in GitHub Actions
- [ ] **A failing quality gate blocks deployment** (you must *demonstrate* this)
- [ ] Model served by Flask in Docker
- [ ] Deployed on AWS, serves a real prediction
- [ ] Kubernetes deployment + scaling shown
- [ ] Airflow + Kubeflow shown
- [ ] Grafana + Prometheus + ≥1 alert + retraining trigger + promotion + rollback
- [ ] A stranger can follow the README and reproduce it

---

## 3. Final architecture

```
┌──────────────────────── DATA SOURCES (all free) ───────────────────────┐
│ Open-Meteo Air Quality API  (no key)  → PM2.5/PM10/NO2/SO2/CO/O3, ~2013+│
│ Open-Meteo Archive API      (no key)  → ERA5 weather, 1940+             │
│ Open-Meteo Forecast API     (no key)  → live + next 5 days weather      │
│ OpenAQ v3                   (free key)→ real sensor ground-truth         │
│ PAQI / Hawanama (CC BY 4.0) → Pakistan validation context               │
└────────────────────────────────┬───────────────────────────────────────┘
                                 ▼
                   src/data/ingestion.py  (Python)
                                 ▼
                   data/raw/*.parquet   ──► tracked by DVC ──► DagsHub storage
                                 ▼
                   src/data/validation.py  (Pandera schemas)
                                 ▼
                   src/features/preprocessing.py  (lags, calendar, weather)
                                 ▼
                   data/processed/features.parquet
                                 ▼
                   Feast feature store  (offline=parquet, online=SQLite/Redis)
                                 ▼
        ┌────────────── TRAINING (3 members in parallel) ──────────────┐
        │  Hassan: XGBoost   Mudassar: LightGBM+RF   Ifraz: LSTM+base  │
        │          all logging to ONE DagsHub MLflow server            │
        └───────────────────────────┬─────────────────────────────────┘
                                    ▼
                   MLflow Model Registry: Staging → Production
                                    ▼
    ┌──────────── SERVING ────────────┐      ┌────── ORCHESTRATION ──────┐
    │ Flask API (Gunicorn, Docker)    │      │ Airflow: schedule+ingest  │
    │  GET  /health                   │      │   └─ triggers ──►          │
    │  GET  /model-info               │      │ Kubeflow: ML graph         │
    │  POST /predict                  │      └───────────────────────────┘
    │  GET  /metrics  (Prometheus)    │
    │  GET  /api/cities, /api/forecast│      ┌────── MONITORING ─────────┐
    │ BentoML service (2nd path)      │ ───► │ Prometheus → Grafana       │
    └──────────────┬──────────────────┘      │ Evidently  → drift reports │
                   ▼                          │ CloudWatch → AWS logs      │
    React + Leaflet map (Vite)                └───────────────────────────┘
                   ▼
    AWS: EC2 t3.micro (free tier) + ECR + S3 + CloudWatch
    Local: Minikube (Kubernetes) + Kubeflow + Airflow + Prometheus + Grafana
```

**Why some things run locally:** §10 of the requirements explicitly permits it — *"allow selected infrastructure to run locally instead of requiring every component to remain hosted on AWS"*. Kubeflow and a Kubernetes cluster on AWS would cost real money. Run them on Minikube on a laptop, record screencasts, and say so in the README. The **one thing that must be on AWS** is the Flask prediction API.

---

## 4. Every tool explained in plain English

Read this section before touching anything. If you understand *why* each tool exists, the rest of the document becomes obvious.

### 4.1 Git + GitHub — version control for **code**

Git saves snapshots ("commits") of your code so you can go back in time and so three people can work at once.

**The only workflow you need:**

```bash
git checkout main
git pull origin main                 # get everyone's latest work
git checkout -b feature/add-lag-features   # your own branch
# ...edit files...
git add src/features/preprocessing.py
git commit -m "feat: add 1h/3h/24h PM2.5 lag features"
git push origin feature/add-lag-features
# then open a Pull Request on GitHub, someone else reviews, then Merge
```

**Rules for your team:**
- **Never commit directly to `main`.** Branch → PR → one teammate approves → merge. The rubric explicitly wants "branches and pull requests".
- Branch names: `feature/...`, `fix/...`, `docs/...`
- Commit messages: `feat:`, `fix:`, `docs:`, `test:`, `chore:` prefix.
- Never commit: `.env`, `*.csv`, `*.parquet`, `.pkl`, AWS keys. That is what `.gitignore` and DVC are for.

**Handling a merge conflict (the rubric asks you to document this):**

```bash
git checkout main && git pull
git checkout my-branch
git merge main
# Git prints: CONFLICT (content): Merge conflict in src/features/preprocessing.py
```
Open the file. You will see:
```
<<<<<<< HEAD
my version of the line
=======
main's version of the line
>>>>>>> main
```
Delete the markers, keep the correct combined code, then:
```bash
git add src/features/preprocessing.py
git commit -m "merge: resolve conflict in preprocessing"
```

**Conflict in a `.dvc` file is special** — a `.dvc` file contains a hash pointing to data. You cannot "merge" two hashes. You must pick one side, then re-run the pipeline:
```bash
git checkout --theirs data/raw/airquality.parquet.dvc   # or --ours
git add data/raw/airquality.parquet.dvc
dvc checkout                 # pull the data matching that hash
dvc repro                    # regenerate downstream stages
git commit -m "merge: resolve .dvc conflict, keep main's dataset version"
```
**Document exactly this in `Documents/MERGE_CONFLICTS.md` with real screenshots.** It is a graded deliverable.

### 4.2 DVC — version control for **data**

GitHub rejects files over 100 MB and is terrible at binary files. Your `features.parquet` will be hundreds of MB.

**What DVC does:** instead of putting the data in Git, DVC puts a tiny text file in Git that contains the data's fingerprint (an MD5 hash), and stores the real file in a "remote" (for you: DagsHub's free storage).

```bash
dvc add data/raw/airquality_hourly.parquet
# creates data/raw/airquality_hourly.parquet.dvc  ← 3 lines of text, goes in Git
# adds the real file to .gitignore
git add data/raw/airquality_hourly.parquet.dvc data/raw/.gitignore
git commit -m "data: add 2013-2026 hourly air quality for 127 cities"
dvc push          # uploads the real 400MB file to DagsHub
```

Your teammate then runs:
```bash
git pull          # gets the .dvc pointer file
dvc pull          # downloads the matching 400MB file
```

**The reproducibility demo the rubric demands (practise this, it's 9 marks):**
```bash
git log --oneline                      # find an old commit, e.g. a1b2c3d
git checkout a1b2c3d                   # code goes back in time
dvc checkout                           # DATA goes back in time to match
python -c "import pandas as pd; print(pd.read_parquet('data/processed/features.parquet').shape)"
# shows the OLD row count — proof that code and data moved together
git checkout main && dvc checkout      # come back
```

DVC also runs **pipelines** (see [Phase 14](#phase-14--dvc-pipeline)) — it knows that if `preprocessing.py` changed, it must re-run feature building and training, but not re-download raw data.

### 4.3 DagsHub — your free shared server (the key to your whole plan)

DagsHub is "GitHub for ML", and it is the piece that makes your idea of *"three members comparing models on one MLflow server for free"* work.

A free DagsHub repo gives you, at no cost:

| Feature | What you get |
|---|---|
| **Hosted MLflow server** | A real MLflow tracking URL all three of you log to. **This is your shared server.** No AWS, no setup, no cost. |
| **DVC remote storage** | ~10 GB free. Your `dvc push` target. |
| **Git mirror** | Mirrors your GitHub repo automatically. |
| **Data viewer** | Browse parquet/CSV in the browser. |

**Setup (do this once, Mudassar owns it):**

1. Sign up at `dagshub.com` with GitHub.
2. **Create → New Repository → Connect a repository** → pick your GitHub repo `Pakistan-AirWatch-AI`.
3. Click the green **Remote** button on the repo page. Copy the three tabs:
   - **DVC** → the `dvc remote add` commands
   - **MLflow** → `MLFLOW_TRACKING_URI`, `MLFLOW_TRACKING_USERNAME`, `MLFLOW_TRACKING_PASSWORD` (the password is a token)
4. **Invite Hassan and Ifraz as collaborators** (Settings → Collaborators). Each of them generates their **own** token under Settings → Tokens. **Never share one token between three people.**

Each member's `.env` (never committed):
```bash
MLFLOW_TRACKING_URI=https://dagshub.com/<owner>/Pakistan-AirWatch-AI.mlflow
MLFLOW_TRACKING_USERNAME=<your-dagshub-username>
MLFLOW_TRACKING_PASSWORD=<your-personal-dagshub-token>
DAGSHUB_USER_TOKEN=<same token, used by DVC>
```

DVC remote setup:
```bash
dvc remote add origin s3://dvc
dvc remote modify origin endpointurl https://dagshub.com/<owner>/Pakistan-AirWatch-AI.s3
dvc remote default origin
# credentials go in the LOCAL config, which is gitignored:
dvc remote modify --local origin access_key_id   <your-dagshub-token>
dvc remote modify --local origin secret_access_key <your-dagshub-token>
```

### 4.4 MLflow — the experiment notebook that never lies

Every time anyone trains a model, MLflow records: what algorithm, what hyperparameters, what dataset version, what git commit, what metrics, how long it took, and the model file itself. Then you open one web page and sort every experiment any of you ever ran by MAE.

**The pattern every training script uses (copy this exactly):**

```python
import mlflow, mlflow.sklearn, subprocess, time, os
from dotenv import load_dotenv
load_dotenv()

mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
mlflow.set_experiment("pm25-forecasting")          # ONE experiment, all 3 members

git_sha  = subprocess.check_output(["git","rev-parse","--short","HEAD"]).decode().strip()
data_ver = subprocess.check_output(["dvc","status","--json"]).decode()[:200]

with mlflow.start_run(run_name="xgboost-depth8-lr005"):
    mlflow.set_tags({
        "member":        "hassan",            # ← so you can filter by person
        "model_family":  "xgboost",
        "git_commit":    git_sha,
        "dataset_version": DATASET_MD5,       # the md5 from the .dvc file
        "horizon":       "multi",
    })
    mlflow.log_params({"max_depth":8, "learning_rate":0.05, "n_estimators":600})

    t0 = time.time()
    model.fit(X_train, y_train)
    mlflow.log_metric("train_seconds", time.time()-t0)

    mlflow.log_metrics({
        "val_mae": val_mae,  "val_rmse": val_rmse,  "val_r2": val_r2,
        "test_mae": test_mae, "test_rmse": test_rmse, "test_r2": test_r2,
        "mae_h1": m1, "mae_h6": m6, "mae_h12": m12, "mae_h24": m24,
        "baseline_mae": persistence_mae,
        "improvement_pct": 100*(persistence_mae-test_mae)/persistence_mae,
    })
    mlflow.log_artifact("reports/residual_plot.png")
    mlflow.log_artifact("reports/feature_importance.png")
    mlflow.sklearn.log_model(model, "model", registered_model_name="pm25-forecaster")
```

**Non-negotiable team rules for MLflow:**
1. **Everyone uses the same experiment name**: `pm25-forecasting`. Otherwise you cannot compare.
2. **Everyone tags `member`.** This is how you produce the comparison table for your report.
3. **Everyone logs the same metric names.** `val_mae` not `MAE` / `mae_val` / `mean_abs_err`. Agree on the list above and freeze it.
4. **Everyone evaluates on the identical test split.** If Ifraz tests on different dates, the comparison is meaningless. The split dates live in `configs/model_params.yaml` and are read from there — never hard-coded.
5. **Log the baseline MAE in every run** so improvement is always visible.

**Model Registry** — the second half of MLflow. Once you pick a winner:
```python
from mlflow.tracking import MlflowClient
c = MlflowClient()
c.transition_model_version_stage("pm25-forecaster", version=7, stage="Staging")
# after tests pass:
c.transition_model_version_stage("pm25-forecaster", version=7, stage="Production",
                                 archive_existing_versions=True)
```
Your Flask API loads `models:/pm25-forecaster/Production`. **Rollback = move the old version back to Production and restart.** That is the rollback demo the rubric wants, and it takes ten seconds.

> ⚠️ DagsHub's MLflow supports the Model Registry, but if you hit any limitation, the fallback is: run `mlflow server` inside `docker-compose` locally for the registry demo, and keep DagsHub for tracking. Test the registry on DagsHub in week 1 so you know which path you're on.

### 4.5 Feast — the feature store (6 marks, surprisingly easy)

**The problem it solves:** during *training* you compute `pm25_lag_24h` with pandas. During *serving* you compute it again, in a different file, with different code. If the two differ even slightly — different fill value for nulls, different timezone — your live predictions are silently wrong. This is called **training–serving skew**.

**What Feast does:** you define each feature *once*. Training reads it from the "offline store" (your parquet file). The API reads it from the "online store" (fast key-value lookup). Same definition, same values.

Minimal setup for you:
- **Entity:** `city_id`
- **Offline store:** file/parquet (free, no infra)
- **Online store:** SQLite (free, no infra) — upgrade to Redis in docker-compose if you want to look fancier
- **Feature views:** `city_weather_hourly`, `city_pollution_lags`, `city_static` (lat/lon/elevation/population)

You must demonstrate: define → `feast apply` → `feast materialize` (offline → online) → `get_online_features()` returns values. Four commands, 6 marks.

### 4.6 Apache Airflow — the scheduler

Airflow runs tasks on a schedule and shows a pretty graph of what ran, what failed, and what it retried. A **DAG** is just a Python file describing "task A, then B, then C".

Your three DAGs:

| DAG | Schedule | What it does |
|---|---|---|
| `hourly_ingest_dag` | `0 * * * *` (hourly) | fetch latest hour from Open-Meteo → validate → write to Postgres → refresh Feast online store |
| `ml_orchestrator_dag` | manual / weekly | validate data → **trigger the Kubeflow pipeline** → wait → report |
| `retraining_dag` | weekly + drift-triggered | check drift → if drift or stale → retrain → evaluate → promote to Staging → notify |

The rubric wants **retries and logging configured**, so always:
```python
default_args = {
    "owner": "airwatch",
    "retries": 3,
    "retry_delay": timedelta(minutes=5),
    "email_on_failure": False,
}
```

Run Airflow via Docker Compose locally. Do **not** try to run Airflow on AWS free tier — it will not fit in 1 GB of RAM.

### 4.7 Kubeflow Pipelines — the ML workflow graph

Airflow schedules; Kubeflow runs each ML step **in its own container on Kubernetes**. The requirements call this "dual orchestration" and it's worth 12 marks together with Airflow.

You write Python, and the KFP SDK compiles it to YAML:

```python
from kfp import dsl, compiler

@dsl.component(base_image="python:3.11", packages_to_install=["pandas","pyarrow"])
def preprocess(raw_path: str, out: dsl.Output[dsl.Dataset]): ...

@dsl.component(base_image="python:3.11", packages_to_install=["xgboost","mlflow"])
def train(features: dsl.Input[dsl.Dataset], model: dsl.Output[dsl.Model]) -> float: ...

@dsl.component(base_image="python:3.11")
def evaluate(model: dsl.Input[dsl.Model], threshold: float) -> bool: ...

@dsl.pipeline(name="pm25-training-pipeline")
def pipeline(raw_path: str = "s3://...", mae_threshold: float = 20.0):
    p = preprocess(raw_path=raw_path)
    t = train(features=p.outputs["out"])
    e = evaluate(model=t.outputs["model"], threshold=mae_threshold)
    with dsl.If(e.output == True):          # ← conditional execution = marks
        register(model=t.outputs["model"])

compiler.Compiler().compile(pipeline, "pipelines/kubeflow/compiled_pipeline.yaml")
```

Install on Minikube (free):
```bash
minikube start --cpus=4 --memory=8192
export PIPELINE_VERSION=2.2.0
kubectl apply -k "github.com/kubeflow/pipelines/manifests/kustomize/cluster-scoped-resources?ref=$PIPELINE_VERSION"
kubectl wait --for condition=established --timeout=60s crd/applications.app.k8s.io
kubectl apply -k "github.com/kubeflow/pipelines/manifests/kustomize/env/dev?ref=$PIPELINE_VERSION"
kubectl port-forward -n kubeflow svc/ml-pipeline-ui 8080:80
# open http://localhost:8080, upload compiled_pipeline.yaml, click Run
```

> **If Kubeflow refuses to install** (it is heavy and fussy), the honest fallback that still scores: install **`kfp` locally** (`pip install kfp`), compile the pipeline, show the generated `compiled_pipeline.yaml`, and run the same component graph with `kfp.local` or a `kind` cluster. Document the attempt and the constraint. Never skip the file — the YAML is the deliverable.

### 4.8 Docker + Docker Compose — "works on every machine"

**Docker image** = a frozen computer with your code, Python, and all libraries inside. **Container** = that image running.

**Docker Compose** = run several containers together with one command. Yours:

```yaml
services:
  api:        # Flask + Gunicorn
  db:         # postgres + postgis
  mlflow:     # local MLflow (backup / offline demo)
  prometheus: # scrapes api:5000/metrics
  grafana:    # dashboards
  airflow-*:  # webserver, scheduler, db
```

One command — `docker compose up -d` — and a teammate has the entire system. This is the "consistent execution on another machine" deliverable.

### 4.9 Kubernetes (Minikube) — scaling and self-healing

Docker runs one container. Kubernetes runs *many copies*, restarts them when they die, and load-balances across them.

What you must demonstrate (6 marks):
```bash
kubectl apply -f k8s/
kubectl get pods                          # 3 replicas Running
kubectl delete pod <one-pod-name>         # kill one
kubectl get pods -w                       # watch Kubernetes recreate it ← record this
kubectl scale deployment airwatch-api --replicas=5
```
Plus **readiness and liveness probes** pointing at `/health` in `k8s/api-deployment.yaml`.

### 4.10 pytest — automated testing

Tests are Python functions starting with `test_`. If `assert` fails, the test fails, CI goes red, and the merge is blocked. Six categories are required — see [Phase 11](#phase-11--testing-with-pytest).

### 4.11 GitHub Actions — CI/CD

A YAML file in `.github/workflows/`. On every push and PR, GitHub spins up a free Ubuntu machine and runs your lint → tests → security scan → Docker build → deploy. **Free and unlimited for public repos** — make your repo public (it's a student project with no secrets in it).

### 4.12 Prometheus + Grafana — operational monitoring

- **Prometheus** scrapes `GET /metrics` on your Flask app every 15 s and stores numbers over time.
- **Grafana** draws those numbers as graphs and fires alerts.

You get Prometheus metrics in Flask with literally two lines:
```python
from prometheus_flask_exporter import PrometheusMetrics
metrics = PrometheusMetrics(app)   # now GET /metrics exists, with request counts + latency
```
Then add custom ones: `predictions_total`, `prediction_latency_seconds`, `model_version_info`, `data_quality_failures_total`.

### 4.13 Evidently — ML-specific drift monitoring

Prometheus watches the *server*. Evidently watches the *data*. Give it a reference dataset (your training data) and current data (last 7 days of live inputs); it produces an HTML report saying which features have drifted.

```python
from evidently import Report
from evidently.presets import DataDriftPreset
report = Report(metrics=[DataDriftPreset()])
result = report.run(reference_data=ref_df, current_data=cur_df)
result.save_html("reports/drift_report.html")
```
If the drift share exceeds your threshold → Airflow triggers retraining. That is the "defined retraining trigger" requirement.

### 4.14 BentoML — the second serving path

The requirements want Flask **and** a BentoML demo. BentoML packages model + preprocessing into a versioned "Bento" and serves it with auto-generated docs and batching.

```python
import bentoml
bentoml.sklearn.save_model("pm25_forecaster", model)   # after training
```
```python
# src/serving/bentoml_service.py
import bentoml, numpy as np
from bentoml.io import JSON

runner = bentoml.sklearn.get("pm25_forecaster:latest").to_runner()
svc = bentoml.Service("airwatch_bento", runners=[runner])

@svc.api(input=JSON(), output=JSON())
def predict(payload): ...
```
```bash
bentoml serve src/serving/bentoml_service.py:svc --port 3000
bentoml build && bentoml containerize airwatch_bento:latest
```
Record a 2-minute screencast. Done. Flask stays the primary API.

### 4.15 Pandera — data validation

Declare what your data must look like; it raises an error if reality disagrees.
```python
import pandera.pandas as pa
schema = pa.DataFrameSchema({
    "city_id":   pa.Column(str, nullable=False),
    "timestamp": pa.Column("datetime64[ns, UTC]", nullable=False),
    "pm2_5":     pa.Column(float, pa.Check.in_range(0, 2000), nullable=True),
    "latitude":  pa.Column(float, pa.Check.in_range(23.0, 37.5)),
    "longitude": pa.Column(float, pa.Check.in_range(60.0, 78.0)),
})
schema.validate(df, lazy=True)   # lazy=True reports ALL errors at once
```

### 4.16 Ruff + pre-commit — code quality

```bash
pip install ruff pre-commit
pre-commit install
```
`.pre-commit-config.yaml` runs Ruff, trailing-whitespace, and a **secret detector** before every commit. The secret detector alone can save your project — it stops an AWS key reaching GitHub.

---

## 5. Who does what

The requirements say any member may work on any module, but everyone must be able to explain everything. Here is the split, matched to the three roles in §4 of the requirements.

### 👤 Hassan — Student 1: Data & ML Engineering *(+ team lead)*

**Owns:**
- `src/data/ingestion.py`, `src/data/validation.py`
- `src/features/preprocessing.py`
- `configs/*.yaml`
- Feast feature store (`feature_store/`)
- The **XGBoost** model family
- `data/` + all DVC data tracking
- Final `REPORT.md` and architecture diagrams

**Learns:** pandas, requests, Pandera, Feast, XGBoost, DVC

**Key outputs:** city list of 120+ cities · 12 years of hourly data in parquet · validated feature table · Feast repo · XGBoost experiments in MLflow · data-quality report

### 👤 Mudassar — Student 2: MLOps & Automation Engineering

**Owns:**
- DagsHub setup and access for the team
- `dvc.yaml` pipeline
- `pipelines/airflow/` (all three DAGs)
- `pipelines/kubeflow/`
- `tests/` (all six categories)
- `.github/workflows/ci.yml` and `deploy.yml`
- `.pre-commit-config.yaml`, Ruff config
- MLflow Model Registry promotion/rollback scripts
- The **LightGBM + RandomForest** model family

**Learns:** DVC pipelines, Airflow, KFP SDK, pytest, GitHub Actions, MLflow registry

**Key outputs:** working `dvc repro` · 3 Airflow DAGs with retries · compiled Kubeflow pipeline · 25+ tests · green CI + a *deliberately red* CI run as evidence · promotion/rollback scripts

### 👤 Ifraz — Student 3: Deployment & Reliability Engineering

**Owns:**
- `src/serving/app.py` (Flask) and `bentoml_service.py`
- `docker/Dockerfile.api`, `Dockerfile.ml`, `docker-compose.yml`
- `k8s/` manifests
- AWS: EC2, ECR, S3, CloudWatch, IAM, budget alert
- `frontend/` React + Leaflet map
- `monitoring/` Prometheus + Grafana + Evidently
- The **LSTM + baselines (persistence, seasonal-naive, linear)** model family

**Learns:** Flask, Docker, Kubernetes, AWS, React/Leaflet, Prometheus/Grafana

**Key outputs:** Flask API with 6 endpoints · working containers · Minikube scaling demo · live AWS endpoint · React map · Grafana dashboard with a firing alert

### Shared rituals (do not skip)

- **One 30-minute sync per week.** Each person: what I did / what's blocked / what I need from you.
- **Every PR reviewed by someone else.** This is graded *and* it's how the other two learn your module.
- **A `Documents/CONTRIBUTIONS.md`** updated weekly — the requirements demand an individual contribution statement.
- **Teach-back sessions:** before the demo, each member explains *someone else's* module to the other two. If you can't, you'll fail the oral defense.

---

## Phase 0 — Setup

**Who:** all three, same day, on a call together.
**Goal:** three identical machines.

### 0.1 Install (Windows)

| Tool | How |
|---|---|
| Python 3.11 | python.org — **tick "Add Python to PATH"** |
| Git | git-scm.com |
| VS Code | code.visualstudio.com + extensions: Python, Pylance, Docker, GitLens |
| Docker Desktop | docker.com — enable WSL2 backend |
| Node.js 20 LTS | nodejs.org |
| Minikube + kubectl | `winget install Kubernetes.minikube Kubernetes.kubectl` |

Verify:
```bash
python --version && git --version && docker --version && node --version && minikube version
```

### 0.2 Accounts (all free)

- GitHub (create org or use Hassan's account; add the other two as collaborators)
- DagsHub (sign in with GitHub)
- OpenAQ API key — `explore.openaq.org` → register → copy key
- AWS Free Tier — **Hassan only.** Needs a debit/credit card for verification. ⚠️ **Before anything else:** Billing → Budgets → create a budget of **$1** with an email alert at 80%. Then IAM → create user `airwatch-deploy` with programmatic access only.
- Grafana Cloud free tier (optional backup to self-hosted)

### 0.3 Python environment

```bash
cd "Pakistan-AirWatch-AI"
python -m venv .venv
.venv\Scripts\activate            # Windows;  source .venv/bin/activate on Mac/Linux
python -m pip install --upgrade pip
```

`requirements.txt` (start here, pin versions as you go):
```
pandas
numpy
pyarrow
requests
python-dotenv
pyyaml
scikit-learn
xgboost
lightgbm
scipy
pandera
evidently
mlflow
dvc[s3]
dagshub
feast
flask
gunicorn
prometheus-flask-exporter
flask-cors
psycopg2-binary
sqlalchemy
geopandas
shapely
bentoml
apache-airflow
kfp
pytest
pytest-cov
ruff
pre-commit
pip-audit
```

```bash
pip install -r requirements.txt
```

> Install `apache-airflow` and `kfp` in **separate** virtualenvs if you hit dependency conflicts — they are both heavy. Airflow will run in Docker anyway.

### 0.4 `.gitignore` (create before your first commit)

```gitignore
.venv/
__pycache__/
*.pyc
.env
.env.*
!.env.example
data/
!data/.gitkeep
mlruns/
*.pkl
*.joblib
*.parquet
*.csv
node_modules/
frontend/dist/
.dvc/cache
.dvc/tmp
*.pem
credentials*
.DS_Store
reports/*.html
```

### 0.5 `.env.example` (committed) vs `.env` (never committed)

```bash
# .env.example — copy to .env and fill in YOUR OWN values
MLFLOW_TRACKING_URI=https://dagshub.com/OWNER/Pakistan-AirWatch-AI.mlflow
MLFLOW_TRACKING_USERNAME=
MLFLOW_TRACKING_PASSWORD=
DAGSHUB_USER_TOKEN=
OPENAQ_API_KEY=
POSTGRES_USER=airwatch
POSTGRES_PASSWORD=
POSTGRES_DB=airwatch
DATABASE_URL=postgresql://airwatch:PASSWORD@localhost:5432/airwatch
AWS_REGION=ap-south-1
```

---

## Phase 1 — Repository skeleton

**Who:** Hassan creates, everyone clones.

```
Pakistan-AirWatch-AI/
├── Documents/
│   ├── MLOps_Course_Project_Requirements.pdf
│   ├── Pakistan_AirWatch_AI_Project_Proposal.pdf
│   ├── PROJECT_ROADMAP.md          ← this file
│   ├── DATA_FEASIBILITY.md         ← Hassan, week 1
│   ├── MERGE_CONFLICTS.md          ← Mudassar
│   ├── MODEL_COMPARISON.md         ← all three
│   ├── RISK_ASSESSMENT.md
│   └── CONTRIBUTIONS.md
├── data/
│   ├── raw/                        # DVC-tracked
│   ├── interim/
│   ├── processed/                  # DVC-tracked
│   └── reference/
│       └── pakistan_cities.csv     # ← small, goes in Git
├── src/
│   ├── __init__.py
│   ├── config.py                   # loads configs/*.yaml + .env
│   ├── data/
│   │   ├── ingestion.py            # Open-Meteo / OpenAQ clients
│   │   ├── historical.py           # 12-year backfill
│   │   ├── live.py                 # hourly live fetch
│   │   └── validation.py           # Pandera schemas
│   ├── features/
│   │   ├── preprocessing.py
│   │   └── build_features.py
│   ├── models/
│   │   ├── baseline.py             # persistence + seasonal naive
│   │   ├── train_xgboost.py        # Hassan
│   │   ├── train_lightgbm.py       # Mudassar
│   │   ├── train_lstm.py           # Ifraz
│   │   ├── tune.py
│   │   ├── evaluate.py
│   │   └── registry.py             # promote / rollback
│   ├── serving/
│   │   ├── app.py                  # Flask
│   │   ├── bentoml_service.py
│   │   ├── model_loader.py
│   │   └── schemas.py
│   └── monitoring/
│       ├── drift.py                # Evidently
│       └── metrics.py              # custom Prometheus metrics
├── feature_store/
│   ├── feature_repo/
│   │   ├── feature_store.yaml
│   │   ├── entities.py
│   │   ├── features.py
│   │   └── feature_views.py
│   └── materialize.py
├── tests/
│   ├── conftest.py
│   ├── test_data.py
│   ├── test_features.py
│   ├── test_feature_store.py
│   ├── test_model.py
│   ├── test_api.py
│   ├── test_pipeline.py
│   └── test_regression.py
├── pipelines/
│   ├── airflow/dags/
│   │   ├── hourly_ingest_dag.py
│   │   ├── ml_orchestrator_dag.py
│   │   └── retraining_dag.py
│   └── kubeflow/
│       ├── components/
│       ├── pipeline_definition.py
│       └── compiled_pipeline.yaml
├── configs/
│   ├── model_params.yaml
│   ├── data_config.yaml
│   └── pipeline_config.yaml
├── docker/
│   ├── Dockerfile.api
│   └── Dockerfile.ml
├── monitoring/
│   ├── prometheus.yml
│   ├── alert_rules.yml
│   └── grafana/dashboards/airwatch.json
├── k8s/
│   ├── api-deployment.yaml
│   ├── api-service.yaml
│   ├── api-hpa.yaml
│   └── configmap.yaml
├── frontend/                       # React + Vite + Leaflet
├── .github/workflows/
│   ├── ci.yml
│   └── deploy.yml
├── docker-compose.yml
├── dvc.yaml
├── params.yaml
├── requirements.txt
├── .env.example
├── .gitignore
├── .pre-commit-config.yaml
├── README.md
└── REPORT.md
```

Create it:
```bash
git init
git branch -M main
# create folders + empty __init__.py files
git add .
git commit -m "chore: initial repository structure"
git remote add origin https://github.com/<owner>/Pakistan-AirWatch-AI.git
git push -u origin main
```
Then on GitHub: **Settings → Branches → Add rule** for `main` → require a pull request + require status checks. This *forces* the PR workflow the rubric wants.

---

## Phase 2 — Git, DVC and DagsHub

**Who:** Mudassar leads, all three follow along.

```bash
dvc init
git commit -m "chore: initialise DVC"

# DagsHub remote (see §4.3 for where to find these values)
dvc remote add -d origin s3://dvc
dvc remote modify origin endpointurl https://dagshub.com/<owner>/Pakistan-AirWatch-AI.s3
dvc remote modify --local origin access_key_id     <YOUR_TOKEN>
dvc remote modify --local origin secret_access_key <YOUR_TOKEN>

git add .dvc/config
git commit -m "chore: configure DagsHub DVC remote"
git push
```

Smoke test (do this before you have real data — catch problems early):
```bash
echo "test" > data/raw/smoke.txt
dvc add data/raw/smoke.txt
git add data/raw/smoke.txt.dvc data/raw/.gitignore
git commit -m "test: dvc smoke test"
dvc push
git push
```
Then Ifraz on his machine: `git pull && dvc pull` → the file appears. **If this works, your whole data workflow works.** Delete the smoke file afterwards.

---

## Phase 3 — Data collection

**Who:** Hassan (lead), Ifraz helps with the city list.

### 3.1 Build the city list (120 cities)

Create `data/reference/pakistan_cities.csv`:

```csv
city_id,city_name,province,latitude,longitude,population,elevation_m
lahore,Lahore,Punjab,31.5204,74.3587,11126000,217
karachi,Karachi,Sindh,24.8607,67.0011,14910000,10
islamabad,Islamabad,ICT,33.6844,73.0479,1015000,540
faisalabad,Faisalabad,Punjab,31.4504,73.1350,3204000,186
rawalpindi,Rawalpindi,Punjab,33.5651,73.0169,2098000,508
...
```

Where to get 120 cities free:
- **GeoNames** (`download.geonames.org/export/dump/PK.zip`) — CC BY 4.0, includes lat/lon/population/elevation. Filter `feature_class = P` and `population > 25000` → you'll get well over 120.
- Cross-check the top 30 manually against Wikipedia.

Pick cities to cover **all provinces**: Punjab, Sindh, KPK, Balochistan, GB, AJK, ICT. An examiner will ask "is Gwadar in there? Is Skardu?" Have the answer be yes.

```python
# scripts/build_city_list.py
import pandas as pd
cols = ["geonameid","name","asciiname","alt","lat","lon","fclass","fcode",
        "country","cc2","admin1","admin2","admin3","admin4","population",
        "elevation","dem","tz","modified"]
df = pd.read_csv("PK.txt", sep="\t", names=cols, low_memory=False)
df = df[(df.fclass == "P") & (df.population > 25000)]
df = df.sort_values("population", ascending=False).head(130)
out = pd.DataFrame({
    "city_id":    df.asciiname.str.lower().str.replace(r"[^a-z0-9]+","_",regex=True),
    "city_name":  df.asciiname,
    "latitude":   df.lat.round(4),
    "longitude":  df.lon.round(4),
    "population": df.population,
    "elevation_m": df.dem,
})
out.drop_duplicates("city_id").to_csv("data/reference/pakistan_cities.csv", index=False)
print(len(out), "cities")
```

### 3.2 ⚠️ Day-1 feasibility check (do this before anything else)

```bash
curl "https://air-quality-api.open-meteo.com/v1/air-quality?latitude=31.5204&longitude=74.3587&hourly=pm2_5&start_date=2013-01-01&end_date=2013-01-02&timezone=UTC"
```

- If you get real numbers → you have ~13 years. 🎉
- If you get an error about the date → walk the start date forward (2016, 2019, 2022) until it works.

**Write the result into `Documents/DATA_FEASIBILITY.md`** with the exact URL, date tested, and earliest available date. That file is evidence for your report and protects you if a source changes.

Also check Pakistan station coverage:
```bash
curl -H "X-API-Key: $OPENAQ_API_KEY" \
  "https://api.openaq.org/v3/locations?iso=PK&limit=200"
```
Record how many stations exist and their date ranges. Expect a small number — that is fine and expected; say so in the report.

### 3.3 Historical backfill

**Strategy:** loop city × year → one API call each → save a parquet per city-year → concatenate.
130 cities × 13 years = **1,690 calls**. Open-Meteo's free tier allows roughly 10,000 calls/day, but each call's "cost" scales with the number of variables and days. **Be polite:** sleep 1–2 seconds between calls, and run the backfill overnight in 2–3 batches. If you get HTTP 429, sleep 60 s and retry.

```python
# src/data/historical.py
import time, requests, pandas as pd, pathlib

AQ_VARS = ["pm2_5","pm10","carbon_monoxide","nitrogen_dioxide",
           "sulphur_dioxide","ozone","dust","aerosol_optical_depth"]
WX_VARS = ["temperature_2m","relative_humidity_2m","dew_point_2m",
           "precipitation","surface_pressure","wind_speed_10m",
           "wind_direction_10m","boundary_layer_height","cloud_cover"]

def _get(url, params, retries=4):
    for i in range(retries):
        r = requests.get(url, params=params, timeout=90)
        if r.status_code == 200:
            return r.json()
        if r.status_code == 429:
            time.sleep(60); continue
        r.raise_for_status()
    raise RuntimeError(f"failed after {retries} retries: {url}")

def fetch_air_quality(lat, lon, start, end):
    j = _get("https://air-quality-api.open-meteo.com/v1/air-quality",
             {"latitude":lat, "longitude":lon, "hourly":",".join(AQ_VARS),
              "start_date":start, "end_date":end, "timezone":"UTC"})
    return pd.DataFrame(j["hourly"])

def fetch_weather(lat, lon, start, end):
    j = _get("https://archive-api.open-meteo.com/v1/archive",
             {"latitude":lat, "longitude":lon, "hourly":",".join(WX_VARS),
              "start_date":start, "end_date":end, "timezone":"UTC"})
    return pd.DataFrame(j["hourly"])

def backfill(cities_csv, start_year, end_year, outdir="data/raw/by_city_year"):
    pathlib.Path(outdir).mkdir(parents=True, exist_ok=True)
    cities = pd.read_csv(cities_csv)
    for _, c in cities.iterrows():
        for year in range(start_year, end_year + 1):
            fp = pathlib.Path(outdir) / f"{c.city_id}_{year}.parquet"
            if fp.exists():            # ← resumable: safe to re-run after a crash
                continue
            s, e = f"{year}-01-01", f"{year}-12-31"
            try:
                aq = fetch_air_quality(c.latitude, c.longitude, s, e)
                wx = fetch_weather(c.latitude, c.longitude, s, e)
            except Exception as ex:
                print(f"SKIP {c.city_id} {year}: {ex}"); continue
            df = aq.merge(wx, on="time", how="outer")
            df["city_id"]   = c.city_id
            df["latitude"]  = c.latitude
            df["longitude"] = c.longitude
            df["elevation_m"] = c.elevation_m
            df.to_parquet(fp, index=False)
            print(f"ok {c.city_id} {year}  rows={len(df)}")
            time.sleep(1.5)            # ← be a good citizen
```

Then concatenate:
```python
import pandas as pd, glob
df = pd.concat([pd.read_parquet(f) for f in glob.glob("data/raw/by_city_year/*.parquet")],
               ignore_index=True)
df["time"] = pd.to_datetime(df["time"], utc=True)
df = df.rename(columns={"time":"timestamp"}).sort_values(["city_id","timestamp"])
df.to_parquet("data/raw/airquality_hourly.parquet", index=False)
print(df.shape, df.timestamp.min(), df.timestamp.max())
```

Expected size: ~130 cities × ~114,000 hours ≈ **14 million rows**, ~1–2 GB as parquet with compression. If that is too big for DagsHub's free tier:
- Store `float32` instead of `float64` (halves it)
- Drop variables you don't use
- Or track only the **processed** features in DVC and keep raw city-year files local, documenting the choice.

**Then version it:**
```bash
dvc add data/raw/airquality_hourly.parquet
git add data/raw/airquality_hourly.parquet.dvc
git commit -m "data: 2013-2026 hourly AQ+weather, 130 Pakistani cities"
dvc push && git push
```

### 3.4 Ground truth from OpenAQ

```python
# src/data/ingestion.py (OpenAQ portion)
import os, requests, pandas as pd
HDRS = {"X-API-Key": os.environ["OPENAQ_API_KEY"]}

def pk_locations():
    r = requests.get("https://api.openaq.org/v3/locations",
                     params={"iso":"PK","limit":1000}, headers=HDRS, timeout=60)
    return pd.json_normalize(r.json()["results"])

def sensor_hours(sensor_id, date_from, date_to, page=1, out=None):
    out = out or []
    while True:
        r = requests.get(f"https://api.openaq.org/v3/sensors/{sensor_id}/hours",
                         params={"datetime_from":date_from,"datetime_to":date_to,
                                 "limit":1000,"page":page},
                         headers=HDRS, timeout=60)
        res = r.json()["results"]
        if not res: break
        out += res; page += 1
    return pd.json_normalize(out)
```
Map each station to its **nearest city** in your list (haversine distance, keep only matches within ~25 km). Save to `data/raw/openaq_ground_truth.parquet`. This is your independent validation set — the thing that makes your evaluation credible.

### 3.5 Live data (for the deployed app)

```python
# src/data/live.py — called hourly by Airflow
def fetch_live_batch(cities_df):
    """Open-Meteo accepts comma-separated coords: one call for many cities."""
    lats = ",".join(cities_df.latitude.astype(str))
    lons = ",".join(cities_df.longitude.astype(str))
    j = _get("https://air-quality-api.open-meteo.com/v1/air-quality",
             {"latitude":lats, "longitude":lons, "hourly":",".join(AQ_VARS),
              "past_days":2, "forecast_days":2, "timezone":"UTC"})
    # with multiple coords the response is a LIST, one object per city
    frames = []
    for city, obj in zip(cities_df.itertuples(), j if isinstance(j, list) else [j]):
        d = pd.DataFrame(obj["hourly"]); d["city_id"] = city.city_id
        frames.append(d)
    return pd.concat(frames, ignore_index=True)
```
Batching 130 cities into a handful of calls per hour keeps you far inside the free limit. **Always cache the response in Postgres** — never let the React map call Open-Meteo directly.

### 3.6 Attribution (required, free)

Put this in the README **and** in the footer of the React app:

> Air-quality and weather data © [Open-Meteo.com](https://open-meteo.com), CC BY 4.0. Ground-station observations via [OpenAQ](https://openaq.org) and their underlying providers. Pakistan context data © Pakistan Air Quality Initiative (PAQI), CC BY 4.0. City coordinates © GeoNames, CC BY 4.0. Academic, non-commercial prototype.

---

## Phase 4 — Data validation

**Who:** Hassan writes the schemas, Mudassar wires them into CI and Airflow.

```python
# src/data/validation.py
import pandera.pandas as pa
from pandera import Check, Column, DataFrameSchema

RAW_SCHEMA = DataFrameSchema(
    {
        "city_id":   Column(str, nullable=False),
        "timestamp": Column("datetime64[ns, UTC]", nullable=False),
        "pm2_5":     Column(float, Check.in_range(0, 2000), nullable=True),
        "pm10":      Column(float, Check.in_range(0, 3000), nullable=True),
        "ozone":     Column(float, Check.in_range(0, 1000), nullable=True),
        "nitrogen_dioxide": Column(float, Check.in_range(0, 1000), nullable=True),
        "temperature_2m":   Column(float, Check.in_range(-20, 60), nullable=True),
        "relative_humidity_2m": Column(float, Check.in_range(0, 100), nullable=True),
        "wind_speed_10m":   Column(float, Check.in_range(0, 200), nullable=True),
        "wind_direction_10m": Column(float, Check.in_range(0, 360), nullable=True),
        "latitude":  Column(float, Check.in_range(23.0, 37.5)),   # Pakistan bbox
        "longitude": Column(float, Check.in_range(60.0, 78.0)),
    },
    checks=[
        Check(lambda df: ~df.duplicated(["city_id","timestamp"]).any(),
              error="duplicate (city_id, timestamp) rows"),
        Check(lambda df: df["pm2_5"].isna().mean() < 0.30,
              error="more than 30% of PM2.5 is missing"),
    ],
    strict=False, coerce=True,
)

def validate_raw(df):
    """Returns (ok: bool, report: dict). Never raises — Airflow needs the report."""
    try:
        RAW_SCHEMA.validate(df, lazy=True)
        return True, {"status":"pass", "rows":len(df)}
    except pa.errors.SchemaErrors as e:
        return False, {"status":"fail", "rows":len(df),
                       "failures": e.failure_cases.to_dict("records")[:50]}
```

**Quality rules to also implement** (each one is easy marks under "data tests"):
- **Freshness:** newest timestamp is < 3 hours old
- **Completeness:** every city has ≥ 90% of expected hourly rows for the last 7 days
- **Physical sanity:** PM2.5 ≤ PM10 (fine particles are a subset of coarse)
- **Flatline detection:** a sensor reporting the identical value for > 12 hours is broken
- **Outlier flagging:** PM2.5 > 1000 µg/m³ → flag, don't silently drop. Record how many you flagged.

Every validation failure increments the Prometheus counter `data_quality_failures_total` → shows up in Grafana → can trigger an alert. That's three rubric items served by one function.

---

## Phase 5 — Feature engineering

**Who:** Hassan.

**The leakage rule again, because this is where teams fail:** to predict hour `t+h`, you may use PM2.5 at `t`, `t-1`, `t-2`, ... and **weather forecast** at `t+h`. You may **never** use PM2.5 at `t+h` or `t+1..t+h` as an input.

```python
# src/features/preprocessing.py
import numpy as np, pandas as pd

LAGS = [1, 2, 3, 6, 12, 24, 48, 72, 168]      # hours; 168 = one week
ROLLS = [3, 6, 12, 24, 72]

def add_calendar(df):
    ts = df["timestamp"]
    df["hour"]  = ts.dt.hour
    df["dow"]   = ts.dt.dayofweek
    df["month"] = ts.dt.month
    df["doy"]   = ts.dt.dayofyear
    df["is_weekend"] = (df["dow"] >= 5).astype(int)
    # cyclical encoding: hour 23 and hour 0 are neighbours
    df["hour_sin"]  = np.sin(2*np.pi*df["hour"]/24)
    df["hour_cos"]  = np.cos(2*np.pi*df["hour"]/24)
    df["month_sin"] = np.sin(2*np.pi*df["month"]/12)
    df["month_cos"] = np.cos(2*np.pi*df["month"]/12)
    # Pakistan-specific season — smog season matters a lot here
    df["is_smog_season"]  = df["month"].isin([10,11,12,1]).astype(int)
    df["is_monsoon"]      = df["month"].isin([7,8,9]).astype(int)
    return df

def add_lags(df, target="pm2_5"):
    g = df.groupby("city_id", sort=False)[target]
    for l in LAGS:
        df[f"{target}_lag_{l}h"] = g.shift(l)
    for w in ROLLS:
        df[f"{target}_roll{w}_mean"] = g.shift(1).rolling(w, min_periods=1).mean()
        df[f"{target}_roll{w}_std"]  = g.shift(1).rolling(w, min_periods=1).std()
        df[f"{target}_roll{w}_max"]  = g.shift(1).rolling(w, min_periods=1).max()
    df[f"{target}_diff_1h"]  = df[f"{target}_lag_1h"]  - df[f"{target}_lag_2h"]
    df[f"{target}_diff_24h"] = df[f"{target}_lag_1h"]  - df[f"{target}_lag_24h"]
    return df

def add_weather_derived(df):
    rad = np.deg2rad(df["wind_direction_10m"])
    df["wind_u"] = -df["wind_speed_10m"] * np.sin(rad)   # direction → components
    df["wind_v"] = -df["wind_speed_10m"] * np.cos(rad)
    # ventilation: wind speed × mixing height ≈ how fast pollution disperses
    df["ventilation_index"] = df["wind_speed_10m"] * df["boundary_layer_height"].fillna(500)
    df["is_calm"] = (df["wind_speed_10m"] < 2).astype(int)
    df["temp_x_humidity"] = df["temperature_2m"] * df["relative_humidity_2m"] / 100
    return df

def add_spatial(df, cities):
    """Mean PM2.5 of the 3 nearest cities, lagged — pollution travels."""
    # precompute neighbours once with a KDTree over lat/lon; shift(1) to avoid leakage
    ...

def make_supervised(df, horizons=(1, 6, 12, 24), target="pm2_5"):
    """Long format: one row per (city, time, horizon) with column y."""
    out = []
    for h in horizons:
        d = df.copy()
        d["horizon"] = h
        d["y"] = d.groupby("city_id")[target].shift(-h)   # the FUTURE value = label
        out.append(d)
    res = pd.concat(out, ignore_index=True)
    return res.dropna(subset=["y"])

def build(raw_df, cities_df):
    df = raw_df.sort_values(["city_id","timestamp"]).copy()
    df = add_calendar(df)
    df = add_lags(df)
    df = add_weather_derived(df)
    df = add_spatial(df, cities_df)
    df = make_supervised(df)
    return df
```

**Chronological split (put this in one place and import it everywhere):**
```python
# src/features/splits.py
import pandas as pd
def chrono_split(df, train_end, val_end):
    ts = pd.to_datetime(df["timestamp"], utc=True)
    return (df[ts <= train_end],
            df[(ts > train_end) & (ts <= val_end)],
            df[ts > val_end])
```
`configs/model_params.yaml`:
```yaml
split:
  train_end: "2024-12-31T23:00:00Z"
  val_end:   "2025-12-31T23:00:00Z"
target: pm2_5
horizons: [1, 6, 12, 24]
quality_gate:
  max_test_mae: 20.0
  min_improvement_over_baseline_pct: 15.0
```

> **Everyone imports `chrono_split` and reads these dates from the YAML.** This is the single most important line in the whole comparison plan — it is what makes three people's numbers comparable.

---

## Phase 6 — Feature Store with Feast

**Who:** Hassan.

```bash
cd feature_store && feast init -m feature_repo && cd ..
```

`feature_store/feature_repo/feature_store.yaml`:
```yaml
project: airwatch
registry: data/registry.db
provider: local
offline_store:
  type: file
online_store:
  type: sqlite
  path: data/online_store.db
entity_key_serialization_version: 3
```

`entities.py`:
```python
from feast import Entity, ValueType
city = Entity(name="city_id", value_type=ValueType.STRING,
              description="Stable identifier for a Pakistani city")
```

`feature_views.py`:
```python
from datetime import timedelta
from feast import FeatureView, Field, FileSource
from feast.types import Float32, Int64
from entities import city

pollution_source = FileSource(
    path="../../data/processed/features.parquet",
    timestamp_field="timestamp",
    created_timestamp_column="ingested_at",
)

city_pollution_lags = FeatureView(
    name="city_pollution_lags",
    entities=[city],
    ttl=timedelta(days=3),
    schema=[
        Field(name="pm2_5_lag_1h",  dtype=Float32),
        Field(name="pm2_5_lag_24h", dtype=Float32),
        Field(name="pm2_5_roll24_mean", dtype=Float32),
        Field(name="pm2_5_roll24_std",  dtype=Float32),
    ],
    source=pollution_source,
    online=True,
    tags={"owner":"hassan","freshness":"hourly"},
)

city_weather_hourly = FeatureView(
    name="city_weather_hourly",
    entities=[city],
    ttl=timedelta(days=3),
    schema=[
        Field(name="temperature_2m", dtype=Float32),
        Field(name="relative_humidity_2m", dtype=Float32),
        Field(name="wind_speed_10m", dtype=Float32),
        Field(name="ventilation_index", dtype=Float32),
    ],
    source=pollution_source,
    online=True,
    tags={"owner":"hassan","freshness":"hourly"},
)
```

Demonstrate the full loop (this *is* the deliverable):
```bash
cd feature_store/feature_repo
feast apply                                        # register definitions
feast materialize-incremental $(date -u +%Y-%m-%dT%H:%M:%S)   # offline → online
feast ui                                           # screenshot this
```

Training-time retrieval (offline):
```python
store = FeatureStore(repo_path="feature_store/feature_repo")
training_df = store.get_historical_features(
    entity_df=entity_df,                            # city_id + timestamp + y
    features=["city_pollution_lags:pm2_5_lag_1h",
              "city_weather_hourly:temperature_2m"],
).to_df()
```

Serving-time retrieval (online, inside Flask):
```python
feats = store.get_online_features(
    features=[...],
    entity_rows=[{"city_id": "lahore"}],
).to_dict()
```

**Document in `REPORT.md`:** feature names, dtypes, source, transformation logic, freshness expectation, owner. That list is explicitly required by §12.1.

---

## Phase 7 — The 3-member model competition

**This is the heart of your plan and it works beautifully. Here's how to run it so the comparison is fair and the MLflow page tells a story.**

### 7.1 The ground rules (agree in writing before anyone trains)

| Rule | Value |
|---|---|
| Dataset | exactly `data/processed/features.parquet` at DVC version `<md5>` — everyone runs `dvc pull` first |
| Split | from `configs/model_params.yaml`, via `chrono_split()` |
| Target | `y` (PM2.5 at t+h), µg/m³ |
| Metrics | `val_mae`, `val_rmse`, `val_r2`, `test_mae`, `test_rmse`, `test_r2`, `mae_h1/h6/h12/h24`, `baseline_mae`, `improvement_pct`, `train_seconds` |
| Experiment | `pm25-forecasting` on the DagsHub MLflow server |
| Required tags | `member`, `model_family`, `git_commit`, `dataset_version` |
| Minimum runs per member | **10** (different hyperparameters) |
| Selection metric | `test_mae`, with `mae_h24` as the tie-breaker |

### 7.2 Who trains what

| Member | Models | Why this one |
|---|---|---|
| **Ifraz** | `persistence` (y = last value), `seasonal_naive` (y = same hour yesterday), `LinearRegression`, `Ridge` | **Baselines first.** Nothing else means anything until these exist. If XGBoost can't beat "same hour yesterday", you have a bug, not a model. Then Ifraz attempts an LSTM (optional, only if time allows). |
| **Hassan** | `XGBoost` — tune `max_depth`, `learning_rate`, `n_estimators`, `subsample`, `colsample_bytree`, `min_child_weight` | The strongest general-purpose model for tabular time series. Likely your winner. |
| **Mudassar** | `LightGBM`, `RandomForest`, `HistGradientBoosting` | LightGBM is faster than XGBoost on 14 M rows and sometimes wins. RandomForest is a useful robustness check. |

### 7.3 Template every training script follows

```python
# src/models/train_xgboost.py  (Hassan; the others copy this shape exactly)
import os, time, json, subprocess, argparse
import pandas as pd, numpy as np, mlflow, mlflow.xgboost, yaml, xgboost as xgb
from dotenv import load_dotenv
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from src.features.splits import chrono_split

MEMBER = "hassan"
FAMILY = "xgboost"

def metrics(y, p):
    return {"mae": mean_absolute_error(y,p),
            "rmse": float(np.sqrt(mean_squared_error(y,p))),
            "r2": r2_score(y,p)}

def main(args):
    load_dotenv()
    cfg = yaml.safe_load(open("configs/model_params.yaml"))
    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
    mlflow.set_experiment("pm25-forecasting")

    df = pd.read_parquet("data/processed/features.parquet")
    tr, va, te = chrono_split(df, cfg["split"]["train_end"], cfg["split"]["val_end"])

    drop = ["y","timestamp","city_id","city_name","province","ingested_at"]
    feats = [c for c in df.columns if c not in drop]

    # baseline for context — logged in EVERY run
    base_pred = te["pm2_5_lag_1h"].fillna(te["pm2_5_roll24_mean"])
    base_mae  = mean_absolute_error(te["y"], base_pred)

    params = dict(max_depth=args.max_depth, learning_rate=args.lr,
                  n_estimators=args.n_estimators, subsample=args.subsample,
                  colsample_bytree=args.colsample, min_child_weight=args.mcw,
                  objective="reg:absoluteerror", tree_method="hist",
                  early_stopping_rounds=50, random_state=42)

    run_name = f"{FAMILY}-d{args.max_depth}-lr{args.lr}-n{args.n_estimators}"
    with mlflow.start_run(run_name=run_name):
        mlflow.set_tags({
            "member": MEMBER, "model_family": FAMILY,
            "git_commit": subprocess.check_output(["git","rev-parse","--short","HEAD"]).decode().strip(),
            "dataset_version": open("data/processed/features.parquet.dvc").read().split("md5: ")[1][:32],
        })
        mlflow.log_params(params)
        mlflow.log_params({"n_features": len(feats), "n_train": len(tr)})

        t0 = time.time()
        model = xgb.XGBRegressor(**params)
        model.fit(tr[feats], tr["y"], eval_set=[(va[feats], va["y"])], verbose=False)
        train_s = time.time() - t0

        vm = metrics(va["y"], model.predict(va[feats]))
        tp = model.predict(te[feats])
        tm = metrics(te["y"], tp)

        per_h = {f"mae_h{h}": mean_absolute_error(te[te.horizon==h]["y"], tp[te.horizon.values==h])
                 for h in cfg["horizons"]}

        mlflow.log_metrics({
            **{f"val_{k}":v  for k,v in vm.items()},
            **{f"test_{k}":v for k,v in tm.items()},
            **per_h,
            "baseline_mae": base_mae,
            "improvement_pct": 100*(base_mae - tm["mae"])/base_mae,
            "train_seconds": train_s,
        })

        # artefacts: plots make your MLflow page look professional
        save_residual_plot(te["y"], tp, "reports/residuals.png")
        save_importance_plot(model, feats, "reports/importance.png")
        mlflow.log_artifact("reports/residuals.png")
        mlflow.log_artifact("reports/importance.png")

        mlflow.xgboost.log_model(model, "model", registered_model_name="pm25-forecaster")
        print(json.dumps({"test_mae": tm["mae"], "baseline": base_mae}, indent=2))

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-depth", type=int, default=8)
    ap.add_argument("--lr", type=float, default=0.05)
    ap.add_argument("--n-estimators", type=int, default=600)
    ap.add_argument("--subsample", type=float, default=0.8)
    ap.add_argument("--colsample", type=float, default=0.8)
    ap.add_argument("--mcw", type=int, default=5)
    main(ap.parse_args())
```

Run many configurations:
```bash
for d in 4 6 8 10; do
  for lr in 0.01 0.05 0.1; do
    python -m src.models.train_xgboost --max-depth $d --lr $lr
  done
done
```
That's 12 runs from one loop. Do the same for LightGBM. You'll have 50+ runs on the shared server in an afternoon.

### 7.4 Producing the comparison table

```python
# scripts/compare_models.py
import mlflow, pandas as pd, os
from dotenv import load_dotenv; load_dotenv()
mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])

runs = mlflow.search_runs(experiment_names=["pm25-forecasting"])
cols = ["tags.member","tags.model_family","metrics.test_mae","metrics.test_rmse",
        "metrics.test_r2","metrics.mae_h1","metrics.mae_h24",
        "metrics.improvement_pct","metrics.train_seconds","run_id"]
tbl = runs[cols].sort_values("metrics.test_mae")
tbl.to_csv("Documents/all_runs.csv", index=False)

best = (tbl.groupby(["tags.member","tags.model_family"])
           .first().reset_index().sort_values("metrics.test_mae"))
print(best.to_markdown(index=False))
```
Paste the output into `Documents/MODEL_COMPARISON.md` and `REPORT.md`. Something like:

| Member | Family | test MAE | test RMSE | R² | MAE@1h | MAE@24h | vs baseline |
|---|---|---|---|---|---|---|---|
| Hassan | xgboost | **11.8** | 19.4 | 0.81 | 5.2 | 18.9 | +38% |
| Mudassar | lightgbm | 12.1 | 19.9 | 0.80 | 5.4 | 19.3 | +36% |
| Mudassar | random_forest | 14.7 | 23.8 | 0.72 | 7.1 | 22.4 | +22% |
| Ifraz | ridge | 17.9 | 28.1 | 0.61 | 9.8 | 25.0 | +5% |
| Ifraz | persistence | 18.9 | 31.2 | 0.52 | 4.9 | 31.5 | — |

**Write a paragraph justifying the choice** — not just "lowest MAE", but *why*: inference latency, model size, interpretability, stability across seasons. Section 3.3 of the requirements says "justify the selected model."

> **Notice the honest detail in that table:** persistence wins at 1h and loses badly at 24h. Pointing that out yourself in the defense shows you understand your model. Examiners love it.

### 7.5 Also compare per-region and per-season

Required by the proposal and good practice:
```python
te["abs_err"] = np.abs(te["y"] - tp)
print(te.groupby("province")["abs_err"].mean().sort_values())
print(te.groupby(te.timestamp.dt.month)["abs_err"].mean())
```
Expect much higher error in smog season (Oct–Jan) and in Lahore/Faisalabad. **Say so.** Then show your coverage map: which cities have independent OpenAQ validation and which don't.

---

## Phase 8 — Model selection, registry and promotion

**Who:** Mudassar.

```python
# src/models/registry.py
import os, mlflow
from mlflow.tracking import MlflowClient

MODEL = "pm25-forecaster"

def client():
    mlflow.set_tracking_uri(os.environ["MLFLOW_TRACKING_URI"])
    return MlflowClient()

def promote_to_staging(run_id):
    c = client()
    mv = [m for m in c.search_model_versions(f"name='{MODEL}'") if m.run_id == run_id][0]
    c.transition_model_version_stage(MODEL, mv.version, "Staging")
    return mv.version

def promote_to_production(version, test_mae, baseline_mae, cfg):
    """QUALITY GATE — this is the function that must be able to say NO."""
    gate = cfg["quality_gate"]
    improvement = 100*(baseline_mae - test_mae)/baseline_mae
    if test_mae > gate["max_test_mae"]:
        raise ValueError(f"GATE FAILED: test_mae {test_mae:.2f} > {gate['max_test_mae']}")
    if improvement < gate["min_improvement_over_baseline_pct"]:
        raise ValueError(f"GATE FAILED: improvement {improvement:.1f}% < "
                         f"{gate['min_improvement_over_baseline_pct']}%")
    c = client()
    c.transition_model_version_stage(MODEL, version, "Production",
                                     archive_existing_versions=True)
    c.set_model_version_tag(MODEL, version, "approved_by", "team-review")
    return version

def rollback():
    """Promote the most recent Archived version back to Production."""
    c = client()
    archived = [m for m in c.search_model_versions(f"name='{MODEL}'")
                if m.current_stage == "Archived"]
    prev = sorted(archived, key=lambda m: int(m.version))[-1]
    c.transition_model_version_stage(MODEL, prev.version, "Production",
                                     archive_existing_versions=True)
    return prev.version
```

**The governance story to tell in your defense:**
1. Any run can be registered → version N, stage `None`
2. Automated evaluation moves the best candidate → `Staging`
3. Integration tests run against Staging
4. **A human (team review) approves** → `Production`
5. The deployed Flask API always loads `models:/pm25-forecaster/Production`
6. If something breaks → `python -m src.models.registry rollback` → restart pods → previous model serving in under a minute

**Demo both paths at the defense:** one model that passes and gets promoted, and one deliberately bad model (train with `n_estimators=1`) that the gate rejects. The second is worth more marks than the first.

---

## Phase 9 — The Flask API

**Who:** Ifraz.

```python
# src/serving/app.py
import os, time, logging, uuid
from flask import Flask, request, jsonify, g
from flask_cors import CORS
from prometheus_flask_exporter import PrometheusMetrics
from prometheus_client import Counter, Histogram, Gauge
from src.serving.model_loader import ModelLoader
from src.serving.schemas import validate_predict_request

app = Flask(__name__)
CORS(app, origins=os.getenv("ALLOWED_ORIGINS","http://localhost:5173").split(","))
metrics = PrometheusMetrics(app)              # gives /metrics for free
metrics.info("airwatch_app", "Pakistan AirWatch AI", version=os.getenv("APP_VERSION","dev"))

PREDICTIONS   = Counter("predictions_total", "Predictions served", ["city_id","horizon"])
PRED_LATENCY  = Histogram("prediction_latency_seconds", "Inference latency")
PRED_VALUE    = Histogram("predicted_pm25_ugm3", "Distribution of predictions",
                          buckets=[10,25,50,100,150,250,500])
DQ_FAILURES   = Counter("data_quality_failures_total", "Validation failures", ["check"])
MODEL_INFO    = Gauge("model_version_info", "Model version in use", ["version","stage"])

logging.basicConfig(level=logging.INFO,
    format='{"ts":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}')
log = logging.getLogger("airwatch")

loader = ModelLoader()                        # loads models:/pm25-forecaster/Production
MODEL_INFO.labels(version=loader.version, stage="Production").set(1)

@app.before_request
def _start():
    g.rid = str(uuid.uuid4())[:8]; g.t0 = time.time()

@app.after_request
def _log(resp):
    log.info(f"rid={g.rid} {request.method} {request.path} -> {resp.status_code} "
             f"{(time.time()-g.t0)*1000:.1f}ms")
    return resp

# ─────────── required endpoints ───────────

@app.get("/health")
def health():
    return jsonify({
        "status": "healthy" if loader.is_ready() else "degraded",
        "model_loaded": loader.is_ready(),
        "timestamp": time.time(),
    }), (200 if loader.is_ready() else 503)

@app.get("/model-info")
def model_info():
    return jsonify({
        "model_name":    loader.name,
        "model_version": loader.version,
        "stage":         loader.stage,
        "run_id":        loader.run_id,
        "algorithm":     loader.algorithm,
        "trained_at":    loader.trained_at,
        "features":      loader.feature_names,
        "metrics":       loader.metrics,
        "target":        "pm2_5_ugm3",
        "horizons":      [1,6,12,24],
    })

@app.post("/predict")
def predict():
    payload = request.get_json(silent=True)
    if payload is None:
        return jsonify({"error":"body must be valid JSON"}), 400
    ok, err, clean = validate_predict_request(payload)
    if not ok:
        DQ_FAILURES.labels(check="request_schema").inc()
        return jsonify({"error":"validation failed","details":err}), 422
    try:
        with PRED_LATENCY.time():
            out = loader.predict(clean)
    except Exception as e:
        log.exception(f"rid={g.rid} prediction failed")
        return jsonify({"error":"internal prediction error","request_id":g.rid}), 500
    for r in out:
        PREDICTIONS.labels(city_id=r["city_id"], horizon=str(r["horizon"])).inc()
        PRED_VALUE.observe(r["pm2_5_pred"])
    return jsonify({"model_version": loader.version,
                    "generated_at": time.time(),
                    "predictions": out}), 200

# ─────────── app endpoints for the React map ───────────

@app.get("/api/cities")        # id, name, lat, lon, province
def cities(): ...

@app.get("/api/forecast")      # ?valid_time=...  → GeoJSON for the whole map
def forecast(): ...

@app.get("/api/history/<city_id>")   # last 7 days observed + predicted
def history(city_id): ...

@app.errorhandler(404)
def nf(e): return jsonify({"error":"not found"}), 404
@app.errorhandler(405)
def na(e): return jsonify({"error":"method not allowed"}), 405
```

`src/serving/schemas.py`:
```python
VALID_HORIZONS = {1,6,12,24}

def validate_predict_request(p):
    errs = []
    if not isinstance(p, dict) or "cities" not in p:
        return False, ["body must be an object with a 'cities' array"], None
    if not isinstance(p["cities"], list) or not (1 <= len(p["cities"]) <= 200):
        return False, ["'cities' must be a list of 1..200 items"], None
    clean = []
    for i, c in enumerate(p["cities"]):
        if not isinstance(c, dict) or "city_id" not in c:
            errs.append(f"cities[{i}]: city_id required"); continue
        h = c.get("horizon", 24)
        if h not in VALID_HORIZONS:
            errs.append(f"cities[{i}]: horizon must be one of {sorted(VALID_HORIZONS)}"); continue
        clean.append({"city_id": str(c["city_id"])[:64], "horizon": int(h)})
    return (len(errs)==0), errs, clean
```

Example request/response for the README:
```bash
curl -X POST http://localhost:5000/predict \
  -H "Content-Type: application/json" \
  -d '{"cities":[{"city_id":"lahore","horizon":24},{"city_id":"karachi","horizon":6}]}'
```
```json
{
  "model_version": "7",
  "generated_at": 1763000000.0,
  "predictions": [
    {"city_id":"lahore","horizon":24,"valid_time":"2026-11-14T06:00:00Z",
     "pm2_5_pred":142.6,"unit":"ug/m3","aqi_us":196,"aqi_category":"Unhealthy",
     "source":"model_prediction","model_version":"7"},
    {"city_id":"karachi","horizon":6,"valid_time":"2026-11-13T12:00:00Z",
     "pm2_5_pred":48.3,"unit":"ug/m3","aqi_us":133,"aqi_category":"Unhealthy for Sensitive Groups",
     "source":"model_prediction","model_version":"7"}
  ]
}
```

**Security notes the rubric wants:**
- Never log the full request body (log the request id and city count only)
- Cap the number of cities per request (done above — prevents a cheap DoS)
- Return 422 for bad input, 500 only for genuine server faults
- Add a simple rate limit (`flask-limiter`) if time allows

**AQI:** use the **US EPA PM2.5 breakpoints**, name the standard explicitly in the UI legend, and apply **NowCast** for hourly display. Do not mix µg/m³ thresholds with AQI numbers in the same legend.

---

## Phase 10 — BentoML

**Who:** Ifraz. Budget: half a day. It is 1–2 marks; don't gold-plate it.

```python
# after a winning training run
import bentoml, mlflow
m = mlflow.pyfunc.load_model("models:/pm25-forecaster/Production")
bentoml.mlflow.import_model("pm25_forecaster", "models:/pm25-forecaster/Production")
```
```python
# src/serving/bentoml_service.py
import bentoml, pandas as pd
from bentoml.io import JSON

runner = bentoml.mlflow.get("pm25_forecaster:latest").to_runner()
svc = bentoml.Service("airwatch_bento", runners=[runner])

@svc.api(input=JSON(), output=JSON(), route="/predict")
async def predict(payload: dict) -> dict:
    df = pd.DataFrame(payload["rows"])
    preds = await runner.async_run(df)
    return {"predictions": preds.tolist(), "serving": "bentoml"}

@svc.api(input=JSON(), output=JSON(), route="/healthz")
def healthz(_): return {"status":"ok"}
```
```bash
bentoml serve src/serving/bentoml_service.py:svc --port 3000
curl -X POST localhost:3000/predict -H "Content-Type: application/json" -d '{"rows":[...]}'
bentoml build
bentoml containerize airwatch_bento:latest
```
**In the report:** "Flask is the production API per the specification. BentoML was evaluated as an alternative serving path; it provides automatic batching, built-in model versioning from the MLflow registry, and a one-command container build. We demonstrate it locally and document how the Bento image would move through the same CI/CD workflow."

---

## Phase 11 — Testing with pytest

**Who:** Mudassar (but everyone writes tests for their own module).

All six categories are explicitly required. Target 25+ tests.

```python
# tests/conftest.py
import pytest, pandas as pd, numpy as np

@pytest.fixture
def sample_raw():
    n = 500
    ts = pd.date_range("2024-01-01", periods=n, freq="h", tz="UTC")
    return pd.DataFrame({
        "city_id": ["lahore"]*n, "timestamp": ts,
        "pm2_5": np.random.gamma(4, 20, n),
        "pm10":  np.random.gamma(5, 30, n),
        "temperature_2m": np.random.normal(22, 8, n),
        "relative_humidity_2m": np.random.uniform(20, 95, n),
        "wind_speed_10m": np.random.gamma(2, 2, n),
        "wind_direction_10m": np.random.uniform(0, 360, n),
        "boundary_layer_height": np.random.uniform(100, 2000, n),
        "latitude": 31.5204, "longitude": 74.3587, "elevation_m": 217,
    })

@pytest.fixture
def api_client():
    from src.serving.app import app
    app.config["TESTING"] = True
    with app.test_client() as c:
        yield c
```

```python
# tests/test_data.py — DATA TESTS
def test_schema_accepts_valid(sample_raw):
    from src.data.validation import validate_raw
    ok, rep = validate_raw(sample_raw); assert ok, rep

def test_schema_rejects_negative_pm25(sample_raw):
    from src.data.validation import validate_raw
    sample_raw.loc[0, "pm2_5"] = -5
    ok, _ = validate_raw(sample_raw); assert not ok

def test_schema_rejects_coords_outside_pakistan(sample_raw):
    from src.data.validation import validate_raw
    sample_raw["latitude"] = 51.5   # London
    ok, _ = validate_raw(sample_raw); assert not ok

def test_duplicates_detected(sample_raw):
    from src.data.validation import validate_raw
    import pandas as pd
    dup = pd.concat([sample_raw, sample_raw.head(1)])
    ok, _ = validate_raw(dup); assert not ok
```

```python
# tests/test_features.py — UNIT TESTS (the most important ones)
def test_lag_shifts_correctly(sample_raw):
    from src.features.preprocessing import add_lags
    out = add_lags(sample_raw.copy())
    assert out["pm2_5_lag_1h"].iloc[5] == sample_raw["pm2_5"].iloc[4]

def test_no_target_leakage(sample_raw):
    """The label at t must NOT appear in any feature column at t."""
    from src.features.preprocessing import build, make_supervised
    out = make_supervised(sample_raw.copy())
    feature_cols = [c for c in out.columns if c not in ("y","timestamp","city_id")]
    for c in feature_cols:
        assert not out[c].equals(out["y"]), f"leakage via {c}"

def test_lags_never_use_future(sample_raw):
    from src.features.preprocessing import add_lags
    out = add_lags(sample_raw.copy())
    # a lag column must correlate with the PAST, and the first N rows must be NaN
    assert out["pm2_5_lag_24h"].head(24).isna().all()

def test_cyclical_encoding_wraps():
    from src.features.preprocessing import add_calendar
    import pandas as pd, numpy as np
    df = pd.DataFrame({"timestamp": pd.to_datetime(["2024-01-01T23:00Z","2024-01-02T00:00Z"])})
    out = add_calendar(df)
    assert abs(out.hour_sin.iloc[0] - out.hour_sin.iloc[1]) < 0.3  # neighbours

def test_chrono_split_has_no_overlap(sample_raw):
    from src.features.splits import chrono_split
    tr, va, te = chrono_split(sample_raw, "2024-01-10", "2024-01-15")
    assert tr.timestamp.max() < va.timestamp.min() < te.timestamp.min()
```

```python
# tests/test_model.py — MODEL TESTS
def test_prediction_shape(trained_model, sample_features):
    p = trained_model.predict(sample_features)
    assert p.shape[0] == len(sample_features)

def test_predictions_are_physically_valid(trained_model, sample_features):
    p = trained_model.predict(sample_features)
    assert (p >= 0).all() and (p < 2000).all()
    assert not np.isnan(p).any()

def test_model_beats_persistence_baseline(trained_model, test_set):
    """REGRESSION TEST — this is the quality gate in test form."""
    import yaml
    cfg = yaml.safe_load(open("configs/model_params.yaml"))
    mae  = mean_absolute_error(test_set.y, trained_model.predict(test_set[FEATS]))
    base = mean_absolute_error(test_set.y, test_set.pm2_5_lag_1h)
    improvement = 100*(base-mae)/base
    assert mae < cfg["quality_gate"]["max_test_mae"]
    assert improvement > cfg["quality_gate"]["min_improvement_over_baseline_pct"]
```

```python
# tests/test_api.py — API TESTS
def test_health(api_client):
    r = api_client.get("/health")
    assert r.status_code in (200, 503) and "model_loaded" in r.get_json()

def test_model_info_fields(api_client):
    j = api_client.get("/model-info").get_json()
    for k in ("model_name","model_version","stage","features"):
        assert k in j

def test_predict_valid(api_client):
    r = api_client.post("/predict", json={"cities":[{"city_id":"lahore","horizon":24}]})
    assert r.status_code == 200
    assert r.get_json()["predictions"][0]["pm2_5_pred"] >= 0

def test_predict_malformed_json(api_client):
    r = api_client.post("/predict", data="not json", content_type="application/json")
    assert r.status_code == 400

def test_predict_bad_horizon(api_client):
    r = api_client.post("/predict", json={"cities":[{"city_id":"lahore","horizon":999}]})
    assert r.status_code == 422

def test_predict_too_many_cities(api_client):
    r = api_client.post("/predict", json={"cities":[{"city_id":f"c{i}"} for i in range(500)]})
    assert r.status_code == 422

def test_unknown_route_404(api_client):
    assert api_client.get("/nope").status_code == 404

def test_metrics_endpoint_exists(api_client):
    assert b"predictions_total" in api_client.get("/metrics").data
```

```python
# tests/test_pipeline.py — INTEGRATION TESTS
def test_raw_to_prediction_end_to_end(sample_raw, tmp_path):
    """ingest → validate → features → train → save → load → predict"""
    from src.data.validation import validate_raw
    from src.features.preprocessing import build
    ok, _ = validate_raw(sample_raw); assert ok
    feats = build(sample_raw, cities_df)
    assert len(feats) > 0 and "y" in feats
    model = quick_train(feats)
    import joblib; p = tmp_path/"m.pkl"; joblib.dump(model, p)
    reloaded = joblib.load(p)
    assert reloaded.predict(feats[FEATS].head(5)).shape == (5,)
```

Run:
```bash
pytest -v --cov=src --cov-report=term-missing --cov-report=html
```
Aim for **≥ 70% coverage on `src/`**. Put the number in the README.

---

## Phase 12 — Docker and Docker Compose

**Who:** Ifraz.

`docker/Dockerfile.api` — multi-stage, non-root, Gunicorn (all three are graded details):
```dockerfile
# ── build stage ──
FROM python:3.11-slim AS builder
WORKDIR /build
RUN apt-get update && apt-get install -y --no-install-recommends gcc g++ \
    && rm -rf /var/lib/apt/lists/*
COPY requirements-api.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements-api.txt

# ── runtime stage ──
FROM python:3.11-slim
RUN useradd -m -u 1000 appuser
WORKDIR /app
COPY --from=builder /install /usr/local
COPY src/ ./src/
COPY configs/ ./configs/
COPY feature_store/ ./feature_store/
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 APP_VERSION=1.0.0
USER appuser
EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:5000/health').status==200 else 1)"
CMD ["gunicorn","--bind","0.0.0.0:5000","--workers","2","--threads","4", \
     "--timeout","120","--access-logfile","-","src.serving.app:app"]
```

> Keep a slim `requirements-api.txt` (flask, gunicorn, mlflow, xgboost, pandas, feast, prometheus-flask-exporter) — do **not** install Airflow or kfp into the API image. A 400 MB image deploys to a t3.micro; a 4 GB one does not.

`docker-compose.yml`:
```yaml
services:
  db:
    image: postgis/postgis:16-3.4
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes: [pgdata:/var/lib/postgresql/data]
    ports: ["5432:5432"]
    healthcheck:
      test: ["CMD-SHELL","pg_isready -U ${POSTGRES_USER}"]
      interval: 10s

  api:
    build: {context: ., dockerfile: docker/Dockerfile.api}
    env_file: .env
    ports: ["5000:5000"]
    depends_on: {db: {condition: service_healthy}}
    restart: unless-stopped

  mlflow:
    image: ghcr.io/mlflow/mlflow:v2.17.0
    command: >
      mlflow server --host 0.0.0.0 --port 5001
      --backend-store-uri sqlite:////mlflow/mlflow.db
      --default-artifact-root /mlflow/artifacts
    volumes: [mlflowdata:/mlflow]
    ports: ["5001:5001"]

  prometheus:
    image: prom/prometheus:v2.54.1
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml:ro
      - ./monitoring/alert_rules.yml:/etc/prometheus/alert_rules.yml:ro
    ports: ["9090:9090"]

  grafana:
    image: grafana/grafana:11.2.0
    environment:
      GF_SECURITY_ADMIN_PASSWORD: ${GRAFANA_PASSWORD}
    volumes:
      - grafanadata:/var/lib/grafana
      - ./monitoring/grafana/dashboards:/etc/grafana/provisioning/dashboards:ro
    ports: ["3001:3000"]
    depends_on: [prometheus]

volumes: {pgdata: {}, mlflowdata: {}, grafanadata: {}}
```

Airflow goes in a **separate** `docker-compose.airflow.yml` (it needs 4+ services and lots of RAM — don't make the main stack depend on it).

```bash
docker compose up -d --build
curl localhost:5000/health
docker compose logs -f api
```

**The "runs on another machine" deliverable:** Ifraz pushes the image, Hassan pulls it on his laptop, runs it, screenshots `/health` returning 200. Record both machines' hostnames in the evidence.

---

## Phase 13 — GitHub Actions CI/CD

**Who:** Mudassar.

`.github/workflows/ci.yml`:
```yaml
name: CI
on:
  push: {branches: [main, develop]}
  pull_request: {branches: [main]}

jobs:
  quality:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.11", cache: pip}
      - run: pip install -r requirements.txt
      - name: Lint (Ruff)
        run: ruff check src tests
      - name: Format check
        run: ruff format --check src tests
      - name: Security scan — dependencies
        run: pip install pip-audit && pip-audit --strict || true
      - name: Secret scan
        uses: gitleaks/gitleaks-action@v2

  test:
    needs: quality
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: {python-version: "3.11", cache: pip}
      - run: pip install -r requirements.txt
      - name: Run tests
        run: pytest -v --cov=src --cov-report=xml --cov-fail-under=70
      - uses: actions/upload-artifact@v4
        with: {name: coverage, path: coverage.xml}

  build:
    needs: test                      # ← build ONLY if tests passed = the quality gate
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - name: Build image
        run: docker build -f docker/Dockerfile.api -t airwatch-api:${{ github.sha }} .
      - name: Scan image (Trivy)
        uses: aquasecurity/trivy-action@master
        with:
          image-ref: airwatch-api:${{ github.sha }}
          severity: CRITICAL,HIGH
          exit-code: "0"             # set to "1" once you've fixed the findings
      - name: Smoke test the container
        run: |
          docker run -d -p 5000:5000 --name smoke airwatch-api:${{ github.sha }}
          sleep 15
          curl -f http://localhost:5000/health
```

`.github/workflows/deploy.yml` (runs only on `main`, only after CI is green):
```yaml
name: Deploy
on:
  workflow_run:
    workflows: [CI]
    types: [completed]
    branches: [main]
  workflow_dispatch:                 # ← manual approval gate

jobs:
  deploy:
    if: github.event.workflow_run.conclusion == 'success'
    runs-on: ubuntu-latest
    environment: production          # ← GitHub asks a human to approve
    permissions: {id-token: write, contents: read}
    steps:
      - uses: actions/checkout@v4
      - uses: aws-actions/configure-aws-credentials@v4
        with:
          role-to-assume: ${{ secrets.AWS_ROLE_ARN }}   # OIDC: no long-lived keys
          aws-region: ${{ secrets.AWS_REGION }}
      - uses: aws-actions/amazon-ecr-login@v2
        id: ecr
      - name: Build & push to ECR
        run: |
          IMG=${{ steps.ecr.outputs.registry }}/airwatch-api
          docker build -f docker/Dockerfile.api -t $IMG:${{ github.sha }} -t $IMG:latest .
          docker push $IMG:${{ github.sha }}
          docker push $IMG:latest
      - name: Deploy to EC2
        run: |
          aws ssm send-command --document-name "AWS-RunShellScript" \
            --targets "Key=instanceids,Values=${{ secrets.EC2_INSTANCE_ID }}" \
            --parameters 'commands=["cd /opt/airwatch && docker compose pull && docker compose up -d"]'
```

**Secrets** go in GitHub → Settings → Secrets and variables → Actions:
`AWS_ROLE_ARN`, `AWS_REGION`, `EC2_INSTANCE_ID`, `MLFLOW_TRACKING_USERNAME`, `MLFLOW_TRACKING_PASSWORD`, `OPENAQ_API_KEY`. **Never a hard-coded key anywhere in the repo.**

### 🔴 Evidence of the quality gate failing (a required deliverable)

Deliberately create this evidence:
1. Branch `demo/failing-gate`
2. Break a test on purpose (e.g. change the MAE threshold to 0.001)
3. Open a PR → **screenshot the red X and the blocked "Merge" button**
4. Fix it → screenshot the green tick and the merge
5. Save both to `Documents/evidence/ci_gate_fail.png` and `ci_gate_pass.png`

Do the same for the **model** gate: train with `n_estimators=1`, let `promote_to_production` raise, screenshot the Airflow task turning red and the model staying in Staging.

---

## Phase 14 — DVC pipeline

**Who:** Mudassar.

`dvc.yaml` turns your scripts into a dependency graph. Change one file, DVC re-runs only what's affected.

```yaml
stages:
  ingest:
    cmd: python -m src.data.historical --config configs/data_config.yaml
    deps:
      - src/data/historical.py
      - data/reference/pakistan_cities.csv
    params:
      - data_config.yaml:
          - start_year
          - end_year
          - variables
    outs:
      - data/raw/airquality_hourly.parquet

  validate:
    cmd: python -m src.data.validation --input data/raw/airquality_hourly.parquet
    deps:
      - src/data/validation.py
      - data/raw/airquality_hourly.parquet
    metrics:
      - reports/data_quality.json: {cache: false}

  features:
    cmd: python -m src.features.build_features
    deps:
      - src/features/preprocessing.py
      - src/features/build_features.py
      - data/raw/airquality_hourly.parquet
    params:
      - model_params.yaml:
          - lags
          - horizons
    outs:
      - data/processed/features.parquet

  train:
    cmd: python -m src.models.train_xgboost
    deps:
      - src/models/train_xgboost.py
      - data/processed/features.parquet
    params:
      - model_params.yaml:
          - xgboost
          - split
    outs:
      - models/model.pkl
    metrics:
      - reports/metrics.json: {cache: false}
    plots:
      - reports/residuals.csv:
          x: predicted
          y: residual

  evaluate:
    cmd: python -m src.models.evaluate --gate
    deps:
      - src/models/evaluate.py
      - models/model.pkl
      - data/processed/features.parquet
    metrics:
      - reports/evaluation.json: {cache: false}
```

```bash
dvc repro            # runs only what changed
dvc dag              # prints the graph — screenshot this for the report
dvc metrics show
dvc metrics diff main        # compare your branch's metrics against main
dvc params diff
dvc push
```

**`dvc metrics diff` in a PR comment is a very strong demo.** It shows reviewers exactly how a code change moved MAE.

---

## Phase 15 — Airflow orchestration

**Who:** Mudassar.

```bash
mkdir -p pipelines/airflow/{dags,logs,plugins}
curl -LfO https://airflow.apache.org/docs/apache-airflow/2.10.2/docker-compose.yaml
echo "AIRFLOW_UID=50000" > .env.airflow
docker compose -f docker-compose.airflow.yml up airflow-init
docker compose -f docker-compose.airflow.yml up -d
# http://localhost:8080  (airflow / airflow)
```

`pipelines/airflow/dags/hourly_ingest_dag.py`:
```python
from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.exceptions import AirflowFailException

default_args = {
    "owner": "airwatch-team",
    "retries": 3,
    "retry_delay": timedelta(minutes=5),
    "retry_exponential_backoff": True,
    "execution_timeout": timedelta(minutes=20),
}

def fetch(**ctx):
    from src.data.live import fetch_live_batch
    import pandas as pd
    df = fetch_live_batch(pd.read_csv("data/reference/pakistan_cities.csv"))
    path = f"/tmp/live_{ctx['ts_nodash']}.parquet"
    df.to_parquet(path)
    ctx["ti"].xcom_push(key="path", value=path)
    return len(df)

def validate(**ctx):
    from src.data.validation import validate_raw
    import pandas as pd
    df = pd.read_parquet(ctx["ti"].xcom_pull(key="path"))
    ok, report = validate_raw(df)
    ctx["ti"].xcom_push(key="report", value=report)
    if not ok:
        raise AirflowFailException(f"data validation failed: {report}")   # ← hard stop
    return report

def load_to_db(**ctx): ...
def refresh_feast(**ctx): ...
def run_drift_check(**ctx): ...

with DAG("hourly_ingest_dag",
         default_args=default_args,
         start_date=datetime(2026, 11, 1),
         schedule="0 * * * *",
         catchup=False,
         max_active_runs=1,
         tags=["ingestion","production"]) as dag:

    t1 = PythonOperator(task_id="fetch_live_data",     python_callable=fetch)
    t2 = PythonOperator(task_id="validate_schema",     python_callable=validate)
    t3 = PythonOperator(task_id="load_to_postgres",    python_callable=load_to_db)
    t4 = PythonOperator(task_id="materialize_feast",   python_callable=refresh_feast)
    t5 = PythonOperator(task_id="drift_check",         python_callable=run_drift_check)

    t1 >> t2 >> t3 >> t4 >> t5
```

`ml_orchestrator_dag.py` — the dual-orchestration DAG the requirements specifically describe:
```python
def trigger_kubeflow(**ctx):
    import kfp
    client = kfp.Client(host="http://host.docker.internal:8080")
    run = client.create_run_from_pipeline_package(
        "pipelines/kubeflow/compiled_pipeline.yaml",
        arguments={"mae_threshold": 20.0},
        experiment_name="airwatch-training",
    )
    ctx["ti"].xcom_push(key="kfp_run_id", value=run.run_id)
    return run.run_id

def wait_for_kubeflow(**ctx):
    import kfp, time
    client = kfp.Client(host="http://host.docker.internal:8080")
    rid = ctx["ti"].xcom_pull(key="kfp_run_id")
    while True:
        st = client.get_run(rid).state
        if st in ("SUCCEEDED","FAILED","ERROR"): break
        time.sleep(30)
    if st != "SUCCEEDED":
        raise AirflowFailException(f"Kubeflow run {rid} ended as {st}")
```

`retraining_dag.py` — with a **branch** so retraining only happens when needed:
```python
from airflow.operators.python import BranchPythonOperator

def decide(**ctx):
    drift = ctx["ti"].xcom_pull(task_ids="check_drift", key="drift_share")
    stale = ctx["ti"].xcom_pull(task_ids="check_model_age", key="days_old")
    if drift > 0.30 or stale > 30:
        return "trigger_retraining"
    return "skip_retraining"

branch = BranchPythonOperator(task_id="decide_retraining", python_callable=decide)
```

**Screenshots to capture:** the DAG graph view, a successful run, a *failed* task showing the 3 retries, and the task log. All four are evidence.

---

## Phase 16 — Kubeflow Pipelines

**Who:** Mudassar + Ifraz (Ifraz owns Minikube).

```bash
minikube start --cpus=4 --memory=8192 --disk-size=40g
export PIPELINE_VERSION=2.2.0
kubectl apply -k "github.com/kubeflow/pipelines/manifests/kustomize/cluster-scoped-resources?ref=$PIPELINE_VERSION"
kubectl wait --for condition=established --timeout=60s crd/applications.app.k8s.io
kubectl apply -k "github.com/kubeflow/pipelines/manifests/kustomize/env/platform-agnostic?ref=$PIPELINE_VERSION"
kubectl -n kubeflow get pods -w          # wait until all Running (~10 min)
kubectl port-forward -n kubeflow svc/ml-pipeline-ui 8080:80
```

`pipelines/kubeflow/pipeline_definition.py`:
```python
from kfp import dsl, compiler

BASE = "python:3.11-slim"

@dsl.component(base_image=BASE, packages_to_install=["pandas","pyarrow","pandera"])
def validate_data(raw: dsl.Input[dsl.Dataset], report: dsl.Output[dsl.Metrics]) -> bool: ...

@dsl.component(base_image=BASE, packages_to_install=["pandas","pyarrow","numpy"])
def engineer_features(raw: dsl.Input[dsl.Dataset],
                      train: dsl.Output[dsl.Dataset],
                      val:   dsl.Output[dsl.Dataset],
                      test:  dsl.Output[dsl.Dataset]): ...

@dsl.component(base_image=BASE, packages_to_install=["xgboost","mlflow","pandas"])
def train_model(train: dsl.Input[dsl.Dataset], val: dsl.Input[dsl.Dataset],
                max_depth: int, lr: float,
                model: dsl.Output[dsl.Model],
                metrics: dsl.Output[dsl.Metrics]) -> str: ...

@dsl.component(base_image=BASE, packages_to_install=["mlflow","scikit-learn","pandas"])
def evaluate_model(model: dsl.Input[dsl.Model], test: dsl.Input[dsl.Dataset],
                   mae_threshold: float) -> bool: ...

@dsl.component(base_image=BASE, packages_to_install=["mlflow"])
def register_model(run_id: str, stage: str = "Staging"): ...

@dsl.pipeline(name="pm25-training-pipeline",
              description="Pakistan AirWatch AI end-to-end training")
def pm25_pipeline(raw_uri: str, mae_threshold: float = 20.0,
                  max_depth: int = 8, lr: float = 0.05):
    raw = dsl.importer(artifact_uri=raw_uri, artifact_class=dsl.Dataset)
    v  = validate_data(raw=raw.output)
    with dsl.If(v.output == True, name="data-is-valid"):           # conditional
        f = engineer_features(raw=raw.output)
        t = train_model(train=f.outputs["train"], val=f.outputs["val"],
                        max_depth=max_depth, lr=lr)
        t.set_cpu_limit("2").set_memory_limit("4G")
        e = evaluate_model(model=t.outputs["model"], test=f.outputs["test"],
                           mae_threshold=mae_threshold)
        with dsl.If(e.output == True, name="passes-quality-gate"):  # the gate
            register_model(run_id=t.output, stage="Staging")

if __name__ == "__main__":
    compiler.Compiler().compile(pm25_pipeline, "pipelines/kubeflow/compiled_pipeline.yaml")
```

```bash
python pipelines/kubeflow/pipeline_definition.py   # produces the YAML
# upload compiled_pipeline.yaml in the KFP UI → Create Run → screenshot the graph
```

**In the defense, explain the division of labour clearly:**
> "Airflow is our *scheduler and data-plane orchestrator*: it runs hourly, fetches and validates data, and decides *whether* to train. Kubeflow is our *ML workflow engine*: it runs each ML step in its own isolated container with its own CPU/memory limits, passing typed artifacts between steps. Airflow triggers Kubeflow through the KFP client and polls for completion. We do not duplicate work between them."

---

## Phase 17 — Kubernetes scaling

**Who:** Ifraz.

`k8s/api-deployment.yaml`:
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: airwatch-api
  labels: {app: airwatch-api}
spec:
  replicas: 3
  selector: {matchLabels: {app: airwatch-api}}
  strategy:
    type: RollingUpdate
    rollingUpdate: {maxSurge: 1, maxUnavailable: 0}   # zero-downtime
  template:
    metadata:
      labels: {app: airwatch-api}
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/port: "5000"
        prometheus.io/path: "/metrics"
    spec:
      containers:
        - name: api
          image: airwatch-api:latest
          imagePullPolicy: IfNotPresent
          ports: [{containerPort: 5000}]
          envFrom:
            - configMapRef: {name: airwatch-config}
            - secretRef:    {name: airwatch-secrets}
          resources:
            requests: {memory: "256Mi", cpu: "100m"}
            limits:   {memory: "768Mi", cpu: "500m"}
          readinessProbe:
            httpGet: {path: /health, port: 5000}
            initialDelaySeconds: 15
            periodSeconds: 10
            failureThreshold: 3
          livenessProbe:
            httpGet: {path: /health, port: 5000}
            initialDelaySeconds: 40
            periodSeconds: 20
            failureThreshold: 3
          securityContext:
            runAsNonRoot: true
            runAsUser: 1000
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
```

`k8s/api-service.yaml`:
```yaml
apiVersion: v1
kind: Service
metadata: {name: airwatch-api-svc}
spec:
  type: NodePort
  selector: {app: airwatch-api}
  ports: [{port: 80, targetPort: 5000, nodePort: 30080}]
```

The demo script (record this as a screencast — 6 marks):
```bash
minikube image load airwatch-api:latest
kubectl apply -f k8s/
kubectl get pods -o wide                      # 3 Running
minikube service airwatch-api-svc --url
curl $(minikube service airwatch-api-svc --url)/health

# ── self-healing ──
kubectl delete pod $(kubectl get pods -l app=airwatch-api -o jsonpath='{.items[0].metadata.name}')
kubectl get pods -w                           # a new pod appears, old one Terminating

# ── scaling ──
kubectl scale deployment airwatch-api --replicas=5
kubectl get pods                              # 5 Running

# ── rolling update ──
kubectl set image deployment/airwatch-api api=airwatch-api:v2
kubectl rollout status deployment/airwatch-api
kubectl rollout undo deployment/airwatch-api  # ← ROLLBACK, also a deliverable

# ── load balancing proof ──
for i in $(seq 1 20); do curl -s $URL/health | jq -r .pod_name; done | sort | uniq -c
```
(Add `"pod_name": os.getenv("HOSTNAME")` to the `/health` response so the last command visibly proves load balancing across pods.)

**Explain the limitations** (the rubric asks): NodePort isn't a real cloud load balancer; Minikube is single-node so this doesn't prove multi-node resilience; no HPA metrics-server by default (install it if you want autoscaling by CPU).

---

## Phase 18 — React frontend

**Who:** Ifraz.

```bash
npm create vite@latest frontend -- --template react
cd frontend
npm install leaflet react-leaflet recharts axios date-fns
npm install -D tailwindcss @tailwindcss/vite
```

Pages:
1. **Map** — Pakistan centred at `[30.3753, 69.3451]`, zoom 5. One `CircleMarker` per city, radius by population, colour by AQI category.
2. **Time slider** — hours 0..24 ahead; moving it refetches `/api/forecast?valid_time=...`
3. **City detail panel** — click a city → 7-day observed line + 24h forecast line (Recharts), source label, timestamp, "model prediction" vs "provider forecast" badge
4. **Layer toggles** — Predicted / Provider forecast / Ground station / Data availability
5. **Legend** — US EPA AQI categories, named explicitly
6. **Footer** — attribution + the academic-prototype disclaimer

```jsx
// AQI colouring — US EPA PM2.5 breakpoints
const AQI_BANDS = [
  {max: 12.0,  color:"#00e400", label:"Good"},
  {max: 35.4,  color:"#ffff00", label:"Moderate"},
  {max: 55.4,  color:"#ff7e00", label:"Unhealthy for Sensitive Groups"},
  {max: 150.4, color:"#ff0000", label:"Unhealthy"},
  {max: 250.4, color:"#8f3f97", label:"Very Unhealthy"},
  {max: Infinity, color:"#7e0023", label:"Hazardous"},
];
const bandFor = v => AQI_BANDS.find(b => v <= b.max);
```

**Transparency requirement (don't skip — it's an ethics mark):** every marker's popup must show `source` (`model_prediction` | `provider_forecast` | `ground_station`), `valid_time`, `generated_at`, `model_version` and `unit`. Style the three sources differently (filled / hatched / ringed).

Build and serve from Flask or Nginx:
```bash
npm run build          # → frontend/dist
```

---

## Phase 19 — AWS deployment on free tier

**Who:** Ifraz (Hassan owns the account and the budget alarm).

### 19.1 ⚠️ Cost safety FIRST — before creating any resource

1. **Billing → Budgets → Create budget** → Cost budget → **$1.00/month** → alert at 50%, 80%, 100% → your email. Screenshot it.
2. **Billing preferences** → enable "Receive Free Tier Usage Alerts".
3. Set a calendar reminder to run the teardown script after the demo.

### 19.2 What stays inside the free tier

| Service | Free tier | Your usage |
|---|---|---|
| **EC2 t3.micro / t2.micro** | 750 h/month for 12 months = one instance always on | 1 instance |
| **ECR** | 500 MB/month private storage | keep ≤ 2 image tags, lifecycle-delete the rest |
| **S3** | 5 GB + 20k GET + 2k PUT | model artifacts + a sample of data |
| **CloudWatch** | 10 custom metrics, 5 GB logs ingest | app logs + 3 metrics |
| **IAM, VPC, Security Groups** | always free | — |
| **Data transfer out** | 100 GB/month | nowhere near it |

> **Do not use:** ECS Fargate (not free), EKS ($0.10/hour for the control plane = ~$73/month ⛔), NAT Gateway (⛔ a classic student bill-shock), RDS beyond the 12-month 750h db.t3.micro, SageMaker. **Run Postgres in a container on the same EC2 instance** instead of RDS.

### 19.3 Setup

```bash
# S3
aws s3 mb s3://airwatch-artifacts-<random> --region ap-south-1
aws s3api put-public-access-block --bucket airwatch-artifacts-<random> \
  --public-access-block-configuration \
  "BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true"

# ECR
aws ecr create-repository --repository-name airwatch-api --region ap-south-1
aws ecr put-lifecycle-policy --repository-name airwatch-api --lifecycle-policy-text \
  '{"rules":[{"rulePriority":1,"selection":{"tagStatus":"any","countType":"imageCountMoreThan","countNumber":2},"action":{"type":"expire"}}]}'
```

**Security group — least privilege (graded):**
| Port | Source | Why |
|---|---|---|
| 22 (SSH) | **your IP only** (`x.x.x.x/32`) | admin |
| 80 (HTTP) | 0.0.0.0/0 | the public API |
| 5432 | **nothing** — not open at all | Postgres is container-to-container only |

Launch EC2 (Ubuntu 22.04, t3.micro, 20 GB gp3, your key pair, the SG above, and an **IAM instance role** with `AmazonEC2ContainerRegistryReadOnly` + a narrow S3 policy — never put access keys on the box).

On the instance:
```bash
sudo apt update && sudo apt install -y docker.io docker-compose-plugin awscli
sudo usermod -aG docker ubuntu && newgrp docker
sudo mkdir -p /opt/airwatch && sudo chown ubuntu /opt/airwatch
# t3.micro has 1 GB RAM — add swap or the build/OOM-killer will bite you
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile && sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

Pull and run (never build on the micro instance — build in GitHub Actions, pull the image):
```bash
aws ecr get-login-password --region ap-south-1 | docker login --username AWS --password-stdin <acct>.dkr.ecr.ap-south-1.amazonaws.com
docker compose -f /opt/airwatch/docker-compose.prod.yml up -d
curl http://localhost/health
```

**Use OIDC for GitHub Actions, not access keys** (2 marks for "identity-based authentication"):
```bash
aws iam create-open-id-connect-provider \
  --url https://token.actions.githubusercontent.com \
  --client-id-list sts.amazonaws.com \
  --thumbprint-list 6938fd4d98bab03faadb97b34396831e3780aea1
```
Then an IAM role trusting `repo:<owner>/Pakistan-AirWatch-AI:ref:refs/heads/main` with only `ecr:*` on your one repo and `ssm:SendCommand` on your one instance.

### 19.4 CloudWatch logs

```yaml
# in docker-compose.prod.yml
  api:
    logging:
      driver: awslogs
      options:
        awslogs-region: ap-south-1
        awslogs-group: /airwatch/api
        awslogs-stream: api
```
Add a metric filter on `"level":"ERROR"` → a CloudWatch alarm → SNS email. That is one of your required alerts.

### 19.5 Teardown script (`scripts/aws_teardown.sh`) — required deliverable

```bash
#!/usr/bin/env bash
set -e
aws ec2 terminate-instances --instance-ids $EC2_ID
aws ecr delete-repository --repository-name airwatch-api --force
aws s3 rm s3://$BUCKET --recursive && aws s3 rb s3://$BUCKET
aws logs delete-log-group --log-group-name /airwatch/api
echo "All billable resources removed. Verify in the Billing console."
```
**Run it after the demo** and screenshot the empty resource lists.

---

## Phase 20 — Monitoring

**Who:** Ifraz.

`monitoring/prometheus.yml`:
```yaml
global: {scrape_interval: 15s, evaluation_interval: 15s}
rule_files: [/etc/prometheus/alert_rules.yml]
scrape_configs:
  - job_name: airwatch-api
    metrics_path: /metrics
    static_configs: [{targets: ["api:5000"]}]
```

`monitoring/alert_rules.yml`:
```yaml
groups:
  - name: airwatch
    rules:
      - alert: HighAPIErrorRate
        expr: |
          sum(rate(flask_http_request_total{status=~"5.."}[5m]))
          / sum(rate(flask_http_request_total[5m])) > 0.05
        for: 2m
        labels: {severity: critical}
        annotations:
          summary: "API 5xx error rate above 5% for 2 minutes"
          runbook: "Check `docker compose logs api`; if the model failed to load, verify the MLflow registry is reachable and roll back with scripts/rollback.sh"

      - alert: HighPredictionLatency
        expr: histogram_quantile(0.95, rate(prediction_latency_seconds_bucket[5m])) > 1.0
        for: 5m
        labels: {severity: warning}
        annotations: {summary: "p95 prediction latency above 1s"}

      - alert: DataQualityFailures
        expr: increase(data_quality_failures_total[1h]) > 10
        for: 1m
        labels: {severity: warning}
        annotations: {summary: "More than 10 data-quality failures in the last hour"}

      - alert: APIDown
        expr: up{job="airwatch-api"} == 0
        for: 1m
        labels: {severity: critical}
        annotations: {summary: "AirWatch API is not responding to scrapes"}
```

**Grafana dashboard panels** (import `monitoring/grafana/dashboards/airwatch.json`):
1. Request rate (req/s) by endpoint
2. Error rate % (big stat, red above 5%)
3. p50 / p95 / p99 prediction latency
4. Total predictions by city (top 10 bar chart)
5. Distribution of predicted PM2.5 (heatmap) ← **this is your drift early-warning**
6. Model version currently serving (stat panel from `model_version_info`)
7. Data-quality failures over time
8. Container CPU / memory

**Demonstrate the alert actually firing** (required):
```bash
# force 5xx responses
for i in $(seq 1 200); do curl -s -X POST localhost:5000/predict -d 'garbage'; done
# or stop the API so APIDown fires
docker compose stop api
```
Screenshot: Prometheus → Alerts → `FIRING` (red), and the Grafana alert panel. Save to `Documents/evidence/alert_firing.png`.

### Evidently drift detection

```python
# src/monitoring/drift.py
import pandas as pd, json
from evidently import Report
from evidently.presets import DataDriftPreset, DataSummaryPreset

NUMERIC = ["pm2_5","pm10","temperature_2m","relative_humidity_2m",
           "wind_speed_10m","boundary_layer_height"]

def run_drift(reference_path, current_path, out_html, out_json):
    ref = pd.read_parquet(reference_path)[NUMERIC]
    cur = pd.read_parquet(current_path)[NUMERIC]
    rep = Report(metrics=[DataDriftPreset(), DataSummaryPreset()])
    res = rep.run(reference_data=ref, current_data=cur)
    res.save_html(out_html)
    d = res.dict()
    drifted = sum(1 for m in d["metrics"] if m.get("value", {}).get("drifted"))
    share = drifted / len(NUMERIC)
    json.dump({"drift_share": share, "n_drifted": drifted}, open(out_json,"w"))
    return share
```
Airflow's `retraining_dag` calls this hourly/daily; `drift_share > 0.30` triggers retraining.

**Simulated drift demo** (the requirements explicitly allow this):
```python
# create obviously drifted data: shift everything to smog-season values
cur = ref.copy()
cur["pm2_5"] = cur["pm2_5"] * 3.5
cur["temperature_2m"] = cur["temperature_2m"] - 12
run_drift(...)        # → drift_share near 1.0 → retraining triggered
```
Record the Evidently HTML report and the Airflow DAG branching to `trigger_retraining`. That single screencast covers "drift detection", "defined retraining trigger" and "controlled test scenario".

### Ground-truth feedback loop

Every prediction is written to a `predictions` table with `city_id, valid_time, horizon, pm2_5_pred, model_version, generated_at`. 24+ hours later, the hourly ingest DAG joins actual observations onto it and computes live MAE per model version → a Grafana panel of **production model error over time**. That is the "model performance when ground-truth labels become available" requirement, and it is genuinely impressive in a demo.

---

## Phase 21 — Automated retraining and rollback

**Who:** Mudassar.

The full lifecycle to demonstrate:

```
Airflow retraining_dag (weekly + drift-triggered)
  │
  ├─ 1. check_drift ────────── Evidently → drift_share
  ├─ 2. check_model_age ────── days since Production model was trained
  ├─ 3. decide_retraining ──── BranchPythonOperator
  │        ├── no → skip_retraining (DAG ends green)
  │        └── yes ↓
  ├─ 4. revalidate_data ────── Pandera on the full current dataset
  ├─ 5. trigger_kubeflow ───── KFP pipeline retrains on fresh data
  ├─ 6. compare_candidate ──── candidate MAE vs CURRENT PRODUCTION MAE
  │                            (not just vs the threshold!)
  ├─ 7. quality_gate ───────── raises → DAG turns red → nothing deploys
  ├─ 8. promote_to_staging ─── MLflow registry
  ├─ 9. [MANUAL APPROVAL] ──── a human clears an Airflow task / approves the GH environment
  ├─10. promote_to_production
  ├─11. redeploy ───────────── kubectl rollout restart / docker compose up -d
  └─12. smoke_test ─────────── curl /health + /model-info shows the new version
                               if it fails → auto-rollback
```

**Candidate vs incumbent comparison (step 6) — this is what the rubric means by "compare the candidate model against the currently deployed model":**
```python
def compare_candidate(**ctx):
    prod_mae      = get_production_model_test_mae()
    candidate_mae = ctx["ti"].xcom_pull(key="candidate_mae")
    rel = 100*(prod_mae - candidate_mae)/prod_mae
    ctx["ti"].xcom_push(key="relative_improvement", value=rel)
    if rel < 2.0:
        raise AirflowFailException(
            f"Candidate MAE {candidate_mae:.2f} is not meaningfully better than "
            f"production {prod_mae:.2f} ({rel:+.1f}%). Not promoting.")
    return rel
```
This stops the "automated deployment blindly promoting every newly trained model" failure the requirements warn about in §6.

**Rollback demo script** (`scripts/rollback.sh`):
```bash
#!/usr/bin/env bash
set -e
echo "Current production version:"; curl -s $API/model-info | jq .model_version
python -m src.models.registry rollback
kubectl rollout restart deployment/airwatch-api     # or: docker compose up -d --force-recreate api
sleep 20
echo "After rollback:"; curl -s $API/model-info | jq .model_version
```
Run it live in the demo. Thirty seconds, and it covers a whole rubric line.

---

## Phase 22 — Security, ethics, risk assessment

**Who:** all three; Hassan compiles into `Documents/RISK_ASSESSMENT.md`.

### Security checklist (implement, don't just describe — the rubric says so)

- [ ] `.env` in `.gitignore`; only `.env.example` committed
- [ ] `gitleaks` in CI
- [ ] GitHub Secrets for every credential; AWS via **OIDC**, no long-lived keys
- [ ] IAM policies scoped to one ECR repo, one S3 bucket, one EC2 instance
- [ ] S3 public access blocked; bucket encrypted (SSE-S3, free)
- [ ] Security group: SSH from your IP only, Postgres not exposed
- [ ] Container runs as non-root with a read-only root filesystem
- [ ] `pip-audit` + Trivy image scan in CI
- [ ] Input validation on `/predict` (type, range, list length cap)
- [ ] Logs contain request IDs, never full request bodies
- [ ] Log retention set to 7 days in CloudWatch
- [ ] Each team member has their own DagsHub/AWS credentials

**If a secret ever reaches GitHub:** rotate it immediately (new token / new AWS key), *then* clean history. Rotating first is what matters — the old value is already public.

### Ethics (§3.13 + §14 of your proposal)

Write these honestly in `REPORT.md`:

1. **Not a health warning system.** Academic prototype. No medical advice. Banner in the UI.
2. **Data provenance is unequal.** Reanalysis-based estimates for most cities; real sensors for a handful. Never present them identically. Label every value.
3. **Bias:** training data quality correlates with urbanisation. Lahore/Karachi are well represented; Balochistan and GB are not. The model will be less accurate exactly where people have the least information already. **State this plainly** — it's the strongest ethics point you can make.
4. **Explainability:** publish SHAP or gain-based feature importances; explain *why* the model predicts high PM2.5 (usually: low ventilation index + smog season + high lag values).
5. **Licensing:** Open-Meteo CC BY 4.0 non-commercial, OpenAQ + provider terms, PAQI CC BY 4.0, GeoNames CC BY 4.0. All cited.
6. **No personal data** is collected anywhere in the system — say so, it's the cleanest privacy answer possible.
7. **Uncertainty:** show MAE alongside each forecast, or prediction intervals from quantile regression. A number without an error bar is a false promise.

### Risk assessment (≥ 3 required; give 6)

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| 1 | Open-Meteo changes terms, rate-limits us, or goes down | Medium | High | Cache every response in Postgres; source adapters behind one interface so a source can be swapped; fall back to the last known good value with a staleness flag; OpenAQ as a secondary source |
| 2 | Very sparse ground-truth → we cannot truly validate | **High** | High | Validate against OpenAQ where it exists; report coverage explicitly; frame as a prototype; never claim sensor-verified nationwide accuracy |
| 3 | AWS free tier exceeded → real charges | Medium | Medium | $1 budget alert; t3.micro only; no EKS/Fargate/NAT; ECR lifecycle policy; teardown script + calendar reminder |
| 4 | Model drifts badly in smog season (Oct–Jan) | High | Medium | Evidently drift monitoring; seasonal features; automated retraining trigger; report per-season error |
| 5 | A team member's module blocks the others | Medium | High | Interface contracts agreed in week 1 (parquet schema, API JSON shape); mock/fixture data so each person can work alone; weekly sync |
| 6 | Kubeflow/Minikube won't run on a laptop | Medium | Medium | `kind` as a lighter alternative; `kfp.local`; the compiled YAML is the deliverable regardless; document the constraint |

---

## Phase 23 — Documentation, report and demo

**Who:** Hassan compiles; everyone writes their own sections.

### `README.md` must contain

1. Title, one-paragraph description, architecture diagram
2. The live AWS endpoint URL
3. Badges: CI status, coverage
4. **Quickstart** — `git clone` → `.env` → `docker compose up` → `curl /health`, verified by someone who hasn't seen it
5. Full local setup (venv, DVC pull, MLflow config)
6. How to run each piece: `dvc repro`, training, tests, Airflow, Kubeflow, Minikube
7. **Environment variable table — names and descriptions only, never values**
8. API docs with real curl examples and responses
9. Data sources + licences + attribution
10. Team + contributions
11. **Cleanup instructions** (teardown script)
12. Known limitations

### `REPORT.md` structure

1. Problem statement & motivation
2. Data sources, licensing, coverage analysis (with your real numbers from `DATA_FEASIBILITY.md`)
3. Data quality findings — how many nulls, outliers, flatlines you found and what you did
4. Feature engineering & the leakage-prevention argument
5. Feature store design (names, dtypes, source, freshness, owner)
6. **Model comparison table + justification of the selected model**
7. Error analysis: by horizon, by season, by province, by data availability
8. MLOps architecture: what's automated vs manual, and where the approval gates are
9. CI/CD and quality gates, with the failed-run evidence
10. Deployment architecture and AWS cost control
11. Monitoring, drift and the retraining lifecycle
12. Security, ethics, bias, limitations
13. Risk assessment
14. Individual contributions
15. Future work
16. References

### Diagrams

Two, both required. Draw in **draw.io** (free) or Mermaid:
- **Architecture diagram** — data sources → ingestion → DVC/DagsHub → features → Feast → training → MLflow → registry → Flask/Docker → AWS → monitoring
- **Workflow diagram** — the automated-demonstration sequence from §6 of the requirements, with fully-automated steps in green and manual/approval gates in orange

### Demo script (rehearse this three times, timed)

| # | Minutes | What | Who |
|---|---|---|---|
| 1 | 2 | Problem + architecture diagram | Hassan |
| 2 | 2 | Repo tour, modular `src/`, commit history, PRs | Hassan |
| 3 | 3 | **DVC time travel**: `git checkout <old> && dvc checkout` → old row count | Hassan |
| 4 | 3 | **MLflow on DagsHub**: 50+ runs, filter by `member`, comparison table, registry stages | all three |
| 5 | 2 | Feast: `feast apply` → `materialize` → online lookup | Hassan |
| 6 | 2 | `dvc repro` + `dvc dag` | Mudassar |
| 7 | 3 | Airflow: DAG graph, a successful run, a failed task with retries | Mudassar |
| 8 | 2 | Kubeflow: pipeline graph, conditional branch | Mudassar |
| 9 | 3 | **CI/CD: the red PR that cannot merge**, then the green one | Mudassar |
| 10 | 2 | Docker Compose up; `/health`, `/model-info`, `/predict` via curl | Ifraz |
| 11 | 2 | BentoML serving the same model | Ifraz |
| 12 | 3 | **Kubernetes: kill a pod, watch it heal, scale to 5, rollback** | Ifraz |
| 13 | 3 | **Live AWS endpoint** + CloudWatch logs + budget alert screenshot | Ifraz |
| 14 | 2 | React map, time slider, source labels | Ifraz |
| 15 | 3 | **Grafana dashboard + fire an alert live** | Ifraz |
| 16 | 3 | **Simulated drift → Airflow retraining → gate REJECTS a bad model → promote a good one → rollback** | Mudassar |
| 17 | 2 | Limitations, bias, ethics | Hassan |

**Have backup screen recordings of every live step.** Demo gods are cruel. A recording shown with "here's the recording in case the network fails" costs nothing; a frozen laptop costs marks.

**Everyone must be able to answer questions about any part.** The examiner will deliberately ask Ifraz about feature leakage and Hassan about Kubernetes probes.

---

## 30. Final deliverables checklist

### Repository
- [ ] Public GitHub repo, modular `src/`, meaningful commit history
- [ ] 15+ merged PRs with reviews from different members
- [ ] `README.md` + `REPORT.md`
- [ ] `requirements.txt` with pinned versions
- [ ] `.env.example`, no secrets anywhere in history

### Data & reproducibility
- [ ] `.dvc/config` pointing at DagsHub
- [ ] Raw + processed datasets versioned, `dvc push` done
- [ ] `dvc.yaml` with 5 stages, `dvc repro` works end to end
- [ ] Time-travel demo recorded
- [ ] `Documents/MERGE_CONFLICTS.md` including a `.dvc` conflict
- [ ] `Documents/DATA_FEASIBILITY.md`

### Experiments
- [ ] 50+ MLflow runs on the shared DagsHub server
- [ ] All runs tagged `member`, `git_commit`, `dataset_version`
- [ ] `Documents/MODEL_COMPARISON.md` + justification
- [ ] Model Registry with None → Staging → Production → Archived
- [ ] Promotion and rollback scripts

### Feature store
- [ ] `feature_store/feature_repo/` complete
- [ ] `feast apply` + `materialize` + online retrieval demonstrated
- [ ] `tests/test_feature_store.py`
- [ ] Feature documentation table in the report

### Pipelines
- [ ] 3 Airflow DAGs with retries + logging
- [ ] Airflow → Kubeflow trigger working
- [ ] `compiled_pipeline.yaml` + a KFP run screenshot
- [ ] Conditional execution in both

### Testing & CI/CD
- [ ] 25+ tests across all six categories, ≥ 70% coverage
- [ ] `ci.yml` (lint + test + security + build + smoke)
- [ ] `deploy.yml` with a manual approval environment
- [ ] **Evidence of a failed gate blocking a merge**
- [ ] **Evidence of the model gate rejecting a bad model**

### Containers & serving
- [ ] `Dockerfile.api` (multi-stage, non-root, Gunicorn, healthcheck)
- [ ] `docker-compose.yml` with 5 services
- [ ] Flask: `/health`, `/model-info`, `/predict`, `/metrics` + app endpoints
- [ ] BentoML service + container
- [ ] "Runs on another machine" evidence

### Kubernetes
- [ ] `k8s/` manifests with readiness + liveness probes
- [ ] 3→5 replica scaling demo
- [ ] Pod-kill self-healing recording
- [ ] Rolling update + `rollout undo`

### AWS
- [ ] Live endpoint URL in the README
- [ ] ECR image, S3 bucket, CloudWatch log group
- [ ] Budget alert screenshot
- [ ] IAM least-privilege policies + OIDC (no static keys)
- [ ] `scripts/aws_teardown.sh` and proof it was run

### Monitoring
- [ ] Prometheus scraping, 4 custom metrics
- [ ] Grafana dashboard, 8 panels
- [ ] ≥ 1 alert shown FIRING
- [ ] Evidently drift report (real + simulated)
- [ ] Ground-truth feedback loop computing live MAE

### Docs
- [ ] Architecture diagram + workflow diagram
- [ ] `RISK_ASSESSMENT.md` with 6 risks
- [ ] `CONTRIBUTIONS.md`
- [ ] Backup recordings of every demo step

---

## 31. Mistakes that will cost you marks

1. **Doing the real work in a Jupyter notebook.** §3.1 forbids it explicitly. Notebooks are for exploration only; commit them under `notebooks/` and make it obvious that `src/` is the real code.
2. **Random train/test split on time-series data.** Instant credibility loss. Chronological only.
3. **Feature leakage.** Using the pollutant value at `t+h` to predict `t+h` gives you R² = 0.99 and an examiner who immediately knows. Keep `test_no_target_leakage`.
4. **No baseline.** "Our MAE is 12" means nothing. "Our MAE is 12 versus persistence at 18.9, a 37% improvement" means everything.
5. **Three different experiment names in MLflow.** Your comparison silently becomes impossible. Agree on `pm25-forecasting` and freeze the metric names on day one.
6. **Committing `.env` or an AWS key.** Install `pre-commit` and `gitleaks` *before* your first real commit.
7. **Everything on `main`, no PRs.** Loses marks under a 9-mark rubric line that is free to earn.
8. **Only showing green CI.** The requirement is to show a *failed* quality gate blocking deployment. Manufacture that evidence deliberately.
9. **Leaving AWS running after the demo.** Budget alert + teardown script + calendar reminder.
10. **Using EKS or Fargate "because it's proper".** ~$73/month for the EKS control plane alone. Minikube locally is explicitly permitted (§3.10).
11. **Claiming a sensor in every city.** Label every value with its source. Honesty about limitations earns marks; overclaiming loses them twice (accuracy *and* ethics).
12. **One person doing everything.** All three are examined individually. Rotate reviews and run teach-back sessions.
13. **Leaving integration to the last week.** Get a trivial end-to-end slice working early — one city, a dummy model, a Flask endpoint returning a constant, a map with one dot. Then improve each layer. Never build three perfect components that have never spoken to each other.
14. **Letting the raw dataset grow past the free DagsHub quota.** Use `float32`, drop unused variables, and track processed features rather than every raw city-year file if space gets tight.

---

## Quick reference — commands you'll use daily

```bash
# ── Daily start ──
.venv\Scripts\activate
git checkout main && git pull && dvc pull

# ── Working ──
git checkout -b feature/xyz
# ...edit...
pytest -q
ruff check src tests --fix
git add -A && git commit -m "feat: ..." && git push origin feature/xyz

# ── Data ──
dvc add data/processed/features.parquet
dvc push
dvc repro
dvc dag
dvc metrics show

# ── Training ──
python -m src.models.train_xgboost --max-depth 8 --lr 0.05
python scripts/compare_models.py

# ── Serving ──
docker compose up -d --build
curl localhost:5000/health
curl -X POST localhost:5000/predict -H "Content-Type: application/json" \
     -d '{"cities":[{"city_id":"lahore","horizon":24}]}'

# ── Kubernetes ──
minikube start && minikube image load airwatch-api:latest
kubectl apply -f k8s/ && kubectl get pods -w

# ── Airflow ──
docker compose -f docker-compose.airflow.yml up -d     # localhost:8080

# ── Monitoring ──
# Prometheus localhost:9090 · Grafana localhost:3001 · MLflow on DagsHub
```

---

## Recommended build order

Build a thin end-to-end slice first, then thicken each layer. Do **not** perfect one phase before touching the next.

```
Setup → Repo skeleton → DVC/DagsHub → Data feasibility check
  → Ingest 5 cities → Validate → Features → Baseline model → MLflow run
  → Flask /health + /predict (constant) → Docker → pytest → GitHub Actions
  ══════════ you now have a working vertical slice ══════════
  → Scale to 130 cities + 12 years → real models → the 3-way competition
  → Feast → dvc.yaml → Airflow → Kubeflow → Kubernetes
  → AWS deployment → React map → Prometheus/Grafana → Evidently
  → Retraining + rollback → BentoML → Docs, report, diagrams → rehearse demo
```

---

**Attribution:** Air-quality and weather data © Open-Meteo.com (CC BY 4.0). Ground-station observations via OpenAQ and underlying providers. Pakistan context data © Pakistan Air Quality Initiative (PAQI), CC BY 4.0. City coordinates © GeoNames (CC BY 4.0). Pakistan AirWatch AI is an academic, non-commercial prototype and is not an official public-health warning system.
