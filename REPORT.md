# Pakistan AirWatch AI — Project Report

**Hourly PM2.5 forecasting for Pakistani cities, built as an end-to-end
MLOps system.**

| | |
|---|---|
| Team | Hassan · Mudassar · Ifraz |
| Repository | https://github.com/MuhammadHassanSaboor/Pakistan-AirWatch-AI |
| Experiment tracking | https://dagshub.com/MuhammadHassanSaboor/Pakistan-AirWatch-AI/experiments |
| Data versioning | DVC → DagsHub S3-compatible remote |
| Report generated | 2026-11-28 |

Every number in this report is taken from a committed artefact in the
repository — `reports/*.json`, `dvc.lock`, `models/production/metadata.json`,
or the MLflow server — and the source is named so each one can be
checked. Where something is incomplete it is marked **OPEN** rather
than rounded up.

---

## 1. Problem and scope

Pakistan has among the worst air quality in the world and very little
public sensing: 134 cities in our reference table, and reference-grade
instruments in two of them. The gap between "where people live" and
"where air quality is measured" is the problem this project addresses.

**Task.** For a given city and a horizon of 1, 6, 12 or 24 hours
ahead, predict PM2.5 concentration in µg/m³.

**Why PM2.5.** It is the pollutant most strongly linked to mortality,
and the one the EPA AQI is most often driven by in this region.

**Framing.** One global regression model with `horizon` as an input
feature, rather than four separate models. This keeps a single artefact
to deploy, lets all horizons share the same learned structure, and
means a new horizon needs no new model.

---

## 2. Data

### 2.1 Sources

| Source | Role | Licence / key |
|---|---|---|
| Open-Meteo Air Quality (CAMS reanalysis) | PM2.5 target + chemistry | free, **no API key**, non-commercial |
| Open-Meteo ERA5 Archive | weather history | free, no API key |
| OpenAQ v3 | ground-truth validation **only** | free key |
| GeoNames | city coordinates, elevation, population | CC BY |

Open-Meteo was chosen over paid providers because it needs no key at
all, which removes a credential from a public repository and lets any
examiner reproduce the ingestion without signing up for anything.

### 2.2 What was actually collected

Source: `reports/data_quality.json`, `reports/feature_summary.json`.

| | |
|---|---|
| Raw rows | **2,822,112** |
| Raw columns | 26 |
| Cities with history | **84** (of 134 defined) |
| Period | 2022-08-05 00:00 → 2026-11-24 23:00 UTC, hourly |
| Missing values in target | 0 |
| Schema validation | **pass** |
| Feature rows | **11,276,772** (2.82 M × 4 horizons) |
| Model features | **100** |

**OPEN — the backfill covers 84 of 134 cities.** 50 cities have no
history, including Karachi and Hyderabad. The consequence is stated
honestly rather than hidden: the model is *trained* on 84 cities and
*serves* all 134, which it can do because city identity is encoded
continuously (latitude, longitude, elevation, log-population) and not
as a categorical — there is no per-city parameter that could be
missing. Predictions for the other 50 cities are therefore genuine
model output, but they carry extra uncertainty that the test metrics in
section 5 do **not** measure.

Closing it is one resumable command, because `fetch.resume: true`
makes ingestion skip the city-chunks already downloaded:

```bash
dvc repro            # ingest (≈450 requests) → validate → features → train
dvc push
```

### 2.3 The target is a reanalysis product, and it reads low

This is the most important caveat in the project and is stated first
rather than buried. We forecast *CAMS reanalysis* PM2.5, not sensor
readings. Validated against OpenAQ (source:
`reports/ground_truth_validation.json`):

| Tier | Hours compared | MAE | Bias | Correlation | Mean observed |
|---|---|---|---|---|---|
| **Reference-grade** (US Diplomatic Posts, Islamabad + Lahore) | 19,327 | **27.38** | **−12.54** | 0.665 | 55.75 |
| Low-cost sensors | 2,911 | 82.76 | −82.02 | 0.710 | 138.89 |

The reanalysis tracks the *shape* of Pakistani air quality (r ≈ 0.67)
but **understates its magnitude**, and the gap widens in dirtier air.

**The dominant error is the target, not the model.** Our model
forecasts the reanalysis to 8.25 µg/m³, while the reanalysis itself
sits 27.38 µg/m³ away from reference instruments. Every number on the
dashboard should be read as "reanalysis scale"; real air is likely
dirtier. Low-cost sensors are used for validation only and never for
training — they over-report humidity-affected particulate, visible in
the −82 bias above.

### 2.4 Versioning (how we know we all trained on the same bytes)

The dataset is versioned with DVC and stored on a DagsHub
S3-compatible remote. `dvc.lock` records an md5 for every pipeline
output:

| Path | md5 | Size |
|---|---|---|
| `data/raw/airquality_hourly.parquet` | `c44c27395799c1bc4df9e44c0d3cef26` | 60.8 MB |
| `data/processed/features.parquet` | `b3dce04aad6b7bb9d829a9ffd94edce2` | 1.32 GB |

Both are present on the remote (1.388 GB total, verified by listing
the bucket). `dvc status -c` reports *"Cache and remote 'origin' are in
sync."*

This matters more than it sounds. The Open-Meteo archive is **not a
fixed dataset**: the start date is pinned but the end date is "now",
and CAMS reanalysis is *revised retroactively*. Three people running
ingestion on three days get three different datasets, and a comparison
table built across them ranks models by which snapshot they happened
to download. Section 6.2 shows that this already happened to us and
how it was caught.

**Recovery demo:** `./scripts/demo_dvc_rollback.sh` corrupts the raw
dataset on purpose, shows `dvc status` detecting it, restores it with
`dvc checkout`, and confirms the md5 matches again — byte for byte,
from the local cache, offline. Verified working.

---

## 3. Feature engineering

All logic lives in `src/features/preprocessing.py`. There are **no
notebooks doing the work**; the notebooks in `notebooks/` import from
`src/` and analyse, nothing more.

Each design choice below is justified by a measurement in
[`notebooks/01_exploratory_data_analysis.ipynb`](notebooks/01_exploratory_data_analysis.ipynb),
which is committed with its outputs.

### 3.1 Inventory (100 features)

Source: `models/production/metadata.json`.

| Group | Count | Examples | Why |
|---|---|---|---|
| Weather & chemistry, current hour | 31 | `pm2_5`, `pm10`, `no2`, `temperature_2m`, `boundary_layer_height`, `ventilation_index`, `wind_u`/`wind_v` | the physical state driving dispersion |
| Lags | 21 | `pm2_5_lag_1h … lag_168h`, `pm10_lag_24h` | PM2.5 autocorrelation is ≈0.9 at 1 h and decays slowly |
| Rolling windows | 20 | `pm2_5_roll{3,6,12,24,72}_{mean,std,min,max}` | recent level *and* volatility |
| Binary regime flags | 11 | `is_smog_season`, `is_shallow_blh`, `is_monsoon`, `is_rush_hour`, `is_calm` | sharp regime changes a tree can split on cheaply |
| Cyclical encodings | 6 | `hour_sin/cos`, `month_sin/cos`, `doy_sin/cos` | hour 23 and hour 0 are adjacent; integers place them 23 apart |
| Static per-city | 4 | `latitude`, `longitude`, `elevation_m`, `population` | continuous city identity — why unseen cities can be served |
| Calendar integers | 4 | `hour`, `day_of_week`, `day_of_year`, `month` | raw ordinals alongside the cyclical pair |
| Spatial | 2 | `neighbour_pm25_lag1h`, `neighbour_diff` | pollution advects between nearby cities |
| Horizon | 1 | `horizon` | makes one model serve 1/6/12/24 h |

Derived physical features worth naming: `ventilation_index`
(wind speed × boundary-layer height — the atmosphere's capacity to
disperse pollution) and `log_ventilation`, which together encode the
winter-inversion mechanism directly rather than making the model
rediscover it.

### 3.2 Leakage prevention

The single highest-risk area in a time-series project, so it is
enforced by tests rather than by care:

- Every lag and rolling window is computed **per city**, after sorting
  by timestamp, so no city borrows another's history.
- Rolling windows are **trailing only** — never centred.
- The target is the value at `t + horizon`; all features are known at
  or before `t`.
- Splits are **chronological**, never random. A random split over
  autocorrelated hourly data leaks the answer directly.

Two tests guard this: one asserts no feature equals the label, and one
fails if *any* feature correlates with the label above 0.999. A leaking
model scores brilliantly and forecasts nothing.

### 3.3 Feature store

Feast, in `feature_store/feature_repo/`. Entity `city_id`; offline
source the Parquet feature table; online store SQLite for the demo.
Demonstrated as `feast apply` → `feast materialize` →
`get_online_features()`.

---

## 4. Model

### 4.1 Choice and configuration

**XGBoost**, `configs/model_params.yaml`:

| Parameter | Value | Reason |
|---|---|---|
| `objective` | `reg:absoluteerror` | the target is strongly right-skewed; squared error lets the thin upper tail dominate and drags predictions up for the ordinary hours that are most of the data |
| `max_depth` | 8 | |
| `learning_rate` | 0.05 | |
| `n_estimators` | 400 | the value the deployed artefact was actually trained with |
| `early_stopping_rounds` | 50 | makes `n_estimators` an upper bound |
| `subsample` / `colsample_bytree` | 0.8 / 0.8 | |
| `min_child_weight` | 5 | |
| `random_state` | 42 | reproducibility |

Gradient-boosted trees rather than a deep sequence model because the
signal is dominated by tabular interactions between lags and weather,
the dataset is 11 M rows wide and shallow in time per city, and a
tree ensemble trains in half an hour on a laptop — which is what the
team actually has.

### 4.2 Splits

Chronological, from `configs/model_params.yaml`:

| Split | Rows | Period |
|---|---|---|
| Train | 7,533,564 | → 2025-05-31 |
| Validation | 1,479,168 | 2025-06-01 → 2025-12-31 |
| Test | 2,264,040 | 2025-12-31 → |

The test set is the most recent period, so the reported error is the
error on data the model could not have seen — the same situation it
faces in production.

---

## 5. Results

Source: `reports/train_metrics.json` and
`models/production/metadata.json`.

| Metric | Value |
|---|---|
| **Test MAE** | **8.25 µg/m³** |
| Test RMSE | 15.34 |
| Test R² | 0.800 |
| Validation MAE | 7.57 |
| Persistence baseline MAE | 14.04 |
| **Improvement over baseline** | **+41.3%** |
| Training time | 2181 s (36 min, laptop CPU) |

### 5.1 Error grows with horizon

| Horizon | MAE (µg/m³) |
|---|---|
| +1 h | **2.63** |
| +6 h | 9.25 |
| +12 h | 10.39 |
| +24 h | **10.73** |

The 24-hour error is ~4× the 1-hour error, which is the honest shape of
this problem: persistence carries the first hour almost entirely, and
beyond that the model is working. Even at +24 h it beats persistence
(10.73 vs 14.04).

### 5.2 Baselines

Every training run evaluates a persistence baseline on its own test
split and logs it as `baseline_mae`, so "we beat the baseline" is
re-checked on every run rather than asserted once.

| Model | Test MAE |
|---|---|
| **XGBoost (production)** | **8.25** |
| Persistence (tomorrow = today) | 14.04 |
| Rolling mean | 11.01 |
| Seasonal naive (same hour yesterday) | 13.69 |

*(Rolling-mean and seasonal-naive figures come from a run on an earlier
dataset cohort — see 6.2 — so they are indicative, not directly
comparable. Re-running them on the versioned dataset is **OPEN**,
owner Ifraz.)*

### 5.3 Quality gate

A model is not deployable just because it trained.
`src/models/evaluate.check_quality_gate` requires:

- test MAE ≤ 25.0 µg/m³
- ≥ 15% improvement over the persistence baseline
- ≥ 2% improvement over the model currently in production

The production model passes (`quality_gate_passed: true`). The gate is
demonstrated *failing* by `./scripts/demo_quality_gate.sh`, which
trains a deliberately crippled model (1 tree, depth 1) and shows it
being refused and left unregistered.

`registry.promote_to_production` is deliberately the **only** path to
Production, so the Airflow DAG, the Kubeflow pipeline and the CLI all
pass through the same gate and it cannot be bypassed by using a
different entry point.

---

## 6. MLOps

### 6.1 Reproducible pipeline

`dvc.yaml` defines five stages:

```
cities → ingest → validate → features → train
```

Each declares its dependencies, parameters and outputs, so DVC re-runs
only what actually changed: editing `preprocessing.py` rebuilds
features and retrains but does **not** re-download the data.

```bash
dvc repro      # reproduce everything stale
dvc dag        # print the dependency graph
dvc metrics show
```

> **Operational note.** `dvc repro -f <stage>` forces the whole
> upstream chain, not just the named stage — it will delete the raw
> dataset and restart the download. Use
> `dvc repro --single-item --force <stage>` to force exactly one.

### 6.2 Experiment tracking, and the comparability problem

All runs go to one MLflow server on DagsHub, experiment
`pm25-forecasting`. `src/models/tracking.py` is the only module that
talks to MLflow, so tag and metric names are identical across all
three members by construction rather than by remembering.

Every run carries `member`, `model_family`, `git_commit`, `git_dirty`,
`train_end`, `val_end`, and `dataset_version` — the DVC md5 of the
feature table it trained on. That last tag is what makes "we compared
these fairly" a checkable claim.

**A real defect this caught.** Two XGBoost runs exist from before DVC
was initialised:

| Run | Test MAE | Test R² |
|---|---|---|
| `xgboost-d8-lr0.05-n400` | 8.25 | 0.800 |
| `xgboost-d8-lr0.05-n600` | **6.80** | **0.696** |

The second has the *better* MAE and the *worse* R². That combination is
impossible for two models scored on the same test set — it is the
fingerprint of two different datasets. The `n600` run predates the
current feature table.

Because those runs recorded no dataset hash, they are grouped instead
by `dataset_cohort`, tagged with their `baseline_mae` — the error of a
persistence forecast on the run's own test split, which depends only on
the data. Runs that agree on it to the full float saw the same split.
This cleanly separates the two groups:

| Cohort (`baseline_mae`) | Runs |
|---|---|
| `14.040491370530798` | `xgboost-n400`, `baseline-persistence` |
| `10.775194832819201` | `xgboost-n600`, `baseline-rolling_mean`, `baseline-seasonal_naive`, `baseline-persistence` |

[`notebooks/02_model_comparison.ipynb`](notebooks/02_model_comparison.ipynb)
performs this check **before** it ranks anything, and refuses to
present a cross-cohort ranking. The stale runs are kept rather than
deleted because the discrepancy is the clearest available demonstration
of why the dataset needed versioning.

**OPEN — run count.** The specification expects 50+ runs on the shared
server; there are currently 7. The infrastructure is shared and
documented in `Documents/TEAM_SETUP.md`; LightGBM (Mudassar) and the
remaining baselines (Ifraz) are not yet run on the versioned dataset.

### 6.3 Model registry and governance

```
run → registered version → Staging → [quality gate] → [human approval] → Production
```

Registered model `pm25-forecaster`. Only runs that pass the gate are
registered at all. Promotion to Production records `approved_by` and
`promoted_at` as version tags, so the audit trail answers "who
deployed this, and when".

Current state, verified against the live server:

| | |
|---|---|
| Version | **1** |
| Stage | **Production** |
| Run | `49cf5b28` |
| `approved_by` | `hassan` |
| `dataset_version` | `b3dce04aad6b7bb9d829a9ffd94edce2` |
| Served by the API | `/model-info` reports v1 / Production / `49cf5b28`, 100 features |

**Two defects this promotion exposed, both fixed.** Worth recording
because both were invisible to a passing test suite:

1. `set_model_version_tag` was called with an *int* version. MLflow's
   REST store puts it into a protobuf string field, which raises
   `TypeError: bad argument type for built-in operation` -- but only
   against a real server, and only *after* the stage transition had
   already succeeded. The model reached Production with **no
   `approved_by` tag**: the governance record silently missing on the
   one operation that most needs it. Our tests stub the MLflow client
   and the stub coerced the version with `str()`, so it was strictly
   more forgiving than the real thing. The stub now preserves the type
   and a test asserts it.
2. `export_production` copied the registry artefacts (`model.xgb`,
   `MLmodel`) and rewrote `metadata.json`, but the offline serving path
   loads `model.pkl` -- which MLflow never writes. An export therefore
   left the *previous* version's `model.pkl` in place beside the new
   version's metadata, so `/model-info` advertised the new model while
   predictions came from the old weights. The exported metadata also
   dropped `feature_names`, which `ModelLoader.predict` uses to check
   and reorder columns; without it that guard is skipped, and a
   gradient-boosted model consumes columns positionally, so a
   differently-ordered frame would yield confident nonsense rather than
   an error. Export now syncs the pickle from the candidate matching
   the version's `run_id`, carries `feature_names`, and deletes a stale
   pickle it cannot replace rather than letting it be served. Four
   tests cover it.

`registry.rollback()` returns the most recently archived version to
Production in seconds; `./scripts/rollback.sh` demonstrates it against
a running API.

### 6.4 Orchestration

| Tool | Location | Role |
|---|---|---|
| Airflow | `pipelines/airflow/dags/` | `hourly_ingest`, `ml_orchestrator`, `retraining` — scheduling, retries, logging |
| Kubeflow | `pipelines/kubeflow/` | `pipeline_definition.py` → `compiled_pipeline.yaml`; each ML step in its own container |

### 6.5 Serving

Flask + Gunicorn, `src/serving/app.py`. Endpoints: `/health`,
`/model-info`, `/predict`, `/api/forecast`, `/api/stats`,
`/api/city/<id>`, `/metrics`. BentoML service in
`src/serving/bentoml_service.py`.

A **degradation ladder** rather than a hard failure: `warming` →
`live` → `stale_cache` → `historical` → `none` (503). The dashboard
labels every value with its source, so a stale number is never shown as
a fresh one.

One detail worth recording, because it produced a false alarm:
`/health` only reads `store.status()` and never triggers a fetch, so on
a cold process the source was `none` and the dashboard rendered
*"Neither the upstream feed nor the local dataset is available"* — true
of the cache, alarming, and misleading. A `warming` state now
distinguishes "no fetch has been attempted yet" from "the fetch
failed".

### 6.6 Containers, Kubernetes, monitoring

- `docker/Dockerfile.api`, `docker-compose.yml`
- `k8s/`: deployment, service, HPA, PodDisruptionBudget, NetworkPolicy,
  ConfigMap, namespace
- Prometheus metrics including `airwatch_predicted_pm25_ugm3`, a
  distribution that doubles as an early drift signal
- Grafana dashboard in `monitoring/grafana/dashboards/airwatch.json`
- Evidently + PSI drift detection in `src/monitoring/drift.py`

### 6.7 Drift detection — and a defect in our own threshold

[`notebooks/03_drift_and_monitoring.ipynb`](notebooks/03_drift_and_monitoring.ipynb)
runs three cases: a control (two adjacent weeks), a real seasonal shift
(90 days vs the last fortnight), and a simulated smog event.

Ranked by features exceeding PSI 0.25, they separate exactly as they
should — control **1/8**, seasonal **2/8**, simulated event **6/8** —
and *diagnosably*: the seasonal case moved the **weather**
(`temperature_2m` PSI 1.65), the simulated case moved the
**pollutants** (`pm2_5` PSI 2.37).

**OPEN — the retrain flag is wired to the wrong number.**
`run_drift_check` sets `retrain_recommended` from `drift_share`, which
is Evidently's count of statistically significant columns. At these
sample sizes a Kolmogorov–Smirnov test rejects the null on differences
far too small to matter, so the share saturates at 100% — it reports
`1.00` even for the control, and `0.75` for the simulated event, making
the control look *worse*. The PSI values are sound; the boolean on top
of them is not. The fix is to threshold on PSI. Owner: Ifraz.

This is recorded rather than quietly patched because changing detector
behaviour belongs in `src/monitoring/drift.py` with tests, not as a
side effect of writing a report.

### 6.8 Testing and CI

| | |
|---|---|
| Tests | **259 passing** |
| Coverage | **71.68%** (gate: 70%) |
| CI | `.github/workflows/ci.yml` |

CI runs `ruff check src tests pipelines`, `ruff format --check`,
`pytest` with the coverage gate, `pip-audit`, ESLint at
`--max-warnings 0`, and the Vite production build. Six test categories:
unit, data, model, API, integration, regression.

### 6.9 Security

- No secrets in git. `.env` is gitignored; `.env.example` carries names
  and instructions only.
- DVC credentials live in `.dvc/config.local`, which is gitignored.
  The committed `.dvc/config` holds only the bucket and endpoint URL.
- Verified by scanning every file in each commit against the actual
  values in `.env` before committing.
- `pip-audit` runs in CI.
- `k8s/networkpolicy.yaml` restricts pod traffic;
  `k8s/secret.example.yaml` carries placeholders only.

---

## 7. Frontend

React 18 + Vite. Leaflet map of all 134 cities coloured by EPA band,
Plotly analytics, and a continuously scrolling city ticker.

Two cartographic decisions worth recording:

- The national outline is built by `scripts/build_pakistan_boundary.py`
  from Natural Earth 10m data (public domain), dissolving Pakistan,
  Azad Kashmir, Gilgit-Baltistan, Jammu & Kashmir and the Siachen
  Glacier into **one** polygon with `unary_union`. Verified: one
  mainland polygon, **zero interior holes**. Siachen is included
  specifically because omitting it punches a hole between
  Gilgit-Baltistan and J&K. Aksai Chin and the Shaksam Valley are
  excluded as Chinese-administered. Indian Occupied Kashmir is labelled
  and unshaded, inside the national border, per the official map
  published by the Government of Pakistan.
- Band colours come from one source of truth shared with the API
  (`src/serving/aqi.legend()`), so the map legend and the JSON response
  cannot drift apart. Text colour on each band chip is chosen by
  measured WCAG contrast rather than by eye — necessary because
  "Moderate" yellow gives 1.89:1 against white while "Hazardous"
  maroon gives 1.70:1 against dark, so no single fixed rule is readable
  in both themes.

---

## 8. Limitations

1. **The target is a reanalysis product and reads ~12.5 µg/m³ low**
   against reference instruments (section 2.3). This dominates total
   error.
2. **84 of 134 cities have training history** (section 2.2).
3. **Ground truth is sparse.** 493 OpenAQ stations match 61 cities, but
   only 2 are reference-grade and they stopped reporting in March 2025.
4. **3.3 years of history**, not 12 — the free archive begins
   2022-08-05.
5. **Coarse spatial resolution.** One grid extraction per city; not to
   be read as street-level.
6. **Uneven accuracy.** Error is lowest in well-observed Punjab cities
   and highest in Balochistan and Gilgit-Baltistan — exactly where
   people already have the least information.
7. **Non-commercial only** while on the free Open-Meteo tier.

---

## 9. Status against the acceptance criteria

| Criterion | Status |
|---|---|
| Model trains via a reproducible pipeline (`dvc repro`) | ✅ 5 stages, `dvc.lock` committed |
| Data + code versions recoverable | ✅ verified by `scripts/demo_dvc_rollback.sh` |
| Experiments in MLflow | ✅ shared DagsHub server (**OPEN:** 7 runs, 50+ expected) |
| Tests run in GitHub Actions | ✅ 259 tests, 72% coverage, gate enforced |
| A failing quality gate blocks deployment | ✅ `scripts/demo_quality_gate.sh` |
| Model served by Flask in Docker | ✅ |
| Kubernetes deployment + scaling | ✅ manifests + HPA (**OPEN:** cluster demo) |
| Airflow + Kubeflow shown | ✅ DAGs + compiled pipeline |
| Monitoring, alert, retraining trigger, promotion, rollback | ✅ (**OPEN:** drift threshold defect, 6.7) |
| **Deployed on a cloud host, serving a real prediction** | ❌ **OPEN** |
| A stranger can follow the README and reproduce it | ✅ |

### Open items

| # | Item | Owner |
|---|---|---|
| 1 | Public deployment. Intended target is **Oracle Cloud Always Free** as an approved equivalent to AWS — needs the teacher's written sign-off first (`SIMPLE_ROADMAP.md` step 17) | all three |
| 2 | LightGBM / RandomForest runs on the versioned dataset | Mudassar |
| 3 | Baselines re-run on the versioned dataset | Ifraz |
| 4 | Fix `retrain_recommended` to threshold on PSI (section 6.7) | Ifraz |
| 5 | Complete the backfill to all 134 cities (`dvc repro`) | Hassan |

---

## 10. Division of work

| Member | Owns |
|---|---|
| **Hassan** | data pipeline, feature engineering, XGBoost, Flask API, React dashboard, DVC + MLflow infrastructure |
| **Mudassar** | Airflow, Kubeflow, tests, CI/CD, LightGBM / RandomForest / HistGradientBoosting |
| **Ifraz** | Docker, Kubernetes, monitoring, drift detection, baseline models |

All three are expected to be able to explain any part of the system.

---

## 11. Attribution

- Weather and air quality: [Open-Meteo](https://open-meteo.com/)
  (CC BY 4.0), incorporating Copernicus Atmosphere Monitoring Service
  and ERA5 data
- Ground truth: [OpenAQ](https://openaq.org/) (CC BY 4.0)
- City coordinates, elevation, population:
  [GeoNames](https://www.geonames.org/) (CC BY 4.0)
- National boundary geometry:
  [Natural Earth](https://www.naturalearthdata.com/) (public domain)
- AQI breakpoints: US EPA, 2024 PM2.5 revision

**This is an academic project, not an official public-health warning
system.** Most displayed values are modelled estimates rather than
sensor readings, and every value in the API response is labelled with
its source.
