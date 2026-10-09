#!/usr/bin/env python3
"""Generate stb-style puchi host API fragments from patched Chibi headers.

Reads puchi/product/puchi_host_symbols.txt (HOST manifest) plus workdir
sexp.h / eval.h / features.h, writes:

  host_api_abi.inc      - types/macros/constants as puchi_*/PUCHI_* (always visible)
  host_api_decls.inc    - PUCHI_API function declarations for HOST + product entrypoints
  host_api_aliases.inc  - sexp_*/SEXP_* -> puchi_*/PUCHI_* (inside IMPLEMENTATION)
  host_api_wrappers.inc - puchi_* function wrappers calling sexp_*
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


def build_abi_and_stripped(
    text: str,
    label: str,
    host_fns: dict[str, str],
    api_fn_names: set[str],
    keep_macros: set[str],
) -> tuple[str, str, list[str]]:
    """Return (abi_fragment, stripped_header, alias_macro_lines).

    Only macros in keep_macros (HOST + transitive deps) go to the always-visible
    ABI as puchi_*/PUCHI_*. Other Chibi macros stay in the stripped header under
    IMPLEMENTATION/TEST with their original sexp_*/SEXP_* bodies.
    """
    abi: list[str] = [f"\n/* ---- from {label} ---- */\n"]
    stripped: list[str] = [f"/* stripped {label} (SEXP_API + gating) */\n"]
    aliases: list[str] = []
    # Function-like macros in this header (possibly #if-gated); prefer puchi_*
    # peers over keeping sexp_* API names as callees in other macro bodies.
    header_fn_macros = set(re.findall(r"#\s*define\s+(sexp_\w+)\s*\(", text))
    keep_callees = api_fn_names - header_fn_macros
    # Referenced by name in PUCHI_FINALIZE_FILENO* but not SEXP_API-declared.
    keep_callees.add("sexp_finalize_fileno")
    # Kept ABI macros that are also callees must stay as sexp_* only when they
    # are *not* themselves emitted as puchi_* macros (keep_macros wins).
    keep_callees -= keep_macros
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
                abi.append(renamed)
                if is_chibi_macro_name(name):
                    if args_s:
                        alias_line = (
                            f"#define {name}{args_s} {puchi_name}{args_s}"
                        )
                        # Dual macro/function names: only alias when the puchi_*
                        # macro is active (avoids rewriting sexp_* definitions).
                        if name in api_fn_names or name in host_fns:
                            aliases.append(f"#if defined({puchi_name})")
                            aliases.append(alias_line)
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
                if re.search(r"typedef\s+struct\s+sexp_struct\s*\*\s*sexp\s*;", buf):
                    abi.append("typedef struct puchi_struct *puchi;\n")
                else:
                    renamed = rename_sexp_identifiers(buf)
                    abi.append(renamed if renamed.endswith("\n") else renamed + "\n")
                    # Enum constant aliases only (not struct fields referencing
                    # features.h knobs like PUCHI_MARK_STACK_COUNT).
                    if re.search(r"\benum\b", buf):
                        for name in set(re.findall(r"\bPUCHI_[A-Z0-9_]+\b", renamed)):
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("workdir", type=Path)
    ap.add_argument("--out-dir", type=Path, default=None)
    args = ap.parse_args()
    wd: Path = args.workdir
    out_dir: Path = args.out_dir or wd

    host_fns, host_macros, _typedefs, _enums = load_manifest(MANIFEST)
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
        tun_lines.append(f"#if !defined({p})")
        tun_lines.append(f"#define {p} {val}")
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

    abi_parts = [
        "/* ==== puchi host ABI (types / macros / constants; generated) ==== */\n",
        "#if !defined(PUCHI_API)\n",
        "#define PUCHI_API extern\n",
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
        "typedef puchi_proc3 sexp_proc3;",
        "typedef puchi_proc4 sexp_proc4;",
        "typedef puchi_proc5 sexp_proc5;",
        "typedef puchi_proc6 sexp_proc6;",
        "typedef puchi_proc7 sexp_proc7;",
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
            text, label, host_fns, api_names, keep_macros
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
    (out_dir / "host_api_abi.inc").write_text("".join(abi_parts), encoding="utf-8")
    alias_body = "\n".join(alias_typedefs + all_aliases) + "\n"
    if re.search(r"^\s*typedef\s+enum\b", alias_body, re.M):
        raise SystemExit("host_api_aliases.inc: typedef enum aliases are forbidden")
    (out_dir / "host_api_aliases.inc").write_text(alias_body, encoding="utf-8")

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
    abi_fn_macros = set(re.findall(r"#\s*define\s+(puchi_\w+)\s*\(", "".join(abi_parts)))

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

    for sexp_name, proto in sorted(host_fns.items()):
        puchi_name = to_puchi(sexp_name)
        gated = puchi_name in abi_fn_macros
        decl = build_host_fn_decl(proto)
        open_guards: list[str] = []
        if sexp_name in _TOWER_ONLY:
            open_guards.append("#if defined(PUCHI_ENABLE_NUMERICAL_TOWER)")
        elif sexp_name in _NO_INTEGER:
            open_guards.append("#if !defined(PUCHI_INTEGER_ONLY)")
        if gated:
            open_guards.append(f"#if !defined({puchi_name})")
        for g in open_guards:
            decl_lines.append(g)
        decl_lines.append(decl)
        for _ in open_guards:
            decl_lines.append("#endif")

        p = rename_sexp_identifiers(proto.strip().rstrip(";"))
        m = re.match(r"(.+?)\b(puchi_\w+)\s*\((.*)\)\s*$", p)
        if not m:
            wrap_lines.append(f"/* skip wrapper for {sexp_name}: {proto} */")
            continue
        ret, fname, args = m.group(1).strip(), m.group(2), m.group(3).strip()
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
                # Prototype with types only (no parameter names)
                type_only = (
                    aname in (
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
                elif aname == "..." or aname.startswith("("):
                    wrap_lines.append(
                        f"/* skip wrapper for {sexp_name}: unhandled params */"
                    )
                    named_params = []
                    break
                else:
                    named_params.append(a)
                call_args.append(aname)
            if not named_params and args and args != "void":
                continue
            if named_params:
                args = ", ".join(named_params)
        call = ", ".join(call_args)
        for g in open_guards:
            wrap_lines.append(g)
        wrap_lines.append(f"{ret} {fname}({args}) {{")
        if ret == "void":
            wrap_lines.append(f"  {sexp_name}({call});")
        else:
            wrap_lines.append(f"  return {sexp_name}({call});")
        wrap_lines.append("}")
        for _ in open_guards:
            wrap_lines.append("#endif")
        wrap_lines.append("")

    for pname, params in PRODUCT_FUNCS:
        decl_lines.append(f"PUCHI_API puchi {pname}({params});")

    decl_lines.append("")
    (out_dir / "host_api_decls.inc").write_text("\n".join(decl_lines) + "\n", encoding="utf-8")
    (out_dir / "host_api_wrappers.inc").write_text("\n".join(wrap_lines) + "\n", encoding="utf-8")

    print(
        f"puchi_gen_host_api: abi={len(''.join(abi_parts))}B "
        f"aliases={len(all_aliases)}, host_fns={len(host_fns)}, "
        f"host_macros={len(host_macros)}, keep_macros={len(keep_macros)} "
        f"(+{len(keep_macros - host_macros)} deps), tunables={len(tunables)}"
    )


if __name__ == "__main__":
    main()
