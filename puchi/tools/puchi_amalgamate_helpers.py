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

from puchi_host_embed import (
    ALWAYS_ZERO_STRIP,
    brand_puchi_features,
    fold_always_zero_type_slots,
    patch_opcodes,
    rewrite_host_allocators,
    rewrite_libc_calls,
    trim_init7_load_port,
)
from puchi_strip_gunk import (
    assert_no_project_includes,
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
    """
    text = normalize_newlines(text)
    lines = [f"static const char {name}[] ="]
    parts = text.splitlines(keepends=True)
    if not parts:
        lines.append('  ""')
    else:
        for part in parts:
            lines.append('  "' + c_escape(part) + '"')
    lines.append(";")
    return "\n".join(lines) + "\n"


def trim_meta7(src: str) -> str:
    """Keep include-shared → load-modules; don't re-include disk init-7 for (chibi).

    Under PUCHI_TEST, find-module-file resolves *.so via sexp_static_libraries.
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
    return (
        ";; trimmed for puchi amalgamation - include-shared via STATIC_LIBS; "
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
        "/* Numeric and OS features are selected by the PUCHI_* macros at the\n"
        " * top of this file. Chibi's 'uncomment to #define SEXP_USE_*' notes\n"
        " * are omitted here; they do not configure puchi.\n"
        " * Heap-size knobs below are still live #ifndef defaults.\n"
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
    bsd_new = (
        "/* puchi: no host-OS feature probe; platform is \"puchi\"/\"portable\" */\n"
        "#define SEXP_BSD 0\n"
        "#define SEXP_DARWIN 0\n"
        "#define SEXP_FREEBSD 0\n"
        "#define SEXP_NETBSD 0\n"
        "#define SEXP_DRAGONFLY 0\n"
        "#define SEXP_OPENBSD 0\n"
    )
    if bsd_old not in text:
        raise SystemExit("scrub_features_h: BSD probe block not found")
    text = text.replace(bsd_old, bsd_new, 1)

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
    abi_new = (
        "\n"
        "/* puchi: no shared-lib / image ABI fingerprint. Harness clibs only. */\n"
        "#if defined(PUCHI_TEST)\n"
        "typedef char sexp_abi_identifier_t[8];\n"
        '#define SEXP_ABI_IDENTIFIER "--------"\n'
        "#define sexp_version_compatible(ctx, subver, genver) 1\n"
        "#define sexp_abi_compatible(ctx, subabi, genabi) 1\n"
        "#endif\n"
    )
    text = text[:abi_start] + abi_new
    return text


def scrub_gc_host(gc_c: str) -> str:
    """Disable CHIBI_MAX_ALLOC getenv; allocators handled by rewrite_host_allocators."""
    text = normalize_newlines(gc_c)
    old = '    max_alloc = getenv("CHIBI_MAX_ALLOC");'
    new = "    max_alloc = NULL; /* puchi: no getenv heap cap */"
    if old not in text:
        raise SystemExit("scrub_gc_host: CHIBI_MAX_ALLOC getenv not found")
    return text.replace(old, new, 1)


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


# Deleted from the amalgamation. Value 0, and defined() is true, so
# `#if SEXP_USE_DL` goes away. With STABLE_ABI also ALWAYS_ZERO,
# `#if SEXP_USE_STABLE_ABI || SEXP_USE_DL` is deleted entirely.
# PLAN9 is never defined. STATIC_LIBS is NOT stripped â€” gated by PUCHI_TEST.
_DEAD_ZERO = set(ALWAYS_ZERO_STRIP) | {"SEXP_USE_BOEHM", "SEXP_USE_GREEN_THREADS", "SEXP_USE_DL"}
_DEAD_UNDEF = {"PLAN9"}


def _strip_pp_comments(expr: str) -> str:
    out = []
    i = 0
    while i < len(expr):
        if expr.startswith("/*", i):
            j = expr.find("*/", i + 2)
            i = len(expr) if j < 0 else j + 2
            out.append(" ")
        elif expr.startswith("//", i):
            break
        else:
            out.append(expr[i])
            i += 1
    return "".join(out)


def _pp_tokens(expr: str) -> list[str]:
    s = _strip_pp_comments(expr)
    i = 0
    toks: list[str] = []
    while i < len(s):
        if s[i].isspace():
            i += 1
            continue
        for op in ("&&", "||", "==", "!=" , "<=", ">="):
            if s.startswith(op, i):
                toks.append(op)
                i += 2
                break
        else:
            if s[i] in "!()&|+-*/%<>^~?:":
                toks.append(s[i])
                i += 1
            elif s[i].isdigit():
                m = re.match(r"0[xX][0-9A-Fa-f]+[uUlL]*|\d+[uUlL]*", s[i:])
                assert m
                toks.append(m.group())
                i += len(m.group())
            elif s[i].isalpha() or s[i] == "_":
                m = re.match(r"[A-Za-z_][A-Za-z0-9_]*", s[i:])
                assert m
                toks.append(m.group())
                i += len(m.group())
            else:
                raise SystemExit(f"preprocessor token: {s[i:]!r}")
    return toks


class _Pv:
    """Preprocessor value: a constant, or an expression we could not fold."""

    def __init__(self, const: int | None, text: str):
        self.const = const
        self.text = text

    def render(self) -> str:
        if self.const is not None:
            return str(self.const)
        return self.text


def _pp_eval(expr: str) -> _Pv:
    toks = _pp_tokens(expr)
    pos = 0

    def peek() -> str | None:
        return toks[pos] if pos < len(toks) else None

    def eat(expected: str | None = None) -> str:
        nonlocal pos
        if pos >= len(toks):
            raise SystemExit(f"truncated preprocessor expr: {expr!r}")
        tok = toks[pos]
        pos += 1
        if expected is not None and tok != expected:
            raise SystemExit(f"expected {expected} in {expr!r}")
        return tok

    def wrap(v: _Pv) -> str:
        if v.const is not None:
            return str(v.const)
        t = v.text
        if re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]*|defined\([^)]*\)|0[xX][0-9A-Fa-f]+[uUlL]*|\d+[uUlL]*",
            t,
        ):
            return t
        return f"({t})"

    def spell(v: _Pv) -> str:
        if v.const is None:
            return wrap(v)
        if re.fullmatch(r"0[xX][0-9A-Fa-f]+[uUlL]*|\d+[uUlL]*", v.text or ""):
            return v.text
        return str(v.const)

    def ident_value(name: str) -> _Pv:
        if name in _DEAD_ZERO or name in _DEAD_UNDEF:
            return _Pv(0, "0")
        return _Pv(None, name)

    def primary() -> _Pv:
        tok = eat()
        if tok == "(":
            v = or_expr()
            eat(")")
            return v
        if tok == "defined":
            if peek() == "(":
                eat("(")
                name = eat()
                eat(")")
            else:
                name = eat()
            if name in _DEAD_ZERO:
                return _Pv(1, "1")
            if name in _DEAD_UNDEF:
                return _Pv(0, "0")
            return _Pv(None, f"defined({name})")
        if re.fullmatch(r"0[xX][0-9A-Fa-f]+[uUlL]*|\d+[uUlL]*", tok):
            return _Pv(int(re.sub(r"[uUlL]+$", "", tok), 0), tok)
        return ident_value(tok)

    def unary() -> _Pv:
        if peek() == "!":
            eat("!")
            v = unary()
            if v.const is not None:
                return _Pv(int(not v.const), "")
            return _Pv(None, "!" + wrap(v))
        if peek() == "~":
            eat("~")
            v = unary()
            if v.const is not None:
                return _Pv(~v.const, "")
            return _Pv(None, "~" + wrap(v))
        return primary()

    def cmp_expr() -> _Pv:
        v = unary()
        while peek() in ("==", "!=", "<", ">", "<=", ">="):
            op = eat()
            r = unary()
            if v.const is not None and r.const is not None:
                n = {
                    "==": v.const == r.const,
                    "!=": v.const != r.const,
                    "<": v.const < r.const,
                    ">": v.const > r.const,
                    "<=": v.const <= r.const,
                    ">=": v.const >= r.const,
                }[op]
                v = _Pv(int(n), "")
            else:
                v = _Pv(None, f"{spell(v)} {op} {spell(r)}")
        return v

    def and_expr() -> _Pv:
        v = cmp_expr()
        while peek() == "&&":
            eat("&&")
            r = cmp_expr()
            if v.const == 0 or r.const == 0:
                v = _Pv(0, "")
            elif v.const == 1:
                v = r
            elif r.const == 1:
                pass
            elif v.const is not None and r.const is not None:
                v = _Pv(int(v.const and r.const), "")
            else:
                v = _Pv(None, f"{spell(v)} && {spell(r)}")
        return v

    def or_expr() -> _Pv:
        v = and_expr()
        while peek() == "||":
            eat("||")
            r = and_expr()
            if v.const == 1 or r.const == 1:
                v = _Pv(1, "")
            elif v.const == 0:
                v = r
            elif r.const == 0:
                pass
            elif v.const is not None and r.const is not None:
                v = _Pv(int(v.const or r.const), "")
            else:
                v = _Pv(None, f"{spell(v)} || {spell(r)}")
        return v

    v = or_expr()
    if pos != len(toks):
        # Arithmetic and other operators we do not fold. Keep the original.
        return _Pv(None, " ".join(toks))
    return v


def _directive(line: str) -> tuple[str, str] | None:
    m = re.match(r"\s*#\s*(\w+)\s*(.*)", line.rstrip("\r\n"))
    if not m:
        return None
    word = m.group(1)
    rest = m.group(2).strip()
    if word in ("if", "ifdef", "ifndef", "elif", "else", "endif"):
        return word, rest
    return None


def _cond(word: str, rest: str) -> _Pv:
    if word == "ifdef":
        name = rest.split()[0]
        if name in _DEAD_ZERO:
            return _Pv(1, "1")
        if name in _DEAD_UNDEF:
            return _Pv(0, "0")
        return _Pv(None, f"defined({name})")
    if word == "ifndef":
        name = rest.split()[0]
        if name in _DEAD_ZERO:
            return _Pv(0, "0")
        if name in _DEAD_UNDEF:
            return _Pv(1, "1")
        return _Pv(None, f"!defined({name})")
    return _pp_eval(rest)


def _self_test_dead_backends() -> None:
    samples = {
        "SEXP_USE_DL": 0,
        "defined(PLAN9)": 0,
        "!defined(PLAN9)": 1,
        "SEXP_USE_STABLE_ABI || SEXP_USE_DL": 0,  # both ALWAYS_ZERO_STRIP
        "SEXP_USE_BOEHM || SEXP_USE_MALLOC": 0,  # both ALWAYS_ZERO_STRIP
        "!SEXP_USE_BOEHM && !SEXP_USE_MALLOC": 1,
        "defined(PLAN9) || !SEXP_USE_FLONUMS": None,
        "! defined(_GNU_SOURCE) && ! defined(_WIN32) && ! defined(PLAN9)": None,
    }
    got = {k: _pp_eval(k) for k in samples}
    assert got["SEXP_USE_DL"].const == 0
    assert got["defined(PLAN9)"].const == 0
    assert got["!defined(PLAN9)"].const == 1
    assert got["SEXP_USE_STABLE_ABI || SEXP_USE_DL"].const == 0
    assert got["SEXP_USE_BOEHM || SEXP_USE_MALLOC"].const == 0
    assert got["!SEXP_USE_BOEHM && !SEXP_USE_MALLOC"].const == 1
    assert got["defined(PLAN9) || !SEXP_USE_FLONUMS"].render() == "!SEXP_USE_FLONUMS"
    assert _pp_eval("! (SEXP_USE_FLONUMS || SEXP_USE_BIGNUMS)").render() == "!(SEXP_USE_FLONUMS || SEXP_USE_BIGNUMS)"
    assert _pp_eval("UINT_MAX == 4294967295U").render() == "UINT_MAX == 4294967295U"
    assert _pp_eval("ULONG_MAX == 4294967295UL").render() == "ULONG_MAX == 4294967295UL"
    assert _pp_eval("1U == 1").const == 1
    assert "PLAN9" not in got["! defined(_GNU_SOURCE) && ! defined(_WIN32) && ! defined(PLAN9)"].render()

    src = (
        "#ifndef PLAN9\n"
        "keep\n"
        "#else\n"
        "drop\n"
        "#endif\n"
        "#ifdef PLAN9\n"
        "drop2\n"
        "#endif\n"
        "#if SEXP_USE_DL\n"
        "drop3\n"
        "#else\n"
        "keep3\n"
        "#endif\n"
        "#if SEXP_USE_STABLE_ABI || SEXP_USE_DL\n"
        "enum\n"
        "#endif\n"
        "#define SEXP_USE_DL 0\n"
    )
    out = strip_dead_backends(src, _tested=True)
    assert "drop" not in out and "drop2" not in out and "drop3" not in out
    assert "keep" in out and "keep3" in out
    assert "enum" not in out
    assert "#define SEXP_USE_DL 0" in out
    assert "SEXP_USE_STABLE_ABI" not in out or "#define SEXP_USE_STABLE_ABI" in out

    # NATIVE_X86 is ALWAYS_ZERO_STRIP â€” the whole branch (including any
    # Boehm re-enable) is deleted from the amalgamation.
    native = (
        "#define SEXP_USE_BOEHM 0\n"
        "#if SEXP_USE_NATIVE_X86\n"
        "#undef SEXP_USE_BOEHM\n"
        "#define SEXP_USE_BOEHM 1\n"
        "#define SEXP_USE_FLONUMS 0\n"
        "#endif\n"
        "after\n"
    )
    native_out = strip_dead_backends(native, _tested=True)
    assert "#define SEXP_USE_BOEHM 0" in native_out
    assert "#define SEXP_USE_BOEHM 1" not in native_out
    assert "#undef SEXP_USE_BOEHM" not in native_out
    assert "SEXP_USE_NATIVE_X86" not in native_out
    assert "after" in native_out


def _reenables_dead_backend(line: str) -> bool:
    """NATIVE_X86 turns Boehm back on. The collector is not in the amalgamation."""
    s = "".join(line.split())
    return s in ("#undefSEXP_USE_BOEHM", "#defineSEXP_USE_BOEHM1")


def strip_dead_backends(src: str, _tested: bool = False) -> str:
    """Drop Plan 9, Boehm, green-thread, and dlopen branches.

    Other #if conditions are kept, with those four facts folded in
    (`SEXP_USE_DL || SEXP_USE_STATIC_LIBS` becomes `SEXP_USE_STATIC_LIBS`).
    """
    if not _tested:
        _self_test_dead_backends()

    raw = src.splitlines(keepends=True)
    lines: list[str] = []
    buf = ""
    for line in raw:
        if buf:
            buf += line
            if not buf.rstrip("\r\n").endswith("\\"):
                lines.append(buf)
                buf = ""
        elif line.lstrip().startswith("#") and line.rstrip("\r\n").endswith("\\"):
            buf = line
        else:
            lines.append(line)
    if buf:
        lines.append(buf)

    out: list[str] = []
    # kind: 'const' (condition folded, directives omitted) or 'live'
    stack: list[dict] = []
    in_comment = False

    def parent_emit() -> bool:
        return all(fr["emit"] and fr["arm"] for fr in stack) if stack else True

    def comment_state(line: str, inside: bool) -> bool:
        i = 0
        while i < len(line):
            if inside:
                j = line.find("*/", i)
                if j < 0:
                    return True
                i = j + 2
                inside = False
            else:
                slash = line.find("//", i)
                block = line.find("/*", i)
                if slash >= 0 and (block < 0 or slash < block):
                    return False
                if block < 0:
                    return False
                i = block + 2
                inside = True
        return inside

    for line in lines:
        body = line
        is_dir = False
        if not in_comment:
            stripped = body.lstrip()
            if stripped.startswith("#"):
                is_dir = _directive(body) is not None
        if not is_dir:
            if parent_emit() and not _reenables_dead_backend(line):
                out.append(line)
            in_comment = comment_state(line, in_comment)
            continue

        word, rest = _directive(body) or ("", "")
        nl = "\n" if body.endswith("\n") else ""

        if word in ("if", "ifdef", "ifndef"):
            emitting = parent_emit()
            val = _cond(word, rest) if emitting else _Pv(0, "")
            if not emitting or val.const == 0:
                stack.append({"kind": "const", "emit": False, "taken": False, "arm": False})
            elif val.const == 1:
                stack.append({"kind": "const", "emit": True, "taken": True, "arm": True})
            else:
                if emitting:
                    out.append(f"#if {val.render()}{nl}")
                stack.append({"kind": "live", "emit": True, "taken": False, "arm": True})
            continue

        if word == "elif":
            fr = stack[-1]
            if not parent_emit() and fr is stack[-1]:
                # parent already dark: stay dark
                if not all(f["emit"] or f is fr for f in stack[:-1]):
                    fr["emit"] = False
                    fr["arm"] = False
                    continue
            outer = all(f["emit"] for f in stack[:-1]) if len(stack) > 1 else True
            val = _cond("if", rest)
            if fr["kind"] == "const":
                if fr["taken"] or not outer:
                    fr["emit"] = False
                    fr["arm"] = False
                elif val.const == 1:
                    fr["emit"] = True
                    fr["taken"] = True
                    fr["arm"] = True
                elif val.const == 0:
                    fr["emit"] = False
                    fr["arm"] = False
                else:
                    fr["kind"] = "live"
                    fr["emit"] = True
                    fr["arm"] = True
                    out.append(f"#if {val.render()}{nl}")
            else:
                if val.const == 0:
                    fr["arm"] = False
                elif val.const == 1:
                    out.append(f"#else{nl}")
                    fr["arm"] = True
                    fr["taken"] = True
                else:
                    out.append(f"#elif {val.render()}{nl}")
                    fr["arm"] = True
            continue

        if word == "else":
            fr = stack[-1]
            outer = all(f["emit"] for f in stack[:-1]) if len(stack) > 1 else True
            if fr["kind"] == "const":
                if fr["taken"] or not outer:
                    fr["emit"] = False
                else:
                    fr["emit"] = True
                    fr["taken"] = True
                fr["arm"] = fr["emit"]
            else:
                if outer:
                    out.append(f"#else{nl}")
                fr["arm"] = True
            continue

        if word == "endif":
            fr = stack.pop()
            outer = parent_emit()
            if fr["kind"] == "live" and outer:
                out.append(f"#endif{nl}")
            continue

        if parent_emit():
            out.append(line)

    if stack:
        raise SystemExit("strip-dead-backends: unmatched #if")
    return "".join(out)


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
        text = scrub_shipped_always_zero_defines(text)
        assert_no_project_includes(text)
        write_text_lf(path, text)


if __name__ == "__main__":
    main()