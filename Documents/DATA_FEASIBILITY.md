# Data Feasibility Report

**Verified:** 25 November 2026
**Verified by:** Hassan (Data & ML Engineering)
**Method:** direct calls to the live APIs, not documentation

> This document exists because the project proposal assumed 10–15 years
> of hourly air-quality data. That assumption was wrong, and finding
> out on day one instead of in week six changed the project plan. Every
> number below is reproducible with the commands shown.

---

## 1. Headline findings

| Question | Answer |
|---|---|
| How far back does free hourly **air-quality** data go? | **5 August 2022** (~3.3 years) |
| How far back does free hourly **weather** data go? | 1940 (ERA5) — but useless without matching pollution labels |
| Do we need an API key? | **No.** Open-Meteo requires no account |
| How many cities can we cover? | **134**, all 7 administrative units |
| Is the data complete? | **100% non-null PM2.5** across the tested range |
| Can we get real sensor ground truth? | Only for a handful of cities, and OpenAQ registration did not deliver a verification email. **Ground truth is currently unavailable to us.** |

**Consequence:** the project trains on ~3.3 years of hourly data for
134 cities. That is roughly **4.6 million city-hours**, covering **four
smog seasons** (2022‑23, 2023‑24, 2024‑25, 2025‑26). This is ample for
the modelling task, but it is not the 12-year record originally
proposed, and the report must say so.

---

## 2. The trap: the archive accepts old dates and returns nulls

This is the finding that matters most, because it fails silently.

```bash
curl "https://air-quality-api.open-meteo.com/v1/air-quality\
?latitude=31.5204&longitude=74.3587&hourly=pm2_5\
&start_date=2013-01-01&end_date=2013-01-02&timezone=UTC"
```

The request returns **HTTP 200** with a full, well-formed response
containing 48 hourly timestamps — and every `pm2_5` value is `null`.

A pipeline that checks only the status code would happily ingest
thirteen years of nothing.

### Binary search for the real start date

| Date requested | Non-null PM2.5 hours |
|---|---|
| 2013-01-01 | 0 / 24 |
| 2019-01-01 | 0 / 24 |
| 2022-07-01 | 0 / 24 |
| 2022-07-29 | 0 / 24 |
| 2022-08-01 | 0 / 24 |
| 2022-08-02 | 0 / 24 |
| **2022-08-05** | **24 / 24** ✅ |
| 2022-08-15 | 24 / 24 |
| 2023-01-01 | 24 / 24 |
| 2025-01-01 | 24 / 24 |

**Earliest usable date: 2022-08-05.** This is set as
`time.air_quality_start` in `configs/data_config.yaml`, and
`src/data/openmeteo.py` clamps any earlier request to it so no quota
is wasted on empty responses.

Sample values returned for Lahore on 1 January 2025:
`[199.8, 203.0, 206.3, ...]` µg/m³ — realistic smog-season figures.

**Re-verify at any time:**
```bash
python -c "from src.data.openmeteo import probe_earliest_data; print(probe_earliest_data())"
```

---

## 3. Weather data reaches much further back

```bash
curl "https://archive-api.open-meteo.com/v1/archive\
?latitude=31.5204&longitude=74.3587\
&hourly=temperature_2m,relative_humidity_2m,wind_speed_10m,boundary_layer_height\
&start_date=2013-01-01&end_date=2013-01-01&timezone=UTC"
```

Returns 24/24 non-null for every variable in 2013, and ERA5 extends to
1940.

**We deliberately do not use it.** Weather without a matching PM2.5
label cannot train a PM2.5 model. Downloading 1940–2022 weather would
cost API quota and produce rows with no target. The weather start date
is therefore pinned to the air-quality start date.

---

## 4. Rate limits — the real constraint

Open-Meteo prices a request by **content**, not by count:

```
weight ≈ locations × ceil(variables / 10) × ceil(days / 14)
```

This was established empirically:

| Request | Result |
|---|---|
| 10 cities × 1 year × 9 variables | 200 OK, 3.4 s, 5.6 MB |
| 20 cities × 1 year × 9 variables | 200 OK, 5.6 s, 11.2 MB |
| 30 cities × 1 year × 9 variables | **429 — "Minutely API request limit exceeded"** |

Three separate quotas exist, and they report themselves distinctly:

- `"Minutely API request limit exceeded"` → wait ~60 s
- `"Hourly API request limit exceeded"` → wait until the hour rolls over
- `"Daily API request limit exceeded"` → wait until midnight UTC

### Why this mattered

Our first backfill retried the **hourly** limit every 65 seconds. It
burned all four retries inside five minutes, failed the batch, and
appeared to "hang". `src/data/openmeteo.py` now parses the 429 body and
waits for the actual quota window (`_rate_limit_wait`), which lets a
multi-hour national backfill run unattended.

### Two decisions that halved our cost

1. **Weather variables trimmed from 12 to 10.** The formula rounds
   `ceil(variables/10)` up, so the 11th variable *doubles* the price of
   every weather request. `dew_point_2m` and `apparent_temperature`
   were dropped — both are derivable from temperature and humidity,
   which we keep.
2. **Batched requests.** Open-Meteo accepts comma-separated
   coordinates on the archive endpoints and returns one block per
   location. Fetching 12 cities per request reduced a national backfill
   from ~1,300 requests to ~216.

Current settings (`configs/data_config.yaml`):
```yaml
batch_size: 12
chunk_months: 6
sleep_seconds: 3.0
max_retries: 8          # must survive several hourly quota windows
```

---

## 5. Data quality findings

Run on 1,273,536 rows covering 36 cities (partial backfill):

### 5.1 Negative concentrations — artifacts, clamped

| Variable | Negative values | Minimum observed |
|---|---|---|
| ozone | 73 | −10.0 |
| nitrogen_dioxide | 42 | −1.5 |
| dust | 29 | −11.0 |
| sulphur_dioxide | 5 | −0.2 |

CAMS reanalysis occasionally emits small negative concentrations. A
negative mass concentration is physically impossible, so
`combine_chunks()` clamps them to zero **and logs the count** — an
unexplained jump in that number would mean the upstream product
changed.

### 5.2 Extreme values — real, and kept

Our first schema capped `dust` at 5,000 µg/m³ and rejected 81 rows.
Inspection showed they were not corruption:

| city | timestamp | dust | pm10 | pm2_5 |
|---|---|---|---|---|
| nushki | 2024-03-20 00:00 | 10,134 | — | 728.3 |
| nushki | 2024-03-19 23:00 | 10,061 | 3,181 | 633.3 |
| nushki | 2024-03-19 22:00 | 8,478 | 3,129 | 464.7 |

This is a **sustained dust storm over Nushki, Balochistan, 19–23 March
2024**. Those are exactly the extreme events a forecasting system
exists to predict. We widened the bounds (`dust` → 20,000, `pm10` →
6,000) rather than deleting real meteorology.

### 5.3 Flatline threshold relaxed

The initial "constant value for >12 h = stuck sensor" rule flagged
Quetta, Turbat, Chilas, Zhob and Muzaffarabad. All are clean, remote,
high-elevation locations where a reanalysis product legitimately holds
a constant low value overnight. The threshold is now 36 hours. A real
stuck sensor repeats indefinitely, not for 16 hours.

### 5.4 Final validation status

```
schema : pass
[PASS] no_duplicate_city_timestamp     0 duplicates
[PASS] target_completeness             0.0% missing
[PASS] data_freshness                  3.7 h old
[PASS] pm25_not_above_pm10             16 violations (0.001%)
[PASS] per_city_coverage               0 cities below 50%
[PASS] no_long_flatlines               0 cities
[PASS] extreme_value_census            0 values above 1000 (informational)
```

---

## 6. Ground truth: currently unavailable

**OpenAQ registration did not complete.** The account was created but
the verification email never arrived (checked inbox and spam, two
attempts). Without the key we cannot pull independent ground-station
observations.

**Impact on the project:** none fatal. The pipeline treats OpenAQ as an
optional source — leave `OPENAQ_API_KEY` blank in `.env` and ingestion
skips it cleanly (`settings.openaq_enabled`). Everything else works.

**Impact on our claims:** significant, and we state it plainly.

> Our training target is CAMS reanalysis PM2.5, which is a *model
> product*, not a sensor reading. We therefore evaluate how well our
> model forecasts the reanalysis, not how well it forecasts reality as
> measured on the ground. A model that predicts the reanalysis
> perfectly would still inherit all of the reanalysis's own biases.

This is the single most important limitation of the project and
belongs in the report, the defence and the dashboard. It is also
**honest and defensible** — every operational weather and air-quality
forecasting system on earth trains on reanalysis data for exactly this
reason: it is the only source with complete spatial coverage.

### If the OpenAQ key arrives later

1. Put it in `.env` as `OPENAQ_API_KEY`
2. Set `openaq.enabled: true` in `configs/data_config.yaml`
3. Expect sparse coverage: Pakistan has monitors in roughly four
   cities (US diplomatic posts in Islamabad, Lahore, Karachi,
   Peshawar) plus some PAQI community monitors
4. Use it for **validation only**, never for training — the coverage is
   far too sparse and too urban-biased to train on

---

## 7. Licensing and terms

| Source | Licence | Obligation |
|---|---|---|
| Open-Meteo Air Quality + Archive | CC BY 4.0, free tier is **non-commercial** | Attribution; stay inside fair-use limits |
| GeoNames (city coordinates) | CC BY 4.0 | Attribution |
| OpenAQ (if enabled) | Per-provider terms | Attribution to OpenAQ and the underlying provider |
| PAQI / Hawanama | CC BY 4.0 | Cite PAQI |
| CARTO + OpenStreetMap (base map) | ODbL / CARTO terms | Attribution on the map |

Attribution appears in the README, the API response payload
(`attribution` field), and the dashboard footer.

**The project must remain non-commercial** while it uses the free
Open-Meteo tier.

---

## 8. Reproducing this report

```bash
conda activate airwatch

# earliest available date
python -c "from src.data.openmeteo import probe_earliest_data; print(probe_earliest_data())"

# full backfill (resumable; takes several hours due to quota)
python -m src.data.ingestion

# validation + profile
python -m src.data.validation
cat reports/data_quality.json
```
