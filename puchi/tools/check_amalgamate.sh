#!/usr/bin/env bash
# check_amalgamate.sh — regenerate puchi.h and fail if it drifts or transforms miss.
#
# Usage: bash puchi/tools/check_amalgamate.sh
# Exit 0 if amalgamate succeeds and puchi/puchi.h is unchanged vs git.
# Exit non-zero if amalgamate fails (patch/overlay miss) or puchi.h is dirty.
set -euo pipefail

TOOLS="$(cd "$(dirname "$0")" && pwd)"
PUCHI="$(cd "$TOOLS/.." && pwd)"
CHIBI="$(cd "$PUCHI/.." && pwd)"

bash "$TOOLS/amalgamate.sh"

cd "$CHIBI"
if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "[puchi] check: not a git checkout; amalgamate succeeded (no dirty check)"
  exit 0
fi

if git diff --quiet -- "puchi/puchi.h"; then
  echo "[puchi] check: puchi.h matches git (clean)"
  exit 0
fi

echo "[puchi] check: puchi.h differs from git after amalgamate:" >&2
git --no-pager diff --stat -- "puchi/puchi.h" >&2
echo "  Commit the regenerated header, or fix patches/overlays and re-run." >&2
exit 1
