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
