#!/usr/bin/env bash
# amalgamate.sh - build puchi.h from upstream Chibi without modifying
# upstream sources.
#
# Usage (from anywhere): bash puchi/tools/amalgamate.sh
# Requires: bash, sed, awk, python3 (Git Bash on Windows is fine).
set -euo pipefail

TOOLS="$(cd "$(dirname "$0")" && pwd)"
PUCHI="$(cd "$TOOLS/.." && pwd)"
CHIBI="$(cd "$PUCHI/.." && pwd)"
cd "$CHIBI"

HELPERS="$TOOLS/puchi_amalgamate_helpers.py"
WORKDIR="$TOOLS/.amalgamate-tmp"
OUT_PUCHI="$PUCHI/puchi.h"

PYTHON=
if command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
elif command -v python >/dev/null 2>&1; then
  PYTHON=python
else
  echo "error: python3 required" >&2
  exit 1
fi

rm -rf "$WORKDIR"
mkdir -p "$WORKDIR"

echo "[puchi] preparing sources..."

# --- synthetic install.h ---
cat > "$WORKDIR/install.h" <<'EOF'
#define sexp_so_extension ".so"
#define sexp_default_module_path ""
#define sexp_platform "puchi"
#define sexp_architecture "portable"
#define sexp_version "0.12.0"
#define sexp_release_name "puchi"
EOF

# --- feature force header (prepended before features.h) ---
cat > "$WORKDIR/puchi_features_force.h" <<'EOF'
/* Forced by amalgamate.sh. Set PUCHI_* macros before including puchi.h.
 *
 * Default:           fixnums + IEEE flonums (overflow wraps; no bignums).
 * PUCHI_INTEGER_ONLY: fixnums only (no floats, no tower).
 * PUCHI_ENABLE_NUMERICAL_TOWER: bignums + ratios + complex (implies flonums).
 */
#if defined(PUCHI_INTEGER_ONLY) && defined(PUCHI_ENABLE_NUMERICAL_TOWER)
#error "PUCHI_INTEGER_ONLY and PUCHI_ENABLE_NUMERICAL_TOWER are mutually exclusive"
#endif
#ifndef SEXP_STATIC_LIBRARY
#define SEXP_STATIC_LIBRARY 1
#endif
/* Always off, and the implementations are deleted by strip-dead-backends.
 * Do not turn these back on in puchi.h; the code is not in the amalgamation.
 * Plan 9 is never defined, so those branches are removed the same way. */
#define SEXP_USE_GREEN_THREADS 0
#define SEXP_USE_DL 0
#define SEXP_USE_BOEHM 0
#ifndef SEXP_USE_IMAGE_LOADING
#define SEXP_USE_IMAGE_LOADING 0
#endif
#ifndef SEXP_USE_MMAP_GC
#define SEXP_USE_MMAP_GC 0
#endif
#ifndef SEXP_USE_GC_FILE_DESCRIPTORS
#define SEXP_USE_GC_FILE_DESCRIPTORS 0
#endif
#ifndef SEXP_USE_STRING_STREAMS
#define SEXP_USE_STRING_STREAMS 0
#endif
#ifndef SEXP_USE_NTP_GETTIME
#define SEXP_USE_NTP_GETTIME 0
#endif
#ifndef SEXP_USE_STATIC_LIBS
#define SEXP_USE_STATIC_LIBS 0
#endif
#ifndef SEXP_USE_STATIC_LIBS_EMPTY
#define SEXP_USE_STATIC_LIBS_EMPTY 0
#endif
#ifndef SEXP_USE_TIME_GC
#define SEXP_USE_TIME_GC 0
#endif
#ifndef SEXP_USE_MODULES
#define SEXP_USE_MODULES 1
#endif
#if defined(PUCHI_INTEGER_ONLY)
#ifndef SEXP_USE_FLONUMS
#define SEXP_USE_FLONUMS 0
#endif
#ifndef SEXP_USE_MATH
#define SEXP_USE_MATH 0
#endif
#ifndef SEXP_USE_BIGNUMS
#define SEXP_USE_BIGNUMS 0
#endif
#ifndef SEXP_USE_RATIOS
#define SEXP_USE_RATIOS 0
#endif
#ifndef SEXP_USE_COMPLEX
#define SEXP_USE_COMPLEX 0
#endif
#elif defined(PUCHI_ENABLE_NUMERICAL_TOWER)
#ifndef SEXP_USE_FLONUMS
#define SEXP_USE_FLONUMS 1
#endif
#ifndef SEXP_USE_MATH
#define SEXP_USE_MATH 1
#endif
#ifndef SEXP_USE_BIGNUMS
#define SEXP_USE_BIGNUMS 1
#endif
#ifndef SEXP_USE_RATIOS
#define SEXP_USE_RATIOS 1
#endif
#ifndef SEXP_USE_COMPLEX
#define SEXP_USE_COMPLEX 1
#endif
#else
/* Default: fast ints + floats */
#ifndef SEXP_USE_FLONUMS
#define SEXP_USE_FLONUMS 1
#endif
#ifndef SEXP_USE_MATH
#define SEXP_USE_MATH 1
#endif
#ifndef SEXP_USE_BIGNUMS
#define SEXP_USE_BIGNUMS 0
#endif
#ifndef SEXP_USE_RATIOS
#define SEXP_USE_RATIOS 0
#endif
#ifndef SEXP_USE_COMPLEX
#define SEXP_USE_COMPLEX 0
#endif
#endif
EOF

# --- patch headers/sources ---
"$PYTHON" "$HELPERS" patch-sexp-h "$CHIBI/include/chibi/sexp.h" "$WORKDIR/sexp.h"
"$PYTHON" "$HELPERS" patch-eval-c "$CHIBI/eval.c" "$WORKDIR/eval.c"
"$PYTHON" "$HELPERS" patch-gc-c "$CHIBI/gc.c" "$WORKDIR/gc.c"
"$PYTHON" "$HELPERS" patch-sexp-c "$CHIBI/sexp.c" "$WORKDIR/sexp.c"

cp "$CHIBI/opcodes.c" "$WORKDIR/opcodes.c"
cp "$CHIBI/vm.c" "$WORKDIR/vm.c"
cp "$CHIBI/simplify.c" "$WORKDIR/simplify.c"
cp "$CHIBI/include/chibi/features.h" "$WORKDIR/features.h"
"$PYTHON" "$HELPERS" strip-features "$WORKDIR/features.h" "$WORKDIR/features.h"
cp "$CHIBI/include/chibi/eval.h" "$WORKDIR/eval.h"
cp "$CHIBI/include/chibi/bignum.h" "$WORKDIR/bignum.h"
cp "$CHIBI/include/chibi/gc_heap.h" "$WORKDIR/gc_heap.h"
cp "$CHIBI/include/chibi/sexp-huff.h" "$WORKDIR/sexp-huff.h"
cp "$CHIBI/include/chibi/sexp-unhuff.h" "$WORKDIR/sexp-unhuff.h"
cp "$CHIBI/include/chibi/sexp-hufftabs.h" "$WORKDIR/sexp-hufftabs.h"
cp "$CHIBI/include/chibi/sexp-hufftabdefs.h" "$WORKDIR/sexp-hufftabdefs.h"
cp "$CHIBI/include/chibi/sexp-hufftabs.c" "$WORKDIR/sexp-hufftabs.c"
cp "$CHIBI/bignum.c" "$WORKDIR/bignum.c"

sed_inplace() {
  local file="$1"; shift
  sed "$@" "$file" > "$file.tmp" && mv "$file.tmp" "$file"
}

"$PYTHON" - "$WORKDIR" <<'PY'
import sys
from pathlib import Path
wd = Path(sys.argv[1])
sexp_c = (wd / "sexp.c").read_text(encoding="utf-8")
tabs = (wd / "sexp-hufftabs.h").read_text(encoding="utf-8")
huff = (wd / "sexp-huff.h").read_text(encoding="utf-8")
unhuff = (wd / "sexp-unhuff.h").read_text(encoding="utf-8")
old = '#include "chibi/sexp-hufftabs.h"\n#include "chibi/sexp-huff.h"\n'
if old not in sexp_c:
    raise SystemExit("huffman includes not found in sexp.c")
sexp_c = sexp_c.replace(old, "/* ---- huffman tables (amalgamated) ---- */\n" + tabs + "\n" + huff + "\n")
old_u = '#include "chibi/sexp-unhuff.h"\n'
if old_u not in sexp_c:
    raise SystemExit("unhuff include not found in sexp.c")
sexp_c = sexp_c.replace(old_u, "/* ---- unhuff (amalgamated) ---- */\n" + unhuff + "\n")
sexp_c = sexp_c.replace("#ifdef _WIN32\n#include <io.h>\n#endif\n", "/* puchi: no io.h */\n")
(wd / "sexp.c").write_text(sexp_c, encoding="utf-8")
print("injected huffman into sexp.c")
PY

# Inject bignum.h into sexp.h at the normal include site (gated by SEXP_USE_BIGNUMS)
"$PYTHON" - "$WORKDIR" <<'PY'
import sys
from pathlib import Path
wd = Path(sys.argv[1])
sexp_h = (wd / "sexp.h").read_text(encoding="utf-8")
bignum_h = (wd / "bignum.h").read_text(encoding="utf-8")
for pat in (
    '#include "chibi/features.h"',
    '#include "chibi/install.h"',
    '#include "chibi/sexp.h"',
    '#include "chibi/eval.h"',
):
    bignum_h = bignum_h.replace(pat, "/* amalgamated */")
old = '#include "chibi/bignum.h"\n'
if old not in sexp_h:
    raise SystemExit("chibi/bignum.h include not found in sexp.h")
sexp_h = sexp_h.replace(
    old,
    "/* ---- bignum.h (amalgamated; active only if SEXP_USE_BIGNUMS) ---- */\n"
    + bignum_h + "\n",
    1,
)
sexp_h = sexp_h.replace(
    "#define sexp_malloc malloc\n#define sexp_free free\n",
    "/* puchi: sexp_malloc/free set at top of puchi.h */\n",
)
(wd / "sexp.h").write_text(sexp_h, encoding="utf-8")
print("injected bignum.h into sexp.h")
PY

for f in sexp.h eval.h bignum.h gc_heap.h features.h gc.c sexp.c eval.c \
         opcodes.c vm.c simplify.c bignum.c; do
  sed_inplace "$WORKDIR/$f" \
    -e 's|#include "chibi/features.h"|/* amalgamated features.h */|' \
    -e 's|#include "chibi/install.h"|/* amalgamated install.h */|' \
    -e 's|#include "chibi/sexp.h"|/* amalgamated sexp.h */|' \
    -e 's|#include "chibi/eval.h"|/* amalgamated eval.h */|' \
    -e 's|#include "chibi/bignum.h"|/* amalgamated bignum.h */|' \
    -e 's|#include "chibi/gc_heap.h"|/* amalgamated gc_heap.h */|' \
    -e 's|#include "chibi/sexp-hufftabdefs.h"|/* amalgamated sexp-hufftabdefs.h */|'
done

sed_inplace "$WORKDIR/bignum.c" \
  -e 's/\bdigit_value\b/puchi_bignum_digit_value/g' \
  -e 's/\bhex_digit\b/puchi_bignum_hex_digit/g'

sed_inplace "$WORKDIR/opcodes.c" 's|#include "opt/plan9-opcodes.c"|/* puchi: no plan9 */|'

for f in gc.c sexp.c eval.c opcodes.c vm.c simplify.c bignum.c; do
  sed_inplace "$WORKDIR/$f" \
    -e 's|#include <unistd.h>|/* puchi: no unistd.h */|' \
    -e 's|#include <dlfcn.h>|/* puchi: no dlfcn.h */|' \
    -e 's|#include <sys/stat.h>|/* puchi: no sys/stat.h */|' \
    -e 's|#include <sys/types.h>|/* puchi: no sys/types.h */|' \
    -e 's|#include <sys/socket.h>|/* puchi: no sys/socket.h */|' \
    -e 's|#include <sys/time.h>|/* puchi: no sys/time.h */|' \
    -e 's|#include <sys/select.h>|/* puchi: no sys/select.h */|' \
    -e 's|#include <sys/mman.h>|/* puchi: no sys/mman.h */|' \
    -e 's|#include <sys/resource.h>|/* puchi: no sys/resource.h */|' \
    -e 's|#include <fcntl.h>|/* puchi: no fcntl.h */|' \
    -e 's|#include <poll.h>|/* puchi: no poll.h */|' \
    -e 's|#include <windows.h>|/* puchi: no windows.h */|' \
    -e 's|#include <winsock2.h>|/* puchi: no winsock2.h */|' \
    -e 's|#include <execinfo.h>|/* puchi: no execinfo.h */|'
done

echo "[puchi] embedding trimmed init-7.scm..."
"$PYTHON" "$HELPERS" trim-init "$CHIBI/lib/init-7.scm" "$WORKDIR/init-7-trimmed.scm"
"$PYTHON" "$HELPERS" embed puchi_init7_scm "$WORKDIR/init-7-trimmed.scm" "$WORKDIR/init7_embed.c"

echo "[puchi] writing puchi.h..."
{
  cat <<'EOF'
/* puchi.h - amalgamated portable Chibi Scheme kernel
 *
 * Generated by puchi/tools/amalgamate.sh. Do not edit this file.
 * Change the scripts and re-run. The block below is the supported API.
 * Everything after "resolved feature flags" is upstream Chibi, pasted so
 * this header can compile alone. Configure it only with the macros here.
 *
 * ----------------------------------------------------------------------
 * How to use
 * ----------------------------------------------------------------------
 * In exactly one .c file:
 *
 *   #define PUCHI_IMPLEMENTATION
 *   #include "puchi.h"
 *
 * Other files include "puchi.h" with no PUCHI_IMPLEMENTATION.
 * Set any option macros before the include.
 *
 *   sexp ctx = sexp_create_context(0, 0);   // heap size, heap max (0 = default)
 *   sexp_load_default_libs(ctx);            // embedded R7RS-ish init, no disk
 *   sexp res = sexp_eval_string(ctx, "(+ 1 2)", -1, NULL);
 *   sexp_delete_context(ctx);
 *
 * sexp_eval_string reads one form. len -1 means strlen. Pass NULL for env
 * to use the context environment. Check sexp_exceptionp on the result.
 *
 * ----------------------------------------------------------------------
 * Numeric modes (pick one; set before include)
 * ----------------------------------------------------------------------
 *   (none)
 *       Fixnums and IEEE flonums (boxed double). Fixnum overflow wraps.
 *       No bignums, ratios, or complex numbers.
 *
 *   #define PUCHI_ENABLE_NUMERICAL_TOWER
 *       Also bignums, exact ratios, and complex. Fixnum overflow promotes
 *       to a bignum. Implies flonums.
 *
 *   #define PUCHI_INTEGER_ONLY
 *       Fixnums only. No flonums and no tower. Float literals will not read.
 *
 * PUCHI_INTEGER_ONLY and PUCHI_ENABLE_NUMERICAL_TOWER together are an error.
 * Do not set SEXP_USE_FLONUMS / SEXP_USE_BIGNUMS / SEXP_USE_RATIOS /
 * SEXP_USE_COMPLEX yourself. Those names appear later as the resolved
 * flags. They are not a menu.
 *
 * ----------------------------------------------------------------------
 * What this core does not do
 * ----------------------------------------------------------------------
 * No OS file I/O, no dlopen, no module search on disk, no green threads,
 * no sockets. open-input-file, load, and call-with-*-file from the
 * embedded init raise an error. A host that needs files or modules
 * supplies them (see puchi/test/puchi_harness.c).
 *
 * ----------------------------------------------------------------------
 * Allocator (optional, before include)
 * ----------------------------------------------------------------------
 *   #define SEXP_MALLOC(ctx, size) my_alloc(ctx, size)
 *   #define SEXP_FREE(ctx, ptr)    my_free(ctx, ptr)
 *
 * Default is malloc / free. The ctx argument may be NULL.
 *
 * License: BSD-style (upstream COPYING / Alex Shinn).
 */
#ifndef PUCHI_H
#define PUCHI_H

#ifdef __cplusplus
extern "C" {
#endif

/* ---- allocator hooks (CRT malloc/free by default) ---- */
#ifndef SEXP_MALLOC
#define SEXP_MALLOC(ctx, size) ((void)(ctx), malloc(size))
#endif
#ifndef SEXP_FREE
#define SEXP_FREE(ctx, ptr) ((void)(ctx), free(ptr))
#endif

#ifndef sexp_malloc
#define sexp_malloc(sz) SEXP_MALLOC(NULL, (sz))
#endif
#ifndef sexp_free
#define sexp_free(p) SEXP_FREE(NULL, (p))
#endif

EOF

  echo "/* ==== puchi feature forces ==== */"
  cat "$WORKDIR/puchi_features_force.h"

  echo "/* ==== resolved feature flags (from features.h; manual omitted) ==== */"
  cat "$WORKDIR/features.h"

  echo "/* ==== install.h ==== */"
  cat "$WORKDIR/install.h"

  echo "/* ==== sexp.h (bignum.h inlined mid-file under SEXP_USE_BIGNUMS) ==== */"
  cat "$WORKDIR/sexp.h"

  echo "/* ==== eval.h ==== */"
  cat "$WORKDIR/eval.h"

  echo "/* ==== gc_heap.h ==== */"
  cat "$WORKDIR/gc_heap.h"

  cat <<'EOF'

/* ---- decls when tower code is compiled out ---- */
#if SEXP_USE_FLONUMS && !SEXP_USE_BIGNUMS
SEXP_API double sexp_to_double(sexp ctx, sexp x);
SEXP_API sexp sexp_add(sexp ctx, sexp a, sexp b);
SEXP_API sexp sexp_sub(sexp ctx, sexp a, sexp b);
SEXP_API sexp sexp_mul(sexp ctx, sexp a, sexp b);
SEXP_API sexp sexp_div(sexp ctx, sexp a, sexp b);
SEXP_API sexp sexp_quotient(sexp ctx, sexp a, sexp b);
SEXP_API sexp sexp_remainder(sexp ctx, sexp a, sexp b);
#endif
#if !SEXP_USE_BIGNUMS
SEXP_API sexp sexp_fixnum_to_bignum(sexp ctx, sexp a);
SEXP_API sexp sexp_exact_sqrt(sexp ctx, sexp self, sexp_sint_t n, sexp z);
#endif

/* ---- puchi high-level API ---- */
SEXP_API sexp sexp_create_context(sexp_uint_t heap_size, sexp_uint_t heap_max_size);
SEXP_API sexp sexp_delete_context(sexp ctx);
SEXP_API sexp sexp_load_default_libs(sexp ctx);

#ifdef __cplusplus
} /* extern "C" declarations */
#endif

/* ========================================================================== */
#if defined(PUCHI_IMPLEMENTATION)
/* ========================================================================== */

#ifdef __cplusplus
extern "C" {
#endif

EOF

  echo "/* ==== gc.c ==== */"
  cat "$WORKDIR/gc.c"

  echo "/* ==== sexp.c ==== */"
  cat "$WORKDIR/sexp.c"

  echo "/* ==== opcodes.c ==== */"
  cat "$WORKDIR/opcodes.c"

  echo "/* ==== vm.c ==== */"
  cat "$WORKDIR/vm.c"

  echo "/* ==== eval.c ==== */"
  cat "$WORKDIR/eval.c"

  echo "/* ==== simplify.c ==== */"
  cat "$WORKDIR/simplify.c"

  echo "/* ==== bignum.c (active only if PUCHI_ENABLE_NUMERICAL_TOWER / SEXP_USE_BIGNUMS) ==== */"
  cat "$WORKDIR/bignum.c"

  cat <<'EOF'

#if !SEXP_USE_BIGNUMS
/* Slim arithmetic for builds without the numerical tower.
 *
 * Chibi implements sexp_add/sub/mul/div, sexp_to_double, and friends in
 * bignum.c, inside #if SEXP_USE_BIGNUMS. That file is still pasted below,
 * but the compiler skips it unless PUCHI_ENABLE_NUMERICAL_TOWER. Fixnum
 * and flonum code in sexp.c / eval.c / vm.c still calls those functions,
 * so a tower-off build needs these definitions or it fails to link
 * (typical missing symbols: sexp_mul, sexp_to_double, sexp_exact_sqrt,
 * sexp_fixnum_to_bignum).
 *
 * If a new upstream call fails to link only when the tower is off:
 *   1. See which .c the symbol is defined in (usually bignum.c).
 *   2. If the call is fixnum/flonum only, add a small stub here.
 *   3. If the call truly needs bignums, guard the call site with
 *      SEXP_USE_BIGNUMS in the amalgamation patch, or require the tower.
 * Do not copy bignum.c into the default build to silence the linker.
 * sexp_fixnum_to_bignum without the tower returns the fixnum unchanged
 * (overflow wraps). sexp_exact_sqrt uses flonum sqrt, or an integer loop
 * when PUCHI_INTEGER_ONLY.
 */
#if SEXP_USE_FLONUMS
double sexp_to_double(sexp ctx, sexp x) {
  (void)ctx;
  if (sexp_flonump(x)) return sexp_flonum_value(x);
  if (sexp_fixnump(x)) return sexp_fixnum_to_double(x);
  return 0.0;
}
static sexp puchi_num_type_error(sexp ctx, sexp x) {
  return sexp_type_exception(ctx, NULL, SEXP_NUMBER, x);
}
sexp sexp_add(sexp ctx, sexp a, sexp b) {
  if (sexp_fixnump(a) && sexp_fixnump(b)) return sexp_fx_add(a, b);
  if (sexp_flonump(a) && sexp_flonump(b)) return sexp_fp_add(ctx, a, b);
  if (sexp_flonump(a) && sexp_fixnump(b))
    return sexp_make_flonum(ctx, sexp_flonum_value(a) + sexp_fixnum_to_double(b));
  if (sexp_fixnump(a) && sexp_flonump(b))
    return sexp_make_flonum(ctx, sexp_fixnum_to_double(a) + sexp_flonum_value(b));
  return puchi_num_type_error(ctx, a);
}
sexp sexp_sub(sexp ctx, sexp a, sexp b) {
  if (sexp_fixnump(a) && sexp_fixnump(b)) return sexp_fx_sub(a, b);
  if (sexp_flonump(a) && sexp_flonump(b)) return sexp_fp_sub(ctx, a, b);
  if (sexp_flonump(a) && sexp_fixnump(b))
    return sexp_make_flonum(ctx, sexp_flonum_value(a) - sexp_fixnum_to_double(b));
  if (sexp_fixnump(a) && sexp_flonump(b))
    return sexp_make_flonum(ctx, a == SEXP_ZERO ? -sexp_flonum_value(b)
                                                 : sexp_fixnum_to_double(a) - sexp_flonum_value(b));
  return puchi_num_type_error(ctx, a);
}
sexp sexp_mul(sexp ctx, sexp a, sexp b) {
  if (sexp_fixnump(a) && sexp_fixnump(b)) return sexp_fx_mul(a, b);
  if (sexp_flonump(a) && sexp_flonump(b)) return sexp_fp_mul(ctx, a, b);
  if (sexp_flonump(a) && sexp_fixnump(b))
    return sexp_make_flonum(ctx, sexp_flonum_value(a) * sexp_fixnum_to_double(b));
  if (sexp_fixnump(a) && sexp_flonump(b))
    return a == SEXP_ZERO ? a
                          : sexp_make_flonum(ctx, sexp_fixnum_to_double(a) * sexp_flonum_value(b));
  return puchi_num_type_error(ctx, a);
}
sexp sexp_div(sexp ctx, sexp a, sexp b) {
  if (sexp_fixnump(a) && sexp_fixnump(b)) {
    if (b == SEXP_ZERO) return sexp_user_exception(ctx, NULL, "divide by zero", b);
    return sexp_fp_div(ctx, sexp_fixnum_to_flonum(ctx, a), sexp_fixnum_to_flonum(ctx, b));
  }
  if (sexp_flonump(a) && sexp_flonump(b)) return sexp_fp_div(ctx, a, b);
  if (sexp_flonump(a) && sexp_fixnump(b))
    return sexp_make_flonum(ctx, sexp_flonum_value(a) / sexp_fixnum_to_double(b));
  if (sexp_fixnump(a) && sexp_flonump(b))
    return sexp_make_flonum(ctx, sexp_fixnum_to_double(a) / sexp_flonum_value(b));
  return puchi_num_type_error(ctx, a);
}
sexp sexp_quotient(sexp ctx, sexp a, sexp b) {
  if (sexp_fixnump(a) && sexp_fixnump(b)) {
    if (b == SEXP_ZERO) return sexp_user_exception(ctx, NULL, "divide by zero", b);
    return sexp_fx_div(a, b);
  }
  return puchi_num_type_error(ctx, a);
}
sexp sexp_remainder(sexp ctx, sexp a, sexp b) {
  if (sexp_fixnump(a) && sexp_fixnump(b)) {
    if (b == SEXP_ZERO) return sexp_user_exception(ctx, NULL, "divide by zero", b);
    return sexp_fx_rem(a, b);
  }
  return puchi_num_type_error(ctx, a);
}
#endif /* SEXP_USE_FLONUMS */

sexp sexp_fixnum_to_bignum(sexp ctx, sexp a) {
  (void)ctx;
  return a;
}

sexp sexp_exact_sqrt(sexp ctx, sexp self, sexp_sint_t n, sexp z) {
#if SEXP_USE_FLONUMS && SEXP_USE_MATH
  sexp res, rem, root;
  res = sexp_inexact_sqrt(ctx, self, n, z);
  if (sexp_exceptionp(res)) return res;
  if (sexp_flonump(res))
    root = sexp_make_fixnum((sexp_sint_t)trunc(sexp_flonum_value(res)));
  else
    root = res;
  rem = sexp_mul(ctx, root, root);
  rem = sexp_sub(ctx, z, rem);
  return sexp_cons(ctx, root, rem);
#else
  sexp_sint_t v, r, rr;
  (void)n;
  if (!sexp_fixnump(z) || sexp_unbox_fixnum(z) < 0)
    return sexp_type_exception(ctx, self, SEXP_FIXNUM, z);
  v = sexp_unbox_fixnum(z);
  r = 0;
  while ((rr = (r + 1) * (r + 1)) > 0 && rr <= v) r++;
  return sexp_cons(ctx, sexp_make_fixnum(r), sexp_make_fixnum(v - r * r));
#endif
}
#endif /* !SEXP_USE_BIGNUMS */

EOF

  cat "$WORKDIR/init7_embed.c"

  cat <<'EOF'

sexp sexp_create_context(sexp_uint_t heap_size, sexp_uint_t heap_max_size) {
  sexp_scheme_init();
  return sexp_make_eval_context(NULL, NULL, NULL, heap_size, heap_max_size);
}

sexp sexp_delete_context(sexp ctx) {
  return sexp_destroy_context(ctx);
}

sexp sexp_load_default_libs(sexp ctx) {
  sexp env, res;
  sexp_gc_var5(ctx2, x, in, s, unused);
  if (!ctx || sexp_exceptionp(ctx)) return ctx;
  env = sexp_context_env(ctx);
  {
    sexp sym, tmp;
    sym = sexp_intern(ctx, "*shared-object-extension*", -1);
    tmp = sexp_c_string(ctx, sexp_so_extension, -1);
    sexp_env_define(ctx, env, sym, tmp);
    sym = sexp_intern(ctx, "*features*", -1);
    sexp_env_define(ctx, env, sym, sexp_global(ctx, SEXP_G_FEATURES));
  }
  sexp_gc_preserve5(ctx, ctx2, x, in, s, unused);
  (void)unused;
  res = SEXP_VOID;
  s = sexp_c_string(ctx, puchi_init7_scm, -1);
  in = sexp_open_input_string(ctx, s);
  if (sexp_exceptionp(in)) {
    sexp_gc_release5(ctx);
    return in;
  }
  ctx2 = sexp_make_eval_context(ctx, NULL, env, 0, 0);
  sexp_context_parent(ctx2) = ctx;
  sexp_context_tailp(ctx2) = 0;
  while ((x = sexp_read(ctx2, in)) != (sexp)SEXP_EOF) {
    res = sexp_exceptionp(x) ? x : sexp_eval(ctx2, x, env);
    if (sexp_exceptionp(res)) {
      sexp_gc_release5(ctx);
      return res;
    }
  }
  sexp_close_port(ctx, in);
  sexp_gc_release5(ctx);
  {
    sexp sym = sexp_intern(ctx, "current-exception-handler", -1);
    sexp_global(ctx, SEXP_G_ERR_HANDLER) = sexp_env_ref(ctx, env, sym, SEXP_FALSE);
  }
  sexp_set_parameter(ctx, env, sexp_global(ctx, SEXP_G_INTERACTION_ENV_SYMBOL), env);
  return env;
}

#ifdef __cplusplus
} /* extern "C" implementation */
#endif

#endif /* PUCHI_IMPLEMENTATION */

#endif /* PUCHI_H */
EOF
} > "$OUT_PUCHI"

echo "[puchi] stripping Plan 9 / Boehm / green threads / dlopen..."
"$PYTHON" "$HELPERS" strip-dead-backends "$OUT_PUCHI"

echo "[puchi] done."
wc -c -l "$OUT_PUCHI" | sed 's|^|  |'
echo "  Re-run after upstream updates: bash puchi/tools/amalgamate.sh"
