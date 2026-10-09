#!/usr/bin/env python3
"""Helpers for amalgamate.sh — embed Scheme, mechanical rewrites, strip dead backends.

Body forks live in puchi/patches/. Product API lives in puchi/product/.
This module is mechanical only (no curated host/port forks).
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from puchi_fold_sexp_use import (
    assert_no_sexp_use,
    fix_sexp_use_c_rvalues,
    scrub_sexp_use_comments,
    scrub_sexp_use_defines,
    strip_dead_backends,
)
from puchi_host_embed import (
    brand_puchi_features,
    fold_always_zero_type_slots,
    patch_opcodes,
    rewrite_host_allocators,
    rewrite_libc_calls,
    trim_init7_load_port,
)
from puchi_strip_gunk import (
    assert_no_chibi_api_leak,
    assert_finalize_fileno_macro,
    assert_no_enum_tag_typedef_aliases,
    assert_no_os_residue,
    assert_no_process_globals,
    assert_no_project_includes,
    scrub_amalgamation_residue,
    scrub_shipped_always_zero_defines,
    trim_init7_dead_arms,
)


def c_escape(s: str) -> str:
    out = []
    for ch in s:
        o = ord(ch)
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif o < 32 or o > 126:
            out.append(f"\\x{o:02x}")
        else:
            out.append(ch)
    return "".join(out)


def normalize_newlines(text: str) -> str:
    """Collapse CRLF/CR to LF so Windows rewrites do not invent blank lines."""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def write_text_lf(path: Path, text: str) -> None:
    """Write UTF-8 text with LF newlines (avoid Path.write_text CRLF on Windows)."""
    path.write_bytes(normalize_newlines(text).encode("utf-8"))


def embed_c_string(name: str, text: str) -> str:
    """Emit a static const char name[] = "..."; one C string per source line.

    Each substring is a single line of the embedded text (including its
    trailing newline and leading indentation) so the C form stays readable.
    Wrapped to silence Clang -Woverlength-strings (ISO C99 4095 limit).
    """
    text = normalize_newlines(text)
    lines = [
        "#ifdef __clang__",
        "#pragma clang diagnostic push",
        '#pragma clang diagnostic ignored "-Woverlength-strings"',
        "#endif",
        f"static const char {name}[] =",
    ]
    parts = text.splitlines(keepends=True)
    if not parts:
        lines.append('  ""')
    else:
        for part in parts:
            lines.append('  "' + c_escape(part) + '"')
    lines.append(";")
    lines.extend(
        [
            "#ifdef __clang__",
            "#pragma clang diagnostic pop",
            "#endif",
        ]
    )
    return "\n".join(lines) + "\n"


def trim_meta7(src: str) -> str:
    """Keep include-shared → load-modules; don't re-include disk init-7 for (chibi).

    Under PUCHI_TEST, find-module-file resolves *.so via the per-heap static library list.
    *chibi-env* is already a snapshot of interaction (embedded init-7); including
    lib/init-7.scm from disk would reload the untrimmed stock file and break loads.
    """
    out = normalize_newlines(src)
    if "((include-shared)\n              (load-modules (cdr x) *shared-object-extension* #f))" not in out:
        raise SystemExit("trim_meta7: include-shared arm not found")
    if "((include-shared-optionally)\n" not in out:
        raise SystemExit("trim_meta7: include-shared-optionally arm not found")
    old_chibi = '(make-module #f *chibi-env* \'((include "init-7.scm")))'
    new_chibi = "(make-module #f *chibi-env* '())"
    if old_chibi not in out:
        raise SystemExit("trim_meta7: (chibi) make-module arm not found")
    out = out.replace(old_chibi, new_chibi, 1)
    out = trim_init7_dead_arms(out)
    return (
        ";; trimmed for puchi amalgamation - include-shared via PUCHI_TEST; "
        "(chibi) skips disk init-7\n" + out
    )


def splice_sexp_to_double(bignum_c: str) -> str:
    """Re-gate sexp_to_double so it builds under FLONUMS without BIGNUMS."""
    text = normalize_newlines(bignum_c)
    if "SEXP_USE_FLONUMS || SEXP_USE_BIGNUMS" in text and "sexp_to_double" in text:
        return text
    old = (
        "double sexp_to_double (sexp ctx, sexp x) {\n"
        "  if (sexp_flonump(x))\n"
        "    return sexp_flonum_value(x);\n"
        "  else if (sexp_fixnump(x))\n"
        "    return sexp_fixnum_to_double(x);\n"
        "  else if (sexp_bignump(x))\n"
        "    return sexp_bignum_to_double(x);\n"
        "#if SEXP_USE_RATIOS\n"
        "  else if (sexp_ratiop(x))\n"
        "    return sexp_ratio_to_double(ctx, x);\n"
        "#endif\n"
        "  else\n"
        "    return 0.0;\n"
        "}\n"
    )
    new = (
        "#endif /* SEXP_USE_BIGNUMS — reopen after sexp_to_double */\n"
        "\n"
        "#if SEXP_USE_FLONUMS || SEXP_USE_BIGNUMS\n"
        "double sexp_to_double (sexp ctx, sexp x) {\n"
        "  if (sexp_flonump(x))\n"
        "    return sexp_flonum_value(x);\n"
        "  else if (sexp_fixnump(x))\n"
        "    return sexp_fixnum_to_double(x);\n"
        "#if SEXP_USE_BIGNUMS\n"
        "  else if (sexp_bignump(x))\n"
        "    return sexp_bignum_to_double(x);\n"
        "#endif\n"
        "#if SEXP_USE_RATIOS\n"
        "  else if (sexp_ratiop(x))\n"
        "    return sexp_ratio_to_double(ctx, x);\n"
        "#endif\n"
        "  else\n"
        "    return 0.0;\n"
        "}\n"
        "#endif /* SEXP_USE_FLONUMS || SEXP_USE_BIGNUMS */\n"
        "\n"
        "#if SEXP_USE_BIGNUMS\n"
    )
    if old not in text:
        raise SystemExit("splice_sexp_to_double: function body not found")
    return text.replace(old, new, 1)


def splice_exact_sqrt(eval_c: str) -> str:
    """Provide flonum/fixnum exact-sqrt when the bignum body is compiled out."""
    text = normalize_newlines(eval_c)
    if "SEXP_USE_MATH && !SEXP_USE_BIGNUMS" in text:
        return text
    marker = (
        "  sexp_gc_release2(ctx);\n"
        "  return res;\n"
        "}\n"
        "#endif\n"
        "\n"
        "sexp sexp_sqrt (sexp ctx, sexp self, sexp_sint_t n, sexp z) {"
    )
    insert = (
        "  sexp_gc_release2(ctx);\n"
        "  return res;\n"
        "}\n"
        "#endif\n"
        "\n"
        "#if SEXP_USE_MATH && !SEXP_USE_BIGNUMS\n"
        "sexp sexp_exact_sqrt (sexp ctx, sexp self, sexp_sint_t n, sexp z) {\n"
        "  sexp_gc_var2(res, rem);\n"
        "  sexp_gc_preserve2(ctx, res, rem);\n"
        "#if SEXP_USE_FLONUMS\n"
        "  res = sexp_inexact_sqrt(ctx, self, n, z);\n"
        "  if (sexp_exceptionp(res)) {\n"
        "    sexp_gc_release2(ctx);\n"
        "    return res;\n"
        "  }\n"
        "  if (sexp_flonump(res))\n"
        "    res = sexp_make_fixnum((sexp_sint_t)PUCHI_TRUNC(sexp_flonum_value(res)));\n"
        "  rem = sexp_fx_mul(res, res);\n"
        "  rem = sexp_fx_sub(z, rem);\n"
        "  if (sexp_negativep(rem)) {\n"
        "    res = sexp_fx_sub(res, SEXP_ONE);\n"
        "    rem = sexp_fx_mul(res, res);\n"
        "    rem = sexp_fx_sub(z, rem);\n"
        "  }\n"
        "  res = sexp_cons(ctx, res, rem);\n"
        "#else\n"
        "  sexp_sint_t v, r, rr;\n"
        "  (void)n;\n"
        "  if (!sexp_fixnump(z) || sexp_unbox_fixnum(z) < 0) {\n"
        "    sexp_gc_release2(ctx);\n"
        "    return sexp_type_exception(ctx, self, SEXP_FIXNUM, z);\n"
        "  }\n"
        "  v = sexp_unbox_fixnum(z);\n"
        "  r = 0;\n"
        "  while ((rr = (r + 1) * (r + 1)) > 0 && rr <= v) r++;\n"
        "  res = sexp_cons(ctx, sexp_make_fixnum(r), sexp_make_fixnum(v - r * r));\n"
        "#endif\n"
        "  sexp_gc_release2(ctx);\n"
        "  return res;\n"
        "}\n"
        "#endif\n"
        "\n"
        "sexp sexp_sqrt (sexp ctx, sexp self, sexp_sint_t n, sexp z) {"
    )
    if marker not in text:
        raise SystemExit("splice_exact_sqrt: marker after bignum exact_sqrt not found")
    return text.replace(marker, insert, 1)


def splice_to_double_decl(sexp_h: str) -> str:
    """Declare sexp_to_double when flonums are on but bignum.h is not included.

    bignum.h already declares sexp_to_double under #if SEXP_USE_BIGNUMS; that
    decl is invisible in ABI-f builds, so we always add a flonum-only decl
    outside the bignum gate (idempotent).
    """
    text = normalize_newlines(sexp_h)
    gate = "#if SEXP_USE_FLONUMS && !SEXP_USE_BIGNUMS\nSEXP_API double sexp_to_double"
    if gate in text:
        return text
    marker = "/***************************** predicates *****************************/"
    decl = (
        "#if SEXP_USE_FLONUMS && !SEXP_USE_BIGNUMS\n"
        "SEXP_API double sexp_to_double (sexp ctx, sexp x);\n"
        "#endif\n"
        "\n"
    )
    if marker not in text:
        raise SystemExit("splice_to_double_decl: predicates marker not found")
    return text.replace(marker, decl + marker, 1)


def splice_reader_mul(sexp_c: str) -> str:
    """Gate #e reader muls: B→sexp_mul, F∧¬B→product puchi_fx_or_fl_mul, else macro."""
    text = normalize_newlines(sexp_c)
    if "puchi_fx_or_fl_mul" in text:
        return text

    old_complex = (
        "        sexp_complex_real(den) = sexp_expt(ctx, SEXP_TEN, sexp_complex_real(den));\n"
        "        sexp_complex_real(den) = sexp_mul(ctx, res, sexp_complex_real(den));\n"
    )
    new_complex = (
        "        sexp_complex_real(den) = sexp_expt(ctx, SEXP_TEN, sexp_complex_real(den));\n"
        "#if SEXP_USE_BIGNUMS\n"
        "        sexp_complex_real(den) = sexp_mul(ctx, res, sexp_complex_real(den));\n"
        "#elif SEXP_USE_FLONUMS\n"
        "        sexp_complex_real(den) = puchi_fx_or_fl_mul(ctx, res, sexp_complex_real(den));\n"
        "#else\n"
        "        sexp_complex_real(den) = sexp_mul(ctx, res, sexp_complex_real(den));\n"
        "#endif\n"
    )
    old_else = (
        "        den = sexp_expt(ctx, SEXP_TEN, den);\n"
        "        res = sexp_mul(ctx, res, den);\n"
    )
    new_else = (
        "        den = sexp_expt(ctx, SEXP_TEN, den);\n"
        "#if SEXP_USE_BIGNUMS\n"
        "        res = sexp_mul(ctx, res, den);\n"
        "#elif SEXP_USE_FLONUMS\n"
        "        res = puchi_fx_or_fl_mul(ctx, res, den);\n"
        "#else\n"
        "        res = sexp_mul(ctx, res, den);\n"
        "#endif\n"
    )
    if old_complex not in text:
        raise SystemExit("splice_reader_mul: #e complex sexp_mul not found")
    if old_else not in text:
        raise SystemExit("splice_reader_mul: #e else sexp_mul not found")
    text = text.replace(old_complex, new_complex, 1)
    text = text.replace(old_else, new_else, 1)
    return text


def splice_min_fixnum_overflow(vm_c: str) -> str:
    """MIN_FIXNUM/-1: raise when ¬B instead of calling sexp_fixnum_to_bignum."""
    text = normalize_newlines(vm_c)
    if 'sexp_raise("integer overflow"' in text:
        return text
    old = (
        "      if (tmp1 == sexp_make_fixnum(SEXP_MIN_FIXNUM) && tmp2 == SEXP_NEG_ONE) {\n"
        "        _ARG1 = sexp_fixnum_to_bignum(ctx, tmp1);\n"
        "        sexp_negate_exact(_ARG1);\n"
        "      } else {\n"
        "        _ARG1 = sexp_fx_div(tmp1, tmp2);\n"
        "      }\n"
    )
    new = (
        "      if (tmp1 == sexp_make_fixnum(SEXP_MIN_FIXNUM) && tmp2 == SEXP_NEG_ONE) {\n"
        "#if SEXP_USE_BIGNUMS\n"
        "        _ARG1 = sexp_fixnum_to_bignum(ctx, tmp1);\n"
        "        sexp_negate_exact(_ARG1);\n"
        "#else\n"
        '        sexp_raise("integer overflow", sexp_list2(ctx, tmp1, tmp2));\n'
        "#endif\n"
        "      } else {\n"
        "        _ARG1 = sexp_fx_div(tmp1, tmp2);\n"
        "      }\n"
    )
    if text.count(old) != 2:
        raise SystemExit(
            f"splice_min_fixnum_overflow: expected 2 MIN_FIXNUM/-1 arms, found {text.count(old)}"
        )
    return text.replace(old, new)


def scrub_features_h(text: str) -> str:
    """Mechanical host scrub of upstream features.h (replaces 005-features-host.diff)."""
    text = normalize_newlines(text)

    start = text.find("/* uncomment this to disable most features */")
    end = text.find("/* the initial heap size in bytes */")
    if start < 0 or end < 0:
        raise SystemExit("scrub_features_h: comment catalog markers not found")
    catalog = (
        "/* Numeric modes are selected by PUCHI_* macros before including\n"
        " * puchi.h. Chibi's uncomment-to-enable feature notes are omitted;\n"
        " * they do not configure puchi. Heap-size knobs below are still live\n"
        " * #ifndef defaults.\n"
        " */\n\n"
    )
    text = text[:start] + catalog + text[end:]

    text = text.replace(
        "/* the default number of opcodes to run each thread for */\n"
        "#ifndef SEXP_DEFAULT_QUANTUM\n"
        "#define SEXP_DEFAULT_QUANTUM 500\n"
        "#endif\n\n",
        "\n",
    )
    text = text.replace(
        "/*         DEFAULTS - DO NOT MODIFY ANYTHING BELOW THIS LINE            */",
        "/* puchi: defaults (dead OS backends stripped by amalgamate) */",
    )

    bsd_old = (
        "#if defined(__APPLE__) || defined(__FreeBSD__) || defined(__NetBSD__) || defined(__DragonFly__) || defined(__OpenBSD__)\n"
        "#define SEXP_BSD 1\n"
        "#else\n"
        "#define SEXP_BSD 0\n"
        "#if ! defined(_GNU_SOURCE) && ! defined(_WIN32) && ! defined(PLAN9)\n"
        "#define _GNU_SOURCE\n"
        "#endif\n"
        "#endif\n"
        "\n"
        "/* Detect specific BSD */\n"
        "#if SEXP_BSD\n"
        "#if defined(__APPLE__)\n"
        "#define SEXP_DARWIN 1\n"
        "#define SEXP_FREEBSD 0\n"
        "#define SEXP_NETBSD 0\n"
        "#define SEXP_DRAGONFLY 0\n"
        "#define SEXP_OPENBSD 0\n"
        "#elif defined(__FreeBSD__)\n"
        "#define SEXP_DARWIN 0\n"
        "#define SEXP_FREEBSD 1\n"
        "#define SEXP_NETBSD 0\n"
        "#define SEXP_DRAGONFLY 0\n"
        "#define SEXP_OPENBSD 0\n"
        "#elif defined(__NetBSD__)\n"
        "#define SEXP_DARWIN 0\n"
        "#define SEXP_FREEBSD 0\n"
        "#define SEXP_NETBSD 1\n"
        "#define SEXP_DRAGONFLY 0\n"
        "#define SEXP_OPENBSD 0\n"
        "#elif defined(__DragonFly__)\n"
        "#define SEXP_DARWIN 0\n"
        "#define SEXP_FREEBSD 0\n"
        "#define SEXP_NETBSD 0\n"
        "#define SEXP_DRAGONFLY 1\n"
        "#define SEXP_OPENBSD 0\n"
        "#elif defined(__OpenBSD__)\n"
        "#define SEXP_DARWIN 0\n"
        "#define SEXP_FREEBSD 0\n"
        "#define SEXP_NETBSD 0\n"
        "#define SEXP_DRAGONFLY 0\n"
        "#define SEXP_OPENBSD 1\n"
        "#endif\n"
        "#endif\n"
    )
    bsd_new = "/* puchi: no host-OS feature probe; platform is \"puchi\"/\"portable\" */\n"
    if bsd_old not in text:
        raise SystemExit("scrub_features_h: BSD probe block not found")
    text = text.replace(bsd_old, bsd_new, 1)

    bit64_old = (
        "#ifndef SEXP_64_BIT\n"
        "#if defined(__amd64) || defined(__x86_64) || defined(_WIN64) || defined(_Wp64) || defined(__LP64__) || defined(__PPC64__) || defined(__mips64__) || defined(__sparc64__) || defined(__arm64)\n"
        "#define SEXP_64_BIT 1\n"
        "#else\n"
        "#define SEXP_64_BIT 0\n"
        "#endif\n"
        "#endif\n"
    )
    bit64_new = (
        "#ifndef SEXP_64_BIT\n"
        "#if UINTPTR_MAX > 0xFFFFFFFFu\n"
        "#define SEXP_64_BIT 1\n"
        "#else\n"
        "#define SEXP_64_BIT 0\n"
        "#endif\n"
        "#endif\n"
    )
    if bit64_old not in text:
        raise SystemExit("scrub_features_h: SEXP_64_BIT probe not found")
    text = text.replace(bit64_old, bit64_new, 1)

    cll_old = (
        "#ifndef SEXP_USE_CUSTOM_LONG_LONGS\n"
        "#if SEXP_64_BIT && !defined(__GNUC__)\n"
        "#define SEXP_USE_CUSTOM_LONG_LONGS 1\n"
        "#else\n"
        "#define SEXP_USE_CUSTOM_LONG_LONGS 0\n"
        "#endif\n"
        "#endif\n"
    )
    # Fold deletes the macro; keep only a comment so the workdir scrub succeeds.
    cll_new = "/* puchi: always portable {hi,lo} 128-bit limb pair */\n"
    if cll_old not in text:
        raise SystemExit("scrub_features_h: CUSTOM_LONG_LONGS block not found")
    text = text.replace(cll_old, cll_new, 1)

    align_old = (
        "#ifndef SEXP_USE_ALIGNED_BYTECODE\n"
        "#if defined(__arm__) || defined(__sparc__) || defined(__sparc64__) || defined(__mips__) || defined(__mips64__) || defined(__riscv)\n"
        "#define SEXP_USE_ALIGNED_BYTECODE 1\n"
        "#else\n"
        "#define SEXP_USE_ALIGNED_BYTECODE 0\n"
        "#endif\n"
        "#endif\n"
    )
    # Forced on in puchi_features_force.h; drop the CPU probe text.
    if align_old not in text:
        raise SystemExit("scrub_features_h: ALIGNED_BYTECODE probe not found")
    text = text.replace(align_old, "\n", 1)

    # Drop PLAN9 / Win32 libc polyfills and compiler #error (PUCHI_* covers libc).
    plan9_win = text.find("#ifdef PLAN9\n#define strcasecmp cistrcmp\n")
    if plan9_win < 0:
        raise SystemExit("scrub_features_h: PLAN9/Win32 polyfill block not found")
    win_end = text.find("\n#ifdef _WIN32\n#define sexp_pos_infinity", plan9_win)
    if win_end < 0:
        raise SystemExit("scrub_features_h: inf/nan block after polyfills not found")
    text = text[:plan9_win] + text[win_end + 1 :]

    inf_old = (
        "#ifdef _WIN32\n"
        "#define sexp_pos_infinity (DBL_MAX*DBL_MAX)\n"
        "#define sexp_neg_infinity -sexp_pos_infinity\n"
        "#define sexp_nan log(-2)\n"
        "#elif PLAN9\n"
        "#define sexp_pos_infinity Inf(1)\n"
        "#define sexp_neg_infinity Inf(-1)\n"
        "#define sexp_nan NaN()\n"
        "#else\n"
        "#define sexp_pos_infinity (1.0/0.0)\n"
        "#define sexp_neg_infinity -sexp_pos_infinity\n"
        "#define sexp_nan (0.0/0.0)\n"
        "#endif\n"
    )
    inf_new = (
        "/* puchi: IEEE-754 bit patterns under IMPLEMENTATION (puchi_f64_from_bits) */\n"
        "#if defined(PUCHI_IMPLEMENTATION)\n"
        "#define sexp_pos_infinity (puchi_f64_from_bits(0x7FF0000000000000ULL))\n"
        "#define sexp_neg_infinity (puchi_f64_from_bits(0xFFF0000000000000ULL))\n"
        "#define sexp_nan          (puchi_f64_from_bits(0x7FF8000000000000ULL))\n"
        "#endif\n"
    )
    if inf_old not in text:
        raise SystemExit("scrub_features_h: inf/nan block not found")
    text = text.replace(inf_old, inf_new, 1)

    for block in (
        "#ifndef sexp_default_user_module_path\n"
        '#define sexp_default_user_module_path "./lib:."\n'
        "#endif\n\n",
        "#ifndef SEXP_ALLOC_HISTOGRAM_BUCKETS\n"
        "#define SEXP_ALLOC_HISTOGRAM_BUCKETS 32\n"
        "#endif\n\n"
        "#ifndef SEXP_BACKTRACE_SIZE\n"
        "#define SEXP_BACKTRACE_SIZE 3\n"
        "#endif\n\n",
        "#ifndef SEXP_STRING_INDEX_TABLE_CHUNK_SIZE\n"
        "#define SEXP_STRING_INDEX_TABLE_CHUNK_SIZE 64\n"
        "#endif\n\n",
        "#ifndef SEXP_EPOCH_OFFSET\n"
        "#if SEXP_USE_2010_EPOCH\n"
        "#define SEXP_EPOCH_OFFSET 1262271600\n"
        "#else\n"
        "#define SEXP_EPOCH_OFFSET 0\n"
        "#endif\n"
        "#endif\n\n",
        "#ifndef SEXP_POLL_SLEEP_TIME\n"
        "#define SEXP_POLL_SLEEP_TIME 5000\n"
        "#define SEXP_POLL_SLEEP_TIME_MS 5\n"
        "#endif\n\n",
    ):
        if block in text:
            text = text.replace(block, "\n", 1)

    # PLAN9 / Win32 string macros → rely on PUCHI_* / rewrite_libc
    text = text.replace("#define strcasecmp cistrcmp\n", "/* puchi: use PUCHI_STRCASECMP */\n")
    text = text.replace("#define strncasecmp cistrncmp\n", "/* puchi: use PUCHI_STRNCASECMP */\n")
    text = text.replace("#define SHUT_RD 0 /* SD_RECEIVE */\n", "")
    text = text.replace("#define SHUT_WR 1 /* SD_SEND */\n", "")
    text = text.replace("#define SHUT_RDWR 2 /* SD_BOTH */\n", "")
    text = text.replace("#define strcasecmp _stricmp\n", "/* puchi: use PUCHI_STRCASECMP */\n")
    text = text.replace("#define strncasecmp _strnicmp\n", "/* puchi: use PUCHI_STRNCASECMP */\n")
    text = text.replace(
        "#define snprintf(buf, len, fmt, val) sprintf(buf, fmt, val)\n",
        "/* puchi: use PUCHI_SNPRINTF */\n",
    )
    text = text.replace("#define strcasecmp lstrcmpi\n", "/* puchi: use PUCHI_STRCASECMP */\n")
    text = text.replace(
        "#define strncasecmp(s1, s2, n) lstrcmpi(s1, s2)\n",
        "/* puchi: use PUCHI_STRNCASECMP */\n",
    )

    api_old = (
        "#ifdef _WIN32\n"
        "#ifdef SEXP_STATIC_LIBRARY\n"
        "#define SEXP_API    extern\n"
        "#else\n"
        "#ifdef BUILDING_DLL\n"
        "#define SEXP_API    __declspec(dllexport)\n"
        "#else\n"
        "#define SEXP_API    __declspec(dllimport)\n"
        "#endif\n"
        "#endif\n"
        "#else\n"
        "#define SEXP_API    extern\n"
        "#endif\n"
    )
    if api_old not in text:
        raise SystemExit("scrub_features_h: SEXP_API block not found")
    text = text.replace(api_old, "#define SEXP_API    extern\n", 1)

    abi_start = text.find("/************************************************************************/\n"
                          "/* Feature signature.")
    if abi_start < 0:
        raise SystemExit("scrub_features_h: ABI signature section not found")
    # Harness ABI types live in product/puchi_test_api.inc (before sexp.h).
    abi_new = (
        "\n"
        "/* puchi: ABI fingerprint omitted; see puchi_test_api.inc under PUCHI_TEST */\n"
    )
    text = text[:abi_start] + abi_new

    # Upstream uses SEXP_DEBUG_GC (typo/alias of USE_) ungated in a few #ifs.
    if "#define SEXP_DEBUG_GC" not in text:
        text += (
            "\n#ifndef SEXP_DEBUG_GC\n"
            "#define SEXP_DEBUG_GC 0\n"
            "#endif\n"
        )
    return text


def scrub_gc_host(gc_c: str) -> str:
    """Disable CHIBI_MAX_ALLOC getenv; allocators handled by rewrite_host_allocators."""
    text = normalize_newlines(gc_c)
    old = '    max_alloc = getenv("CHIBI_MAX_ALLOC");'
    new = "    max_alloc = NULL; /* puchi: no getenv heap cap */"
    if old not in text:
        raise SystemExit("scrub_gc_host: CHIBI_MAX_ALLOC getenv not found")
    return text.replace(old, new, 1)


def scrub_sexp_h(text: str) -> str:
    """Portable ABI layout in sexp.h: no OS/CPU/compiler typedef forks."""
    text = normalize_newlines(text)

    # Unused-param attribute → empty (call sites may use (void)).
    gnuc_old = (
        "#ifdef __GNUC__\n"
        "#define SEXP_NO_WARN_UNUSED __attribute__((unused))\n"
        "#else\n"
        "#define SEXP_NO_WARN_UNUSED\n"
        "#endif\n"
    )
    gnuc_new = "#define SEXP_NO_WARN_UNUSED\n"
    if gnuc_old not in text:
        # Already scrubbed or patched variant
        gnuc_old2 = (
            "#if defined(__GNUC__)\n"
            "#define SEXP_NO_WARN_UNUSED __attribute__((unused))\n"
            "#else\n"
            "#define SEXP_NO_WARN_UNUSED\n"
            "#endif\n"
        )
        if gnuc_old2 in text:
            text = text.replace(gnuc_old2, gnuc_new, 1)
        elif "#define SEXP_NO_WARN_UNUSED\n" not in text:
            raise SystemExit("scrub_sexp_h: SEXP_NO_WARN_UNUSED block not found")
    else:
        text = text.replace(gnuc_old, gnuc_new, 1)

    # Integer typedefs: one stdint layout from UINTPTR_MAX.
    # Match either stock or already-partially-stripped forms by anchoring on markers.
    m = re.search(
        r"#if(?:def)?\s+(?:defined\()?_WIN32.*?/\* procedure flags \*/",
        text,
        flags=re.DOTALL,
    )
    if not m:
        # Alternate: starts with #ifdef _WIN32 or #if defined(_WIN32)
        m = re.search(
            r"#if defined\(_WIN32\).*?/\* procedure flags \*/",
            text,
            flags=re.DOTALL,
        )
    if not m:
        raise SystemExit("scrub_sexp_h: integer typedef block not found")
    typedef_new = (
        "#if UINTPTR_MAX > 0xFFFFFFFFu\n"
        "typedef unsigned int sexp_tag_t;\n"
        "typedef uint64_t sexp_uint_t;\n"
        "typedef int64_t sexp_sint_t;\n"
        '#define SEXP_PRIdFIXNUM "lld"\n'
        "#else\n"
        "typedef unsigned short sexp_tag_t;\n"
        "typedef uint32_t sexp_uint_t;\n"
        "typedef int32_t sexp_sint_t;\n"
        '#define SEXP_PRIdFIXNUM "d"\n'
        "#endif\n"
        "#define sexp_heap_align(n) sexp_align(n, 5)\n"
        "#define sexp_heap_chunks(n) (sexp_heap_align(n)>>5)\n"
        "\n"
        "/* procedure flags */"
    )
    text = text[: m.start()] + typedef_new + text[m.end() :]

    # Always stdint for 8/32-bit lane types; drop ULONG_MAX fallbacks.
    inttypes_pat = re.compile(
        r"#if defined\(SEXP_USE_INTTYPES\)|#ifdef SEXP_USE_INTTYPES",
    )
    im = inttypes_pat.search(text)
    if not im:
        raise SystemExit("scrub_sexp_h: SEXP_USE_INTTYPES block not found")
    prid_m = re.search(
        r"#if \(?defined\(__APPLE__\)|#if defined\(__APPLE__\)",
        text[im.start() :],
    )
    if not prid_m:
        # After typedef scrub, look for PRIdOFF block
        prid_m = re.search(r"#if defined\(__APPLE__\)", text[im.start() :])
    if not prid_m:
        raise SystemExit("scrub_sexp_h: PRIdOFF / inttypes end not found")
    inttypes_end = im.start() + prid_m.start()
    inttypes_new = (
        "#if defined(SEXP_USE_INTTYPES)\n"
        "/* puchi: stdint.h in banner */\n"
        "#define SEXP_UINT8_DEFINED 1\n"
        "typedef uint8_t  sexp_uint8_t;\n"
        "#define SEXP_UINT32_DEFINED 1\n"
        "typedef uint32_t sexp_uint32_t;\n"
        "typedef int32_t sexp_int32_t;\n"
        "#endif\n"
        "\n"
    )
    # Prefer matching through end of the whole #ifdef SEXP_USE_INTTYPES ... #endif
    # and the following PRIdOFF block together.
    prid_block = re.search(
        r"#if \(defined\(__APPLE__\) \|\| defined\(_WIN64\)\) \|\| \(defined\(__CYGWIN__\) && \(__SIZEOF_POINTER__ == 8\)\)\n"
        r'#define SEXP_PRIdOFF "lld"\n'
        r"#else\n"
        r'#define SEXP_PRIdOFF "ld"\n'
        r"#endif\n",
        text,
    )
    if not prid_block:
        prid_block = re.search(
            r"#if defined\(__APPLE__\) \|\| defined\(_WIN64\) \|\| \(defined\(__CYGWIN__\) && __SIZEOF_POINTER__ == 8\)\n"
            r'#define SEXP_PRIdOFF "lld"\n'
            r"#else\n"
            r'#define SEXP_PRIdOFF "ld"\n'
            r"#endif\n",
            text,
        )
    if not prid_block:
        raise SystemExit("scrub_sexp_h: PRIdOFF block not found")

    # Replace from inttypes start through PRIdOFF end.
    prid_new = (
        "#if UINTPTR_MAX > 0xFFFFFFFFu\n"
        '#define SEXP_PRIdOFF "lld"\n'
        "#else\n"
        '#define SEXP_PRIdOFF "ld"\n'
        "#endif\n"
    )
    text = text[: im.start()] + inttypes_new + prid_new + text[prid_block.end() :]

    # Fileno: no separate Win32 sock field; sock accessor is the fd.
    text = re.sub(
        r"#if defined\(_WIN32\)\n\s*SOCKET_TYPE sock;\n#endif\n",
        "",
        text,
    )
    text = re.sub(
        r"#ifdef _WIN32\n\s*SOCKET_TYPE sock;\n#endif\n",
        "",
        text,
    )
    sock_acc_old = (
        "#if defined(PUCHI_TEST)\n"
        "#if defined(_WIN32)\n"
        "#define sexp_fileno_sock(f)      (sexp_pred_field(f, fileno, sexp_filenop, sock))\n"
        "#else\n"
        "#define sexp_fileno_sock(f)      (sexp_fileno_fd(f))\n"
        "#endif\n"
        "#endif\n"
    )
    sock_acc_new = (
        "#if defined(PUCHI_TEST)\n"
        "#define sexp_fileno_sock(f)      (sexp_fileno_fd(f))\n"
        "#endif\n"
    )
    if sock_acc_old in text:
        text = text.replace(sock_acc_old, sock_acc_new, 1)
    else:
        sock_acc_old2 = (
            "#ifdef _WIN32\n"
            "#define sexp_fileno_sock(f)      (sexp_pred_field(f, fileno, sexp_filenop, sock))\n"
            "#else\n"
            "#define sexp_fileno_sock(f)      (sexp_fileno_fd(f))\n"
            "#endif\n"
        )
        if sock_acc_old2 in text:
            text = text.replace(
                sock_acc_old2,
                "#define sexp_fileno_sock(f)      (sexp_fileno_fd(f))\n",
                1,
            )

    # Pedantic hygiene: rename reserved identifiers / fix GC-var extra-semi.
    text = _scrub_sexp_h_warning_hygiene(text)

    return text


def _scrub_sexp_h_warning_hygiene(text: str) -> str:
    """Rename reserved macros/ids and fix sexp_gc_var trailing-semicolon ;;."""
    text = text.replace("__HALF_MAX_SIGNED", "PUCHI_HALF_MAX_SIGNED")
    text = text.replace("__MAX_SIGNED", "PUCHI_MAX_SIGNED")
    text = text.replace("__MIN_SIGNED", "PUCHI_MIN_SIGNED")
    text = text.replace("_sexp_type_specs", "puchi_type_specs")

    # Native-GC sexp_gc_var: drop trailing ';' so callers' ';' is not empty.
    gc_var_old = (
        "#define sexp_gc_var(x, y)                       \\\n"
        "  sexp x = SEXP_VOID;                           \\\n"
        "  struct sexp_gc_var_t y = {NULL, NULL};\n"
    )
    gc_var_new = (
        "#define sexp_gc_var(x, y)                       \\\n"
        "  sexp x = SEXP_VOID;                           \\\n"
        "  struct sexp_gc_var_t y = {NULL, NULL}\n"
    )
    if gc_var_old not in text:
        raise SystemExit("scrub_sexp_h: sexp_gc_var macro not found")
    text = text.replace(gc_var_old, gc_var_new, 1)

    # Boehm stub path (usually stripped later): same trailing-'; issue.
    text = text.replace(
        "#define sexp_gc_var(x, y)            sexp x = SEXP_VOID;\n",
        "#define sexp_gc_var(x, y)            sexp x = SEXP_VOID\n",
    )

    gc_macros_old = (
        "#define sexp_gc_var1(x) sexp_gc_var(x, __sexp_gc_preserver1)\n"
        "#define sexp_gc_var2(x, y) sexp_gc_var1(x) sexp_gc_var(y, __sexp_gc_preserver2)\n"
        "#define sexp_gc_var3(x, y, z) sexp_gc_var2(x, y) sexp_gc_var(z, __sexp_gc_preserver3)\n"
        "#define sexp_gc_var4(x, y, z, w) sexp_gc_var3(x, y, z) sexp_gc_var(w, __sexp_gc_preserver4)\n"
        "#define sexp_gc_var5(x, y, z, w, v) sexp_gc_var4(x, y, z, w) sexp_gc_var(v, __sexp_gc_preserver5)\n"
        "#define sexp_gc_var6(x, y, z, w, v, u) sexp_gc_var5(x, y, z, w, v) sexp_gc_var(u, __sexp_gc_preserver6)\n"
        "#define sexp_gc_var7(x, y, z, w, v, u, t) sexp_gc_var6(x, y, z, w, v, u) sexp_gc_var(t, __sexp_gc_preserver7)\n"
        "\n"
        "#define sexp_gc_preserve1(ctx, x) sexp_gc_preserve(ctx, x, __sexp_gc_preserver1)\n"
        "#define sexp_gc_preserve2(ctx, x, y) sexp_gc_preserve1(ctx, x); sexp_gc_preserve(ctx, y, __sexp_gc_preserver2)\n"
        "#define sexp_gc_preserve3(ctx, x, y, z) sexp_gc_preserve2(ctx, x, y); sexp_gc_preserve(ctx, z, __sexp_gc_preserver3)\n"
        "#define sexp_gc_preserve4(ctx, x, y, z, w) sexp_gc_preserve3(ctx, x, y, z); sexp_gc_preserve(ctx, w, __sexp_gc_preserver4)\n"
        "#define sexp_gc_preserve5(ctx, x, y, z, w, v) sexp_gc_preserve4(ctx, x, y, z, w); sexp_gc_preserve(ctx, v, __sexp_gc_preserver5)\n"
        "#define sexp_gc_preserve6(ctx, x, y, z, w, v, u) sexp_gc_preserve5(ctx, x, y, z, w, v); sexp_gc_preserve(ctx, u, __sexp_gc_preserver6)\n"
        "#define sexp_gc_preserve7(ctx, x, y, z, w, v, u, t) sexp_gc_preserve6(ctx, x, y, z, w, v, u); sexp_gc_preserve(ctx, t, __sexp_gc_preserver7)\n"
        "\n"
        "#define sexp_gc_release1(ctx) sexp_gc_release(ctx, NULL, __sexp_gc_preserver1)\n"
        "#define sexp_gc_release2(ctx) sexp_gc_release(ctx, NULL, __sexp_gc_preserver1)\n"
        "#define sexp_gc_release3(ctx) sexp_gc_release(ctx, NULL, __sexp_gc_preserver1)\n"
        "#define sexp_gc_release4(ctx) sexp_gc_release(ctx, NULL, __sexp_gc_preserver1)\n"
        "#define sexp_gc_release5(ctx) sexp_gc_release(ctx, NULL, __sexp_gc_preserver1)\n"
        "#define sexp_gc_release6(ctx) sexp_gc_release(ctx, NULL, __sexp_gc_preserver1)\n"
        "#define sexp_gc_release7(ctx) sexp_gc_release(ctx, NULL, __sexp_gc_preserver1)\n"
    )
    gc_macros_new = (
        "#define sexp_gc_var1(x) sexp_gc_var(x, puchi_gc_preserver1)\n"
        "#define sexp_gc_var2(x, y) sexp_gc_var1(x); sexp_gc_var(y, puchi_gc_preserver2)\n"
        "#define sexp_gc_var3(x, y, z) sexp_gc_var2(x, y); sexp_gc_var(z, puchi_gc_preserver3)\n"
        "#define sexp_gc_var4(x, y, z, w) sexp_gc_var3(x, y, z); sexp_gc_var(w, puchi_gc_preserver4)\n"
        "#define sexp_gc_var5(x, y, z, w, v) sexp_gc_var4(x, y, z, w); sexp_gc_var(v, puchi_gc_preserver5)\n"
        "#define sexp_gc_var6(x, y, z, w, v, u) sexp_gc_var5(x, y, z, w, v); sexp_gc_var(u, puchi_gc_preserver6)\n"
        "#define sexp_gc_var7(x, y, z, w, v, u, t) sexp_gc_var6(x, y, z, w, v, u); sexp_gc_var(t, puchi_gc_preserver7)\n"
        "\n"
        "#define sexp_gc_preserve1(ctx, x) sexp_gc_preserve(ctx, x, puchi_gc_preserver1)\n"
        "#define sexp_gc_preserve2(ctx, x, y) sexp_gc_preserve1(ctx, x); sexp_gc_preserve(ctx, y, puchi_gc_preserver2)\n"
        "#define sexp_gc_preserve3(ctx, x, y, z) sexp_gc_preserve2(ctx, x, y); sexp_gc_preserve(ctx, z, puchi_gc_preserver3)\n"
        "#define sexp_gc_preserve4(ctx, x, y, z, w) sexp_gc_preserve3(ctx, x, y, z); sexp_gc_preserve(ctx, w, puchi_gc_preserver4)\n"
        "#define sexp_gc_preserve5(ctx, x, y, z, w, v) sexp_gc_preserve4(ctx, x, y, z, w); sexp_gc_preserve(ctx, v, puchi_gc_preserver5)\n"
        "#define sexp_gc_preserve6(ctx, x, y, z, w, v, u) sexp_gc_preserve5(ctx, x, y, z, w, v); sexp_gc_preserve(ctx, u, puchi_gc_preserver6)\n"
        "#define sexp_gc_preserve7(ctx, x, y, z, w, v, u, t) sexp_gc_preserve6(ctx, x, y, z, w, v, u); sexp_gc_preserve(ctx, t, puchi_gc_preserver7)\n"
        "\n"
        "#define sexp_gc_release1(ctx) sexp_gc_release(ctx, NULL, puchi_gc_preserver1)\n"
        "#define sexp_gc_release2(ctx) sexp_gc_release(ctx, NULL, puchi_gc_preserver1)\n"
        "#define sexp_gc_release3(ctx) sexp_gc_release(ctx, NULL, puchi_gc_preserver1)\n"
        "#define sexp_gc_release4(ctx) sexp_gc_release(ctx, NULL, puchi_gc_preserver1)\n"
        "#define sexp_gc_release5(ctx) sexp_gc_release(ctx, NULL, puchi_gc_preserver1)\n"
        "#define sexp_gc_release6(ctx) sexp_gc_release(ctx, NULL, puchi_gc_preserver1)\n"
        "#define sexp_gc_release7(ctx) sexp_gc_release(ctx, NULL, puchi_gc_preserver1)\n"
    )
    if gc_macros_old not in text:
        raise SystemExit("scrub_sexp_h: sexp_gc_varN / preserveN macros not found")
    text = text.replace(gc_macros_old, gc_macros_new, 1)
    return text


def scrub_bignum_h(text: str) -> str:
    """Always use the portable 128-bit struct; delete mode(TI) / long-long arms."""
    text = normalize_newlines(text)
    old = (
        "#if SEXP_USE_CUSTOM_LONG_LONGS\n"
        "/* puchi: stdint.h in banner */\n"
        "typedef struct\n"
        "{\n"
        "  uint64_t hi;\n"
        "  uint64_t lo;\n"
        "} sexp_luint_t;\n"
        "typedef struct\n"
        "{\n"
        "  int64_t  hi;\n"
        "  uint64_t lo;\n"
        "} sexp_lsint_t;\n"
        "#elif SEXP_64_BIT\n"
        "typedef unsigned int uint128_t __attribute__((mode(TI)));\n"
        "typedef int sint128_t __attribute__((mode(TI)));\n"
        "typedef uint128_t sexp_luint_t;\n"
        "typedef sint128_t sexp_lsint_t;\n"
        "#else\n"
        "typedef unsigned long long sexp_luint_t;\n"
        "typedef long long sexp_lsint_t;\n"
        "#endif\n"
    )
    # Upstream before stdint scrub:
    old_up = (
        "#if SEXP_USE_CUSTOM_LONG_LONGS\n"
        "#ifdef PLAN9\n"
        "#include <ape/stdint.h>\n"
        "#else\n"
        "#include <stdint.h>\n"
        "#endif\n"
        "typedef struct\n"
        "{\n"
        "  uint64_t hi;\n"
        "  uint64_t lo;\n"
        "} sexp_luint_t;\n"
        "typedef struct\n"
        "{\n"
        "  int64_t  hi;\n"
        "  uint64_t lo;\n"
        "} sexp_lsint_t;\n"
        "#elif SEXP_64_BIT\n"
        "typedef unsigned int uint128_t __attribute__((mode(TI)));\n"
        "typedef int sint128_t __attribute__((mode(TI)));\n"
        "typedef uint128_t sexp_luint_t;\n"
        "typedef sint128_t sexp_lsint_t;\n"
        "#else\n"
        "typedef unsigned long long sexp_luint_t;\n"
        "typedef long long sexp_lsint_t;\n"
        "#endif\n"
    )
    new = (
        "/* puchi: always portable 128-bit limb pair */\n"
        "typedef struct\n"
        "{\n"
        "  uint64_t hi;\n"
        "  uint64_t lo;\n"
        "} sexp_luint_t;\n"
        "typedef struct\n"
        "{\n"
        "  int64_t  hi;\n"
        "  uint64_t lo;\n"
        "} sexp_lsint_t;\n"
    )
    if old in text:
        text = text.replace(old, new, 1)
    elif old_up in text:
        text = text.replace(old_up, new, 1)
    else:
        raise SystemExit("scrub_bignum_h: long-long typedef block not found")
    return text


def trim_init7(src: str) -> str:
    """Remove file/load helpers and stub (library) in cond-expand."""
    # Delete call-with-*-file / with-*-file (no error stubs).
    deletions = [
        r"\(define \(call-with-input-file file proc\)\n"
        r"  \(let\* \(\(in \(open-input-file file\)\)\n"
        r"         \(res \(proc in\)\)\)\n"
        r"    \(close-input-port in\)\n"
        r"    res\)\)\n",
        r"\(define \(call-with-output-file file proc\)\n"
        r"  \(let\* \(\(out \(open-output-file file\)\)\n"
        r"         \(res \(proc out\)\)\)\n"
        r"    \(close-output-port out\)\n"
        r"    res\)\)\n",
        r"\(define \(with-input-from-file file thunk\)\n"
        r"  \(let \(\(old-in \(current-input-port\)\)\n"
        r"        \(tmp-in \(open-input-file file\)\)\)\n"
        r"    \(dynamic-wind\n"
        r"      \(lambda \(\) \(current-input-port tmp-in\)\)\n"
        r"      \(lambda \(\) \(let \(\(res \(thunk\)\)\) \(close-input-port tmp-in\) res\)\)\n"
        r"      \(lambda \(\) \(current-input-port old-in\)\)\)\)\)\n",
        r"\(define \(with-output-to-file file thunk\)\n"
        r"  \(let \(\(old-out \(current-output-port\)\)\n"
        r"        \(tmp-out \(open-output-file file\)\)\)\n"
        r"    \(dynamic-wind\n"
        r"      \(lambda \(\) \(current-output-port tmp-out\)\)\n"
        r"      \(lambda \(\) \(let \(\(res \(thunk\)\)\) \(close-output-port tmp-out\) res\)\)\n"
        r"      \(lambda \(\) \(current-output-port old-out\)\)\)\)\)\n",
    ]
    out = src
    for pat in deletions:
        out2, n = re.subn(pat, "", out, count=1, flags=re.MULTILINE)
        if n == 0:
            raise SystemExit(f"trim_init7 pattern not matched:\n{pat[:80]}...")
        out = out2

    # Replace (define (load ... entire definition with stub
    load_start = out.find("(define (load file . o)")
    if load_start < 0:
        raise SystemExit("trim_init7: load definition not matched")
    # End at the blank line / section after the closing parens of load
    marker = "\n;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;\n;; promises"
    load_end = out.find(marker, load_start)
    if load_end < 0:
        raise SystemExit("trim_init7: load definition end marker not found")
    stub = (
        "(define (load file . o)\n"
        "  (error \"load: not available in puchi core; host/harness may redefine\" file))\n"
    )
    out = out[:load_start] + stub + out[load_end:]

    # Stub (library) feature in cond-expand:
    # ((library) (eval `(find-module ',(cadr x)) (%meta-env)))
    lib_line = "((library) (eval `(find-module ',(cadr x)) (%meta-env)))"
    if lib_line in out:
        out = out.replace(lib_line, "((library) #f)", 1)
    else:
        idx = out.find("((library)")
        if idx >= 0:
            line_start = out.rfind("\n", 0, idx) + 1
            line_end = out.find("\n", idx)
            out = out[:line_start] + "             ((library) #f)\n" + out[line_end + 1 :]
        else:
            raise SystemExit("trim_init7: (library) cond-expand clause not found")

    # Stock and/or use cond; bootstrap still needs if-style (er-macro + qq).
    and_old = (
        "(define-syntax and\n"
        "  (er-macro-transformer\n"
        "   (lambda (expr rename compare)\n"
        "     (cond ((null? (cdr expr)))\n"
        "           ((null? (cddr expr)) (cadr expr))\n"
        "           (else (list (rename 'if) (cadr expr)\n"
        "                       (cons (rename 'and) (cddr expr))\n"
        "                       #f))))))\n"
    )
    and_new = (
        "(define-syntax and\n"
        "  (er-macro-transformer\n"
        "   (lambda (expr rename compare)\n"
        "     (if (null? (cdr expr))\n"
        "         #t\n"
        "         (if (null? (cddr expr))\n"
        "             (cadr expr)\n"
        "             (list (rename 'if) (cadr expr)\n"
        "                   (cons (rename 'and) (cddr expr))\n"
        "                   #f))))))\n"
    )
    or_old = (
        "(define-syntax or\n"
        "  (er-macro-transformer\n"
        "   (lambda (expr rename compare)\n"
        "     (cond ((null? (cdr expr)) #f)\n"
        "           ((null? (cddr expr)) (cadr expr))\n"
        "           (else\n"
        "            (list (rename 'let) (list (list (rename 'tmp) (cadr expr)))\n"
        "                  (list (rename 'if) (rename 'tmp)\n"
        "                        (rename 'tmp)\n"
        "                        (cons (rename 'or) (cddr expr)))))))))\n"
    )
    or_new = (
        "(define-syntax or\n"
        "  (er-macro-transformer\n"
        "   (lambda (expr rename compare)\n"
        "     (if (null? (cdr expr))\n"
        "         #f\n"
        "         (if (null? (cddr expr))\n"
        "             (cadr expr)\n"
        "             (list (rename 'let) (list (list (rename 'tmp) (cadr expr)))\n"
        "                   (list (rename 'if) (rename 'tmp)\n"
        "                         (rename 'tmp)\n"
        "                         (cons (rename 'or) (cddr expr)))))))))\n"
    )
    if and_old not in out:
        raise SystemExit("trim_init7: stock and form not found")
    if or_old not in out:
        raise SystemExit("trim_init7: stock or form not found")
    out = out.replace(and_old, and_new, 1)
    out = out.replace(or_old, or_new, 1)

    out = (
        ";; trimmed for puchi amalgamation - file/load/library stubs\n" + out
    )
    return trim_init7_dead_arms(trim_init7_load_port(out))




def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("trim-init")
    p.add_argument("input")
    p.add_argument("output")

    p = sub.add_parser("trim-meta")
    p.add_argument("input")
    p.add_argument("output")

    p = sub.add_parser("embed")
    p.add_argument("name")
    p.add_argument("input")
    p.add_argument("output")

    p = sub.add_parser("strip-dead-backends")
    p.add_argument("path")

    p = sub.add_parser("rewrite-libc")
    p.add_argument("path")

    p = sub.add_parser("rewrite-alloc")
    p.add_argument("path")

    p = sub.add_parser("patch-opcodes")
    p.add_argument("path")

    p = sub.add_parser("scrub-features")
    p.add_argument("path")

    p = sub.add_parser("scrub-sexp")
    p.add_argument("path")

    p = sub.add_parser("scrub-bignum")
    p.add_argument("path")

    p = sub.add_parser("scrub-gc")
    p.add_argument("path")

    p = sub.add_parser("splice-abi-f")
    p.add_argument("workdir")

    p = sub.add_parser("brand-sexp")
    p.add_argument("path")

    p = sub.add_parser("post-strip-puchi")
    p.add_argument("path")

    args = ap.parse_args()
    if args.cmd == "trim-init":
        text = Path(args.input).read_text(encoding="utf-8")
        write_text_lf(Path(args.output), trim_init7(text))
    elif args.cmd == "trim-meta":
        text = Path(args.input).read_text(encoding="utf-8")
        write_text_lf(Path(args.output), trim_meta7(text))
    elif args.cmd == "embed":
        text = Path(args.input).read_text(encoding="utf-8")
        write_text_lf(Path(args.output), embed_c_string(args.name, text))
    elif args.cmd == "strip-dead-backends":
        path = Path(args.path)
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("cp1252")
        write_text_lf(path, strip_dead_backends(normalize_newlines(text)))
    elif args.cmd == "rewrite-libc":
        path = Path(args.path)
        write_text_lf(path, rewrite_libc_calls(path.read_text(encoding="utf-8")))
    elif args.cmd == "rewrite-alloc":
        path = Path(args.path)
        write_text_lf(path, rewrite_host_allocators(path.read_text(encoding="utf-8")))
    elif args.cmd == "patch-opcodes":
        path = Path(args.path)
        write_text_lf(path, patch_opcodes(path.read_text(encoding="utf-8")))
    elif args.cmd == "scrub-features":
        path = Path(args.path)
        write_text_lf(path, scrub_features_h(path.read_text(encoding="utf-8")))
    elif args.cmd == "scrub-sexp":
        path = Path(args.path)
        write_text_lf(path, scrub_sexp_h(path.read_text(encoding="utf-8")))
    elif args.cmd == "scrub-bignum":
        path = Path(args.path)
        write_text_lf(path, scrub_bignum_h(path.read_text(encoding="utf-8")))
    elif args.cmd == "scrub-gc":
        path = Path(args.path)
        write_text_lf(path, scrub_gc_host(path.read_text(encoding="utf-8")))
    elif args.cmd == "splice-abi-f":
        wd = Path(args.workdir)
        write_text_lf(wd / "bignum.c", splice_sexp_to_double((wd / "bignum.c").read_text(encoding="utf-8")))
        write_text_lf(wd / "eval.c", splice_exact_sqrt((wd / "eval.c").read_text(encoding="utf-8")))
        write_text_lf(wd / "sexp.h", splice_to_double_decl((wd / "sexp.h").read_text(encoding="utf-8")))
        write_text_lf(wd / "sexp.c", splice_reader_mul((wd / "sexp.c").read_text(encoding="utf-8")))
        write_text_lf(wd / "vm.c", splice_min_fixnum_overflow((wd / "vm.c").read_text(encoding="utf-8")))
    elif args.cmd == "brand-sexp":
        path = Path(args.path)
        text = brand_puchi_features(path.read_text(encoding="utf-8"))
        text = fold_always_zero_type_slots(text)
        write_text_lf(path, text)
    elif args.cmd == "post-strip-puchi":
        path = Path(args.path)
        text = normalize_newlines(path.read_text(encoding="utf-8"))
        text = fix_sexp_use_c_rvalues(text)
        text = scrub_sexp_use_defines(text)
        text = scrub_sexp_use_comments(text)
        text = scrub_shipped_always_zero_defines(text)
        text = scrub_amalgamation_residue(text)
        assert_no_project_includes(text)
        assert_no_os_residue(text)
        assert_no_sexp_use(text)
        assert_no_process_globals(text)
        assert_no_chibi_api_leak(text)
        assert_finalize_fileno_macro(text)
        assert_no_enum_tag_typedef_aliases(text)
        write_text_lf(path, text)


if __name__ == "__main__":
    main()