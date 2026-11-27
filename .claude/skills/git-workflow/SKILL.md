---
name: git-workflow
description: Team Git workflow for AirWatch — Mudassar's branch, syncing with Hassan's main, commits, PRs and resolving conflicts (including .dvc files). Use for "commit", "push", "open a PR", "sync with main", "merge conflict".
---

# Git workflow

- Mudassar's branch: `mudassar_working`. Hassan merges via PRs into `main`.
- Never push to `main`. Never force-push a shared branch.
- Only commit/push when the user asks.

## Sync with the team
```bash
git fetch origin
git log --oneline HEAD..origin/main     # what teammates added
git merge origin/main                   # or rebase only if branch is unpushed
```

## Commit
Conventional commits, small and focused:
`feat(pipeline): ...`, `fix(ci): ...`, `test(api): ...`, `docs: ...`, `chore(dvc): ...`
Run the `ci-check` skill first. Never stage `.env`, `.dvc/config.local`, `mlruns/`, data under `data/raw|processed`.

## Pull request
```bash
git push -u origin mudassar_working
gh pr create --base main --head mudassar_working --title "..." --body "..."
```
Body: what changed, which rubric item it covers, how it was tested. Ask a teammate to review.

## Conflicts
- Code: resolve by hand, re-run `ci-check`.
- `.dvc` / `dvc.lock`: pick the side whose data you want, `dvc checkout`; if both changed data, merge the data, `dvc add` again, commit the new `.dvc`. Document the case in `Documents/WORKFLOW.md` (rubric asks for this).
