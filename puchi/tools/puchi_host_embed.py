"""Host-owned embed surface: feature flags and mechanical rewrites.

Body forks (FILE* → stream_ops, diskless boot, etc.) live in puchi/patches/.
This module keeps the ALWAYS_ZERO_STRIP set, libc → PUCHI_* rewrites, opcode
stripping, and the port-aware load stub used after trim_init7.
"""
from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# ALWAYS_ZERO_STRIP — must stay forced 0; strip_dead_backends deletes bodies.
# Do not re-enable after upstream Chibi refresh.
# ---------------------------------------------------------------------------
ALWAYS_ZERO_STRIP = frozenset(
    {
        "SEXP_USE_GREEN_THREADS",
        "SEXP_USE_DEBUG_THREADS",
        "SEXP_USE_DL",
        "SEXP_USE_BOEHM",
        "SEXP_USE_MMAP_GC",
        "SEXP_USE_POLL_PORT",
        "SEXP_USE_GC_FILE_DESCRIPTORS",
        "SEXP_USE_STRING_STREAMS",
        "SEXP_USE_NTP_GETTIME",
        "SEXP_USE_TIME_GC",
        "SEXP_USE_IMAGE_LOADING",
        "SEXP_USE_SEND_FILE",
        "SEXP_USE_UNIFY_FILENOS_BY_NUMBER",
        "SEXP_USE_BIDIRECTIONAL_PORTS",
        "SEXP_USE_AUTOCLOSE_PORTS",
        "SEXP_USE_LIMITED_MALLOC",
        "SEXP_USE_NATIVE_X86",
        "SEXP_USE_2010_EPOCH",
        "SEXP_USE_MAIN_HELP",
        "SEXP_USE_MAIN_ERROR_ADVISE",
        "SEXP_USE_DEBUG_GC",
        "SEXP_USE_SAFE_GC_MARK",
        "SEXP_USE_TRACK_ALLOC_SOURCE",
        "SEXP_USE_TRACK_ALLOC_BACKTRACE",
        "SEXP_USE_TRACK_ALLOC_TIMES",
        "SEXP_USE_TRACK_ALLOC_SIZES",
        "SEXP_USE_HEADER_MAGIC",
        "SEXP_USE_DEBUG_VM",
        "SEXP_USE_PROFILE_VM",
        "SEXP_USE_SAFE_ACCESSORS",
        "SEXP_USE_SAFE_VECTOR_ACCESSORS",
        "SEXP_USE_AUTO_FORCE",
        "SEXP_USE_CONSERVATIVE_GC",
        "SEXP_USE_FIXED_CHUNK_SIZE_HEAPS",
        "SEXP_USE_MALLOC",
        "SEXP_USE_IMMEDIATE_FLONUMS",
        "SEXP_USE_PLACEHOLDER_DIGITS",
        "SEXP_USE_SPLICING_LET_SYNTAX",
        "SEXP_USE_FLAT_SYNTACTIC_CLOSURES",
        "SEXP_USE_UNWRAPPED_TOPLEVEL_BINDINGS",
        "SEXP_USE_UNSAFE_PUSH",
        "SEXP_USE_STRING_INDEX_TABLE",
        "SEXP_USE_STRING_REF_CACHE",
        "SEXP_USE_TAIL_JUMPS",
        "SEXP_USE_UNBOXED_LOCALS",
        "SEXP_USE_RESERVE_OPCODE",
        "SEXP_USE_PEDANTIC",
        "SEXP_USE_SIGNED_SHIFTS",
        "SEXP_USE_STABLE_ABI",
        "SEXP_USE_GLOBAL_HEAP",
        "SEXP_USE_GLOBAL_SYMBOLS",
    }
)

# Longer names first so rewrite does not partially match.
LIBC_REWRITES = [
    ("strncasecmp", "PUCHI_STRNCASECMP"),
    ("strcasecmp", "PUCHI_STRCASECMP"),
    ("memcpy", "PUCHI_MEMCPY"),
    ("memmove", "PUCHI_MEMMOVE"),
    ("memset", "PUCHI_MEMSET"),
    ("memcmp", "PUCHI_MEMCMP"),
    ("strlen", "PUCHI_STRLEN"),
    ("strcmp", "PUCHI_STRCMP"),
    ("strncmp", "PUCHI_STRNCMP"),
    ("strncpy", "PUCHI_STRNCPY"),
    ("strchr", "PUCHI_STRCHR"),
    ("snprintf", "PUCHI_SNPRINTF"),
    ("sprintf", "PUCHI_SPRINTF"),
    ("sscanf", "PUCHI_SSCANF"),
    ("isalpha", "PUCHI_ISALPHA"),
    ("isxdigit", "PUCHI_ISXDIGIT"),
    ("isdigit", "PUCHI_ISDIGIT"),
    ("isspace", "PUCHI_ISSPACE"),
    ("tolower", "PUCHI_TOLOWER"),
    ("toupper", "PUCHI_TOUPPER"),
    ("pow", "PUCHI_POW"),
    ("exp", "PUCHI_EXP"),
    ("log", "PUCHI_LOG"),
    ("sin", "PUCHI_SIN"),
    ("cos", "PUCHI_COS"),
    ("tan", "PUCHI_TAN"),
    ("atan", "PUCHI_ATAN"),
    ("atan2", "PUCHI_ATAN2"),
    ("sinh", "PUCHI_SINH"),
    ("cosh", "PUCHI_COSH"),
    ("sqrt", "PUCHI_SQRT"),
    ("floor", "PUCHI_FLOOR"),
    ("ceil", "PUCHI_CEIL"),
    ("fabs", "PUCHI_FABS"),
    ("fabsl", "PUCHI_FABSL"),
    ("fmod", "PUCHI_FMOD"),
    ("trunc", "PUCHI_TRUNC"),
    ("isfinite", "PUCHI_ISFINITE"),
    ("isnan", "PUCHI_ISNAN"),
    ("isinf", "PUCHI_ISINF"),
    ("round", "PUCHI_ROUND"),
    ("labs", "PUCHI_LABS"),
    ("acos", "PUCHI_ACOS"),
]

# Scheme opcode names removed from core (harness/host installs via foreigns).
STRIP_OPCODE_NAMES = (
    "fileno?",
    "open-input-file-descriptor",
    "open-output-file-descriptor",
    "port-fileno",
    "open-binary-input-file",
    "open-binary-output-file",
    "open-input-file",
    "open-output-file",
    "current-module-path",
    "find-module-file",
    "load-module-file",
    "add-module-directory",
)


def patch_opcodes(opcodes: str) -> str:
    """Remove Scheme opcodes that hosts/harness install, plus fileno/fd surface."""
    lines = opcodes.splitlines(keepends=True)
    out = []
    for line in lines:
        drop = False
        for name in STRIP_OPCODE_NAMES:
            if f'"{name}"' in line:
                drop = True
                break
        if not drop:
            out.append(line)
    return "".join(out)


def rewrite_libc_calls(src: str) -> str:
    """Rewrite libc call sites to PUCHI_* wrappers.

    Rewrites normal code and #define macro bodies; skips #include and
    lines that define PUCHI_* themselves.
    """
    src = re.sub(
        r"\? strcasecmp : strcmp\)",
        "? PUCHI_STRCASECMP : PUCHI_STRCMP)",
        src,
    )
    src = re.sub(
        r"\? strcmp : strcasecmp\)",
        "? PUCHI_STRCMP : PUCHI_STRCASECMP)",
        src,
    )
    lines = src.splitlines(keepends=True)
    out = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("#include"):
            out.append(line)
            continue
        if stripped.startswith("#define PUCHI_"):
            out.append(line)
            continue
        if stripped.startswith("#") and not stripped.startswith("#define"):
            out.append(line)
            continue
        for libc, wrap in LIBC_REWRITES:
            line = re.sub(rf"\b{libc}\s*\(", f"{wrap}(", line)
        out.append(line)
    return "".join(out)


def rewrite_host_allocators(src: str) -> str:
    """Rewrite malloc/free/sexp_malloc/sexp_free to SEXP_MALLOC/SEXP_FREE."""
    lines = src.splitlines(keepends=True)
    out = []
    for line in lines:
        stripped = line.lstrip()
        if stripped.startswith("#include"):
            out.append(line)
            continue
        if stripped.startswith("#define SEXP_MALLOC") or stripped.startswith("#define SEXP_FREE"):
            out.append(line)
            continue
        if stripped.startswith("#define sexp_malloc") or stripped.startswith("#define sexp_free"):
            out.append(line)
            continue
        # Already rewritten
        if "SEXP_MALLOC" in line or "SEXP_FREE" in line:
            out.append(line)
            continue
        line = re.sub(r"\bsexp_malloc\s*\(", "SEXP_MALLOC(NULL, ", line)
        line = re.sub(r"\bsexp_free\s*\(", "SEXP_FREE(NULL, ", line)
        line = re.sub(r"\bmalloc\s*\(", "SEXP_MALLOC(NULL, ", line)
        line = re.sub(r"\bfree\s*\(", "SEXP_FREE(NULL, ", line)
        out.append(line)
    return "".join(out)


def brand_puchi_features(src: str) -> str:
    """Advertise puchi-* features while keeping ``chibi`` for cond-expand.

    Libraries under lib/ use ``(cond-expand (chibi ...) (else (import (scheme
    base)) ...))``. Dropping the ``chibi`` feature makes those else-branches
    import (scheme base) while it is still loading → cyclic module error.

    Do not re-inject OS feature strings (``windows``, …). The harness may cons
    ``windows`` onto ``*features*`` at runtime when needed for upstream libs.
    """
    src = src.replace('"chibi-" sexp_version', '"puchi-" sexp_version')
    # Drop any leftover OS feature arm before branding.
    src = re.sub(
        r"#if defined\(_WIN32\)\n\s*\"windows\",\n#endif\n",
        "",
        src,
    )
    # Keep "chibi" and add "puchi" alongside (do not replace).
    src = re.sub(
        r'^(\s*)"chibi",\s*$',
        r'\1"chibi",\n\1"puchi",',
        src,
        flags=re.MULTILINE,
    )
    return src


def fold_always_zero_type_slots(src: str) -> str:
    """Simplify type-table slot expressions that reference ALWAYS_ZERO flags."""
    src = src.replace(
        "1+SEXP_USE_STRING_INDEX_TABLE",
        "1",
    )
    src = re.sub(
        r"3\+\(SEXP_USE_STABLE_ABI\|\|SEXP_USE_RENAME_BINDINGS\)",
        "3+(SEXP_USE_RENAME_BINDINGS)",
        src,
    )
    src = re.sub(
        r"12\+\(SEXP_USE_STABLE_ABI\|\|SEXP_USE_DL\)",
        "12",
        src,
    )
    return src


def trim_init7_load_port(src: str) -> str:
    """After trim_init7 file stubs, restore load that accepts ports."""
    stub = (
        "(define (load file . o)\n"
        '  (error "load: not available in puchi core; host/harness may redefine" file))\n'
    )
    port_load = """(define (load file . o)
  (let ((env (if (pair? o) (car o) (interaction-environment))))
    (cond
     ((port? file)
      (let ((old-env (current-environment)))
        (dynamic-wind
          (lambda () (set-current-environment! env))
          (lambda ()
            (set-port-line! file 1)
            (let lp ()
              (let ((x (read file)))
                (cond
                 ((eof-object? x) (if #f #f))
                 (else (eval x env) (lp))))))
          (lambda () (set-current-environment! old-env)))))
     (else
      (error "load: file paths not available in puchi core; host may redefine" file)))))
"""
    if stub in src:
        return src.replace(stub, port_load, 1)
    raise SystemExit("trim_init7_load_port: load stub not found")
