#!/usr/bin/env bash
# Prove that a previous version of the DATA can be recovered exactly.
#
# This is a required deliverable: "data + code versions recoverable",
# demonstrated as `git checkout <old> && dvc checkout`. Versioning the
# code alone is not enough — a model is only reproducible if the bytes
# it trained on can be recovered too.
#
# What it shows, without touching the remote or retraining anything:
#
#   1. the md5 that dvc.lock records for the dataset
#   2. the md5 of the file actually on disk  -> they match
#   3. the file is damaged on purpose        -> they no longer match,
#                                               and `dvc status` says so
#   4. `dvc checkout` restores it            -> byte-identical again
#
#   ./scripts/demo_dvc_rollback.sh
#
# Safe to run: step 4 puts everything back. The file is restored from
# the local DVC cache, so it works offline.

set -euo pipefail

TARGET="data/raw/airquality_hourly.parquet"

md5_of() { python -c "
import hashlib, sys
h = hashlib.md5()
with open(sys.argv[1], 'rb') as f:
    for chunk in iter(lambda: f.read(1 << 22), b''):
        h.update(chunk)
print(h.hexdigest())
" "$1"; }

locked_md5() { python -c "
import sys, yaml, pathlib
doc = yaml.safe_load(pathlib.Path('dvc.lock').read_text(encoding='utf-8'))
for stage in (doc.get('stages') or {}).values():
    for out in stage.get('outs') or []:
        if out.get('path') == sys.argv[1]:
            print(out['md5']); raise SystemExit
print('NOT-IN-LOCK')
" "$1"; }

echo "=============================================================="
echo " 1. What dvc.lock says this dataset should be"
echo "=============================================================="
EXPECTED="$(locked_md5 "$TARGET")"
echo "  target        : $TARGET"
echo "  dvc.lock md5  : $EXPECTED"

if [ "$EXPECTED" = "NOT-IN-LOCK" ]; then
  echo
  echo "  Not tracked yet. Run 'dvc repro' (or 'dvc commit') first."
  exit 1
fi

echo
echo "=============================================================="
echo " 2. What is actually on disk"
echo "=============================================================="
if [ ! -f "$TARGET" ]; then
  echo "  missing locally — pulling it from the remote"
  dvc pull "$TARGET"
fi
ACTUAL="$(md5_of "$TARGET")"
echo "  on-disk md5   : $ACTUAL"
[ "$ACTUAL" = "$EXPECTED" ] && echo "  MATCH" || { echo "  MISMATCH"; exit 1; }
dvc status "$TARGET" || true

echo
echo "=============================================================="
echo " 3. Damaging the file on purpose"
echo "=============================================================="
# Truncating is a more honest test than deleting: a deleted file is
# obviously wrong, while a corrupted one still exists and still opens.
SIZE_BEFORE=$(python -c "import os,sys;print(os.path.getsize(sys.argv[1]))" "$TARGET")
python -c "
import sys
with open(sys.argv[1], 'r+b') as f:
    f.truncate(int(sys.argv[2]) // 2)
" "$TARGET" "$SIZE_BEFORE"
echo "  truncated to half its size"
echo "  on-disk md5   : $(md5_of "$TARGET")"
echo "  expected      : $EXPECTED"
echo
echo "  dvc status now reports the change:"
dvc status "$TARGET" || true

echo
echo "=============================================================="
echo " 4. Restoring it with dvc checkout"
echo "=============================================================="
dvc checkout --force "$TARGET"
RESTORED="$(md5_of "$TARGET")"
echo "  on-disk md5   : $RESTORED"
echo "  dvc.lock md5  : $EXPECTED"
echo

if [ "$RESTORED" = "$EXPECTED" ]; then
  echo "=============================================================="
  echo " RECOVERED, byte for byte."
  echo
  echo " To recover the dataset as it was at an OLDER COMMIT, the same"
  echo " two steps work on history:"
  echo
  echo "     git checkout <old-commit> -- dvc.lock"
  echo "     dvc checkout"
  echo
  echo " Code and data move together, which is the whole point."
  echo "=============================================================="
else
  echo "RESTORE FAILED: got $RESTORED, expected $EXPECTED" >&2
  echo "The cache may be missing this version. Try: dvc pull" >&2
  exit 1
fi
