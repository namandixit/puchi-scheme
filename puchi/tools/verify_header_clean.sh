#!/usr/bin/env bash
# verify_header_clean.sh - README "Order of operations", step 4.
# After a gate run the amalgamation it performed must have reproduced the
# committed puchi/puchi.h byte for byte. Compared against HEAD, so a
# regenerated-but-uncommitted (or only staged) header fails too.
# Called by build_puchi_tests.sh and build_puchi_tests.bat. Exit 0 = clean (or
# not a git checkout, where there is nothing to compare against).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "[puchi] verify: not a git checkout; skipping the puchi.h check"
  exit 0
fi

if ! git diff --quiet HEAD -- puchi/puchi.h; then
  echo "error: puchi/puchi.h differs from HEAD after the gate." >&2
  git --no-pager diff --stat HEAD -- puchi/puchi.h >&2
  echo "  Commit and push the regenerated header, then rerun (see README," >&2
  echo "  'Order of operations')." >&2
  exit 1
fi
echo "[puchi] verify: puchi.h matches HEAD"
