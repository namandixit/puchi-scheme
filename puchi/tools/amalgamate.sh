#!/usr/bin/env bash
# amalgamate.sh - build puchi.h from upstream Chibi without modifying
# upstream sources.
#
# Pipeline: copy → patches → mechanical rewrite → Scheme trim/embed →
#           concat product + transformed sources → strip-dead-backends.
#
# Usage (from anywhere): bash puchi/tools/amalgamate.sh
# Requires: bash, sed, patch (or git apply), python3 (Git Bash on Windows is fine).
set -euo pipefail

TOOLS="$(cd "$(dirname "$0")" && pwd)"
PUCHI="$(cd "$TOOLS/.." && pwd)"
CHIBI="$(cd "$PUCHI/.." && pwd)"
PRODUCT="$PUCHI/product"
PATCHES="$PUCHI/patches"
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

# Product feature forces (puchi-owned; not from upstream)
cp "$PRODUCT/puchi_features_force.h" "$WORKDIR/puchi_features_force.h"

# --- copy upstream headers/sources into workdir ---
cp "$CHIBI/include/chibi/sexp.h" "$WORKDIR/sexp.h"
cp "$CHIBI/eval.c" "$WORKDIR/eval.c"
cp "$CHIBI/gc.c" "$WORKDIR/gc.c"
cp "$CHIBI/sexp.c" "$WORKDIR/sexp.c"
cp "$CHIBI/opcodes.c" "$WORKDIR/opcodes.c"
cp "$CHIBI/vm.c" "$WORKDIR/vm.c"
cp "$CHIBI/simplify.c" "$WORKDIR/simplify.c"
cp "$CHIBI/include/chibi/features.h" "$WORKDIR/features.h"
cp "$CHIBI/include/chibi/eval.h" "$WORKDIR/eval.h"
cp "$CHIBI/include/chibi/bignum.h" "$WORKDIR/bignum.h"
cp "$CHIBI/include/chibi/sexp-huff.h" "$WORKDIR/sexp-huff.h"
cp "$CHIBI/include/chibi/sexp-unhuff.h" "$WORKDIR/sexp-unhuff.h"
cp "$CHIBI/include/chibi/sexp-hufftabs.h" "$WORKDIR/sexp-hufftabs.h"
cp "$CHIBI/include/chibi/sexp-hufftabdefs.h" "$WORKDIR/sexp-hufftabdefs.h"
cp "$CHIBI/include/chibi/sexp-hufftabs.c" "$WORKDIR/sexp-hufftabs.c"
cp "$CHIBI/bignum.c" "$WORKDIR/bignum.c"
# gc_heap.h intentionally omitted (image packing — empty / unused in puchi)

# --- apply unified diffs from puchi/patches/ (fail on reject) ---
apply_patches() {
  local n=0
  shopt -s nullglob
  local diffs=("$PATCHES"/*.diff)
  shopt -u nullglob
  if [ ${#diffs[@]} -eq 0 ]; then
    echo "[puchi] no patches in $PATCHES (ok during bootstrap)"
    return 0
  fi
  echo "[puchi] applying patches..."
  for diff in "${diffs[@]}"; do
    echo "  $(basename "$diff")"
    if command -v patch >/dev/null 2>&1; then
      patch -p0 -d "$WORKDIR" --batch --forward < "$diff"
    elif command -v git >/dev/null 2>&1; then
      git apply --unsafe-paths --directory="$WORKDIR" "$diff"
    else
      echo "error: need patch or git to apply $diff" >&2
      exit 1
    fi
    n=$((n + 1))
  done
  echo "[puchi] applied $n patch(es)"
}
apply_patches

# --- mechanical transforms (body forks live in puchi/patches/) ---
echo "[puchi] mechanical rewrites..."
"$PYTHON" "$HELPERS" scrub-features "$WORKDIR/features.h"
"$PYTHON" "$HELPERS" scrub-gc "$WORKDIR/gc.c"
"$PYTHON" "$HELPERS" patch-opcodes "$WORKDIR/opcodes.c"
"$PYTHON" "$HELPERS" brand-sexp "$WORKDIR/sexp.c"
# ABI-f splices for bignum.c / eval.c (sexp.h decl runs after bignum.h inject)

# Libc only through PUCHI_* wrappers (defaults in banner)
for f in sexp.c eval.c gc.c vm.c opcodes.c simplify.c bignum.c sexp.h; do
  if [ -f "$WORKDIR/$f" ]; then
    "$PYTHON" "$HELPERS" rewrite-libc "$WORKDIR/$f"
  fi
done

# Host allocators (gc.c / sexp.c malloc→SEXP_MALLOC)
for f in gc.c sexp.c eval.c; do
  if [ -f "$WORKDIR/$f" ]; then
    "$PYTHON" "$HELPERS" rewrite-alloc "$WORKDIR/$f"
  fi
done

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
# Banner already has stdint.h (CUSTOM_LONG_LONGS needs the types, not a second include).
bignum_h = bignum_h.replace("#include <stdint.h>\n", "/* puchi: stdint.h in banner */\n")
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

# Re-gate sexp_to_double / exact-sqrt + flonum-only decl (after bignum.h inject)
"$PYTHON" "$HELPERS" splice-abi-f "$WORKDIR"
# Splice may insert fresh libc calls; rewrite again on touched files
"$PYTHON" "$HELPERS" rewrite-libc "$WORKDIR/eval.c"
"$PYTHON" "$HELPERS" rewrite-libc "$WORKDIR/bignum.c"

for f in sexp.h eval.h bignum.h features.h gc.c sexp.c eval.c \
         opcodes.c vm.c simplify.c bignum.c; do
  sed_inplace "$WORKDIR/$f" \
    -e 's|#include "chibi/features.h"|/* amalgamated features.h */|' \
    -e 's|#include "chibi/install.h"|/* amalgamated install.h */|' \
    -e 's|#include "chibi/sexp.h"|/* amalgamated sexp.h */|' \
    -e 's|#include "chibi/eval.h"|/* amalgamated eval.h */|' \
    -e 's|#include "chibi/bignum.h"|/* amalgamated bignum.h */|' \
    -e 's|#include "chibi/gc_heap.h"|/* puchi: no gc_heap.h */|' \
    -e 's|#include "chibi/sexp-hufftabdefs.h"|/* amalgamated sexp-hufftabdefs.h */|'
done

# Inline opt/fcall.c and opt/opcode_names.h (true single-header)
"$PYTHON" - "$WORKDIR" "$CHIBI" <<'PY'
import sys
from pathlib import Path
wd, chibi = Path(sys.argv[1]), Path(sys.argv[2])
vm = (wd / "vm.c").read_text(encoding="utf-8")
fcall = (chibi / "opt" / "fcall.c").read_text(encoding="utf-8")
old = '#include "opt/fcall.c"\n'
if old not in vm:
    raise SystemExit("opt/fcall.c include not found in vm.c")
vm = vm.replace(
    old,
    "/* ---- opt/fcall.c (amalgamated) ---- */\n" + fcall + "\n",
    1,
)
vm = vm.replace('#include "opt/x86.c"\n', "/* puchi: no native x86 backend */\n")
(wd / "vm.c").write_text(vm, encoding="utf-8")
ev = (wd / "eval.c").read_text(encoding="utf-8")
names = (chibi / "opt" / "opcode_names.h").read_text(encoding="utf-8")
old_n = '#include "opt/opcode_names.h"\n'
if old_n not in ev:
    raise SystemExit("opt/opcode_names.h include not found in eval.c")
ev = ev.replace(
    old_n,
    "#if SEXP_USE_STATIC_LIBS\n"
    "/* ---- opt/opcode_names.h (amalgamated; harness STATIC_LIBS) ---- */\n"
    + names
    + "#endif\n",
    1,
)
(wd / "eval.c").write_text(ev, encoding="utf-8")
print("inlined opt/fcall.c and opt/opcode_names.h")
PY

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

echo "[puchi] embedding trimmed meta-7.scm..."
"$PYTHON" "$HELPERS" trim-meta "$CHIBI/lib/meta-7.scm" "$WORKDIR/meta-7-trimmed.scm"
"$PYTHON" "$HELPERS" embed puchi_meta7_scm "$WORKDIR/meta-7-trimmed.scm" "$WORKDIR/meta7_embed.c"

echo "[puchi] writing puchi.h..."
{
  cat "$PRODUCT/puchi_banner.h.in"

  echo "/* ==== puchi feature forces ==== */"
  cat "$WORKDIR/puchi_features_force.h"

  echo "/* ==== resolved feature flags (from features.h; manual omitted) ==== */"
  cat "$WORKDIR/features.h"

  echo "/* ==== sexp.h (bignum.h inlined mid-file under SEXP_USE_BIGNUMS) ==== */"
  cat "$WORKDIR/sexp.h"

  echo "/* ==== eval.h ==== */"
  cat "$WORKDIR/eval.h"

  cat "$PRODUCT/puchi_api_decls.inc"
  echo

  echo "/* ==== gc.c ==== */"
  cat "$WORKDIR/gc.c"

  echo "/* ==== puchi #e mul (F∧¬B; before sexp.c call sites) ==== */"
  cat "$PRODUCT/puchi_fx_or_fl_mul.inc"
  echo

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

  cat "$WORKDIR/init7_embed.c"
  cat "$WORKDIR/meta7_embed.c"

  echo
  cat "$PRODUCT/puchi_api.inc"
  echo

  cat "$PRODUCT/puchi_enable_modules.inc"
  echo

  cat <<'EOF'
#ifdef __cplusplus
} /* extern "C" implementation */
#endif

#endif /* PUCHI_IMPLEMENTATION */

#endif /* PUCHI_H */
EOF
} > "$OUT_PUCHI"

echo "[puchi] stripping Plan 9 / Boehm / green threads / dlopen..."
"$PYTHON" "$HELPERS" strip-dead-backends "$OUT_PUCHI"

echo "[puchi] post-strip scrub + single-header assert..."
"$PYTHON" "$HELPERS" post-strip-puchi "$OUT_PUCHI"

echo "[puchi] done."
wc -c -l "$OUT_PUCHI" | sed 's|^|  |'
echo "  Re-run after upstream updates: bash puchi/tools/amalgamate.sh"
