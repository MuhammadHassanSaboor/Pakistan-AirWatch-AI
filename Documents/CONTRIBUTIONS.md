# Individual Contributions

Required by §11 of the course specification. Update this file as work
lands — it is evidence, not a formality.

**Every member must be able to explain every component at the oral
defence.** These are ownership lines, not walls. The examiner will
deliberately ask Hassan about Kubernetes probes and Ifraz about feature
leakage.

---

## Hassan — Data & ML Engineering, API, Frontend

### Owns
| Area | Files |
|---|---|
| Configuration | `src/config.py`, `configs/*.yaml` |
| City reference | `src/data/cities.py` |
| Data acquisition | `src/data/openmeteo.py`, `src/data/ingestion.py` |
| Validation | `src/data/validation.py` |
| Feature engineering | `src/features/preprocessing.py`, `build_features.py`, `splits.py` |
| Feature store | `feature_store/` |
| XGBoost | `src/models/train_xgboost.py` |
| Serving | `src/serving/` |
| Dashboard | `frontend/` |

### Delivered
- 134-city reference table covering all 7 administrative units,
  validated against a Pakistan bounding box
- **Data feasibility investigation** that changed the project plan:
  established by binary search that the free air-quality archive
  returns nulls before 2022-08-05 despite answering HTTP 200
- Batched, resumable ingestion with quota-aware 429 handling; reduced
  a national backfill from ~1,300 requests to ~216
- Discovered Open-Meteo's `locations × variables × days` pricing and
  trimmed weather variables from 12 to 10, halving request cost
- Pandera schema plus 7 quality rules; identified the Nushki dust storm
  (March 2024, dust 10,134 µg/m³) as genuine meteorology rather than
  corruption and widened bounds instead of deleting it
- 100-feature pipeline with enforced leakage safety
- XGBoost model: **test MAE 6.80 µg/m³, +36.9% over persistence**
- Flask API: 3 required endpoints + 5 dashboard endpoints + Prometheus
- Feast feature store: online retrieval in ~10 ms, point-in-time
  correct offline joins
- React dashboard: Leaflet map, Plotly analytics, Framer Motion

### Key judgement calls
- Chose Flask over Laravel: the specification mandates Flask, and a
  second language would have earned zero marks
- Made the serving layer **import** the training feature code rather
  than reimplement it, eliminating training/serving skew structurally
- Projected the Feast source down to observation grain after finding
  that duplicate entity keys make point-in-time joins return nothing

---

## Mudassar — MLOps & Automation Engineering

### Owns
| Area | Files |
|---|---|
| DVC pipeline | `dvc.yaml` |
| Orchestration | `pipelines/airflow/dags/*.py` |
| ML workflow graph | `pipelines/kubeflow/` |
| Testing | `tests/` |
| CI/CD | `.github/workflows/ci.yml` |
| Model governance | `src/models/registry.py`, `evaluate.py`, `tracking.py` |
| LightGBM / RandomForest | `src/models/train_lightgbm.py` |
| Code quality | `.pre-commit-config.yaml`, `pyproject.toml` |

### Delivered
- 5-stage DVC pipeline with parameter tracking and metrics
- Three Airflow DAGs with retries, exponential backoff, branching and
  explicit non-retryable failures for schema violations
- Kubeflow pipeline compiling to 763 lines / 8 components with **two
  conditional gates** — invalid data and failing models cannot reach
  the register step
- 127 tests across all six required categories
- CI where `build` declares `needs: [quality, test, config]`, making a
  Docker image physically impossible to produce from a red run
- Quality gate with three conditions including "must beat the currently
  deployed model"
- Registry operations: promotion, archival, rollback, local export
- Shared MLflow tracking helpers that force tag and metric consistency
  across all three members

### Key judgement calls
- Routed every member's training through one harness
  (`train_base.py`) so the comparison is valid by construction rather
  than by discipline
- Made `promote_to_production()` the single path to Production and had
  it re-run the gate internally, so no caller can bypass it
- Set `retries=0` on validation and gate tasks: a schema violation or a
  rejected model will not fix itself on retry

---

## Ifraz — Deployment & Reliability Engineering

### Owns
| Area | Files |
|---|---|
| Containers | `docker/Dockerfile.api`, `docker-compose.yml` |
| Orchestration | `k8s/*.yaml` |
| Monitoring | `monitoring/`, `src/monitoring/drift.py` |
| Baselines | `src/models/train_baselines.py` |
| Operational scripts | `scripts/*.sh` |

### Delivered
- Multi-stage Dockerfile: non-root uid 1000, read-only root filesystem,
  dropped capabilities, healthcheck, Gunicorn
- Slim `requirements-api.txt` keeping Airflow and Kubeflow out of the
  serving image
- 5-service docker-compose stack with health-gated dependencies
- Kubernetes manifests with **three distinct probes** (startup,
  readiness, liveness), HPA, PodDisruptionBudget and a NetworkPolicy
- Prometheus with 4 custom metrics; 11-panel Grafana dashboard
- 7 alert rules, each carrying a runbook annotation
- Evidently drift detection with an independent PSI fallback — verified
  on a simulated smog-season event producing 75% drift
- **The baselines**, run before any other model: persistence,
  seasonal-naive, rolling-mean, ridge, decision tree
- Rollback, alert-trigger and gate-demonstration scripts

### Key judgement calls
- Separated readiness from liveness deliberately: a pod whose model has
  not loaded should receive no traffic but must **not** be killed, or
  it would crash-loop before it could ever finish loading
- Added a PSI fallback to drift detection so it survives Evidently's
  API changing between versions
- Chose NodePort over LoadBalancer and documented why: a cloud load
  balancer is billable

---

## Shared work

All three members contributed to:

- Requirements analysis and architecture decisions
- Interpreting the data feasibility findings and revising the plan
- The three-way model comparison protocol
- Code review — every PR reviewed by someone who did not write it
- `Documents/` — planning, workflow, architecture, risk assessment
- Final report, diagrams and demonstration rehearsal

---

## Weekly log

| Week | Hassan | Mudassar | Ifraz |
|---|---|---|---|
| 1 | Environment, repo, city table, **data feasibility** | DVC + DagsHub, pre-commit | Docker scaffold, accounts |
| 2 | Ingestion, validation, 100-feature pipeline | Test suite, CI workflow | Baselines, compose stack |
| 3 | XGBoost, MLflow integration, Feast | Registry, quality gate, DVC pipeline | Prometheus, Grafana, drift |
| 4 | Flask API, React dashboard | Airflow DAGs, Kubeflow pipeline | Kubernetes manifests, scripts |
| 5 | _(to fill in)_ | _(to fill in)_ | _(to fill in)_ |

---

## Oral defence preparation

Each member must be able to answer questions on **another member's**
module. Rehearse these specifically:

| Question | Why it is asked |
|---|---|
| Why is a random train/test split wrong here? | Tests whether you understand time-series leakage |
| Show me a feature that would leak, and the test that catches it | Tests whether the guard is real |
| Your MAE is 6.8 — is that good? | The only correct answer references the baseline |
| Why does MAE at +12h exceed MAE at +24h for persistence? | Tests whether you understand the daily cycle |
| What happens if a retrained model is worse? | Tests the governance chain |
| Why is readiness separate from liveness? | Tests whether the probes were copied or understood |
| Where is your ground truth? | The honest answer is "we do not have one, and here is what that means" |
| Which cities is your model least reliable for, and why does that matter? | Tests the ethics position |
