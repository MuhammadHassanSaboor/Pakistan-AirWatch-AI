# Risk Assessment, Ethics and Limitations

Required by §3.13 of the course specification. Eight project-specific
risks, each with the mitigation actually implemented in the codebase —
not a generic list.

---

## 1. Risk register

### R1 — No independent ground truth (**realised**)

| | |
|---|---|
| Likelihood | **Certain — this has already happened** |
| Impact | High |
| Status | Accepted and disclosed |

OpenAQ registration did not complete: the verification email never
arrived after two attempts. We therefore have no sensor measurements
to validate against, and our training target is CAMS *reanalysis*
PM2.5 — a model product.

**What this means:** we measure how well our model forecasts the
reanalysis, not how well it forecasts reality as measured on the
ground. A model that matched the reanalysis perfectly would still
inherit every bias the reanalysis has.

**Mitigations implemented**
- OpenAQ is an *optional* source: leave `OPENAQ_API_KEY` blank and the
  pipeline skips it cleanly (`settings.openaq_enabled`)
- The limitation is stated in the README, this document, the API
  response (`disclaimer` field) and permanently in the dashboard header
- Every value carries a `source` label distinguishing
  `model_prediction` from `provider_forecast` from `ground_station`
- If a key arrives later: set it in `.env`, flip
  `openaq.enabled: true`, and use it for **validation only** — Pakistan
  has monitors in roughly four cities, far too sparse and too
  urban-biased to train on

**Why this is still defensible:** every operational weather and
air-quality forecasting system trains on reanalysis, because it is the
only source with complete spatial coverage. The error is not using
reanalysis; the error would be pretending it is sensor data.

---

### R2 — Free-tier API quota limits data collection (**realised**)

| | |
|---|---|
| Likelihood | **Certain — hit the daily limit on day one** |
| Impact | Medium |
| Status | Managed |

Open-Meteo prices requests by `locations × ceil(variables/10) ×
ceil(days/14)` and enforces per-minute, per-hour and per-day quotas. A
full 134-city backfill exceeds one day's allowance.

**Mitigations implemented**
- Fully **resumable** ingestion: one parquet per (city, 6-month
  window); re-running skips what exists, so an interrupted multi-hour
  download costs nothing
- **Quota-aware waiting**: `_rate_limit_wait()` parses which window the
  429 refers to and waits for *that* window. Retrying an hourly limit
  every 65 s merely exhausts the retry budget
- **Batched requests**: 12 cities per call, ~1,300 requests → ~216
- **Variable trimming**: weather cut from 12 to 10 variables, halving
  the cost of every weather request. The 11th variable doubles the
  price because the formula rounds up
- `max_retries: 8` so a run survives several quota windows unattended

**Residual:** the backfill completes across more than one day. Resume
with a single command; no manual bookkeeping.

---

### R3 — Feature leakage producing a worthless model

| | |
|---|---|
| Likelihood | High without controls |
| Impact | **Critical** |
| Status | Controlled |

Using PM2.5 at `t+h` to predict `t+h` yields R² ≈ 0.99 and a model that
cannot forecast anything. The failure is invisible in every metric —
it looks like success.

**Mitigations implemented**
- All lags computed with `groupby(city_id).shift(lag)`; rolling windows
  on `shift(1)` so the current hour never enters its own average
- Spatial neighbour features use `pm2_5_lag_1h`, never current values
- Weather may legitimately use `t+h` (a forecast genuinely exists);
  pollutants never may
- **Four automated tests**, including a correlation sweep that fails
  if *any* feature correlates with the label above 0.999
- Tests assert lags do not cross city boundaries and that the first
  rows of each city's series are NaN

---

### R4 — Model degrades during smog season

| | |
|---|---|
| Likelihood | High |
| Impact | Medium |
| Status | Controlled |

Pakistani PM2.5 is strongly seasonal. October–January in Punjab
involves crop-residue burning and temperature inversions that push
values far outside summer distributions. A model trained mostly on
summer data drifts every autumn.

**Mitigations implemented**
- Explicit seasonal features: `is_smog_season`, `is_burning_window`,
  cyclical month encoding
- The **test split deliberately contains a full smog season**, so the
  headline metric is measured on the hard case
- Evidently drift monitoring with a PSI fallback; >30% drifted features
  triggers retraining
- Per-month and per-province error breakdown logged with every run
- `PredictionDistributionShift` Prometheus alert

---

### R5 — An automated pipeline deploys a worse model

| | |
|---|---|
| Likelihood | Medium |
| Impact | High |
| Status | Controlled |

Scheduled retraining that promotes whatever it produces will eventually
ship a regression.

**Mitigations implemented**
- A three-part quality gate: absolute MAE ≤ 25, ≥15% better than
  persistence, **and ≥2% better than the currently deployed model**
- `promote_to_production()` is the only path to Production and re-runs
  the gate internally — no entry point can bypass it
- A **human approval task** in the retraining DAG that must be cleared
  explicitly
- Post-deployment smoke test verifies the API is actually serving the
  promoted version
- Automatic rollback task triggered by `one_failed`
- `scripts/demo_quality_gate.sh` demonstrates rejection on demand

---

### R6 — Secrets leaked in a public repository

| | |
|---|---|
| Likelihood | Medium |
| Impact | High |
| Status | Controlled |

This repository is public. One committed token is a real incident.

**Mitigations implemented**
- `.env` gitignored; only `.env.example` with placeholders is committed
- `gitleaks` in pre-commit **and** in CI
- A `no-env-file` pre-commit hook blocking `.env` by filename
- A `no-data-files` hook blocking parquet/pkl/csv from Git
- CI asserts `.env.example` contains no credential-shaped strings
- `/model-info` is covered by a test asserting it never leaks
  "password", "token", "secret" or a connection string
- Each member uses their **own** DagsHub token
- Kubernetes secrets created imperatively; only a template is committed

**Response if it happens:** revoke the token first (DagsHub → Settings
→ Tokens → delete), then clean history. The value is public the moment
it is pushed; rotation is what matters.

---

### R7 — Upstream source changes or disappears

| | |
|---|---|
| Likelihood | Low |
| Impact | High |
| Status | Partially controlled |

The entire project depends on one free, non-commercial API.

**Mitigations implemented**
- Every response cached locally in versioned parquet; the historical
  dataset survives any upstream change
- Pandera validation detects a schema change immediately and halts the
  pipeline **before** training rather than after
- Source access is isolated in `src/data/openmeteo.py`, so a
  replacement provider is one module
- `StaleUpstreamData` alert fires when the cache exceeds 3 hours

**Residual:** a permanent Open-Meteo shutdown would require a new
source. Candidates: CAMS directly via Copernicus (free, registration
required), NASA MERRA-2.

---

### R8 — A teammate is blocked by another's incomplete work

| | |
|---|---|
| Likelihood | Medium |
| Impact | Medium |
| Status | Controlled |

**Mitigations implemented**
- Interfaces fixed in `configs/*.yaml` before implementation
- Synthetic fixtures in `tests/conftest.py` let every module be
  developed and tested with no network, no DVC pull and no MLflow
- `train_base.py` means a member only writes an estimator factory
- `ModelLoader` runs without a model; the API still starts
- The frontend renders a useful error state when the API is down

---

## 2. Ethics

### 2.1 This is not a public-health service

Stated permanently in the dashboard header (non-dismissible), the
footer, the API response payload and the README. No medical advice is
given. AQI health advisory text is quoted from the US EPA scale with
the standard named, rather than written by us.

### 2.2 Geographic bias — the most serious ethical issue

Model accuracy is not uniform. It is best where the atmosphere is
well-observed and the training data is dense — large Punjab cities —
and worst in Balochistan and Gilgit-Baltistan.

**That is exactly where people currently have the least air-quality
information.** A system that is most confident where information is
already abundant, and least reliable where it is scarce, can widen an
information gap rather than close it.

**What we do about it**
- Per-province error is computed and reported for every model run
- All seven administrative units are represented in the city list,
  including Gwadar, Skardu, Chitral and Dalbandin — not just Punjab
- The report states per-region error explicitly rather than quoting a
  single national number
- We do not rank districts "most polluted to least" without stating
  coverage, because a ranking built on uneven data manufactures
  authority it has not earned

### 2.3 Provenance must be visible

Three different kinds of number appear in this system:

| Source | What it is |
|---|---|
| `ground_station` | a physical sensor reading |
| `provider_forecast` | Open-Meteo's own forward projection |
| `model_prediction` | our model's output |

They are styled differently in the UI, labelled in every API response,
and plotted as separate series in the city chart. Presenting them
identically would be the most misleading thing this project could do.

### 2.4 Privacy

**No personal data is collected, processed or stored.** The system
handles geographic coordinates of cities and atmospheric measurements.
There are no users to profile. Request logs contain a request id,
method, path, status and duration — never request bodies.

### 2.5 Explainability

Feature importance is logged as an artifact with every run. The model's
reasoning is physically interpretable: high predictions follow low
`ventilation_index` (stagnant air, shallow mixing layer), high recent
lags, and smog-season flags. That is a mechanism a non-specialist can
follow, not a black box.

### 2.6 Licensing

All sources are CC BY 4.0 or equivalent and are attributed in the
README, the API payload and the dashboard footer. The free Open-Meteo
tier is **non-commercial**, so the project must remain non-commercial.

### 2.7 Uncertainty

A point forecast without an error bar is a false promise. `/model-info`
exposes the model's test MAE so a client can present the expected
error, and the per-horizon breakdown (MAE roughly quadruples from +1h
to +24h) shows that a 24-hour forecast is far less certain than a
1-hour one.

---

## 3. Limitations summary

1. The target is a reanalysis product, not a sensor measurement
2. No independent ground-truth validation is available
3. Accuracy varies by region, worst where data is sparsest
4. 3.3 years of history, not the 12 originally proposed
5. Coarse spatial resolution — one grid extraction per city
6. Training coverage is currently 84 cities; the model generalises to
   all 134 because city identity is encoded continuously, but cities
   outside the training set carry additional uncertainty
7. Non-commercial use only while on the free tier
8. Forecast horizon is capped at 24 hours
