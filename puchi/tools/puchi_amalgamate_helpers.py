#!/usr/bin/env python3
"""Helpers for amalgamate.sh — embed Scheme as C strings and trim init-7.

Host-owned embed contract (see puchi_host_embed.py + amalgamate.sh banner):
CPU/memory only in core; host supplies alloc/diagnose/fatal and stream_ops;
ALWAYS_ZERO_STRIP flags are forced 0 and deleted by strip-dead-backends;
STATIC_LIBS only under PUCHI_TEST; libc only via PUCHI_* wrappers.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from puchi_host_embed import (
    ALWAYS_ZERO_STRIP,
    features_force_extra,
    patch_eval_c_host,
    patch_eval_h_host,
    patch_opcodes,
    patch_sexp_c_host,
    patch_sexp_h_host,
    rewrite_libc_calls,
    trim_init7_load_port,
)
from puchi_strip_gunk import (
    assert_no_project_includes,
    scrub_dead_feature_knobs,
    scrub_eval_c_disk_boot,
    scrub_eval_h_gunk,
    scrub_portable_poll_stubs,
    scrub_sexp_c_gunk,
    scrub_sexp_h_gunk,
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
    """Stub include-shared arms so meta-7 never touches DLLs / .so files."""
    out = normalize_newlines(src)
    replacements = [
        (
            "((include-shared)\n"
            "              (load-modules (cdr x) *shared-object-extension* #f))",
            "((include-shared)\n"
            '              (error "include-shared: not available in puchi" x))',
        ),
        (
            "((include-shared-optionally)\n"
            "              (load-modules (list (cadr x)) *shared-object-extension* #f\n"
            "                            (lambda () (load-modules (cddr x) \"\" #f))))",
            "((include-shared-optionally)\n"
            "              (load-modules (cddr x) \"\" #f))",
        ),
    ]
    for old, new in replacements:
        if old not in out:
            print(f"warning: trim_meta7 pattern not matched:\n{old[:60]}...", file=sys.stderr)
        else:
            out = out.replace(old, new, 1)
    return ";; trimmed for puchi amalgamation - no include-shared / DLLs\n" + out


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

    out = bootstrap_fix_init7(out)
    out = (
        ";; trimmed for puchi amalgamation - file/load/library stubs\n" + out
    )
    return trim_init7_dead_arms(trim_init7_load_port(out))


def bootstrap_fix_init7(src: str) -> str:
    """Rewrite early syntax expanders so bootstrap does not crash on Windows.

    ``or``/``and`` using ``cond`` in expanders AV during compile — use ``if``.
    ``make-renamer`` internal define + set! circular rename mutates badly on
    first macro use — rewrite without internal define.
    Insert list-based ``letrec`` before ``quasiquote`` so qq's internal define
    can compile; drop the later quasiquote-based upstream ``letrec``.
    """
    out = src
    renamer_old = """(define make-renamer
  (lambda (mac-env)
    (define rename
      ((lambda (renames)
         (lambda (identifier)
           ((lambda (cell)
              (if cell
                  (cdr cell)
                  ((lambda (name)
                     (set! renames (cons (cons identifier name) renames))
                     name)
                   ((lambda (id)
                      (syntactic-closure-set-rename! id rename)
                      id)
                    (close-syntax identifier mac-env)))))
            (assq identifier renames))))
       '()))
    rename))"""
    # Box the alist + self-ref so we need no internal define / set! of a local.
    renamer_new = """(define make-renamer
  (lambda (mac-env)
    ((lambda (box)
       ((lambda (rename)
          (set-car! (cdr box) rename)
          rename)
        (lambda (identifier)
          ((lambda (found)
             (if found
                 (cdr found)
                 ((lambda (name)
                    (set-car! box (cons (cons identifier name) (car box)))
                    name)
                  ((lambda (id)
                     (syntactic-closure-set-rename! id (car (cdr box)))
                     id)
                   (close-syntax identifier mac-env)))))
           (assq identifier (car box))))))
     (cons '() (cons #f '())))))"""
    or_old = """(define-syntax or
  (er-macro-transformer
   (lambda (expr rename compare)
     (cond ((null? (cdr expr)) #f)
           ((null? (cddr expr)) (cadr expr))
           (else
            (list (rename 'let) (list (list (rename 'tmp) (cadr expr)))
                  (list (rename 'if) (rename 'tmp)
                        (rename 'tmp)
                        (cons (rename 'or) (cddr expr)))))))))"""
    or_new = """(define-syntax or
  (er-macro-transformer
   (lambda (expr rename compare)
     (if (null? (cdr expr))
         #f
         (if (null? (cddr expr))
             (cadr expr)
             (list (rename 'let) (list (list (rename 'tmp) (cadr expr)))
                   (list (rename 'if) (rename 'tmp)
                         (rename 'tmp)
                         (cons (rename 'or) (cddr expr)))))))))"""
    and_old = """(define-syntax and
  (er-macro-transformer
   (lambda (expr rename compare)
     (cond ((null? (cdr expr)))
           ((null? (cddr expr)) (cadr expr))
           (else (list (rename 'if) (cadr expr)
                       (cons (rename 'and) (cddr expr))
                       #f))))))"""
    and_new = """(define-syntax and
  (er-macro-transformer
   (lambda (expr rename compare)
     (if (null? (cdr expr))
         #t
         (if (null? (cddr expr))
             (cadr expr)
             (list (rename 'if) (cadr expr)
                   (cons (rename 'and) (cddr expr))
                   #f))))))"""
    letrec_boot = """(define-syntax letrec
  (er-macro-transformer
   (lambda (expr rename compare)
     ((lambda (defs)
        (list (cons (rename 'lambda) (cons '() (append defs (cddr expr))))))
      (map (lambda (x) (cons (rename 'define) x)) (cadr expr))))))

"""
    for label, old, new in (
        ("make-renamer", renamer_old, renamer_new),
        ("or", or_old, or_new),
        ("and", and_old, and_new),
    ):
        if old not in out:
            print(f"warning: bootstrap_fix_init7 {label} pattern not matched", file=sys.stderr)
        else:
            out = out.replace(old, new, 1)

    qq_mark = "(define-syntax quasiquote\n"
    if qq_mark not in out:
        print("warning: bootstrap_fix_init7 quasiquote marker not found", file=sys.stderr)
    else:
        out = out.replace(qq_mark, letrec_boot + qq_mark, 1)
        letrec_up = """(define-syntax letrec
  (er-macro-transformer
   (lambda (expr rename compare)
     ((lambda (defs)
        `((,(rename 'lambda) () ,@defs ,@(cddr expr))))
      (map (lambda (x) (cons (rename 'define) x)) (cadr expr))))))

"""
        if letrec_up in out:
            out = out.replace(letrec_up, "", 1)
        else:
            print("warning: bootstrap_fix_init7 upstream letrec not removed", file=sys.stderr)
    return out


def patch_features_host(features_h: str) -> str:
    """Collapse DLL export nest; delete ABI fingerprint; PUCHI_TEST residue only."""
    # SEXP_API always extern (puchi is never a shared library).
    features_h = re.sub(
        r"#ifdef _WIN32\n"
        r"#ifdef SEXP_STATIC_LIBRARY\n"
        r"#define SEXP_API\s+extern\n"
        r"#else\n"
        r"#ifdef BUILDING_DLL\n"
        r"#define SEXP_API\s+__declspec\(dllexport\)\n"
        r"#else\n"
        r"#define SEXP_API\s+__declspec\(dllimport\)\n"
        r"#endif\n"
        r"#endif\n"
        r"#else\n"
        r"#define SEXP_API\s+extern\n"
        r"#endif\n",
        "#define SEXP_API    extern\n",
        features_h,
        count=1,
    )
    # Delete feature ABI fingerprint cascade; harness-only helpers under PUCHI_TEST.
    abi_repl = (
        "/* puchi: no shared-lib / image ABI fingerprint. Harness clibs only. */\n"
        "#if defined(PUCHI_TEST)\n"
        "typedef char sexp_abi_identifier_t[8];\n"
        '#define SEXP_ABI_IDENTIFIER "--------"\n'
        "#define sexp_version_compatible(ctx, subver, genver) 1\n"
        "#define sexp_abi_compatible(ctx, subabi, genabi) 1\n"
        "#endif\n"
    )
    features_h = re.sub(
        r"/[*]{10,}/\n"
        r"/[*] Feature signature\..*?"
        r"#define sexp_abi_compatible\(ctx, subabi, genabi\).*?\n",
        abi_repl,
        features_h,
        count=1,
        flags=re.DOTALL,
    )
    if "Feature signature" in features_h or "SEXP_ABI_GC" in features_h:
        raise SystemExit("ABI fingerprint block not patched in features.h")
    if "BUILDING_DLL" in features_h or "dllimport" in features_h:
        raise SystemExit("BUILDING_DLL nest still present in features.h")
    if "sexp_abi_identifier_t" not in features_h:
        raise SystemExit("PUCHI_TEST ABI residue missing from features.h")
    # Trim Win32 CRT shims that duplicate PUCHI_STRCASECMP / PUCHI_SNPRINTF.
    features_h = features_h.replace("#define strcasecmp _stricmp\n", "/* puchi: use PUCHI_STRCASECMP */\n")
    features_h = features_h.replace("#define strncasecmp _strnicmp\n", "/* puchi: use PUCHI_STRNCASECMP */\n")
    features_h = features_h.replace(
        "#define snprintf(buf, len, fmt, val) sprintf(buf, fmt, val)\n",
        "/* puchi: use PUCHI_SNPRINTF */\n",
    )
    features_h = features_h.replace("#define strcasecmp lstrcmpi\n", "/* puchi: use PUCHI_STRCASECMP */\n")
    features_h = features_h.replace(
        "#define strncasecmp(s1, s2, n) lstrcmpi(s1, s2)\n",
        "/* puchi: use PUCHI_STRNCASECMP */\n",
    )
    features_h = features_h.replace("#define strcasecmp cistrcmp\n", "/* puchi: use PUCHI_STRCASECMP */\n")
    features_h = features_h.replace("#define strncasecmp cistrncmp\n", "/* puchi: use PUCHI_STRNCASECMP */\n")
    return features_h


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
    body = features_h[idx:]
    # Socket shutdown constants — no sockets in puchi core.
    body = re.sub(
        r"#elif defined\(_WIN32\)\n"
        r"#define SHUT_RD 0 /\* SD_RECEIVE \*/\n"
        r"#define SHUT_WR 1 /\* SD_SEND \*/\n"
        r"#define SHUT_RDWR 2 /\* SD_BOTH \*/\n",
        "#elif defined(_WIN32)\n",
        body,
    )
    body = re.sub(
        r"#ifndef SHUT_RD\n#define SHUT_RD 0\n#endif\n"
        r"#ifndef SHUT_WR\n#define SHUT_WR 1\n#endif\n"
        r"#ifndef SHUT_RDWR\n#define SHUT_RDWR 2\n#endif\n",
        "",
        body,
    )
    body = scrub_dead_feature_knobs(body)
    return patch_features_host(head + note + body)


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

    # Banner owns all system #includes; this block is macros only.
    portable = r'''
/* ---- puchi: portable host surface (no OS backends) ---- */
#define sexp_isalpha(x) (PUCHI_ISALPHA(x))
#define sexp_isxdigit(x) (PUCHI_ISXDIGIT(x))
#define sexp_isdigit(x) (PUCHI_ISDIGIT(x))
#define sexp_tolower(x) (PUCHI_TOLOWER(x))
#define sexp_toupper(x) (PUCHI_TOUPPER(x))

/* Harness fileno sock field (production has no fileno type). */
#if defined(PUCHI_TEST)
#define SOCKET_TYPE sexp_sint_t
#endif

#ifdef __GNUC__
#define SEXP_NO_WARN_UNUSED __attribute__((unused))
#else
#define SEXP_NO_WARN_UNUSED
#endif

'''
    # Skip ctype.h include since banner already has it
    after_ctype = sexp_h.find("\n", end) + 1
    return sexp_h[:after_install] + portable + sexp_h[after_ctype:]


def stub_file_ops_in_eval(eval_c: str) -> str:
    """Delete OS file-open bodies; host/harness install foreigns when needed."""
    for name in (
        "sexp_open_input_file_op",
        "sexp_open_output_file_op",
        "sexp_open_binary_input_file",
        "sexp_open_binary_output_file",
    ):
        eval_c = re.sub(
            rf"sexp {name} \(sexp ctx, sexp self, sexp_sint_t n, sexp path\) \{{.*?\n\}}\n+",
            "",
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
    eval_c = patch_eval_c_host(eval_c)
    eval_c = scrub_eval_c_disk_boot(eval_c)
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
        "#if defined(PUCHI_TEST)\n"
        "    close(sexp_fileno_fd(fileno));\n"
        "#else\n"
        "    (void)fileno;\n"
        "#endif",
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
    # Drop socket shutdown arms entirely (no sockets in puchi; fileno path stays).
    sexp_c = re.sub(
        r"      if \(sexp_port_shutdownp\(port\)\) \{\n"
        r"        /\* shutdown the socket if requested \*/\n"
        r"        if \(sexp_iportp\(port\)\)\n"
        r"          shutdown\(sexp_port_sock\(port\), sexp_oportp\(port\) \? SHUT_RDWR : SHUT_RD\);\n"
        r"        if \(sexp_oportp\(port\)\)\n"
        r"          shutdown\(sexp_port_sock\(port\), SHUT_WR\);\n"
        r"      \}\n",
        "",
        sexp_c,
        count=1,
    )
    # Fallback if comments differ / already stubbed
    sexp_c = re.sub(
        r"      if \(sexp_port_shutdownp\(port\)\) \{\n"
        r"        /\* shutdown the socket if requested \*/\n"
        r"        if \(sexp_iportp\(port\)\)\n"
        r"          /\* puchi: no sockets \*/ \(void\)port;\n"
        r"        if \(sexp_oportp\(port\)\)\n"
        r"          /\* puchi: no sockets \*/ \(void\)port;\n"
        r"      \}\n",
        "",
        sexp_c,
        count=1,
    )
    sexp_c = sexp_c.replace(
        "shutdown(sexp_port_sock(port), sexp_oportp(port) ? SHUT_RDWR : SHUT_RD);",
        "((void)0)",
    )
    sexp_c = sexp_c.replace(
        "shutdown(sexp_port_sock(port), SHUT_WR);",
        "((void)0)",
    )
    sexp_c = sexp_c.replace("free(sexp_cpointer_value(obj));", "SEXP_FREE(NULL, sexp_cpointer_value(obj));")
    sexp_c = re.sub(r"\bfree\(", "SEXP_FREE(NULL, ", sexp_c)
    # Fix double-wrap if any SEXP_FREE(NULL, SEXP_FREE
    sexp_c = sexp_c.replace("SEXP_FREE(NULL, SEXP_FREE(NULL, ", "SEXP_FREE(NULL, ")
    sexp_c = re.sub(r"sexp_malloc\(", "SEXP_MALLOC(NULL, ", sexp_c)
    sexp_c = patch_sexp_c_host(sexp_c)
    return sexp_c


# Deleted from the amalgamation. Value 0, and defined() is true, so
# `#if SEXP_USE_DL` goes away. With STABLE_ABI also ALWAYS_ZERO,
# `#if SEXP_USE_STABLE_ABI || SEXP_USE_DL` is deleted entirely.
# PLAN9 is never defined. STATIC_LIBS is NOT stripped — gated by PUCHI_TEST.
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

    # NATIVE_X86 is ALWAYS_ZERO_STRIP — the whole branch (including any
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

    p = sub.add_parser("patch-eval-h")
    p.add_argument("input")
    p.add_argument("output")

    p = sub.add_parser("rewrite-libc")
    p.add_argument("path")

    p = sub.add_parser("patch-opcodes")
    p.add_argument("path")

    sub.add_parser("features-force-extra")

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
        # Git Bash `cat` on Windows may emit cp1252; normalize to utf-8.
        raw = path.read_bytes()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("cp1252")
        write_text_lf(path, strip_dead_backends(normalize_newlines(text)))
    elif args.cmd == "strip-features":
        text = Path(args.input).read_text(encoding="utf-8")
        write_text_lf(Path(args.output), strip_features_manual(text))
    elif args.cmd == "patch-sexp-h":
        text = Path(args.input).read_text(encoding="utf-8")
        text = replace_platform_block(text)
        text = patch_sexp_h_host(text)
        text = scrub_sexp_h_gunk(text)
        text = scrub_portable_poll_stubs(text)
        write_text_lf(Path(args.output), text)
    elif args.cmd == "patch-eval-c":
        text = Path(args.input).read_text(encoding="utf-8")
        write_text_lf(Path(args.output), stub_file_ops_in_eval(text))
    elif args.cmd == "patch-gc-c":
        text = Path(args.input).read_text(encoding="utf-8")
        write_text_lf(Path(args.output), patch_gc_c(text))
    elif args.cmd == "patch-sexp-c":
        text = Path(args.input).read_text(encoding="utf-8")
        text = patch_sexp_c(text)
        text = scrub_sexp_c_gunk(text)
        write_text_lf(Path(args.output), text)
    elif args.cmd == "patch-eval-h":
        text = Path(args.input).read_text(encoding="utf-8")
        text = patch_eval_h_host(text)
        text = scrub_eval_h_gunk(text)
        write_text_lf(Path(args.output), text)
    elif args.cmd == "rewrite-libc":
        path = Path(args.path)
        write_text_lf(path, rewrite_libc_calls(path.read_text(encoding="utf-8")))
    elif args.cmd == "patch-opcodes":
        path = Path(args.path)
        write_text_lf(path, patch_opcodes(path.read_text(encoding="utf-8")))
    elif args.cmd == "features-force-extra":
        sys.stdout.write(features_force_extra())
    elif args.cmd == "post-strip-puchi":
        path = Path(args.path)
        text = normalize_newlines(path.read_text(encoding="utf-8"))
        text = scrub_shipped_always_zero_defines(text)
        assert_no_project_includes(text)
        write_text_lf(path, text)


if __name__ == "__main__":
    main()
