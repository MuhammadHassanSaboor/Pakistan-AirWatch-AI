---
name: project-context
description: Pakistan AirWatch AI project map — team roles, what exists, what is still missing against the MLOps course rubric, and repo conventions. Load at the start of any task in this repo, or when asked "what's left", "what should I do next", or about rubric coverage.
---

# Pakistan AirWatch AI — project context

Hourly PM2.5 forecasting (+1/+6/+12/+24h) for 134 Pakistani cities. One global
XGBoost model, Open-Meteo data (no API key), Flask API, React dashboard.
Course spec: `Documents/MLOps_Course_Project_Requirements.pdf`. Full plan:
`Documents/PROJECT_ROADMAP.md`. Ownership: `Documents/CONTRIBUTIONS.md`.

## Team
| Member | Role | Owns |
|---|---|---|
| Hassan | Data & ML, API, frontend | `src/data`, `src/features`, `feature_store/`, `src/serving`, `frontend/` |
| **Mudassar** (this user) | MLOps & automation | `dvc.yaml`, `pipelines/`, `tests/`, `.github/workflows/`, `src/models/registry.py`, `evaluate.py`, `tracking.py`, `train_lightgbm.py` |
| Ifraz | Deployment & reliability | `docker/`, `docker-compose*.yml`, `k8s/`, `monitoring/`, `scripts/` |

Mudassar works on branch `mudassar_working`. Never push to `main`; open a PR.

## Already in the repo
- Ingestion → Pandera validation → 100 features → Feast (offline + online)
- XGBoost / LightGBM / baselines through one harness `src/models/train_base.py`
- Quality gate in `configs/model_params.yaml` (`max_test_mae: 25`, `≥15%` over persistence, `≥2%` over production)
- Registry CLI: `python -m src.models.registry {list,best,compare,promote,promote-production,rollback,export-production}`
- Flask API (`/health`, `/model-info`, `/predict`, `/metrics`, `/api/*`) + BentoML service
- 3 Airflow DAGs (`hourly_ingest_dag`, `ml_orchestrator_dag`, `retraining_dag`), Kubeflow pipeline (5 components, 2 conditional gates)
- `ci.yml`: ruff, gitleaks, pip-audit, pytest (cov ≥ 70), config checks, Docker build + Trivy + smoke test, frontend build
- k8s manifests (probes, HPA, PDB, NetworkPolicy), Prometheus + Grafana + 7 alert rules, Evidently drift

## Known gaps (verify before relying on this list — it may be stale)
1. **DVC not initialised** — no `.dvc/` folder, no `.dvc` files, no remote. `dvc.yaml` has no `evaluate` stage.
2. **No AWS deploy workflow** — `.github/workflows/deploy.yml` missing (ECR push, ECS/EC2 deploy, OIDC auth). 12 marks.
3. **No `REPORT.md`** and no architecture/workflow diagram files.
4. Spec layout extras missing: `docker/Dockerfile.ml`, `pipelines/kubeflow/components/`, `k8s/aws-iam-role-policy.yaml`.
5. Evidence still to capture: failed-gate CI run, DVC rollback demo, Airflow/Kubeflow run screenshots, alert firing, pod-kill demo, AWS budget alert.

## Conventions
- Python 3.11, conda env `airwatch`. Run modules as `python -m src....`.
- Ruff (line 88, double quotes); format with `ruff format src tests`.
- Conventional commits: `feat(scope): ...`, `fix(ci): ...`, `docs: ...`.
- Chronological splits only. Never use PM2.5 at `t+h` as an input.
- Never commit `.env`, DagsHub tokens or AWS keys; use GitHub secrets / OIDC.
