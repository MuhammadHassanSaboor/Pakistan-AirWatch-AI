# Project Plan — Pakistan AirWatch AI

**Team:** Hassan · Mudassar · Ifraz
**Course:** MLOps Semester Project
**Status:** build in progress; see §7 for what is done

---

## 1. What we are building

An hourly PM2.5 forecasting system for **134 Pakistani cities**, with a
web dashboard, served through a production-shaped MLOps pipeline.

**The prediction task, stated precisely:**

> For a given city, at a given hour, predict the PM2.5 concentration
> (µg/m³) 1, 6, 12 and 24 hours into the future.

One **global** model serves every city and every horizon. City identity
enters as features (latitude, longitude, elevation, log-population) and
`horizon` is itself a feature. We do not train 134 separate models —
that would waste the shared structure between cities and make the
registry unmanageable.

---

## 2. Decisions already made, and why

| Decision | Choice | Reason |
|---|---|---|
| Backend framework | **Flask** | Mandated by the specification (§3.8) and by the rubric. Laravel would add a second language for zero marks |
| Frontend | React + Vite + Leaflet + Plotly | Interactive map plus analytical charts |
| Experiment tracking | MLflow on DagsHub | Free hosted tracking server all three members share |
| Data versioning | DVC → DagsHub remote | Git cannot hold a 585 MB parquet |
| Primary model | XGBoost | Strongest general-purpose tabular time-series learner |
| Target | PM2.5 in µg/m³ | The pollutant with the clearest health relevance for Pakistan |
| Split | Chronological, never random | It is a time series; a random split leaks the future |
| Cloud | Deferred | Deployment comes later; everything runs locally meanwhile |

### Why not a uniform geographic grid

The original proposal described a lat/lon grid. We model **named
cities** instead because:

- a city gives a stable, human-readable entity key for Feast
  (`lahore`, not `cell_0417`)
- 134 cities × hourly is a dataset that trains on a laptop
- a fine grid over sparse data implies a precision the source cannot
  support — the map would look authoritative and be fiction

---

## 3. The data reality

Summarised here; full evidence in [DATA_FEASIBILITY.md](DATA_FEASIBILITY.md).

| | |
|---|---|
| Source | Open-Meteo (no API key, no account) |
| Air-quality coverage | **2022-08-05 → today** (~3.3 years) |
| Rows | ~4.6 million city-hours at full coverage |
| Smog seasons captured | 4 |
| PM2.5 completeness | 100% non-null |
| Ground-truth sensors | **Unavailable** — OpenAQ verification email never arrived |

**The honest framing we will defend:** we forecast CAMS *reanalysis*
PM2.5, which is a model product rather than a sensor reading. We say
so in the report, in the API response, and on the dashboard. Every
operational forecasting system trains on reanalysis for the same
reason — it is the only source with complete spatial coverage.

---

## 4. Who owns what

Everyone must be able to explain every component at the oral defence.
These are ownership lines, not walls.

### Hassan — Data & ML Engineering (+ integration)
- `src/data/` — ingestion, Open-Meteo client, validation
- `src/features/` — feature engineering, splits
- `feature_store/` — Feast definitions and materialisation
- `src/models/train_xgboost.py` — the XGBoost family
- `src/serving/` — Flask API
- `frontend/` — the React dashboard
- `configs/` — the settings every member reads from

### Mudassar — MLOps & Automation
- `pipelines/airflow/` — the three DAGs
- `pipelines/kubeflow/` — the component graph
- `tests/` — all six test categories
- `.github/workflows/` — CI/CD
- `dvc.yaml` — the reproducible pipeline
- `src/models/registry.py` — promotion, rollback
- `src/models/train_lightgbm.py` — the LightGBM / RandomForest family

### Ifraz — Deployment & Reliability
- `docker/`, `docker-compose.yml`
- `k8s/` — manifests, scaling, probes
- `monitoring/` — Prometheus, Grafana, alert rules
- `src/monitoring/drift.py` — Evidently drift detection
- `src/models/train_baselines.py` — **the baselines, first**
- Deployment when we reach it

### Shared, weekly
- One 30-minute sync: done / blocked / needed
- Every PR reviewed by someone who did not write it
- `CONTRIBUTIONS.md` updated as we go
- Teach-back: each member explains *another* member's module

---

## 5. The three-way model comparison

This is the heart of the project and the thing most likely to go wrong
quietly. Rules agreed in advance:

| Rule | Value |
|---|---|
| Dataset | the exact same `features.parquet`, pulled with `dvc pull` |
| Split | `chrono_split()` reading dates from `configs/model_params.yaml` |
| Experiment name | `pm25-forecasting` — identical for all three |
| Required tags | `member`, `model_family`, `git_commit`, `dataset_version` |
| Required metrics | the frozen list in `model_params.yaml` |
| Runs per member | ≥ 10 |
| Winner | lowest `test_mae`, tie-break on `mae_h24` |

**Nobody writes their own split or metric code.** Everything routes
through `src/models/train_base.py`, so the only thing a member supplies
is the estimator. That is what makes the comparison valid rather than
three people reporting incomparable numbers.

| Member | Family | Purpose |
|---|---|---|
| Ifraz | persistence, seasonal-naive, rolling-mean, ridge, tree | **The benchmark.** Run first — nothing else means anything without it |
| Hassan | XGBoost | Expected winner |
| Mudassar | LightGBM, RandomForest, HistGradientBoosting | Speed comparison + a non-boosting robustness check |

### Results so far

Trained on 84 cities / 11.3 M feature rows. Test window is
2026-01-01 → today, which contains a full smog season.

| Model | test MAE | test R² | vs persistence | Gate |
|---|---|---|---|---|
| **XGBoost** d8 lr0.05 n400 | **8.247** | **0.800** | **+41.3%** | **PASS** |
| persistence (reference) | 14.040 | — | — | FAIL (by definition) |

Error by lead time, which a single averaged number would hide:

| Horizon | MAE (µg/m³) |
|---|---|
| +1 h | 2.63 |
| +6 h | 9.25 |
| +12 h | 10.39 |
| +24 h | 10.73 |

Earlier run on the first 36 cities: MAE 6.80, +36.9%. The absolute
error rose with the larger city set because it adds heavily polluted
Punjab and Sindh cities — the baseline rose too (10.78 → 14.04), and
the model's *relative* advantage improved. This is why the baseline is
logged on every run: an absolute MAE means nothing on its own.

The three baselines *failing* the quality gate is the gate working
correctly: a baseline is a yardstick, never a deployable model.

---

## 6. Build order

Thin end-to-end slice first, then thicken each layer. We never build
three perfect components that have never spoken to each other.

```
environment + repo + DVC/DagsHub
  → verify data actually exists          ← done first, changed the plan
  → ingest → validate → features
  → baselines → XGBoost → MLflow
  → Flask API → tests → Docker
  ══ working vertical slice ══
  → Feast → dvc.yaml → Airflow → Kubeflow
  → React dashboard → Prometheus/Grafana → Evidently
  → retraining + rollback → deployment
  → report, diagrams, rehearsal
```

---

## 7. Status

| Component | State | Evidence |
|---|---|---|
| Conda environment | ✅ | `airwatch`, Python 3.11 |
| 134-city reference table | ✅ | all 7 provinces, validated |
| Data feasibility verified | ✅ | `Documents/DATA_FEASIBILITY.md` |
| Historical backfill | 🔄 running | resumable; rate-limited by quota |
| Validation (Pandera + rules) | ✅ | all checks pass |
| Feature engineering | ✅ | 100 features, 5.1 M supervised rows |
| Leakage guards | ✅ | 22 feature tests pass |
| Baselines | ✅ | persistence MAE 10.775 |
| XGBoost | ✅ | test MAE 6.80, +36.9% |
| Quality gate | ✅ | rejects baselines, passes XGBoost |
| Model registry + promotion | ✅ | v1 in Production |
| Feast | ✅ | online 10 ms; offline point-in-time correct |
| Flask API | ✅ | live predictions verified |
| Test suite | ✅ | 127 tests passing |
| Docker | ✅ | multi-stage, non-root, Gunicorn |
| docker-compose | ✅ | api + db + mlflow + prometheus + grafana |
| CI/CD | ✅ | quality gate blocks the build job |
| DVC pipeline | ✅ | 5 stages |
| Airflow DAGs | ✅ | 3 DAGs, syntax-validated |
| Kubeflow pipeline | ✅ | compiles, 8 components, 2 gates |
| Kubernetes manifests | ✅ | probes, HPA, PDB, NetworkPolicy |
| Drift detection | ✅ | Evidently + PSI fallback |
| React dashboard | ✅ | builds and runs |
| Prometheus + Grafana | ✅ | 11-panel dashboard, 7 alert rules |
| Deployment | ⏸ deferred | by request |
| Final report | ⏳ | `REPORT.md` |

---

## 8. Known risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| No ground-truth sensors | **Certain** | State the limitation explicitly; frame as reanalysis forecasting |
| Open-Meteo quota slows the backfill | **Certain** | Resumable ingestion, quota-aware waiting; it finishes unattended |
| Open-Meteo changes terms or endpoints | Low | Every response cached locally; source adapters are swappable |
| Model degrades in smog season | High | Seasonal features, drift monitoring, retraining DAG |
| Kubeflow too heavy for a laptop | Medium | `kind` or `kfp.local`; the compiled YAML is the deliverable either way |
| One member blocked by another | Medium | Interfaces fixed in configs; synthetic fixtures let each work alone |

---

## 9. What we will not claim

- That every city has a sensor. **It does not.**
- That the forecast is validated against ground truth. **It is not.**
- Street-level accuracy. The source resolution does not support it.
- That this is a public-health service. It is a student prototype, and
  the dashboard says so permanently.
