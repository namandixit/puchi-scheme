"""Post-amalgamation scrub: ALWAYS_ZERO define cleanup and single-header assert.

C body forks live in puchi/patches/; feature scrubbing is mechanical
(scrub_features_h). This module only runs after strip-dead-backends.
"""
from __future__ import annotations

import re

from puchi_host_embed import ALWAYS_ZERO_STRIP


def trim_init7_dead_arms(src: str) -> str:
    """Drop empty (threads) / (auto-force) cond-expand arms if present."""
    src = re.sub(
        r"\n\s*\(threads\)\s*\n(?:\s*\([^\n]*\)\n)*",
        "\n",
        src,
        count=1,
    )
    src = re.sub(
        r"\n\s*\(auto-force\)[^\n]*\n",
        "\n",
        src,
    )
    return src


def assert_no_project_includes(puchi_h: str) -> None:
    bad = []
    for m in re.finditer(r'#include\s+"([^"]+)"', puchi_h):
        path = m.group(1)
        if path.startswith(("opt/", "chibi/", "lib/")):
            bad.append(path)
    if bad:
        raise SystemExit(
            "puchi.h still has project #include(s) (not a single header): "
            + ", ".join(sorted(set(bad)))
        )


# OS / CPU / compiler tokens that must not appear in the product header.
_FORBIDDEN_OS_TOKENS = (
    "_WIN32",
    "_WIN64",
    "_Wp64",
    "_MSC_VER",
    "__APPLE__",
    "__linux__",
    "__CYGWIN__",
    "__MINGW",
    "PLAN9",
    "__arm",
    "__sparc",
    "__mips",
    "__riscv",
    "__amd64",
    "__x86_64",
    "__LP64__",
    "__GNUC__",
    "mode(TI)",
)


def _strip_c_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"//.*?$", "", src, flags=re.MULTILINE)
    return src


def _drop_gated_regions(src: str, gate_names: tuple[str, ...]) -> str:
    """Remove #if/#ifdef/#ifndef … #endif regions whose condition mentions gate_names.

    Handles nested #if correctly (line-oriented). A gated region swallows its
    #elif/#else arms too.
    """
    lines = src.splitlines(keepends=True)
    out: list[str] = []
    # stack entries: True if this level is a gate we are dropping
    stack: list[bool] = []

    def cond_is_gate(cond: str) -> bool:
        return any(name in cond for name in gate_names)

    def dropping() -> bool:
        return any(stack)

    for line in lines:
        s = line.lstrip()
        if s.startswith("#if"):
            # #if / #ifdef / #ifndef
            parts = s.split(None, 1)
            cond = parts[1] if len(parts) > 1 else ""
            gate = cond_is_gate(cond)
            if not dropping():
                if gate:
                    stack.append(True)
                else:
                    stack.append(False)
                    out.append(line)
            else:
                stack.append(True)
            continue
        if s.startswith("#elif") or s.startswith("#else"):
            if not stack:
                out.append(line)
                continue
            if stack[-1]:
                # stay in drop mode for this level
                continue
            out.append(line)
            continue
        if s.startswith("#endif"):
            if not stack:
                out.append(line)
                continue
            was_gate = stack.pop()
            if was_gate:
                continue
            if not dropping():
                out.append(line)
            continue
        if not dropping():
            out.append(line)
    return "".join(out)


def assert_no_os_residue(puchi_h: str) -> None:
    """Fail if amalgamated header still branches on OS/CPU/compiler or ships OS features."""
    code = _strip_c_comments(puchi_h)
    hits = []
    for tok in _FORBIDDEN_OS_TOKENS:
        if tok in code:
            hits.append(tok)
    if re.search(r'"windows"\s*,', code):
        hits.append('"windows" feature')
    # ".so" / sexp_so_extension only inside PUCHI_TEST or STATIC_LIBS (harness).
    without_test = _drop_gated_regions(
        code, ("PUCHI_TEST", "SEXP_USE_STATIC_LIBS")
    )
    if '".so"' in without_test or "sexp_so_extension" in without_test:
        hits.append('".so" outside PUCHI_TEST/STATIC_LIBS')
    if hits:
        raise SystemExit(
            "puchi.h still has platform residue: " + ", ".join(sorted(set(hits)))
        )


def scrub_shipped_always_zero_defines(puchi_h: str) -> str:
    """After strip-dead-backends, drop leftover #define NAME 0 for ALWAYS_ZERO."""
    for name in ALWAYS_ZERO_STRIP:
        puchi_h = re.sub(rf"#undef {name}\n", "", puchi_h)
        puchi_h = re.sub(rf"#define {name} 0\n", "", puchi_h)
        puchi_h = re.sub(
            rf"#ifndef {name}\n#define {name} 0\n#endif\n",
            "",
            puchi_h,
        )
    for name in (
        "SEXP_USE_GREEN_THREADS",
        "SEXP_USE_DL",
        "SEXP_USE_BOEHM",
        "SEXP_USE_IMAGE_LOADING",
        "SEXP_USE_MMAP_GC",
        "SEXP_USE_GC_FILE_DESCRIPTORS",
        "SEXP_USE_STRING_STREAMS",
        "SEXP_USE_NTP_GETTIME",
        "SEXP_USE_TIME_GC",
    ):
        puchi_h = re.sub(rf"#define {name} 0\n", "", puchi_h)
        puchi_h = re.sub(
            rf"#ifndef {name}\n#define {name} 0\n#endif\n",
            "",
            puchi_h,
        )
    return puchi_h
