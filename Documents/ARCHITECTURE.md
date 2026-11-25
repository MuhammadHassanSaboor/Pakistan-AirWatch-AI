# Architecture

How the system is put together, and why each boundary sits where it
does. For the day-to-day commands see [WORKFLOW.md](WORKFLOW.md).

---

## 1. System diagram

```
┌─────────────────────────── DATA SOURCES (free, no key) ───────────────────────┐
│  Open-Meteo Air Quality API      pollutants, hourly, 2022-08-05 → now         │
│  Open-Meteo Archive API (ERA5)   weather, hourly                              │
│  Open-Meteo Forecast API         live + 3 days ahead  (serving path)          │
│  OpenAQ v3                       OPTIONAL ground truth — currently unavailable│
└────────────────────────────────────┬──────────────────────────────────────────┘
                                     │  batched · resumable · quota-aware
                                     ▼
                        src/data/ingestion.py
                        data/raw/chunks/<city>__<from>__<to>.parquet
                                     │  combine + schema-normalise + clamp
                                     ▼
                        data/raw/airquality_hourly.parquet  ──► DVC ──► DagsHub
                                     │
                                     ▼
                        src/data/validation.py
                        Pandera schema + 7 quality rules
                                     │
                           FAIL ◄────┴────► PASS
                      pipeline halts           │
                                               ▼
                        src/features/preprocessing.py
                        lags · rolling · calendar · weather · spatial
                                               │
                                               ▼
                        data/processed/features.parquet (100 features)
                                               │
                        ┌──────────────────────┴──────────────────────┐
                        ▼                                             ▼
          feature_store/ (Feast)                           src/features/splits.py
          offline (parquet) ─materialize─► online (SQLite)  train / val / test
                        │                                             │
                        └──────────────────┬──────────────────────────┘
                                           ▼
            ┌──────────────── TRAINING ─────────────────┐
            │  Ifraz: baselines   Hassan: XGBoost       │
            │  Mudassar: LightGBM / RandomForest        │
            │  all → ONE MLflow experiment, same split  │
            └─────────────────────┬─────────────────────┘
                                  ▼
                        src/models/evaluate.py
                        ══ QUALITY GATE ══
                MAE ≤ 25  AND  ≥15% better than persistence
                AND ≥2% better than the DEPLOYED model
                                  │
                    FAIL ◄────────┴────────► PASS
              not registered                 │
                                             ▼
                        MLflow Model Registry
                   None → Staging → [human] → Production
                                             │
        ┌────────────── SERVING ─────────────┴──────────────┐
        │  Flask + Gunicorn (Docker, non-root, read-only)   │
        │    GET  /health        GET  /model-info           │
        │    POST /predict       GET  /metrics              │
        │    GET  /api/{cities,forecast,history,legend,stats}│
        │                       │                           │
        │  LiveFeatureStore ────┘  (Open-Meteo, 55 min TTL) │
        │    └─ imports src/features/preprocessing ─────────┤  ← no skew
        └──────────────────────┬────────────────────────────┘
                               │
            ┌──────────────────┼──────────────────┐
            ▼                  ▼                  ▼
   React dashboard     Prometheus → Grafana   Evidently drift
   Leaflet + Plotly    7 alert rules          + PSI fallback
                               │                  │
                               └────────┬─────────┘
                                        ▼
                        Airflow retraining_dag
                 drift → retrain → gate → approval → promote
                            → smoke test → rollback on failure
```

---

## 2. Why the boundaries are where they are

### The serving layer imports the training feature code

`src/serving/live_features.py` calls the same functions from
`src/features/preprocessing.py` that the training pipeline calls. It
does not reimplement them.

This is the single most important structural decision in the project.
Training/serving skew — where `pm2_5_lag_24h` means something slightly
different in production than it did in training — is invisible in every
metric. Latency is fine, the API returns 200, and the predictions are
quietly wrong. Sharing the implementation makes the failure impossible
rather than merely unlikely, and
`tests/test_pipeline.py::test_serving_features_match_training_features`
fails if the serving path can no longer produce a training feature.

### The browser never talks to Open-Meteo

Every request goes to our Flask API. If the map called Open-Meteo
directly, each pan would consume upstream quota, there would be no
shared cache, and the rate limit would be exhausted in minutes. Our API
caches the upstream response for 55 minutes, which matches the hourly
update cadence of the data.

### One global model, not 134

City identity enters through `latitude`, `longitude`, `elevation_m` and
`log_population` — continuous features, not a categorical. Two
consequences:

1. Cities share statistical strength. A smog pattern learned in Lahore
   informs Faisalabad.
2. **The model generalises to cities it never trained on.** This is why
   the dashboard can serve all 134 cities while the training set
   currently covers 84: there is no per-city parameter to be missing.

### `horizon` is a feature, not four models

One model serves +1h, +6h, +12h and +24h. The alternative — four
models — quadruples the registry, the promotion decisions and the
rollback surface, for no accuracy gain over including lead time as an
input.

### Feast sources are at observation grain

The supervised table carries four rows per city-hour, one per horizon.
Feast requires one row per `(entity, event_timestamp)`; duplicate keys
make a point-in-time join return *nothing*, silently.
`feature_store/materialize.py --prepare` therefore projects the
supervised table back down to the observation grain. Horizon expansion
is a training concern, not a feature-store concern.

---

## 3. Components

### Data acquisition — `src/data/`

| Module | Responsibility |
|---|---|
| `cities.py` | the 134-city reference table, embedded and validated |
| `openmeteo.py` | HTTP client: retries, batching, quota-aware 429 handling |
| `ingestion.py` | resumable backfill, chunk assembly, schema normalisation |
| `validation.py` | Pandera schema + quality rules |

**Batching.** Open-Meteo accepts comma-separated coordinates, so 12
cities fetch in one request. That turns ~1,300 requests into ~216.

**Quota awareness.** Open-Meteo enforces separate per-minute, per-hour
and per-day limits and names which one was hit in the 429 body.
`_rate_limit_wait()` parses that and waits for the correct window —
retrying an hourly limit every 65 seconds just burns the retry budget.

### Feature engineering — `src/features/`

100 features in five families:

| Family | Examples | Leakage status |
|---|---|---|
| Lags | `pm2_5_lag_{1,2,3,6,12,24,48,72,168}h` | past only |
| Rolling | mean/std/max/min over 3–72 h, on `shift(1)` | past only |
| Calendar | hour/month sin-cos, `is_smog_season`, `is_burning_window` | known in advance |
| Weather | temperature, humidity, wind u/v, `ventilation_index` | forecast, legitimately future |
| Spatial | `neighbour_pm25_lag1h` from the 3 nearest cities | past only |

`ventilation_index = wind_speed × boundary_layer_height` is the
strongest physical predictor: it measures how fast the atmosphere can
disperse pollution.

### Training — `src/models/`

`train_base.py` holds the entire harness — loading, splitting,
evaluation, MLflow logging, plots, gate, artifacts. A member's training
script supplies only an estimator factory. That is what makes three
people's numbers comparable rather than three incompatible reports.

### Serving — `src/serving/`

| Module | Responsibility |
|---|---|
| `app.py` | Flask routes, Prometheus metrics, error handling |
| `model_loader.py` | loads from the registry or disk; never raises at import |
| `live_features.py` | cached upstream fetch + shared feature code |
| `schemas.py` | request validation |
| `aqi.py` | US EPA PM2.5 → AQI conversion |

`ModelLoader` degrades rather than crashing: with no model the service
still starts, `/health` reports `degraded` **with the reason**, and
`/predict` returns 503. A crash-looping container cannot tell a monitor
*why* it is unhealthy.

---

## 4. Data model

### Entity
`city_id` — a stable slug (`lahore`, `dera_ghazi_khan`), the join key
everywhere.

### Grain
| Table | Grain |
|---|---|
| `airquality_hourly.parquet` | one row per (city, hour) |
| `feast_features.parquet` | one row per (city, hour) |
| `features.parquet` | one row per (city, hour, horizon) |

### Prediction record
Every prediction carries `city_id`, `horizon`, `base_time`,
`valid_time`, `generated_at`, `model_version`, `unit`, AQI fields and
**`source`**. The `source` field is not decoration: it is how the UI
distinguishes a model output from a provider forecast from a sensor
reading, which the specification requires and which honesty requires.

---

## 5. Chronological splitting

```
2022-08-05 ──────── train ──────── 2025-05-31
2025-06-01 ──────── val   ──────── 2025-12-31
2026-01-01 ──────── test  ──────── today
```

Never random. A random split lets the model see 15:00 while predicting
14:00 of the same day, which leaks the answer through the lag features
and produces a model that scores beautifully and forecasts nothing.

The test window deliberately contains a complete smog season
(Oct 2026 – now) plus January 2026, so the headline metric is measured
on the hardest conditions rather than on easy summer air.

---

## 6. Security

| Concern | Control |
|---|---|
| Secrets in a public repo | `.gitignore`, `gitleaks` in pre-commit **and** CI, a `no-env-file` hook, CI assertion that `.env.example` holds no credential-shaped strings |
| Credential sharing | each member generates their own DagsHub token |
| Container | non-root uid 1000, read-only root filesystem, dropped capabilities, `no-new-privileges` |
| Image | Trivy scan in CI; slim `requirements-api.txt` keeps Airflow/Kubeflow out of the serving image |
| Dependencies | `pip-audit` in CI |
| API input | type/range/length validation; ≤200 cities per request; 1 MB body cap |
| Logging | request id and timing only — **never** request bodies |
| Network | Kubernetes NetworkPolicy: ingress on 5000 only, egress to DNS and 443 only |
| Kubernetes secrets | created imperatively; only a `secret.example.yaml` template is committed |

---

## 7. Deliberate trade-offs

| Choice | Alternative | Why |
|---|---|---|
| SQLite online store | Redis | Free, zero infra; Redis is the documented production upgrade |
| NodePort service | LoadBalancer | A cloud LB is billable; the trade-off is documented |
| Minikube | managed Kubernetes | EKS costs ~$73/month for the control plane alone |
| `plotly.js-basic` | full Plotly | We use scatter/bar/histogram only — 4.7 MB → 1.1 MB |
| Reanalysis target | sensor ground truth | No ground truth is available to us; stated as the primary limitation |
| 10 weather variables | 12 | The 11th doubles every request's quota cost; the two dropped are derivable |

---

## 8. Failure modes and responses

| Failure | Detection | Response |
|---|---|---|
| Upstream API down | `airwatch_upstream_data_age_seconds` | `StaleUpstreamData` alert; cached predictions continue |
| Upstream quota exhausted | 429 body names the window | Wait for that window; backfill resumes automatically |
| Model fails to load | `/health` 503 with reason | `ModelNotLoaded` alert; roll back |
| Bad model promoted | smoke test compares served version | Automatic rollback task in the retraining DAG |
| Input drift | Evidently / PSI > 30% | Retraining DAG branches to retrain |
| Schema change upstream | Pandera validation | Non-retryable task failure; pipeline halts before training |
| Bad data reaches training | — | Cannot: validation gates the feature stage |
