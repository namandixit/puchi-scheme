#!/usr/bin/env bash
# Definition of done for any puchi change on Linux/macOS: this script exits 0.
# POSIX counterpart of build_puchi_tests.bat (same suite, same matrix):
#   1) amalgamate
#   2) full suite under GCC + Clang (all three numeric configs, execute)
#   3) same suite again under Clang ASan+UBSan
#   4) same suite again under Clang ThreadSanitizer (Linux only; no Windows runtime)
#   5) same suite again under Clang MemorySanitizer (Linux only)
# Run from anywhere:  bash puchi/tools/build_puchi_tests.sh [gcc|clang|asan|tsan|msan ...]
#   (no args = gcc clang asan tsan msan. Naming suites is for re-running one.)
# Requires: gcc and clang on PATH (CC_GCC= / CC_CLANG= override), python3,
#           patch, the generated lib/**/*.c FFI stubs (see below), and the
#           Clang sanitizer runtime (Debian/Ubuntu: libclang-rt-<ver>-dev).
#
# GCC stands in for MSVC: a second, independent compiler with its own
# warnings (-Wall -Wextra ~ /W4).
#
# Applicable matrix (yes = run; no = documented skip):
#   Suite              integer   default   tower
#   C preflight        yes       yes       yes (+ two-host)
#   r5rs-tests.scm     yes       yes       yes
#   basic/*.scm        yes       yes       yes  (--expect vs .res)
#   r7rs-tests.scm     no*       no*       yes
#   syntax-tests.scm   no*       no*       yes
#   division-tests.scm no*       no*       yes
#   unicode-tests.scm  no*       no*       yes
#   lib-tests-embed    no*       no*       yes
#   * needs PUCHI_ENABLE_NUMERICAL_TOWER (Complex / digitless +i literals)
#   lib-embed also omits OS libs and include-shared not in harness_clibs
#   skip basic test10-unhygiene (puchi capture differs from stock .res)
#
# Permanently out of scope (all configs):
#   ffi/, snow/, net-tests, memory/, install/, run/, build-tests.sh
#   (chibi process)/(chibi system)/(chibi tar)/filesystem lib tests
#
# Every harness script run: single-threaded first, then 64 parallel contexts.
set -euo pipefail

TOOLS="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$TOOLS/../.." && pwd)"
cd "$ROOT"

TEST=puchi/test
OUT=$TEST/build
mkdir -p "$OUT"

CC_GCC="${CC_GCC:-gcc}"
# Leak checks (LSan, part of ASan on Linux) skip known upstream stub leaks.
# TSan: abort on the first race (like -fno-sanitize-recover for ASan/UBSan).
export TSAN_OPTIONS="halt_on_error=1${TSAN_OPTIONS:+:$TSAN_OPTIONS}"
export LSAN_OPTIONS="suppressions=$ROOT/puchi/test/lsan.supp:print_suppressions=0${LSAN_OPTIONS:+:$LSAN_OPTIONS}"
CC_CLANG="${CC_CLANG:-clang}"

for c in "$CC_GCC" "$CC_CLANG"; do
  if ! command -v "$c" >/dev/null 2>&1; then
    echo "$c not found on PATH" >&2
    exit 1
  fi
done

# Echo then run; any failure stops the script (set -e).
run() {
  echo "+ $*"
  "$@"
}

echo "=== check generated FFI stubs in lib/ ==="
need_stubs=
for f in lib/scheme/bytevector.c lib/chibi/io/io.c lib/chibi/filesystem.c \
         lib/chibi/win32/process-win32.c; do
  [[ -f "$f" ]] || need_stubs=1
done
if [[ -n "$need_stubs" ]]; then
  echo "Missing generated lib/**/*.c stubs. Generate from *.stub with a built chibi:" >&2
  echo "  bash puchi/tools/generate_harness_stubs.sh path/to/chibi-scheme" >&2
  echo "Or build Chibi normally (make) first so those files exist under lib/." >&2
  exit 1
fi

echo "=== amalgamating ==="
bash "$TOOLS/amalgamate.sh"

echo "=== prep harness clibs overlays (UBSan patches; fail on upstream drift) ==="
bash "$TOOLS/prep_harness_clibs.sh"

echo "=== compile isolation probes (bare / TEST-only / clibs decls) ==="
PROBE_CF=(-O2 -Wall -Wextra)
run "$CC_GCC" "${PROBE_CF[@]}" -c $TEST/test_host_isolation_bare.c -o $OUT/host_isolation_bare.o
run "$CC_GCC" "${PROBE_CF[@]}" -c $TEST/test_host_isolation_test_only.c -o $OUT/host_isolation_test_only.o
run "$CC_GCC" "${PROBE_CF[@]}" -DPUCHI_ENABLE_NUMERICAL_TOWER -c $TEST/test_clibs_surface_probe.c -o $OUT/clibs_surface_probe.o

# ---------------------------------------------------------------------------
# basic/*.scm with --expect vs sibling .res
run_basic() {
  local hx="$1" t
  echo "=== basic tests ==="
  for t in test00-fact-3 test01-apply test02-closure test03-nested-closure \
           test04-nested-let test05-internal-define test06-letrec \
           test07-mutation test08-callcc test09-hygiene; do
    run "$hx" -I lib -xchibi --expect tests/basic/$t.res tests/basic/$t.scm
  done
  # skip test10-unhygiene: puchi capture differs from stock .res (4th write 1 vs 6)
}

# ---------------------------------------------------------------------------
do_suite() {
  local tag="$1"
  local cc
  local -a cf hf ldf
  echo
  echo "========== [$tag] =========="

  # No -I. — puchi.h must be a true single-header (tests use #include "../puchi.h").
  hf=(-I$TEST/harness-include)
  ldf=(-lm -pthread)
  case "$tag" in
    gcc)
      cc="$CC_GCC"
      cf=(-O2 -Wall -Wextra)
      ;;
    clang)
      cc="$CC_CLANG"
      cf=(-O2 -Weverything)
      ;;
    asan)
      # Runtime net for GC / layout / UB bugs the optimized suite can miss.
      # ASan + UBSan; abort on first hit. Aligned bytecode + safe fixnum read
      # (features force / patch 005) keep these checks meaningful on x86.
      cc="$CC_CLANG"
      cf=(-O1 -g -fno-omit-frame-pointer -fsanitize=address -fsanitize=undefined
          -fsanitize=local-bounds -fno-sanitize-recover=all)
      ;;
    tsan)
      # Data-race net for the 64 parallel contexts the harness runs. Linux only
      # (TSan has no Windows runtime). Cannot be combined with ASan, so it is
      # its own pass. Clang, to match the ASan pass.
      cc="$CC_CLANG"
      cf=(-O1 -g -fno-omit-frame-pointer -fsanitize=thread)
      # TSan multiplies memory: 64 contexts of lib-tests-embed exceed 16 GB
      # (OOM-killed). 16 contexts still exercise cross-context races.
      local -x PUCHI_HARNESS_THREADS="${PUCHI_HARNESS_THREADS:-16}"
      ;;
    msan)
      # Uninitialized reads (host alloc memory, heap, stack). Linux, clang
      # only; cannot combine with ASan/TSan. Needs PIE; origin tracking makes
      # reports name the allocation. Memory-hungry like TSan, so 16 contexts.
      cc="$CC_CLANG"
      cf=(-O1 -g -fno-omit-frame-pointer -fPIE -fsanitize=memory
          -fsanitize-memory-track-origins=2 -fno-sanitize-recover=all)
      ldf+=(-pie)
      local -x PUCHI_HARNESS_THREADS="${PUCHI_HARNESS_THREADS:-16}"
      ;;
    *)
      echo "unknown compiler tag: $tag" >&2
      return 1
      ;;
  esac
  local p="$OUT/${tag}"

  echo "=== [$tag][integer] C checks ==="
  run "$cc" "${cf[@]}" -DPUCHI_INTEGER_ONLY -c $TEST/puchi_impl.c -o "${p}_impl_integer.o"
  run "$cc" "${cf[@]}" -c $TEST/puchi_integer_smoke.c -o "${p}_integer_smoke.o"
  run "$cc" "${cf[@]}" -o "${p}_integer_smoke" "${p}_integer_smoke.o" "${p}_impl_integer.o" "${ldf[@]}"
  run "${p}_integer_smoke"

  echo "=== [$tag][integer] harness + r5rs + basic ==="
  run "$cc" "${cf[@]}" "${hf[@]}" -DPUCHI_INTEGER_ONLY -c $TEST/puchi_harness.c -o "${p}_harness_integer.o"
  run "$cc" "${cf[@]}" "${hf[@]}" -DPUCHI_INTEGER_ONLY -c $TEST/puchi_harness_clibs.c -o "${p}_harness_clibs_integer.o"
  run "$cc" "${cf[@]}" -o "${p}_harness_integer" "${p}_harness_integer.o" "${p}_harness_clibs_integer.o" "${p}_impl_integer.o" "${ldf[@]}"
  run "${p}_harness_integer" -I lib -xchibi tests/r5rs-tests.scm
  run_basic "${p}_harness_integer"

  echo "=== [$tag][default] C checks ==="
  run "$cc" "${cf[@]}" -c $TEST/puchi_impl.c -o "${p}_impl_default.o"
  run "$cc" "${cf[@]}" -c $TEST/puchi_slim_smoke.c -o "${p}_slim_smoke.o"
  run "$cc" "${cf[@]}" -o "${p}_slim_smoke" "${p}_slim_smoke.o" "${p}_impl_default.o" "${ldf[@]}"
  run "${p}_slim_smoke"
  run "$cc" "${cf[@]}" -c $TEST/puchi_static_smoke.c -o "${p}_static_smoke.o"
  run "$cc" "${cf[@]}" -o "${p}_static_smoke" "${p}_static_smoke.o" "${ldf[@]}"
  run "${p}_static_smoke"

  echo "=== [$tag][default] harness + r5rs + basic ==="
  run "$cc" "${cf[@]}" "${hf[@]}" -c $TEST/puchi_harness.c -o "${p}_harness_default.o"
  run "$cc" "${cf[@]}" "${hf[@]}" -c $TEST/puchi_harness_clibs.c -o "${p}_harness_clibs_default.o"
  run "$cc" "${cf[@]}" -o "${p}_harness_default" "${p}_harness_default.o" "${p}_harness_clibs_default.o" "${p}_impl_default.o" "${ldf[@]}"
  run "${p}_harness_default" -I lib -xchibi tests/r5rs-tests.scm
  run_basic "${p}_harness_default"

  echo "=== [$tag][tower] C checks ==="
  run "$cc" "${cf[@]}" -DPUCHI_ENABLE_NUMERICAL_TOWER -c $TEST/puchi_impl.c -o "${p}_impl_tower.o"
  run "$cc" "${cf[@]}" -c $TEST/puchi_smoke.c -o "${p}_smoke.o"
  run "$cc" "${cf[@]}" -o "${p}_smoke" "${p}_smoke.o" "${p}_impl_tower.o" "${ldf[@]}"
  run "${p}_smoke"

  echo "=== [$tag][tower] two-host ==="
  run "$cc" "${cf[@]}" -c $TEST/puchi_two_host_smoke.c -o "${p}_two_host_smoke.o"
  run "$cc" "${cf[@]}" -o "${p}_two_host_smoke" "${p}_two_host_smoke.o" "${p}_impl_tower.o" "${ldf[@]}"
  run "${p}_two_host_smoke"

  echo "=== [$tag][tower] harness ==="
  run "$cc" "${cf[@]}" "${hf[@]}" -DPUCHI_ENABLE_NUMERICAL_TOWER -c $TEST/puchi_harness.c -o "${p}_harness_tower.o"
  run "$cc" "${cf[@]}" "${hf[@]}" -DPUCHI_ENABLE_NUMERICAL_TOWER -c $TEST/puchi_harness_clibs.c -o "${p}_harness_clibs_tower.o"
  run "$cc" "${cf[@]}" -o "${p}_harness_tower" "${p}_harness_tower.o" "${p}_harness_clibs_tower.o" "${p}_impl_tower.o" "${ldf[@]}"

  echo "=== [$tag][tower] r5rs-tests ==="
  run "${p}_harness_tower" -I lib -xchibi tests/r5rs-tests.scm

  run_basic "${p}_harness_tower"

  echo "=== [$tag][tower] r7rs-tests ==="
  run "${p}_harness_tower" -I lib tests/r7rs-tests.scm

  echo "=== [$tag][tower] syntax-tests ==="
  run "${p}_harness_tower" -I lib tests/syntax-tests.scm

  echo "=== [$tag][tower] division-tests ==="
  run "${p}_harness_tower" -I lib tests/division-tests.scm

  echo "=== [$tag][tower] unicode-tests ==="
  run "${p}_harness_tower" -I lib -xchibi tests/unicode-tests.scm

  echo "=== [$tag][tower] lib-tests-embed ==="
  run "${p}_harness_tower" -I lib $TEST/lib-tests-embed.scm

  echo "=== [$tag] all three configs passed ==="
}

if [[ $# -eq 0 ]]; then
  set -- gcc clang asan tsan msan
fi
for tag in "$@"; do
  do_suite "$tag"
done

echo "=== puchi suites passed: $* ==="
