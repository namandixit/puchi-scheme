#!/usr/bin/env bash
# Copy upstream harness FFI stubs into puchi/test/build/clibs/ and apply
# puchi-owned UBSan patches. Fails if upstream drifted (patch reject).
#
# Usage (from repo root):  bash puchi/tools/prep_harness_clibs.sh
set -euo pipefail

TOOLS="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$TOOLS/../.." && pwd)"
CLIBS="$ROOT/puchi/test/clibs"
OUT="$ROOT/puchi/test/build/clibs"

cd "$ROOT"
mkdir -p "$OUT"

need=(
  "lib/srfi/151/bit.c"
  "lib/scheme/bytevector.c"
)
for f in "${need[@]}"; do
  if [[ ! -f "$f" ]]; then
    echo "error: missing $f (generate stubs first if needed)" >&2
    exit 1
  fi
done

cp -f lib/srfi/151/bit.c "$OUT/srfi_151_bit.c"
cp -f lib/scheme/bytevector.c "$OUT/scheme_bytevector.c"

apply_one() {
  local name="$1"
  local diff="$CLIBS/${name}.ubsan.diff"
  if [[ ! -f "$diff" ]]; then
    echo "error: missing patch $diff" >&2
    exit 1
  fi
  echo "[puchi] patching build/clibs/${name}.c"
  # patch -p0 from OUT so paths in the diff (srfi_151_bit.c) resolve locally
  if ! (cd "$OUT" && patch -p0 --batch < "$diff"); then
    echo "error: patch failed for ${name}.c — upstream stub likely changed." >&2
    echo "  Refresh: edit/fix $diff against current lib/ copy, see $CLIBS/README.md" >&2
    exit 1
  fi
}

apply_one srfi_151_bit
apply_one scheme_bytevector
echo "[puchi] harness clibs overlays ready under puchi/test/build/clibs/"
