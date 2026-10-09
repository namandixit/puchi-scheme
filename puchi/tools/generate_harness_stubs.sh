#!/usr/bin/env bash
# Generate the FFI stub .c files the puchi harness needs into lib/
# (same paths a normal Chibi build uses; those files are gitignored).
#
# Usage:
#   bash puchi/tools/generate_harness_stubs.sh /path/to/chibi-scheme
#
# Or with CHIBI in the environment / on PATH:
#   bash puchi/tools/generate_harness_stubs.sh
set -euo pipefail

TOOLS="$(cd "$(dirname "$0")" && pwd)"
CHIBI_ROOT="$(cd "$TOOLS/../.." && pwd)"
cd "$CHIBI_ROOT"

CHIBI_BIN="${1:-${CHIBI:-}}"
if [[ -z "$CHIBI_BIN" ]]; then
  if command -v chibi-scheme >/dev/null 2>&1; then
    CHIBI_BIN=$(command -v chibi-scheme)
  else
    echo "error: pass path to chibi-scheme or set CHIBI=" >&2
    echo "  (needed once to regenerate lib/**/*.c from *.stub)" >&2
    exit 1
  fi
fi

FFI="$CHIBI_ROOT/tools/chibi-ffi"
if [[ ! -f "$FFI" ]]; then
  echo "error: missing $FFI" >&2
  exit 1
fi

stubs=(
  lib/scheme/bytevector.stub
  lib/chibi/io/io.stub
  lib/chibi/filesystem.stub
  lib/chibi/win32/process-win32.stub
)

echo "[puchi] generating harness stubs with: $CHIBI_BIN"
for stub in "${stubs[@]}"; do
  out="${stub%.stub}.c"
  echo "  $stub -> $out"
  "$CHIBI_BIN" "$FFI" "$stub"
  if [[ ! -f "$out" ]]; then
    echo "error: expected output missing: $out" >&2
    exit 1
  fi
done
echo "[puchi] stub generation done."
echo "[puchi] next: bash puchi/tools/prep_harness_clibs.sh"
echo "  (applies puchi/test/clibs/*.ubsan.diff; fails if stubs drifted)."
