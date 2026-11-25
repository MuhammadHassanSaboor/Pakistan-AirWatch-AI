# Workflow — how work actually flows through this project

Covers the daily developer loop, the data pipeline, the model
lifecycle, and the automation that ties them together. Read
[PLANNING.md](PLANNING.md) first for *what* we are building.

---

## 1. The daily loop

```bash
conda activate airwatch

git checkout main && git pull
dvc pull                       # fetch the data matching this commit

git checkout -b feature/my-thing
# ... edit ...

pytest -q                      # must be green before you push
ruff check src tests --fix
ruff format src tests

git add -A
git commit -m "feat: what this does"
git push origin feature/my-thing
# open a Pull Request; someone else reviews and merges
```

**Branch protection is deliberate.** Nobody pushes to `main`. The
pre-commit hook `no-commit-to-branch` enforces it locally and GitHub
enforces it on the server, so the PR history the rubric asks for is
produced by the process rather than by remembering.

### Commit message prefixes
`feat:` `fix:` `docs:` `test:` `chore:` `data:` `refactor:`

---

## 2. Data flow

```
Open-Meteo Air Quality API ─┐
(no key, 2022-08-05 → now)  │
                            ├─► src/data/ingestion.py
Open-Meteo Archive API ─────┘     batched, resumable, quota-aware
(ERA5 weather)                              │
                                            ▼
                              data/raw/chunks/*.parquet
                              one file per (city, 6-month window)
                                            │
                                            ▼  combine_chunks()
                              data/raw/airquality_hourly.parquet
                              schema-normalised, negatives clamped
                                            │
                                            ▼
                              src/data/validation.py
                              Pandera schema + 7 quality rules
                                            │
                                   FAIL ◄───┴───► PASS
                               pipeline stops        │
                                                     ▼
                              src/features/preprocessing.py
                              lags · rolling · calendar · weather · spatial
                                            │
                                            ▼
                              data/processed/features.parquet
                              5.1 M rows × 100 features
                                            │
                        ┌───────────────────┴───────────────────┐
                        ▼                                       ▼
            feature_store (Feast)                    chrono_split()
            offline ─materialize─► online            train / val / test
                        │                                       │
                        └───────────────┬───────────────────────┘
                                        ▼
                                 model training
```

### Why chunk files

Each `(city, 6-month window)` lands in its own parquet. A full national
backfill makes hundreds of requests over several hours against a
rate-limited free API; without per-chunk resume, a single 429 at hour
three would mean starting over. Re-running skips everything already on
disk.

### Running it

```bash
python -m src.data.cities                 # build the 134-city table
python -m src.data.ingestion              # full backfill (resumable)
python -m src.data.ingestion --limit 12   # quick smoke test
python -m src.data.ingestion --combine-only
python -m src.data.validation             # writes reports/data_quality.json
python -m src.features.build_features
```

---

## 3. The leakage rule

The single most important rule in the project.

To predict PM2.5 at time **t + h**, a feature may use:

| Allowed | Why |
|---|---|
| PM2.5 at t, t−1, t−2 … (lags) | genuinely known at prediction time |
| rolling stats computed on `shift(1)` | the current hour never feeds its own average |
| **weather forecast** at t + h | a weather forecast really is available ahead of time |
| calendar features at t + h | the clock is known |
| static city attributes | latitude does not change |

| Forbidden | Why |
|---|---|
| PM2.5 at t + h | that is the answer |
| any pollutant between t+1 and t+h | the future |
| neighbour pollution at t + h | the future, borrowed from next door |

Breaking this produces R² near 0.99 and a model that cannot forecast
anything. Four tests in `tests/test_features.py` enforce it, including
a correlation sweep that fails if *any* feature correlates with the
label above 0.999.

---

## 4. Model lifecycle

```
                    experiment
                        │
   each member runs their family, same data, same split,
   same experiment name, tagged with their name
                        │
                        ▼
              MLflow (DagsHub, shared)
                        │
                 compare on test_mae
                        │
                        ▼
                 QUALITY GATE
       test_mae ≤ 25  AND  ≥15% better than persistence
                        │
            FAIL ◄──────┴──────► PASS
      never registered            registered → version N
                                         │
                                         ▼
                                     Staging
                                         │
                            integration tests run
                                         │
                                         ▼
                            ⚠ HUMAN APPROVAL ⚠
                                         │
                                         ▼
                                   Production
                       (previous version → Archived)
                                         │
                                         ▼
                         API loads models:/…/Production
                                         │
                              smoke test fails?
                                         │
                                         ▼
                                   ROLLBACK
                      Archived version → Production, ~30 s
```

### Commands

```bash
# train
python -m src.models.train_baselines --all          # Ifraz, first
python -m src.models.train_xgboost                  # Hassan
python -m src.models.train_xgboost --sweep          # 24 configurations
python -m src.models.train_lightgbm --sweep         # Mudassar

# compare
python -m src.models.registry compare
python -m src.models.registry best

# govern
python -m src.models.registry list
python -m src.models.registry promote --run-id <id> --stage Staging
python -m src.models.registry promote-production --version 7
python -m src.models.registry rollback
python -m src.models.registry export-production
```

**`promote_to_production()` is the only path to Production**, and it
re-runs the quality gate internally. The Airflow DAG, the Kubeflow
pipeline and the CLI all call it, so there is no entry point that can
bypass the gate by accident.

---

## 5. Reproducible pipeline (DVC)

```bash
dvc repro             # re-runs only the stages whose inputs changed
dvc dag               # prints the dependency graph
dvc metrics show
dvc metrics diff main # how did this branch move the metrics?
dvc push              # upload data to DagsHub
```

Stages: `cities → ingest → validate → features → train`

### Time travel

```bash
git log --oneline
git checkout <old-commit>
dvc checkout                  # the DATA moves back in time too
python -c "import pandas as pd; print(pd.read_parquet('data/processed/features.parquet').shape)"
git checkout main && dvc checkout
```

Code and data move together. That is the whole point of DVC and it is
a graded deliverable.

---

## 6. Orchestration: Airflow vs Kubeflow

They do different jobs and never duplicate work.

| | Airflow | Kubeflow |
|---|---|---|
| Owns | the clock and the data plane | the ML workflow graph |
| Decides | **whether** and **when** to train | **how** the training graph executes |
| Granularity | tasks in one process | each step in its own container |
| Cost | cheap to run continuously | heavier, run on demand |

```
Airflow hourly_ingest_dag        every hour
  fetch → validate → load → rolling history → drift check

Airflow ml_orchestrator_dag      manual / triggered
  revalidate → rebuild features → ►► trigger Kubeflow ►► wait
                                       │
                                       ▼
                        Kubeflow pm25-training-pipeline
                          validate_data
                            └─if valid─► engineer_features
                                           └─► train_model
                                                 └─► evaluate_model
                                                       └─if gate passes─►
                                                            register_model

Airflow retraining_dag           weekly + drift-triggered
  drift? age? → branch → retrain → compare vs PRODUCTION
              → gate → Staging → human approval → Production
              → smoke test → (on failure) rollback
```

### Running them

```bash
# Airflow
docker compose -f docker-compose.airflow.yml up -d     # localhost:8080

# Kubeflow
python pipelines/kubeflow/pipeline_definition.py        # compile the YAML
minikube start --cpus=4 --memory=8192
kubectl apply -k "github.com/kubeflow/pipelines/manifests/kustomize/cluster-scoped-resources?ref=2.2.0"
kubectl apply -k "github.com/kubeflow/pipelines/manifests/kustomize/env/platform-agnostic?ref=2.2.0"
kubectl port-forward -n kubeflow svc/ml-pipeline-ui 8080:80
# upload compiled_pipeline.yaml in the UI
```

---

## 7. Serving

```
browser ──► Vite dev proxy ──► Flask API ──► ModelLoader
                                   │              │
                                   │              └─► models/production/model.pkl
                                   │                  or MLflow Production stage
                                   ▼
                            LiveFeatureStore
                     Open-Meteo live (cached 55 min)
                                   │
                       src/features/preprocessing.py
                       ── the SAME functions training uses ──
```

That shared import is what prevents training/serving skew. There is no
second implementation of `pm2_5_lag_24h` that can drift from the first;
`tests/test_pipeline.py::test_serving_features_match_training_features`
fails if the serving path can no longer produce a training feature.

**The browser never calls Open-Meteo directly.** Every map pan would
otherwise hit the upstream API, blow the rate limit within minutes, and
make caching impossible.

```bash
python -m src.serving.app                    # dev
docker compose up -d --build                 # full stack
curl localhost:5000/health
curl -X POST localhost:5000/predict -H "Content-Type: application/json" \
     -d '{"cities":[{"city_id":"lahore","horizon":24}]}'
```

---

## 8. CI/CD

```
push / PR
   │
   ├─ quality    ruff lint · ruff format · gitleaks · pip-audit
   ├─ test       pytest, coverage ≥ 70%
   ├─ config     YAML parses · split dates ordered · 134 cities · no secrets in .env.example
   │
   └─► build     ← needs: [quality, test, config]   THE QUALITY GATE
         docker build → trivy scan → run container → curl /health
   │
   └─► frontend  npm ci → eslint → vite build
```

`build` declares `needs: [quality, test, config]`. A failing test makes
the Docker image **physically impossible to produce**, so nothing can
be deployed from a red run. That dependency line *is* the gate — not a
convention, a constraint.

### Producing the required failure evidence

```bash
git checkout -b demo/failing-gate
# break a test deliberately
git commit -am "test: demonstrate the quality gate blocking a merge"
git push origin demo/failing-gate
# open a PR → screenshot the red X and the blocked Merge button
# fix → screenshot green
```

Save both to `Documents/evidence/`.

---

## 9. Monitoring

| Layer | Tool | Question it answers |
|---|---|---|
| Service | Prometheus + Grafana | Is the API healthy, fast, erroring? |
| Data | Evidently + PSI | Is the input still the world we trained on? |
| Model | ground-truth join | Is the deployed model still accurate? |

```bash
docker compose up -d                 # Prometheus :9090, Grafana :3001
python -m src.monitoring.drift                 # real drift check
python -m src.monitoring.drift --simulate      # controlled demo event
```

### Demonstrating an alert firing

```bash
docker compose stop api        # APIDown fires after 1 minute
# or hammer the API with malformed requests → HighAPIErrorRate
```

Screenshot Prometheus → Alerts showing **FIRING**.

---

## 10. Merge conflicts, including `.dvc` files

Ordinary file:
```bash
git merge main
# edit the file, remove the <<<<<<< ======= >>>>>>> markers
git add <file> && git commit
```

A `.dvc` file is different — it holds a content hash, and two hashes
cannot be merged. Pick a side, then regenerate:

```bash
git checkout --theirs data/processed/features.parquet.dvc
git add data/processed/features.parquet.dvc
dvc checkout      # pull the data matching that hash
dvc repro         # regenerate everything downstream
git commit -m "merge: resolve .dvc conflict, keep main's dataset version"
```

Document a real occurrence with screenshots in
`Documents/MERGE_CONFLICTS.md` — it is a graded deliverable.

---

## 11. Secrets

This repository is **public**. The rules are not optional.

- `.env` is gitignored; only `.env.example` is committed, with
  placeholders
- every member generates their **own** DagsHub token — never shared
- `gitleaks` runs in pre-commit **and** in CI
- a `no-env-file` pre-commit hook blocks `.env` by filename
- CI asserts `.env.example` contains no credential-shaped strings
- Kubernetes credentials go in a Secret created imperatively, never in
  a committed manifest

**If a token ever reaches GitHub:** revoke it first (DagsHub →
Settings → Tokens → delete), then worry about history. The old value is
already public the moment it is pushed.
