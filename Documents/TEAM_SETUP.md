# Team setup — getting an identical dataset and a shared MLflow server

**Read this before you train anything.** If you skip the `dvc pull`
step and let the ingestion pipeline download its own data, your model
cannot be compared with anyone else's, and the comparison table is the
deliverable. Section 4 explains exactly why.

Everything below is free. No AWS account, no credit card.

---

## 1. One-time setup

### 1.1 Environment

Conda only — no `venv`.

```bash
conda create -n airwatch python=3.11 -y
conda activate airwatch
pip install -r requirements.txt
```

### 1.2 Get a DagsHub token

The repo is mirrored at
**https://dagshub.com/MuhammadHassanSaboor/Pakistan-AirWatch-AI**.
Hassan adds you as a collaborator; you then generate your own token.

1. Sign in to DagsHub (sign in with GitHub is easiest).
2. Top-right avatar → **Your Settings** → **Tokens**.
3. Copy the **default access token** (it looks like 40 hex characters).

That one token is used for three different things: the MLflow
password, the DVC remote access key, and the DVC remote secret key.
That is not a mistake — DagsHub accepts the same token in all three
slots.

### 1.3 Write your `.env`

```bash
cp .env.example .env
```

Then fill in these six lines. **Use your own token and username, not
Hassan's**, so the audit trail shows who ran what:

```ini
MLFLOW_TRACKING_URI=https://dagshub.com/MuhammadHassanSaboor/Pakistan-AirWatch-AI.mlflow
MLFLOW_TRACKING_USERNAME=<your-dagshub-username>
MLFLOW_TRACKING_PASSWORD=<your-token>
MLFLOW_EXPERIMENT_NAME=pm25-forecasting
DAGSHUB_USER_TOKEN=<your-token>

# hassan | mudassar | ifraz  -- this is the tag the comparison groups by
AIRWATCH_MEMBER=mudassar
```

> `.env` is gitignored and must stay that way. The repo is public.
> Never commit it, never paste a token into a notebook, a commit
> message, or a screenshot. If you ever do, revoke the token on
> DagsHub immediately — it is one click, and a leaked token gives
> write access to the whole repo.

### 1.4 Tell DVC your credentials

The remote itself is already configured in `.dvc/config`, which is
committed. Only the secret part is per-person, and it goes in
`.dvc/config.local`, which is **not** committed:

```bash
dvc remote modify --local origin access_key_id     <your-token>
dvc remote modify --local origin secret_access_key <your-token>
```

Check it worked:

```bash
dvc doctor          # "Supports:" must list s3
dvc remote list     # origin  s3://dvc
```

If `s3` is missing from `Supports:`, your `boto3` is not installed —
re-run `pip install -r requirements.txt`.

---

## 2. Get the data

```bash
dvc pull
```

That downloads about **1.4 GB**: the raw hourly dataset (61 MB) and
the built feature table (1.3 GB). It takes a while once, and then
never again.

Verify you have the same bytes as everyone else:

```bash
dvc status          # expect: "Data and pipelines are up to date."
dvc status -c       # expect: "Cache and remote 'origin' are in sync."
```

Those two commands compare md5 hashes recorded in `dvc.lock` against
your files and against the remote. If they pass, your dataset is
byte-identical to Hassan's. That is the guarantee the whole comparison
rests on.

**Do not run `python -m src.data.ingestion`.** It would re-download
from Open-Meteo and give you a *different* dataset — see section 4.

---

## 3. Train your models

```bash
conda activate airwatch

# Mudassar
python -m src.models.train_lightgbm

# Ifraz
python -m src.models.train_baselines
```

Each script logs to the shared MLflow server automatically, because
`src/models/tracking.py` reads `.env` and is the only module that
talks to MLflow. You do not call MLflow yourself.

Then look at your run next to everyone else's:

- in the browser: **DagsHub → Experiments**
- in the terminal: `python -m src.models.registry compare`
- in a notebook: `notebooks/02_model_comparison.ipynb`

### What every run must carry

`tracking.standard_tags()` attaches these for you. Listed so you can
confirm nothing is missing if your run looks odd in the table:

| Tag | Why it matters |
|---|---|
| `member` | the column the comparison table groups by |
| `model_family` | xgboost / lightgbm / baseline / ... |
| `dataset_version` | md5 of the feature table from `dvc.lock` — proves which data you trained on |
| `git_commit`, `git_dirty` | `git_dirty=true` means the run is not reproducible |
| `train_end`, `val_end` | the chronological split boundaries |

And these metrics, enforced by `tracking.verify_required_metrics()`:
`test_mae`, `test_rmse`, `test_r2`, `baseline_mae`, `improvement_pct`,
plus `mae_h1` / `mae_h6` / `mae_h12` / `mae_h24`.

### If you change the pipeline, not just the model

```bash
dvc repro           # re-runs only the stages whose inputs changed
dvc push            # upload any new data you produced
git add dvc.lock && git commit -m "..."
```

> **Careful with `dvc repro -f <stage>`.** The `--force` flag applies
> to the whole upstream chain, not just the stage you named: it will
> happily delete the raw dataset and start re-downloading 216 requests
> from Open-Meteo. To force a single stage and nothing else, use
> `dvc repro --single-item --force <stage>`. (Learned the hard way.)

---

## 4. Why the `dvc pull` step is not optional

The ingestion pipeline pulls from the Open-Meteo archive, which is
**not a fixed dataset**:

- The start date is pinned (`2022-08-05`) but the end date is "now",
  so fetching a day later gives you more rows.
- It serves CAMS reanalysis, which is *revised retroactively*. Values
  for a date you already downloaded can change later.

So three people running ingestion on three days get three different
datasets. Train on those and the leaderboard is meaningless: you would
be ranking models by which snapshot of the data they happened to get.

This is not hypothetical — it already happened in this project. Two
XGBoost runs exist from before DVC was set up, and the one with the
*better* MAE (6.80 vs 8.25) has the *worse* R² (0.70 vs 0.80). That
combination is impossible for two models scored on the same test set,
and it is the fingerprint of exactly this mistake.

`notebooks/02_model_comparison.ipynb` now checks for this before it
ranks anything, by grouping runs on `baseline_mae` — the error of a
persistence forecast on the run's own test split, which depends only
on the data. Runs that agree on it saw the same split; runs that do not
are not comparable, whatever their metrics look like side by side.

---

## 5. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `ERROR: unexpected error - cannot import name '_DIR_MARK' from 'pathspec'` | `pathspec` 1.x is installed. `pip install pathspec==0.12.1` |
| `URL 's3://' is supported but requires these missing dependencies: ['boto3']` | `pip install -r requirements.txt` (boto3 is pinned there) |
| `dvc doctor` does not list `s3` under `Supports:` | same as above |
| aiobotocore/botocore version error on `dvc push` | `pip install boto3==1.43.117 botocore==1.43.117` |
| MLflow runs land in a local `mlruns/` folder | credentials missing from `.env`; `tracking.configure()` falls back to local and logs a warning saying so |
| `403` from DagsHub | you are not a collaborator yet, or the token was revoked |
| `No module named 'src'` | run from the repo root, or use `python -m ...` |
| Notebook kernel missing | `python -m ipykernel install --user --name python3 --display-name "Python 3 (airwatch)"` |

---

## 6. Division of work

From `README.md`:

| Member | Owns |
|---|---|
| **Hassan** | data pipeline, features, XGBoost, serving API, React dashboard, DVC + MLflow infrastructure |
| **Mudassar** | Airflow, Kubeflow, tests, CI/CD, LightGBM / RandomForest / HistGradientBoosting |
| **Ifraz** | Docker, Kubernetes, monitoring, drift detection, baseline models |

The examiner will deliberately cross-examine: Hassan may be asked
about Kubernetes and Ifraz about the React map. All three of us need to
be able to explain any part of this.

### Open items

| # | Item | Owner |
|---|---|---|
| 1 | LightGBM run on the pulled dataset | Mudassar |
| 2 | Baselines re-run on the pulled dataset (the existing ones predate DVC) | Ifraz |
| 3 | **Known bug:** `run_drift_check` thresholds `retrain_recommended` on `drift_share`, which is Evidently's count of statistically significant columns. At our sample sizes that count saturates at 100%, so the flag is always `True` — even for a control window. It should threshold on PSI instead. Demonstrated with numbers in `notebooks/03_drift_and_monitoring.ipynb`, section 3.2. | Ifraz |
| 4 | Deploy the API publicly, and get the teacher's written approval for Oracle Always Free in place of AWS before building it (`SIMPLE_ROADMAP.md` step 17) | all three |
