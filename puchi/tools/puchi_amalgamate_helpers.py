#!/usr/bin/env python3
"""Helpers for amalgamate.sh — embed Scheme as C strings and trim init-7."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


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


def embed_c_string(name: str, text: str, wrap: int = 72) -> str:
    """Emit a static const char name[] = "..."; broken into lines."""
    escaped = c_escape(text)
    lines = [f"static const char {name}[] ="]
    i = 0
    n = len(escaped)
    while i < n:
        chunk = []
        length = 0
        while i < n and length < wrap:
            if escaped[i] == "\\" and i + 1 < n:
                # keep escape sequence together
                if escaped[i + 1] == "x" and i + 3 < n:
                    piece = escaped[i : i + 4]
                    i += 4
                else:
                    piece = escaped[i : i + 2]
                    i += 2
            else:
                piece = escaped[i]
                i += 1
            chunk.append(piece)
            length += len(piece)
        lines.append('  "' + "".join(chunk) + '"')
    lines.append(";")
    return "\n".join(lines) + "\n"


def trim_init7(src: str) -> str:
    """Remove file/load helpers and stub (library) in cond-expand."""
    # Replace call-with-*-file and with-*-file definitions with stubs that error.
    replacements = [
        (
            r"\(define \(call-with-input-file file proc\)\n"
            r"  \(let\* \(\(in \(open-input-file file\)\)\n"
            r"         \(res \(proc in\)\)\)\n"
            r"    \(close-input-port in\)\n"
            r"    res\)\)\n",
            "(define (call-with-input-file file proc)\n"
            "  (error \"call-with-input-file: not available in puchi core\" file))\n",
        ),
        (
            r"\(define \(call-with-output-file file proc\)\n"
            r"  \(let\* \(\(out \(open-output-file file\)\)\n"
            r"         \(res \(proc out\)\)\)\n"
            r"    \(close-output-port out\)\n"
            r"    res\)\)\n",
            "(define (call-with-output-file file proc)\n"
            "  (error \"call-with-output-file: not available in puchi core\" file))\n",
        ),
        (
            r"\(define \(with-input-from-file file thunk\)\n"
            r"  \(let \(\(old-in \(current-input-port\)\)\n"
            r"        \(tmp-in \(open-input-file file\)\)\)\n"
            r"    \(dynamic-wind\n"
            r"      \(lambda \(\) \(current-input-port tmp-in\)\)\n"
            r"      \(lambda \(\) \(let \(\(res \(thunk\)\)\) \(close-input-port tmp-in\) res\)\)\n"
            r"      \(lambda \(\) \(current-input-port old-in\)\)\)\)\)\n",
            "(define (with-input-from-file file thunk)\n"
            "  (error \"with-input-from-file: not available in puchi core\" file))\n",
        ),
        (
            r"\(define \(with-output-to-file file thunk\)\n"
            r"  \(let \(\(old-out \(current-output-port\)\)\n"
            r"        \(tmp-out \(open-output-file file\)\)\)\n"
            r"    \(dynamic-wind\n"
            r"      \(lambda \(\) \(current-output-port tmp-out\)\)\n"
            r"      \(lambda \(\) \(let \(\(res \(thunk\)\)\) \(close-output-port tmp-out\) res\)\)\n"
            r"      \(lambda \(\) \(current-output-port old-out\)\)\)\)\)\n",
            "(define (with-output-to-file file thunk)\n"
            "  (error \"with-output-to-file: not available in puchi core\" file))\n",
        ),
    ]
    out = src
    for pat, repl in replacements:
        out2, n = re.subn(pat, repl, out, count=1, flags=re.MULTILINE)
        if n == 0:
            print(f"warning: trim_init7 pattern not matched:\n{pat[:60]}...", file=sys.stderr)
        out = out2

    # Replace (define (load ... entire definition with stub
    load_start = out.find("(define (load file . o)")
    if load_start < 0:
        print("warning: load definition not matched for trim", file=sys.stderr)
    else:
        # End at the blank line / section after the closing parens of load
        marker = "\n;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;;\n;; promises"
        load_end = out.find(marker, load_start)
        if load_end < 0:
            print("warning: load definition end marker not found", file=sys.stderr)
        else:
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
            print("warning: (library) cond-expand clause not found", file=sys.stderr)

    return (
        ";; trimmed for puchi amalgamation - file/load/library stubs\n" + out
    )


def strip_features_manual(features_h: str) -> str:
    """Drop Chibi's 'uncomment this #define' essay.

    Those comments tell a Chibi builder to edit features.h. In puchi.h the
    PUCHI_* block already set the flags, so the essay is wrong.
    Keep the copyright and the real #ifndef/#define logic.
    """
    marker = "#ifndef SEXP_INITIAL_HEAP_SIZE"
    idx = features_h.find(marker)
    if idx < 0:
        raise SystemExit("SEXP_INITIAL_HEAP_SIZE not found in features.h")
    # Keep the leading copyright comment (through the first blank line).
    blank = features_h.find("\n\n")
    if blank < 0 or blank > idx:
        head = ""
    else:
        head = features_h[: blank + 2]
    note = (
        "/* Numeric and OS features are selected by the PUCHI_* macros at the\n"
        " * top of this file. Chibi's 'uncomment to #define SEXP_USE_*' notes\n"
        " * are omitted here; they do not configure puchi.\n"
        " * Heap-size knobs below are still live #ifndef defaults.\n"
        " */\n\n"
    )
    return head + note + features_h[idx:]


def replace_platform_block(sexp_h: str) -> str:
    """Replace OS-specific include block in sexp.h with portable includes."""
    start = sexp_h.find('#include "chibi/features.h"')
    if start < 0:
        raise SystemExit("features.h include not found in sexp.h")
    # Keep features + install includes; replace from SOCKET block through PLAN9 else includes
    # We replace from after install.h through the PLAN9/else include block.
    install = sexp_h.find('#include "chibi/install.h"')
    if install < 0:
        raise SystemExit("install.h include not found")
    after_install = sexp_h.find("\n", install) + 1

    # Find end of the big platform block: after `#endif` that closes PLAN9 (line ~115),
    # before SEXP_USE_TRACK_ALLOC_BACKTRACE or #include <ctype.h>
    marker = "#include <ctype.h>"
    end = sexp_h.find(marker)
    if end < 0:
        raise SystemExit("ctype.h marker not found")

    portable = r'''
/* ---- puchi: portable host surface (no OS backends) ---- */
#include <stddef.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <stdio.h>
#include <ctype.h>
#include <errno.h>
#include <math.h>
#include <float.h>
#include <limits.h>
#include <stdint.h>

typedef intptr_t SOCKET_TYPE;

#define sexp_isalpha(x) (isalpha(x))
#define sexp_isxdigit(x) (isxdigit(x))
#define sexp_isdigit(x) (isdigit(x))
#define sexp_tolower(x) (tolower(x))
#define sexp_toupper(x) (toupper(x))

#define SEXP_USE_POLL_PORT 0
#define sexp_poll_input(ctx, port) ((void)(ctx), (void)(port), 0)
#define sexp_poll_output(ctx, port) ((void)(ctx), (void)(port), 0)

#if SEXP_USE_GC_FILE_DESCRIPTORS
#define sexp_out_of_file_descriptors() (errno == EMFILE)
#else
#define sexp_out_of_file_descriptors() (0)
#endif

#ifdef __GNUC__
#define SEXP_NO_WARN_UNUSED __attribute__((unused))
#else
#define SEXP_NO_WARN_UNUSED
#endif

'''
    # Skip ctype.h include since we already included it
    after_ctype = sexp_h.find("\n", end) + 1
    return sexp_h[:after_install] + portable + sexp_h[after_ctype:]


def stub_file_ops_in_eval(eval_c: str) -> str:
    """Replace fopen/stat/dlopen implementations with puchi stubs."""
    # open input file
    eval_c = re.sub(
        r"sexp sexp_open_input_file_op \(sexp ctx, sexp self, sexp_sint_t n, sexp path\) \{.*?\n\}",
        "sexp sexp_open_input_file_op (sexp ctx, sexp self, sexp_sint_t n, sexp path) {\n"
        "  sexp_assert_type(ctx, sexp_stringp, SEXP_STRING, path);\n"
        "  return sexp_file_exception(ctx, self,\n"
        '    "open-input-file: not available in puchi core (host may redefine)", path);\n'
        "}",
        eval_c,
        count=1,
        flags=re.DOTALL,
    )
    eval_c = re.sub(
        r"sexp sexp_open_output_file_op \(sexp ctx, sexp self, sexp_sint_t n, sexp path\) \{.*?\n\}",
        "sexp sexp_open_output_file_op (sexp ctx, sexp self, sexp_sint_t n, sexp path) {\n"
        "  sexp_assert_type(ctx, sexp_stringp, SEXP_STRING, path);\n"
        "  return sexp_file_exception(ctx, self,\n"
        '    "open-output-file: not available in puchi core (host may redefine)", path);\n'
        "}",
        eval_c,
        count=1,
        flags=re.DOTALL,
    )

    # find_module_file_raw — return NULL always (no stat)
    eval_c = re.sub(
        r"char\* sexp_find_module_file_raw \(sexp ctx, const char \*file\) \{.*?\n  return NULL;\n\}",
        "char* sexp_find_module_file_raw (sexp ctx, const char *file) {\n"
        "  (void)ctx; (void)file;\n"
        "  return NULL;\n"
        "}",
        eval_c,
        count=1,
        flags=re.DOTALL,
    )

    # Module path getenv — ignore
    eval_c = eval_c.replace(
        "user_path = getenv(SEXP_MODULE_PATH_VAR);",
        "user_path = NULL; /* puchi: no getenv */",
    )
    eval_c = eval_c.replace(
        "no_sys_path = getenv(SEXP_NO_SYSTEM_PATH_VAR);",
        "no_sys_path = (char*)\"1\"; /* puchi: never use system module path */",
    )

    eval_c = eval_c.replace("if (strictp) exit(1);", "if (strictp) abort();")

    return eval_c


def patch_gc_c(gc_c: str) -> str:
    gc_c = gc_c.replace("#include <sys/resource.h>", "/* puchi: no sys/resource.h */")
    gc_c = gc_c.replace("#include <sys/mman.h>", "/* puchi: no sys/mman.h */")
    # malloc/free wrappers
    gc_c = re.sub(
        r"#define sexp_malloc malloc\n#define sexp_free free",
        "#ifndef sexp_malloc\n"
        "#define sexp_malloc(sz) SEXP_MALLOC(NULL, (sz))\n"
        "#endif\n"
        "#ifndef sexp_free\n"
        "#define sexp_free(p) SEXP_FREE(NULL, (p))\n"
        "#endif",
        gc_c,
    )
    # limited malloc path
    gc_c = gc_c.replace("max_alloc = getenv(\"CHIBI_MAX_ALLOC\");", "max_alloc = NULL;")
    gc_c = re.sub(
        r"if \(\!\(res = malloc\(size\)\)\) return NULL;",
        "if (!(res = SEXP_MALLOC(NULL, size))) return NULL;",
        gc_c,
    )
    gc_c = gc_c.replace("void sexp_free(void* ptr) {\n  free(ptr);\n}",
                        "void sexp_free(void* ptr) {\n  SEXP_FREE(NULL, ptr);\n}")
    gc_c = gc_c.replace("free(heap);", "SEXP_FREE(NULL, heap);")
    gc_c = gc_c.replace("*ptr = malloc(sizeof(**ptr));", "*ptr = SEXP_MALLOC(NULL, sizeof(**ptr));")
    gc_c = gc_c.replace("free(old);", "SEXP_FREE(NULL, old);")
    gc_c = gc_c.replace("free(debug_text);", "SEXP_FREE(NULL, debug_text);")
    # fprintf debug stays — only used under DEBUG flags (off by default)
    return gc_c


def patch_sexp_c(sexp_c: str) -> str:
    # Avoid POSIX close/dlclose when finalizing — no-op if we never create those
    sexp_c = sexp_c.replace(
        "close(sexp_fileno_fd(fileno));",
        "/* puchi: no close() */ (void)fileno;",
    )
    sexp_c = re.sub(
        r"#ifdef _WIN32\n\s*FreeLibrary.*?#else\n\s*dlclose\(sexp_dl_handle\(dl\)\);\n#endif",
        "/* puchi: no dynamic libraries */ (void)dl;",
        sexp_c,
        count=1,
        flags=re.DOTALL,
    )
    sexp_c = sexp_c.replace(
        "fclose(sexp_port_stream(port));",
        "/* puchi: no fclose; stream ports unsupported */ (void)port;",
    )
    # fread/fwrite in buffered ports — leave; only hit for FILE* streams
    sexp_c = sexp_c.replace(
        "shutdown(sexp_port_sock(port), sexp_oportp(port) ? SHUT_RDWR : SHUT_RD);",
        "/* puchi: no sockets */ (void)port;",
    )
    sexp_c = sexp_c.replace(
        "shutdown(sexp_port_sock(port), SHUT_WR);",
        "/* puchi: no sockets */ (void)port;",
    )
    sexp_c = sexp_c.replace("free(sexp_cpointer_value(obj));", "SEXP_FREE(NULL, sexp_cpointer_value(obj));")
    sexp_c = re.sub(r"\bfree\(", "SEXP_FREE(NULL, ", sexp_c)
    # Fix double-wrap if any SEXP_FREE(NULL, SEXP_FREE
    sexp_c = sexp_c.replace("SEXP_FREE(NULL, SEXP_FREE(NULL, ", "SEXP_FREE(NULL, ")
    sexp_c = re.sub(r"sexp_malloc\(", "SEXP_MALLOC(NULL, ", sexp_c)
    return sexp_c


# Deleted from the amalgamation. Value 0, and defined() is true, so
# `#if SEXP_USE_DL` goes away while `#if SEXP_USE_STABLE_ABI || SEXP_USE_DL`
# becomes `#if SEXP_USE_STABLE_ABI`. PLAN9 is never defined.
_DEAD_ZERO = {"SEXP_USE_BOEHM", "SEXP_USE_GREEN_THREADS", "SEXP_USE_DL"}
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
        "SEXP_USE_STABLE_ABI || SEXP_USE_DL": None,
        "SEXP_USE_BOEHM || SEXP_USE_MALLOC": None,
        "!SEXP_USE_BOEHM && !SEXP_USE_MALLOC": None,
        "defined(PLAN9) || !SEXP_USE_FLONUMS": None,
        "! defined(_GNU_SOURCE) && ! defined(_WIN32) && ! defined(PLAN9)": None,
    }
    got = {k: _pp_eval(k) for k in samples}
    assert got["SEXP_USE_DL"].const == 0
    assert got["defined(PLAN9)"].const == 0
    assert got["!defined(PLAN9)"].const == 1
    assert got["SEXP_USE_STABLE_ABI || SEXP_USE_DL"].const is None
    assert "SEXP_USE_DL" not in got["SEXP_USE_STABLE_ABI || SEXP_USE_DL"].render()
    assert got["SEXP_USE_BOEHM || SEXP_USE_MALLOC"].render() == "SEXP_USE_MALLOC"
    assert "BOEHM" not in got["!SEXP_USE_BOEHM && !SEXP_USE_MALLOC"].render()
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
    assert "keep" in out and "keep3" in out and "enum" in out
    assert "SEXP_USE_DL" not in out.split("enum")[0]
    assert "#define SEXP_USE_DL 0" in out
    assert "#if SEXP_USE_STABLE_ABI" in out

    native = (
        "#define SEXP_USE_BOEHM 0\n"
        "#if SEXP_USE_NATIVE_X86\n"
        "#undef SEXP_USE_BOEHM\n"
        "#define SEXP_USE_BOEHM 1\n"
        "#define SEXP_USE_FLONUMS 0\n"
        "#endif\n"
    )
    native_out = strip_dead_backends(native, _tested=True)
    assert "#define SEXP_USE_BOEHM 0" in native_out
    assert "#define SEXP_USE_BOEHM 1" not in native_out
    assert "#undef SEXP_USE_BOEHM" not in native_out
    assert "#define SEXP_USE_FLONUMS 0" in native_out


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

    p = sub.add_parser("embed")
    p.add_argument("name")
    p.add_argument("input")
    p.add_argument("output")

    p = sub.add_parser("strip-dead-backends")
    p.add_argument("path")

    p = sub.add_parser("strip-features")
    p.add_argument("input")
    p.add_argument("output")

    p = sub.add_parser("patch-sexp-h")
    p.add_argument("input")
    p.add_argument("output")

    p = sub.add_parser("patch-eval-c")
    p.add_argument("input")
    p.add_argument("output")

    p = sub.add_parser("patch-gc-c")
    p.add_argument("input")
    p.add_argument("output")

    p = sub.add_parser("patch-sexp-c")
    p.add_argument("input")
    p.add_argument("output")

    args = ap.parse_args()
    if args.cmd == "trim-init":
        text = Path(args.input).read_text(encoding="utf-8")
        Path(args.output).write_text(trim_init7(text), encoding="utf-8")
    elif args.cmd == "embed":
        text = Path(args.input).read_text(encoding="utf-8")
        Path(args.output).write_text(embed_c_string(args.name, text), encoding="utf-8")
    elif args.cmd == "strip-dead-backends":
        path = Path(args.path)
        path.write_text(strip_dead_backends(path.read_text(encoding="utf-8")), encoding="utf-8")
    elif args.cmd == "strip-features":
        text = Path(args.input).read_text(encoding="utf-8")
        Path(args.output).write_text(strip_features_manual(text), encoding="utf-8")
    elif args.cmd == "patch-sexp-h":
        text = Path(args.input).read_text(encoding="utf-8")
        Path(args.output).write_text(replace_platform_block(text), encoding="utf-8")
    elif args.cmd == "patch-eval-c":
        text = Path(args.input).read_text(encoding="utf-8")
        Path(args.output).write_text(stub_file_ops_in_eval(text), encoding="utf-8")
    elif args.cmd == "patch-gc-c":
        text = Path(args.input).read_text(encoding="utf-8")
        Path(args.output).write_text(patch_gc_c(text), encoding="utf-8")
    elif args.cmd == "patch-sexp-c":
        text = Path(args.input).read_text(encoding="utf-8")
        Path(args.output).write_text(patch_sexp_c(text), encoding="utf-8")


if __name__ == "__main__":
    main()
