---
name: ci-check
description: Run the same checks GitHub Actions CI runs (ruff lint + format, pytest with 70% coverage, config sanity) locally before committing or opening a PR. Use when asked to "run CI", "check before push", "run tests", or after changing Python code.
---

# Run CI checks locally

Mirror `.github/workflows/ci.yml`. Run from the repo root in the `airwatch`
conda env (`conda activate airwatch`). Stop at the first failing step, fix it,
then re-run from that step.

1. **Lint**
   ```bash
   ruff check src tests pipelines
   ruff format --check src tests
   ```
   Fix with `ruff check --fix src tests pipelines` and `ruff format src tests`.

2. **Tests + coverage gate**
   ```bash
   pytest -q --cov=src --cov-report=term-missing --cov-fail-under=70
   ```
   Skip network tests offline: `pytest -m "not network"`.

3. **Config sanity**
   ```bash
   python -c "from src.config import DATA_CFG, MODEL_CFG, split_dates; import pandas as pd; t,v=split_dates(); assert pd.Timestamp(t)<pd.Timestamp(v); print('configs OK')"
   python -m src.data.cities
   ```

4. **Workflow YAML changed?** Validate syntax:
   `python -c "import yaml,sys; [yaml.safe_load(open(f)) for f in sys.argv[1:]]" .github/workflows/*.yml`

5. **Optional, if Docker is running:** `docker build -f docker/Dockerfile.api -t airwatch-api:local .`

Report each step as pass/fail with the failing output. Never claim CI will pass
without having run steps 1–3.
