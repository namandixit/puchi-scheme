#!/usr/bin/env python3
"""Generate stb-style puchi host API fragments from patched Chibi headers.

Reads puchi/product/puchi_host_symbols.txt (HOST manifest) plus workdir
sexp.h / eval.h / features.h, writes:

  host_api_abi.inc      - types/macros/constants as puchi_*/PUCHI_* (always visible)
  host_api_decls.inc    - PUCHI_API function declarations for HOST + product entrypoints
  host_api_aliases.inc  - sexp_*/SEXP_* -> puchi_*/PUCHI_* (inside IMPLEMENTATION)
  host_api_wrappers.inc - puchi_* function wrappers calling sexp_*
  host_api_test_decls.inc / host_api_test_wrappers.inc - non-HOST SEXP_API as puchi_TEST_*
  host_api_test_clib_aliases.inc - TEST_CLIB-only sexp_* -> puchi_* / puchi_TEST_*
  features_host.inc     - PUCHI_* tunables promoted from features.h #if !defined(SEXP_*)
  sexp.h / eval.h       - rewritten: HOST ABI moved out; SEXP_API decls kept
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "product" / "puchi_host_symbols.txt"

# Do not rename these SEXP_* tokens — strip-dead-backends / features still need them.
_SEXP_KEEP = {
    "SEXP_API",
    "SEXP_INLINE",
    "SEXP_H",
    "SEXP_EVAL_H",
    "SEXP_BIGNUM_H",
    "SEXP_ABI_IDENTIFIER",
}

PRODUCT_FUNCS = [
    (
        "puchi_create_context",
        "puchi_uint_t heap_size, puchi_uint_t heap_max_size, const puchi_host *host",
    ),
    ("puchi_delete_context", "puchi ctx"),
    ("puchi_load_default_libs", "puchi ctx"),
    ("puchi_enable_modules", "puchi ctx, const puchi_module_ops *ops"),
    (
        "puchi_make_eval_context_host",
        "puchi ctx, puchi stack, puchi env, puchi_uint_t size, "
        "puchi_uint_t max_size, const puchi_host *host",
    ),
]

# Enums that stay in stripped IMPL/TEST headers (original sexp_* names).
# Not needed by always-visible HOST macros; hosts must not see them.
_IMPL_ONLY_ENUM_TAGS = frozenset(
    {
        "sexp_opcode_names",
        "sexp_opcode_classes",
        "sexp_core_form_names",
    }
)

# Typedefs kept only under IMPL/TEST (manifest has proc1/proc2 only).
_IMPL_ONLY_TYPEDEFS = frozenset(
    {
        "sexp_proc3",
        "sexp_proc4",
        "sexp_proc5",
        "sexp_proc6",
        "sexp_proc7",
    }
)


def to_puchi(name: str) -> str:
    if name == "sexp":
        return "puchi"
    if name == "sexp_struct":
        return "puchi_struct"
    if name.startswith("SEXP_USE_"):
        return name  # feature flags stay
    if name.startswith("SEXP_"):
        return "PUCHI_" + name[5:]
    if name.startswith("sexp_"):
        return "puchi_" + name[5:]
    return name


def load_manifest(path: Path):
    host_fns: dict[str, str] = {}
    host_macros: set[str] = set()
    host_typedefs: set[str] = set()
    host_enums: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        kind = parts[0]
        if kind == "function" and len(parts) >= 3:
            host_fns[parts[1]] = parts[2]
        elif kind == "macro" and len(parts) >= 2:
            host_macros.add(parts[1])
        elif kind == "typedef" and len(parts) >= 2:
            host_typedefs.add(parts[1])
        elif kind == "enum" and len(parts) >= 2:
            host_enums.add(parts[1])
    return host_fns, host_macros, host_typedefs, host_enums


def rename_sexp_identifiers(text: str, keep_fns: set[str] | None = None) -> str:
    """Rename sexp_/SEXP_/sexp/sexp_struct to puchi equivalents; keep SEXP_USE_*.

    keep_fns: SEXP_API function names left as sexp_* inside macro bodies so
    host macros still call the real Chibi definitions.
    """
    protected: dict[str, str] = {}

    def protect(m: re.Match) -> str:
        key = f"__PUCHI_KEEP_{len(protected)}__"
        protected[key] = m.group(0)
        return key

    text = re.sub(r"\bSEXP_USE_[A-Z0-9_]+\b", protect, text)
    for name in _SEXP_KEEP:
        text = re.sub(rf"\b{name}\b", protect, text)
    if keep_fns:
        for fn in sorted(keep_fns, key=len, reverse=True):
            text = re.sub(rf"\b{re.escape(fn)}\b", protect, text)

    text = re.sub(r"\bsexp_struct\b", "puchi_struct", text)
    text = re.sub(r"\bSEXP_", "PUCHI_", text)
    text = re.sub(r"\bsexp_", "puchi_", text)
    text = re.sub(r"\bsexp\b", "puchi", text)

    for key, val in protected.items():
        text = text.replace(key, val)
    return text


# Size/layout knobs that appear in the always-visible ABI struct (must be defined
# before host ABI). Feature flags (SEXP_USE_*) stay in features.h under impl.
_HOST_SIZE_KNOBS = {
    "SEXP_INITIAL_HEAP_SIZE",
    "SEXP_MAXIMUM_HEAP_SIZE",
    "SEXP_MINIMUM_HEAP_SIZE",
    "SEXP_GROW_HEAP_RATIO",
    "SEXP_GROW_HEAP_FACTOR",
    "SEXP_MARK_STACK_COUNT",
    "SEXP_DEFAULT_QUANTUM",
    "SEXP_MAX_ANALYZE_DEPTH",
    "SEXP_FLEXIBLE_ARRAY_SIZE",
    "SEXP_BACKTRACE_SIZE",
    "SEXP_ALLOC_HISTOGRAM_BUCKETS",
    "SEXP_MAXIMUM_TYPES",
}


def extract_if_defined_tunables(features: str) -> tuple[str, list[tuple[str, str]]]:
    """Promote host size knobs from features.h to PUCHI_* (always-visible)."""
    tunables: list[tuple[str, str]] = []

    # #ifndef SEXP_FOO / #define SEXP_FOO val / #endif
    ifndef_pat = re.compile(
        r"#ifndef\s+(SEXP_[A-Z0-9_]+)\s*\n#define\s+\1\b([^\n]*)\n#endif",
        re.M,
    )
    # #if !defined(SEXP_FOO) / #define ... / #endif
    ifnd_pat = re.compile(
        r"#if\s*!defined\((SEXP_[A-Z0-9_]+)\)\s*\n#define\s+\1\b([^\n]*)\n#endif",
        re.M,
    )
    # Bare #define SEXP_MARK_STACK_COUNT 1024 (no ifndef)
    bare_pat = re.compile(
        r"#define\s+(SEXP_[A-Z0-9_]+)\s+([^\n]+)\n",
        re.M,
    )

    def consider(name: str, val: str) -> None:
        if name.startswith("SEXP_USE_") or name not in _HOST_SIZE_KNOBS:
            return
        if any(n == name for n, _ in tunables):
            return
        tunables.append((name, val.strip()))

    def repl_block(m: re.Match) -> str:
        name, val = m.group(1), m.group(2).strip()
        consider(name, val)
        if name not in _HOST_SIZE_KNOBS:
            return m.group(0)
        p = to_puchi(name)
        return f"#if !defined({name})\n#define {name} {p}\n#endif"

    features = ifndef_pat.sub(repl_block, features)
    features = ifnd_pat.sub(repl_block, features)

    def repl_bare(m: re.Match) -> str:
        name, val = m.group(1), m.group(2).strip()
        if name not in _HOST_SIZE_KNOBS:
            return m.group(0)
        consider(name, val)
        p = to_puchi(name)
        return f"#if !defined({name})\n#define {name} {p}\n#endif\n"

    features = bare_pat.sub(repl_bare, features)
    return features, tunables


def split_header_chunks(text: str) -> list[tuple[str, str]]:
    """Return list of (kind, chunk) where kind is 'api_fn'|'other'."""
    lines = text.splitlines(keepends=True)
    chunks: list[tuple[str, str]] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if "SEXP_API" in line:
            chunk = line
            j = i
            while j + 1 < len(lines) and ";" not in chunk:
                j += 1
                chunk += lines[j]
            chunks.append(("api_fn", chunk))
            i = j + 1
            continue
        chunks.append(("other", line))
        i += 1
    return chunks


def is_pp_line(chunk: str) -> bool:
    s = chunk.lstrip()
    return s.startswith("#")


def is_conditional_pp(chunk: str) -> bool:
    s = chunk.lstrip()
    return bool(
        re.match(
            r"#\s*(if|ifdef|ifndef|elif|else|endif)\b",
            s,
        )
    )


def is_include_guard_define(chunk: str) -> bool:
    m = re.match(r"#\s*define\s+(SEXP_H|SEXP_EVAL_H|SEXP_BIGNUM_H)\b", chunk.lstrip())
    return m is not None


def gather_define(chunks: list[tuple[str, str]], i: int) -> tuple[str, int]:
    dbuf = chunks[i][1]
    j = i
    while dbuf.rstrip("\r\n").endswith("\\") and j + 1 < len(chunks):
        j += 1
        dbuf += chunks[j][1]
    return dbuf, j


def gather_balanced(chunks: list[tuple[str, str]], i: int) -> tuple[str, int]:
    buf = chunks[i][1]
    j = i
    depth = buf.count("{") - buf.count("}")
    if "{" not in buf and ";" in buf:
        return buf, i
    while j + 1 < len(chunks) and depth <= 0 and "{" not in buf:
        j += 1
        buf += chunks[j][1]
        depth = buf.count("{") - buf.count("}")
    while depth > 0 and j + 1 < len(chunks):
        j += 1
        buf += chunks[j][1]
        depth += chunks[j][1].count("{") - chunks[j][1].count("}")
    # typedef/struct ending
    while ";" not in buf and j + 1 < len(chunks) and depth <= 0:
        j += 1
        buf += chunks[j][1]
    return buf, j


def collect_api_fn_names(text: str) -> set[str]:
    names: set[str] = set()
    for kind, chunk in split_header_chunks(text):
        if kind != "api_fn":
            continue
        m = re.search(r"\b(sexp_\w+)\s*\(", chunk)
        if m:
            names.add(m.group(1))
        else:
            m = re.search(r"\b(sexp_\w+)\s*;", chunk)
            if m:
                names.add(m.group(1))
    return names


def collect_api_fn_protos(text: str) -> dict[str, str]:
    """Map SEXP_API function name -> prototype string (no SEXP_API / trailing ;)."""
    protos: dict[str, str] = {}
    for kind, chunk in split_header_chunks(text):
        if kind != "api_fn":
            continue
        clean = re.sub(r"\s+", " ", chunk.strip()).rstrip(";").strip()
        clean = re.sub(r"^SEXP_API\s+", "", clean)
        m = re.search(r"\b(sexp_\w+)\s*\(", clean)
        if m:
            protos[m.group(1)] = clean
    return protos


def collect_api_fn_pp_guards(text: str) -> dict[str, list[str]]:
    """Map SEXP_API name -> active #if/#ifdef stack at the decl (feature gates)."""
    guards: dict[str, list[str]] = {}
    stack: list[str] = []
    for kind, chunk in split_header_chunks(text):
        raw = chunk.lstrip()
        if kind == "other" and is_conditional_pp(chunk):
            if re.match(r"#\s*if(n?def)?\b", raw):
                stack.append(chunk.strip())
            elif re.match(r"#\s*elif\b", raw):
                if stack:
                    stack[-1] = chunk.strip()
            elif re.match(r"#\s*else\b", raw):
                if stack:
                    # Keep a marker so we know we're on the else branch; rewrite
                    # to a negated form is unnecessary — wrappers use the same
                    # nesting via copied #if lines is not practical; store as-is
                    # only for ifndef/ifdef/if that we can mirror. For else,
                    # drop this level from emission (complex); skip tracking.
                    pass
            elif re.match(r"#\s*endif\b", raw):
                if stack:
                    stack.pop()
            continue
        if kind != "api_fn":
            continue
        m = re.search(r"\b(sexp_\w+)\s*\(", chunk)
        if not m:
            continue
        name = m.group(1)
        # Only keep simple feature gates we know how to mirror as PUCHI_*.
        mirrored: list[str] = []
        for g in stack:
            g2 = g.strip()
            if re.search(r"SEXP_USE_BIGNUMS|SEXP_USE_RATIOS|SEXP_USE_COMPLEX", g2):
                mirrored.append("#if defined(PUCHI_ENABLE_NUMERICAL_TOWER)")
            elif re.search(r"SEXP_USE_FLONUMS", g2) and "BIGNUM" not in g2:
                mirrored.append("#if !defined(PUCHI_INTEGER_ONLY)")
            elif "PUCHI_ENABLE_NUMERICAL_TOWER" in g2 or "PUCHI_INTEGER_ONLY" in g2:
                mirrored.append(g2 if g2.startswith("#") else f"#if {g2}")
            elif re.search(r"defined\s*\(\s*PUCHI_TEST\s*\)", g2):
                mirrored.append("#if defined(PUCHI_TEST)")
        # Dedup while preserving order
        seen: set[str] = set()
        out: list[str] = []
        for x in mirrored:
            if x not in seen:
                seen.add(x)
                out.append(x)
        guards[name] = out
    return guards


def collect_macro_catalog(text: str) -> dict[str, list[str]]:
    """Map #define name -> list of bodies (all #if variants) for dep scanning."""
    cat: dict[str, list[str]] = {}
    chunks = split_header_chunks(text)
    i = 0
    while i < len(chunks):
        kind, chunk = chunks[i]
        if kind == "api_fn":
            i += 1
            continue
        if is_pp_line(chunk):
            mdef = re.match(r"#\s*define\s+([A-Za-z_][A-Za-z0-9_]*)", chunk.lstrip())
            if mdef:
                name = mdef.group(1)
                dbuf, j = gather_define(chunks, i)
                margs = re.match(
                    r"#\s*define\s+" + re.escape(name) + r"(\([^)]*\))?(.*)",
                    dbuf.lstrip(),
                    re.S,
                )
                body = margs.group(2) if margs else ""
                cat.setdefault(name, []).append(body)
                i = j + 1
                continue
        i += 1
    return cat


def compute_macro_closure(
    seed: set[str], catalogs: list[dict[str, list[str]]]
) -> set[str]:
    """HOST macros plus macros their bodies transitively reference."""
    catalog: dict[str, list[str]] = {}
    for cat in catalogs:
        for name, bodies in cat.items():
            catalog.setdefault(name, []).extend(bodies)

    keep = set(seed)
    queue = list(keep)
    while queue:
        name = queue.pop()
        for body in catalog.get(name, []):
            for ref in re.findall(r"\b(?:sexp_\w+|SEXP_[A-Z0-9_]+)\b", body):
                if ref.startswith("SEXP_USE_") or ref in _SEXP_KEEP:
                    continue
                if ref in catalog and ref not in keep:
                    keep.add(ref)
                    queue.append(ref)
    return keep


def is_chibi_macro_name(name: str) -> bool:
    return name.startswith("sexp_") or (
        name.startswith("SEXP_") and not name.startswith("SEXP_USE_")
    )


def _enum_tag_name(buf: str) -> str | None:
    m = re.search(r"\benum\s+(sexp_[A-Za-z0-9_]+)\b", buf)
    return m.group(1) if m else None


def _typedef_declared_names(buf: str) -> set[str]:
    """Names introduced by a typedef (best-effort for one-line / small forms)."""
    names: set[str] = set()
    # typedef ... (*sexp_proc3) (...);
    for m in re.finditer(r"\(\s*\*\s*(sexp_[A-Za-z0-9_]+)\s*\)", buf):
        names.add(m.group(1))
    # typedef struct foo *sexp;  /  typedef unsigned int sexp_tag_t;
    m = re.search(
        r"typedef\s+.+\b(sexp_[A-Za-z0-9_]+|sexp)\s*;",
        buf.strip().split("\n")[-1] if ";" in buf else buf,
    )
    if m:
        names.add(m.group(1))
    return names


def build_abi_and_stripped(
    text: str,
    label: str,
    host_fns: dict[str, str],
    api_fn_names: set[str],
    keep_macros: set[str],
    host_macros: set[str] | None = None,
    host_typedefs: set[str] | None = None,
    host_enums: set[str] | None = None,
) -> tuple[str, str, list[str]]:
    """Return (abi_fragment, stripped_header, alias_macro_lines).

    Only macros in keep_macros (HOST + transitive deps) go to the always-visible
    ABI as puchi_*/PUCHI_*. Other Chibi macros stay in the stripped header under
    IMPLEMENTATION/TEST with their original sexp_*/SEXP_* bodies.

    Enums in _IMPL_ONLY_ENUM_TAGS and typedefs in _IMPL_ONLY_TYPEDEFS stay
    stripped (original names). Other structs/enums/typedefs remain always-visible
    (object layout + HOST tag enums). host_typedefs/host_enums are retained for
    documentation / future allowlisting; impl-only sets are the active filter.
    """
    # host_typedefs / host_enums document the HOST manifest; the active filter
    # for this pass is the impl-only denylist (opcodes / proc3–7).
    _ = (host_typedefs, host_enums)
    host_macros = host_macros or set()
    abi: list[str] = [f"\n/* ---- from {label} ---- */\n"]
    stripped: list[str] = [f"/* stripped {label} (SEXP_API + gating) */\n"]
    aliases: list[str] = []
    glue_banner_emitted = False
    # Function-like macros in this header (possibly #if-gated); prefer puchi_*
    # peers over keeping sexp_* API names as callees in other macro bodies.
    # Always-visible Host macros must not spell sexp_* in their bodies — rename
    # callees to puchi_* (HOST wrappers / decls provide the linkable symbols).
    # Keep sexp_finalize_fileno only if it appears in Host ABI (normally IMPL-only).
    keep_callees: set[str] = {"sexp_finalize_fileno"}
    keep_callees -= keep_macros
    _ = api_fn_names  # catalog still drives API fn extraction elsewhere
    chunks = split_header_chunks(text)
    i = 0

    while i < len(chunks):
        kind, chunk = chunks[i]

        if kind == "api_fn":
            stripped.append(chunk if chunk.endswith("\n") else chunk + "\n")
            i += 1
            continue

        # Include guards / includes: stripped only (never ABI — avoids extra #endif)
        if re.match(r"#\s*ifndef\s+SEXP_(H|EVAL_H|BIGNUM_H)\b", chunk.lstrip()):
            stripped.append(chunk)
            i += 1
            continue
        if is_include_guard_define(chunk):
            stripped.append(chunk)
            i += 1
            continue
        if re.match(r"#\s*endif\b", chunk.lstrip()) and re.search(
            r"SEXP_(H|EVAL_H|BIGNUM_H)", chunk
        ):
            stripped.append(chunk)
            i += 1
            continue
        if chunk.lstrip().startswith("#include"):
            i += 1
            continue

        # Conditionals: both sides (ABI may have empty nests after macro trim;
        # keeps #if/#endif balance).
        if is_conditional_pp(chunk):
            stripped.append(chunk if chunk.endswith("\n") else chunk + "\n")
            abi.append(rename_sexp_identifiers(chunk if chunk.endswith("\n") else chunk + "\n"))
            i += 1
            continue

        # Other preprocessor (pragma, error, undef, define SEXP_API/INLINE)
        if is_pp_line(chunk):
            mdef = re.match(r"#\s*define\s+([A-Za-z_][A-Za-z0-9_]*)", chunk.lstrip())
            if mdef:
                name = mdef.group(1)
                dbuf, j = gather_define(chunks, i)
                if name in ("SEXP_API", "SEXP_INLINE"):
                    stripped.append(dbuf if dbuf.endswith("\n") else dbuf + "\n")
                    i = j + 1
                    continue
                # Non-kept Chibi macros: leave original body in stripped only.
                if is_chibi_macro_name(name) and name not in keep_macros:
                    stripped.append(dbuf if dbuf.endswith("\n") else dbuf + "\n")
                    i = j + 1
                    continue
                # Feature-flag defines stay in stripped (never ABI).
                if name.startswith("SEXP_USE_"):
                    stripped.append(dbuf if dbuf.endswith("\n") else dbuf + "\n")
                    i = j + 1
                    continue
                # Non-Chibi defines that aren't in the keep set stay stripped.
                if not is_chibi_macro_name(name) and name not in keep_macros:
                    stripped.append(dbuf if dbuf.endswith("\n") else dbuf + "\n")
                    i = j + 1
                    continue
                # Kept macro → ABI as puchi_*/PUCHI_* + IMPL alias.
                margs = re.match(
                    r"#\s*define\s+" + re.escape(name) + r"(\([^)]*\))?(.*)",
                    dbuf.lstrip(),
                    re.S,
                )
                args_s = margs.group(1) if margs and margs.group(1) else ""
                body_s = margs.group(2) if margs else dbuf
                puchi_name = to_puchi(name)
                body_renamed = rename_sexp_identifiers(
                    body_s, keep_fns=keep_callees - {name}
                )
                if is_chibi_macro_name(name):
                    renamed = f"#define {puchi_name}{args_s}{body_renamed}"
                else:
                    renamed = rename_sexp_identifiers(dbuf, keep_fns=api_fn_names)
                if not renamed.endswith("\n"):
                    renamed += "\n"
                # One-time banner before first transitive INTERNAL glue macro.
                if (
                    not glue_banner_emitted
                    and name not in host_macros
                    and is_chibi_macro_name(name)
                ):
                    abi.append(
                        "/* ABI glue: INTERNAL helpers required by HOST macros.\n"
                        " * Not a host calling convention — prefer documented\n"
                        " * puchi_* / PUCHI_* entrypoints and HOST-rated macros. */\n"
                    )
                    glue_banner_emitted = True
                abi.append(renamed)
                if is_chibi_macro_name(name):
                    if args_s:
                        alias_line = (
                            f"#define {name}{args_s} {puchi_name}{args_s}"
                        )
                        # Dual macro/function names: only alias when the puchi_*
                        # macro is active (avoids rewriting sexp_* definitions).
                        # sexp_alloc is special: bare decl (no SEXP_API) so it is
                        # not in api_fn_names, yet gc.c defines the body — an
                        # ungated alias rewrites that into static puchi_alloc.
                        _dual = (
                            name in api_fn_names
                            or name in host_fns
                            or name
                            in (
                                "sexp_alloc",
                                "sexp_alloc_atomic",
                            )
                        )
                        if _dual:
                            aliases.append(f"#if defined({puchi_name})")
                            aliases.append(alias_line)
                            if name in ("sexp_alloc", "sexp_alloc_atomic"):
                                # Native GC: no puchi_alloc macro; point the
                                # host name at the static sexp_alloc body.
                                aliases.append("#else")
                                aliases.append(f"#define {puchi_name} {name}")
                            aliases.append("#endif")
                        else:
                            aliases.append(alias_line)
                    else:
                        # Skip object-like alias if a function-like form exists
                        # (e.g. sexp_alloc_atomic both (ctx,size) and bare).
                        if any(a.startswith(f"#define {name}(") for a in aliases):
                            pass
                        else:
                            aliases.append(f"#define {name} {puchi_name}")
                i = j + 1
                continue
            # #undef / #error / #pragma — both sides (renamed in abi)
            stripped.append(chunk if chunk.endswith("\n") else chunk + "\n")
            abi.append(rename_sexp_identifiers(chunk if chunk.endswith("\n") else chunk + "\n"))
            i += 1
            continue

        # struct / union / enum / typedef involving sexp
        if re.match(r"\s*(typedef\s+)?(struct|union|enum)\b", chunk) or chunk.lstrip().startswith(
            "typedef"
        ):
            # One-line typedef?
            if chunk.lstrip().startswith("typedef") and ";" in chunk:
                buf = chunk
                j = i
            else:
                buf, j = gather_balanced(chunks, i)
            if re.search(r"\bsexp_|\bsexp\b|\bSEXP_", buf) or "struct" in buf or "enum" in buf or "union" in buf:
                enum_tag = _enum_tag_name(buf)
                td_names = _typedef_declared_names(buf)
                # Impl-only enums/typedefs: keep original sexp_* names in stripped.
                if enum_tag in _IMPL_ONLY_ENUM_TAGS or (
                    td_names & _IMPL_ONLY_TYPEDEFS
                ):
                    stripped.append(buf if buf.endswith("\n") else buf + "\n")
                    i = j + 1
                    continue
                if re.search(r"typedef\s+struct\s+sexp_struct\s*\*\s*sexp\s*;", buf):
                    abi.append("typedef struct puchi_struct *puchi;\n")
                else:
                    renamed = rename_sexp_identifiers(buf)
                    abi.append(renamed if renamed.endswith("\n") else renamed + "\n")
                    # Enum constant aliases only (not struct fields referencing
                    # features.h knobs like PUCHI_MARK_STACK_COUNT).
                    if re.search(r"\benum\b", buf):
                        # dict.fromkeys: dedupe in source order (a set's
                        # order varies with PYTHONHASHSEED → puchi.h drift).
                        for name in dict.fromkeys(re.findall(r"\bPUCHI_[A-Z0-9_]+\b", renamed)):
                            if name.startswith("PUCHI_USE_"):
                                continue
                            aliases.append(f"#define SEXP_{name[6:]} {name}")
                        # Do not typedef enum tags to sexp_*: in C the tag
                        # namespace is separate from ordinary identifiers
                        # (e.g. enum sexp_opcode_names vs const char** sexp_opcode_names).
                i = j + 1
                continue
            stripped.append(buf if buf.endswith("\n") else buf + "\n")
            i = j + 1
            continue

        # Blank / comment / misc: keep in stripped; copy comments to abi sparingly
        stripped.append(chunk if chunk.endswith("\n") else chunk + "\n")
        i += 1

    return "".join(abi), "".join(stripped), aliases


def build_host_fn_decl(proto: str) -> str:
    p = rename_sexp_identifiers(proto.strip().rstrip(";"))
    return "PUCHI_API " + p + ";"


def build_test_fn_decl(proto: str) -> str:
    """SEXP_API proto → PUCHI_API puchi_TEST_<stem>(...);"""
    p = rename_sexp_identifiers(proto.strip().rstrip(";"))
    p = re.sub(r"\bpuchi_(\w+)\s*\(", r"puchi_TEST_\1(", p, count=1)
    return "PUCHI_API " + p + ";"


# Bodies live in bignum.c under PUCHI_ENABLE_NUMERICAL_TOWER only.
_TOWER_ONLY = {
    "sexp_acos",
    "sexp_asin",
    "sexp_atan",
    "sexp_add",
    "sexp_sub",
    "sexp_mul",
    "sexp_div",
    "sexp_bignum_to_double",
    "sexp_bignum_to_sint",
    "sexp_bignum_to_uint",
    "sexp_ceiling",
    "sexp_compare",
    "sexp_cos",
    "sexp_exact_sqrt",
    "sexp_exp",
    "sexp_floor",
    "sexp_inexact_sqrt",
    "sexp_log",
    "sexp_quotient",
    "sexp_ratio_to_double",
    "sexp_remainder",
    "sexp_round",
    "sexp_sin",
    "sexp_sqrt",
    "sexp_tan",
    "sexp_to_double",
    "sexp_trunc",
}
# Present with flonums (default or tower), absent under INTEGER_ONLY.
_NO_INTEGER = {
    "sexp_make_flonum",
}


def open_guards_for(
    sexp_name: str,
    puchi_macro_name: str,
    abi_fn_macros: set[str],
    pp_guards: dict[str, list[str]] | None = None,
) -> list[str]:
    open_guards: list[str] = []
    if pp_guards and sexp_name in pp_guards and pp_guards[sexp_name]:
        open_guards.extend(pp_guards[sexp_name])
    elif sexp_name in _TOWER_ONLY:
        open_guards.append("#if defined(PUCHI_ENABLE_NUMERICAL_TOWER)")
    elif sexp_name in _NO_INTEGER:
        # Host production: no flonum API under INTEGER_ONLY. Harness/clibs still
        # need the wrapper (bytevector ieee stubs); sexp_* body exists when
        # immediate flonums are off.
        open_guards.append(
            "#if !defined(PUCHI_INTEGER_ONLY) || defined(PUCHI_TEST)"
        )
    if puchi_macro_name in abi_fn_macros:
        open_guards.append(f"#if !defined({puchi_macro_name})")
    return open_guards


def emit_wrapper_lines(
    sexp_name: str,
    proto: str,
    fname: str,
    open_guards: list[str],
) -> list[str] | None:
    """Return wrapper body lines, or None if proto cannot be wrapped."""
    p = rename_sexp_identifiers(proto.strip().rstrip(";"))
    # Replace the puchi_* name in the renamed proto with fname (may be puchi_TEST_*).
    puchi_stem = to_puchi(sexp_name)
    p = re.sub(rf"\b{re.escape(puchi_stem)}\s*\(", f"{fname}(", p, count=1)
    m = re.match(r"(.+?)\b(" + re.escape(fname) + r")\s*\((.*)\)\s*$", p)
    if not m:
        return None
    ret, _fn, args = m.group(1).strip(), m.group(2), m.group(3).strip()
    call_args: list[str] = []
    named_params: list[str] = []
    if args and args != "void":
        for idx, a in enumerate(args.split(",")):
            a = a.strip()
            if not a:
                continue
            tokens = a.replace("*", " * ").split()
            if not tokens:
                continue
            aname = tokens[-1]
            type_only = (
                aname
                in (
                    "puchi",
                    "puchi_sint_t",
                    "puchi_uint_t",
                    "puchi_proc1",
                    "puchi_proc2",
                    "puchi_proc3",
                    "char",
                    "int",
                    "void",
                    "double",
                    "long",
                    "size_t",
                    "*",
                )
                or aname.endswith("_t")
                or aname.endswith("*")
            )
            if type_only:
                aname = f"a{idx}"
                named_params.append(f"{a} {aname}")
            elif aname == "...":
                # Chibi pattern: fixed args ending in `int n`, then n sexp varargs.
                # Cannot forward `...` portably; rebuild the list and call the
                # non-variadic sibling when the name ends in `_ls`.
                if not (
                    sexp_name.endswith("_ls")
                    and call_args
                    and named_params
                    and named_params[-1].endswith(" n")
                ):
                    return None
                fixed = ", ".join(named_params)
                lines: list[str] = []
                for g in open_guards:
                    lines.append(g)
                lines.append(f"PUCHI_API {ret} {fname}({fixed}, ...) {{")
                lines.append("  int i;")
                lines.append("  va_list ap;")
                lines.append("  sexp_gc_var2(res, ir);")
                lines.append("  sexp_gc_preserve2(ctx, res, ir);")
                lines.append("  va_start(ap, n);")
                lines.append("  for (i = 0, ir = SEXP_NULL; i < n; ++i)")
                lines.append("    ir = sexp_cons(ctx, va_arg(ap, sexp), ir);")
                lines.append("  ir = sexp_nreverse(ctx, ir);")
                # Drop trailing `_ls` / call non-variadic sibling (same-TU static).
                sibling = sexp_name[: -3] if sexp_name.endswith("_ls") else sexp_name
                # sibling(ctx, self, msg, ir) — drop `n` from fixed call args.
                sib_args = ", ".join(call_args[:-1] + ["ir"])
                lines.append(f"  res = {sibling}({sib_args});")
                lines.append("  sexp_gc_release2(ctx);")
                lines.append("  va_end(ap);")
                lines.append("  return res;")
                lines.append("}")
                for _ in open_guards:
                    lines.append("#endif")
                lines.append("")
                return lines
            elif aname.startswith("("):
                return None
            else:
                named_params.append(a)
            call_args.append(aname)
        if not named_params and args and args != "void":
            return None
        if named_params:
            args = ", ".join(named_params)
    call = ", ".join(call_args)
    lines: list[str] = []
    for g in open_guards:
        lines.append(g)
    lines.append(f"PUCHI_API {ret} {fname}({args}) {{")
    if ret == "void":
        lines.append(f"  {sexp_name}({call});")
    else:
        lines.append(f"  return {sexp_name}({call});")
    lines.append("}")
    for _ in open_guards:
        lines.append("#endif")
    lines.append("")
    return lines


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir", type=Path)
    ap.add_argument("--out-dir", type=Path, default=None)
    args = ap.parse_args()
    wd: Path = args.workdir
    out_dir: Path = args.out_dir or wd

    host_fns, host_macros, host_typedefs, host_enums = load_manifest(MANIFEST)
    sexp_h = (wd / "sexp.h").read_text(encoding="utf-8")
    eval_h = (wd / "eval.h").read_text(encoding="utf-8")
    features = (wd / "features.h").read_text(encoding="utf-8")

    keep_macros = compute_macro_closure(
        host_macros,
        [collect_macro_catalog(sexp_h), collect_macro_catalog(eval_h)],
    )

    features_new, tunables = extract_if_defined_tunables(features)
    (wd / "features.h").write_text(features_new, encoding="utf-8")

    tun_lines = [
        "/* Host-tunable knobs (defaults from Chibi features.h; override before include) */",
        "/* Word size — needed by always-visible ABI (before features.h under IMPL). */",
        "#if !defined(PUCHI_64_BIT)",
        "#if UINTPTR_MAX > 0xFFFFFFFFu",
        "#define PUCHI_64_BIT 1",
        "#else",
        "#define PUCHI_64_BIT 0",
        "#endif",
        "#endif",
    ]
    for sexp_name, val in tunables:
        p = to_puchi(sexp_name)
        # Host tunables are always-visible — no sexp_* tokens in defaults.
        val_p = rename_sexp_identifiers(val)
        tun_lines.append(f"#if !defined({p})")
        tun_lines.append(f"#define {p} {val_p}")
        tun_lines.append("#endif")
    tun_lines.append("")
    (out_dir / "features_host.inc").write_text("\n".join(tun_lines) + "\n", encoding="utf-8")

    # features.h under IMPL: prefer PUCHI_64_BIT
    features_new2 = features_new
    features_new2 = re.sub(
        r"#if\s*!defined\(SEXP_64_BIT\)\s*\n#if[^\n]+\n#define SEXP_64_BIT 1\n#else\n#define SEXP_64_BIT 0\n#endif\n#endif",
        "#if !defined(SEXP_64_BIT)\n#define SEXP_64_BIT PUCHI_64_BIT\n#endif",
        features_new2,
        count=1,
    )
    if features_new2 == features_new:
        # Scrubbed form may already use UINTPTR_MAX
        features_new2 = re.sub(
            r"#if\s*!defined\(SEXP_64_BIT\)\s*\n#if UINTPTR_MAX[^\n]*\n#define SEXP_64_BIT 1\n#else\n#define SEXP_64_BIT 0\n#endif\n#endif",
            "#if !defined(SEXP_64_BIT)\n#define SEXP_64_BIT PUCHI_64_BIT\n#endif",
            features_new,
            count=1,
        )
    (wd / "features.h").write_text(features_new2, encoding="utf-8")

    # stb howto §4: PUCHI_STATIC makes decls+defs file-private (single-TU embeds).
    # Harness multi-TU clibs must not define PUCHI_STATIC.
    abi_parts = [
        "/* ==== puchi host ABI (types / macros / constants; generated) ==== */\n",
        "#ifdef PUCHI_STATIC\n",
        "#define PUCHI_API static\n",
        "#else\n",
        "#if !defined(PUCHI_API)\n",
        "#define PUCHI_API extern\n",
        "#endif\n",
        "#endif\n",
        "\n",
    ]
    alias_typedefs = [
        "/* Compatibility aliases: Chibi sexp_* names -> puchi_* (IMPLEMENTATION) */",
        "typedef puchi sexp;",
        "typedef puchi_tag_t sexp_tag_t;",
        "typedef puchi_uint_t sexp_uint_t;",
        "typedef puchi_sint_t sexp_sint_t;",
        "typedef puchi_proc1 sexp_proc1;",
        "typedef puchi_proc2 sexp_proc2;",
        # sexp_proc3..7 stay as original typedefs in stripped headers (not ABI).
        "#if defined(PUCHI_TEST)",
        "typedef puchi_init_proc sexp_init_proc;",
        "#endif",
        "typedef puchi_free_list sexp_free_list;",
        "typedef puchi_heap sexp_heap;",
        "typedef puchi_proc_num_args_t sexp_proc_num_args_t;",
        "#define sexp_struct puchi_struct",
        "#if defined(PUCHI_ENABLE_NUMERICAL_TOWER)",
        "typedef puchi_luint_t sexp_luint_t;",
        "typedef puchi_lsint_t sexp_lsint_t;",
        "#endif",
        "",
    ]
    all_aliases: list[str] = []

    for label, text in (("sexp.h", sexp_h), ("eval.h", eval_h)):
        api_names = collect_api_fn_names(text)
        abi, stripped, aliases = build_abi_and_stripped(
            text,
            label,
            host_fns,
            api_names,
            keep_macros,
            host_macros=host_macros,
            host_typedefs=host_typedefs,
            host_enums=host_enums,
        )
        abi_parts.append(abi)
        all_aliases.extend(aliases)
        (wd / label).write_text(stripped, encoding="utf-8")

    # Struct-tag aliases so Chibi `struct sexp_foo` matches ABI `struct puchi_foo`.
    abi_text = "".join(abi_parts)
    for tag in sorted(set(re.findall(r"\bstruct\s+(puchi_\w+)\b", abi_text))):
        sexp_tag = "sexp_" + tag[len("puchi_") :]
        all_aliases.append(f"#define {sexp_tag} {tag}")

    def dedup(items: list[str]) -> list[str]:
        seen: set[str] = set()
        out: list[str] = []
        for x in items:
            # Preprocessor structure tokens must not be deduped.
            if x in ("#endif", "#else") or x.startswith("#if ") or x.startswith(
                "#ifdef "
            ) or x.startswith("#ifndef "):
                out.append(x)
                continue
            if x in seen:
                continue
            seen.add(x)
            out.append(x)
        return out

    all_aliases = dedup(all_aliases)
    # Never alias enum tags via typedef: C ordinary namespace would collide with
    # globals like `const char** sexp_opcode_names`.
    all_aliases = [
        a for a in all_aliases if not re.match(r"\s*typedef\s+enum\b", a)
    ]
    abi_joined = "".join(abi_parts)
    (out_dir / "host_api_abi.inc").write_text(abi_joined, encoding="utf-8")
    alias_body = "\n".join(alias_typedefs + all_aliases) + "\n"
    if re.search(r"^\s*typedef\s+enum\b", alias_body, re.M):
        raise SystemExit("host_api_aliases.inc: typedef enum aliases are forbidden")
    (out_dir / "host_api_aliases.inc").write_text(alias_body, encoding="utf-8")

    # Host macros rename sexp_* callees to puchi_*; ensure every SEXP_API name
    # referenced from the ABI has a linkable puchi_* wrapper (not only manifest).
    api_protos: dict[str, str] = {}
    api_protos.update(collect_api_fn_protos(sexp_h))
    api_protos.update(collect_api_fn_protos(eval_h))
    abi_refs = set(re.findall(r"\bpuchi_(\w+)\b", abi_joined))
    for suffix in sorted(abi_refs):
        sexp_name = "sexp_" + suffix
        if sexp_name in api_protos and sexp_name not in host_fns:
            host_fns[sexp_name] = api_protos[sexp_name]

    decl_lines = [
        "/* ==== puchi host API function declarations (generated) ==== */",
        "",
    ]
    wrap_lines = [
        "/* ==== puchi host API wrappers -> sexp_* (generated) ==== */",
        "",
    ]

    # Function-like macros in ABI (often #if-gated) are the host API in those
    # configs; skip decl/wrapper when the macro is defined to avoid collisions.
    abi_fn_macros = set(re.findall(r"#\s*define\s+(puchi_\w+)\s*\(", abi_joined))
    # Existing sexp_* macros (function-like or object) — do not alias over them
    # and do not emit TEST wrappers that call a macro instead of a function.
    existing_sexp_macros = set(
        re.findall(r"#\s*define\s+(sexp_\w+)\b", alias_body)
    )
    existing_sexp_macros |= set(
        re.findall(r"#\s*define\s+(sexp_\w+)\b", abi_joined)
    )
    existing_sexp_macros |= set(
        re.findall(r"#\s*define\s+(sexp_\w+)\b", sexp_h)
    )
    existing_sexp_macros |= set(
        re.findall(r"#\s*define\s+(sexp_\w+)\b", eval_h)
    )

    pp_guards: dict[str, list[str]] = {}
    pp_guards.update(collect_api_fn_pp_guards(sexp_h))
    pp_guards.update(collect_api_fn_pp_guards(eval_h))

    host_wrapped: set[str] = set()
    for sexp_name, proto in sorted(host_fns.items()):
        puchi_name = to_puchi(sexp_name)
        open_guards = open_guards_for(
            sexp_name, puchi_name, abi_fn_macros, pp_guards
        )
        for g in open_guards:
            decl_lines.append(g)
        decl_lines.append(build_host_fn_decl(proto))
        for _ in open_guards:
            decl_lines.append("#endif")

        lines = emit_wrapper_lines(sexp_name, proto, puchi_name, open_guards)
        if lines is None:
            wrap_lines.append(f"/* skip wrapper for {sexp_name}: {proto} */")
            continue
        wrap_lines.extend(lines)
        host_wrapped.add(sexp_name)

    for pname, params in PRODUCT_FUNCS:
        decl_lines.append(f"PUCHI_API puchi {pname}({params});")

    decl_lines.append("")
    (out_dir / "host_api_decls.inc").write_text(
        "\n".join(decl_lines) + "\n", encoding="utf-8"
    )
    (out_dir / "host_api_wrappers.inc").write_text(
        "\n".join(wrap_lines) + "\n", encoding="utf-8"
    )

    # --- non-HOST SEXP_API → puchi_TEST_* (harness / clibs only) ---
    # Hand-written puchi_TEST_* (add_static_libraries, load_op, …) stay in product/.
    test_decl_lines = [
        "/* ==== auto puchi_TEST_* decls for non-HOST SEXP_API (generated) ==== */",
        "",
    ]
    test_wrap_lines = [
        "/* ==== auto puchi_TEST_* wrappers -> sexp_* (generated) ==== */",
        "",
    ]
    clib_alias_lines = [
        "/* ==== TEST_CLIB: sexp_* -> puchi_* / puchi_TEST_* (generated) ==== */",
        "#if defined(PUCHI_TEST_CLIB)",
        "",
    ]

    # Hand-written puchi_TEST_* in product/ — do not auto-duplicate.
    hand_test: set[str] = set()
    product = ROOT / "product"
    for path in (
        product / "puchi_test_api_decls.inc",
        product / "puchi_test_api_impl.inc",
    ):
        if path.is_file():
            hand_test.update(
                re.findall(r"\b(puchi_TEST_\w+)\s*\(", path.read_text(encoding="utf-8"))
            )

    # Only wrap SEXP_API symbols that still have a definition in amalgamated .c
    # (backends deleted by strip-dead-backends leave orphan decls).
    defined_sexp: set[str] = set()
    def_pat = re.compile(
        r"^[ \t]*(?:static\s+|SEXP_API\s+|inline\s+|extern\s+)*"
        r"[\w\s\*]+\b(sexp_\w+)\s*\([^;{]*\)\s*\{",
        re.M,
    )
    for cname in ("gc.c", "sexp.c", "eval.c", "opcodes.c", "vm.c", "simplify.c", "bignum.c"):
        cp = wd / cname
        if cp.is_file():
            defined_sexp.update(def_pat.findall(cp.read_text(encoding="utf-8")))

    non_host = {
        n: p
        for n, p in api_protos.items()
        if n not in host_fns and n not in host_wrapped
    }
    test_count = 0
    for sexp_name, proto in sorted(non_host.items()):
        stem = sexp_name[5:] if sexp_name.startswith("sexp_") else sexp_name
        test_name = f"puchi_TEST_{stem}"
        if test_name in hand_test:
            # Still alias clibs to the hand-written symbol.
            # #undef so gated function-like dual aliases in host_api_aliases
            # cannot hide the object-like redirect.
            clib_alias_lines.append(f"#undef {sexp_name}")
            clib_alias_lines.append(f"#define {sexp_name} {test_name}")
            continue
        if sexp_name not in defined_sexp:
            continue
        # Macro-only name (empty stub / field glue) — not a callable body.
        if sexp_name in existing_sexp_macros:
            continue

        open_guards = open_guards_for(sexp_name, test_name, set(), pp_guards)

        for g in open_guards:
            test_decl_lines.append(g)
        test_decl_lines.append(build_test_fn_decl(proto))
        for _ in open_guards:
            test_decl_lines.append("#endif")

        lines = emit_wrapper_lines(sexp_name, proto, test_name, open_guards)
        if lines is None:
            test_wrap_lines.append(f"/* skip TEST wrapper for {sexp_name}: {proto} */")
        else:
            test_wrap_lines.extend(lines)
            test_count += 1
            clib_alias_lines.append(f"#undef {sexp_name}")
            clib_alias_lines.append(f"#define {sexp_name} {test_name}")

    # HOST names: redirect clib calls to puchi_*. Always #undef first — alias_body
    # may contain gated `#define sexp_X(...) puchi_X(...)` that mark the name
    # "defined" for #ifndef even when the gate is false in this TU.
    # Mirror wrapper open_guards so aliases are not live when the puchi_* body
    # is compiled out.
    for sexp_name in sorted(host_wrapped):
        puchi_name = to_puchi(sexp_name)
        open_guards = open_guards_for(
            sexp_name, puchi_name, abi_fn_macros, pp_guards
        )
        for g in open_guards:
            clib_alias_lines.append(g)
        clib_alias_lines.append(f"#undef {sexp_name}")
        clib_alias_lines.append(f"#define {sexp_name} {puchi_name}")
        for _ in open_guards:
            clib_alias_lines.append("#endif")

    clib_alias_lines.append("")
    clib_alias_lines.append("#endif /* PUCHI_TEST_CLIB */")
    clib_alias_lines.append("")

    test_decl_lines.append("")
    (out_dir / "host_api_test_decls.inc").write_text(
        "\n".join(test_decl_lines) + "\n", encoding="utf-8"
    )
    (out_dir / "host_api_test_wrappers.inc").write_text(
        "\n".join(test_wrap_lines) + "\n", encoding="utf-8"
    )
    (out_dir / "host_api_test_clib_aliases.inc").write_text(
        "\n".join(clib_alias_lines) + "\n", encoding="utf-8"
    )

    print(
        f"puchi_gen_host_api: abi={len(''.join(abi_parts))}B "
        f"aliases={len(all_aliases)}, host_fns={len(host_fns)}, "
        f"test_wrappers={test_count}, "
        f"host_macros={len(host_macros)}, keep_macros={len(keep_macros)} "
        f"(+{len(keep_macros - host_macros)} deps), tunables={len(tunables)}"
    )


if __name__ == "__main__":
    main()
