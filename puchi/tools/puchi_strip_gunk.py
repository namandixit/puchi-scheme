"""Post-amalgamation scrub: ALWAYS_ZERO define cleanup, residue, asserts.

C body forks live in puchi/patches/; feature scrubbing is mechanical
(scrub_features_h). This module runs after strip-dead-backends.
"""
from __future__ import annotations

import re
from pathlib import Path

from puchi_host_embed import ALWAYS_ZERO_STRIP

# Never-true Scheme feature identifiers in init-7 / meta-7 cond-expand.
_NEVER_TRUE_SCHEME_FEATURES = (
    "threads",
    "auto-force",
    "safe-string-cursors",
    "mini-float",
)


def _read_scheme_list(src: str, start: int) -> tuple[str, int] | None:
    """Read one balanced list starting at src[start]=='('. Return (text, end)."""
    if start >= len(src) or src[start] != "(":
        return None
    depth = 0
    i = start
    in_str = False
    while i < len(src):
        c = src[i]
        if in_str:
            if c == "\\":
                i += 2
                continue
            if c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            i += 1
            continue
        if c == ";":
            while i < len(src) and src[i] != "\n":
                i += 1
            continue
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return src[start : i + 1], i + 1
        i += 1
    return None


def _split_top_level_lists(body: str) -> list[str]:
    """Split a cond-expand body (inside the outer parens) into clause lists."""
    clauses: list[str] = []
    i = 0
    while i < len(body):
        while i < len(body) and body[i].isspace():
            i += 1
        if i >= len(body):
            break
        if body[i] == ";":
            while i < len(body) and body[i] != "\n":
                i += 1
            continue
        if body[i] != "(":
            # Skip non-list tokens (shouldn't happen in cond-expand)
            while i < len(body) and not body[i].isspace() and body[i] != "(":
                i += 1
            continue
        got = _read_scheme_list(body, i)
        if not got:
            break
        text, end = got
        clauses.append(text)
        i = end
    return clauses


def _clause_feature(clause: str) -> str | None:
    """Return the feature symbol of a cond-expand clause, or None."""
    m = re.match(r"\(\s*([A-Za-z0-9!$%&*/:<=>?^_~+-]+)", clause)
    return m.group(1) if m else None


def _clause_body(clause: str) -> str:
    """Body forms inside a clause after the feature identifier."""
    m = re.match(r"\(\s*[A-Za-z0-9!$%&*/:<=>?^_~+-]+\s*", clause)
    if not m:
        return ""
    inner = clause[m.end() : -1]  # drop trailing )
    return inner.strip()


def trim_never_true_cond_expand(src: str, features: tuple[str, ...] = _NEVER_TRUE_SCHEME_FEATURES) -> str:
    """Rewrite cond-expand forms: drop never-true arms; unwrap else-only."""
    out: list[str] = []
    i = 0
    while i < len(src):
        if src.startswith("(cond-expand", i) and (
            i + 12 >= len(src) or not src[i + 12].isalnum()
        ):
            got = _read_scheme_list(src, i)
            if not got:
                out.append(src[i])
                i += 1
                continue
            form, end = got
            # Inner text between (cond-expand and final )
            inner_start = len("(cond-expand")
            inner = form[inner_start:-1]
            clauses = _split_top_level_lists(inner)
            if not clauses:
                out.append(form)
                i = end
                continue
            kept: list[str] = []
            for cl in clauses:
                feat = _clause_feature(cl)
                if feat in features:
                    continue
                kept.append(cl)
            if not kept:
                # Entire cond-expand was never-true — drop it.
                i = end
                continue
            if len(kept) == 1 and _clause_feature(kept[0]) == "else":
                body = _clause_body(kept[0])
                # Preserve a leading newline if the original had one after cond-expand
                out.append(body)
                i = end
                continue
            # Rebuild cond-expand with remaining clauses (e.g. complex/ratios/windows).
            rebuilt = "(cond-expand\n"
            for cl in kept:
                rebuilt += " " + cl + "\n"
            rebuilt += ")"
            out.append(rebuilt)
            i = end
            continue
        out.append(src[i])
        i += 1
    return "".join(out)


def trim_init7_dead_arms(src: str) -> str:
    """Drop never-true cond-expand arms; keep else / windows / complex / ratios."""
    return trim_never_true_cond_expand(src)


def assert_no_project_includes(puchi_h: str) -> None:
    bad = []
    for m in re.finditer(r'#include\s+"([^"]+)"', puchi_h):
        path = m.group(1)
        if path.startswith(("opt/", "chibi/", "lib/")) or path == "clibs.c":
            bad.append(path)
    if bad:
        raise SystemExit(
            "puchi.h still has project #include(s) (not a single header): "
            + ", ".join(sorted(set(bad)))
        )


def assert_no_process_globals(puchi_h: str) -> None:
    """Fail if host/module/init state is still process-global."""
    hits = []
    for name in (
        "puchi_g_host",
        "puchi_g_module_ops",
        "sexp_initialized_p",
        "scheme_initialized_p",
        "SEXP_MALLOC(NULL",
        "SEXP_FREE(NULL",
    ):
        if name in puchi_h:
            hits.append(name)
    if hits:
        raise SystemExit(
            "puchi.h still has process-global host residue: " + ", ".join(hits)
        )


# OS / CPU / compiler tokens that must not appear in the product header.
# `_MSC_VER` is allowed: only for diagnostic push/pop around the amalgamation
# (puchi_diag_push.inc / puchi_diag_pop.inc). `__clang__` is likewise used there.
_FORBIDDEN_OS_TOKENS = (
    "_WIN32",
    "_WIN64",
    "_Wp64",
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
    """Remove #if/#ifdef/#ifndef … #endif regions whose condition mentions gate_names."""
    lines = src.splitlines(keepends=True)
    out: list[str] = []
    stack: list[bool] = []

    def cond_is_gate(cond: str) -> bool:
        return any(name in cond for name in gate_names)

    def dropping() -> bool:
        return any(stack)

    for line in lines:
        s = line.lstrip()
        if s.startswith("#if"):
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
    without_test = _drop_gated_regions(code, ("PUCHI_TEST",))
    if '".so"' in without_test or "puchi_TEST_so_extension" in without_test:
        hits.append('".so" outside PUCHI_TEST')
    if hits:
        raise SystemExit(
            "puchi.h still has platform residue: " + ", ".join(sorted(set(hits)))
        )


def _always_visible_prefix(puchi_h: str) -> str:
    """Prefix before CRT/diag (first IMPL||TEST) — Host + TEST decls only."""
    gate = "#if defined(PUCHI_IMPLEMENTATION) || defined(PUCHI_TEST)"
    idx = puchi_h.find(gate)
    if idx < 0:
        raise SystemExit("puchi.h missing PUCHI_IMPLEMENTATION || PUCHI_TEST gate")
    return puchi_h[:idx]


def assert_no_sexp_tokens_outside_impl(puchi_h: str) -> None:
    """Host/TEST/CRT prefix (before IMPLEMENTATION-only sexp surface) has no sexp_*."""
    pre = None
    for m in re.finditer(r"#if\s+defined\(PUCHI_IMPLEMENTATION\)", puchi_h):
        after = puchi_h[m.end() :]
        # Skip CRT/diag gates: #if defined(PUCHI_IMPLEMENTATION) || defined(PUCHI_TEST)
        if re.match(r"\s*\|\|", after):
            continue
        pre = puchi_h[: m.start()]
        break
    if pre is None:
        pre = puchi_h
    code = _strip_c_comments(pre)
    hits = []
    if re.search(r"\bsexp_", code):
        hits.append("sexp_*")
    if re.search(r"\bSEXP_", code):
        hits.append("SEXP_*")
    if re.search(r"\bsexp\b", code):
        hits.append("sexp")
    if hits:
        raise SystemExit(
            "puchi.h outside PUCHI_IMPLEMENTATION still has Chibi names: "
            + ", ".join(hits)
        )


def assert_no_chibi_api_leak(puchi_h: str) -> None:
    """Always-visible section must not export Chibi SEXP_API or typedef … sexp."""
    pre = _always_visible_prefix(puchi_h)
    code = _strip_c_comments(pre)
    hits = []
    if "SEXP_API" in code:
        hits.append("SEXP_API")
    if re.search(r"\btypedef\b[^;]*\bsexp\b", code):
        hits.append("typedef … sexp")
    if hits:
        raise SystemExit(
            "puchi.h always-visible section leaks Chibi API: "
            + ", ".join(hits)
        )


def assert_no_vm_enums_in_host_abi(puchi_h: str) -> None:
    """Bare hosts must not see opcode / opcode-class / core-form enums."""
    pre = _strip_c_comments(_always_visible_prefix(puchi_h))
    hits = []
    for pat, label in (
        (r"\bPUCHI_OP_[A-Z0-9_]+\b", "PUCHI_OP_*"),
        (r"\bPUCHI_OPC_[A-Z0-9_]+\b", "PUCHI_OPC_*"),
        (r"\bPUCHI_CORE_[A-Z0-9_]+\b", "PUCHI_CORE_*"),
        (r"\benum\s+puchi_opcode_names\b", "enum puchi_opcode_names"),
        (r"\benum\s+puchi_opcode_classes\b", "enum puchi_opcode_classes"),
        (r"\benum\s+puchi_core_form_names\b", "enum puchi_core_form_names"),
        (r"\bpuchi_proc[3-7]\b", "puchi_proc3..7"),
    ):
        if re.search(pat, pre):
            hits.append(label)
    if hits:
        raise SystemExit(
            "puchi.h always-visible section still has VM/compiler surface: "
            + ", ".join(hits)
        )


def assert_host_api_decls_are_manifest(puchi_h: str) -> None:
    """Every always-visible PUCHI_API decl must be a HOST manifest fn or product."""
    root = Path(__file__).resolve().parents[1]
    man = (root / "product" / "puchi_host_symbols.txt").read_text(encoding="utf-8")
    allowed: set[str] = set()
    for line in man.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        kind = parts[0]
        if kind == "function" and len(parts) >= 2:
            name = parts[1]
            if name.startswith("sexp_"):
                allowed.add("puchi_" + name[5:])
        elif kind == "product" and len(parts) >= 2:
            allowed.add(parts[1])
    # Product entrypoints also listed in the generator.
    allowed.update(
        {
            "puchi_create_context",
            "puchi_delete_context",
            "puchi_load_default_libs",
            "puchi_enable_modules",
            "puchi_make_eval_context_host",
            "puchi_port_name",
            "puchi_port_set_name",
            "puchi_port_set_sourcep",
            "puchi_port_set_no_close",
            "puchi_context_parent",
            "puchi_context_set_parent",
            "puchi_context_set_tailp",
            "puchi_context_set_env",
            "puchi_set_global",
            "puchi_set_standard_ports",
            "puchi_stack_trace",
        }
    )
    pre = _always_visible_prefix(puchi_h)
    decls = set(
        re.findall(r"PUCHI_API\s+[^\n]*?\b(puchi_[A-Za-z0-9_]+)\s*\(", pre)
    )
    # Harness-only decls (under #if PUCHI_TEST) are not HOST manifest entries.
    decls = {d for d in decls if not d.startswith("puchi_TEST_")}
    extra = sorted(decls - allowed)
    if extra:
        raise SystemExit(
            "puchi.h always-visible PUCHI_API decls not on HOST manifest/product: "
            + ", ".join(extra[:20])
            + ("…" if len(extra) > 20 else "")
        )


def assert_finalize_fileno_macro(puchi_h: str) -> None:
    """PUCHI_FINALIZE_FILENO must keep the Chibi callee name when non-NULL."""
    if re.search(r"#define\s+PUCHI_FINALIZE_FILENO\s+puchi_finalize_fileno\b", puchi_h):
        raise SystemExit(
            "puchi.h: PUCHI_FINALIZE_FILENO must reference sexp_finalize_fileno, "
            "not puchi_finalize_fileno"
        )


def filter_dead_auto_test_wrappers(puchi_h: str) -> str:
    """Drop auto puchi_TEST_* wrappers whose sexp_* bodies were strip-deleted.

    Hand-written puchi_TEST_* (product/) are left alone. Also drops matching
    auto decls and TEST_CLIB aliases for the same stems.
    """
    gate = "#if defined(PUCHI_IMPLEMENTATION) && !defined(PUCHI_TEST_CLIB)"
    start = puchi_h.find(gate)
    if start < 0:
        return puchi_h
    depth = 0
    end = len(puchi_h)
    for m in re.finditer(r"^[ \t]*#(if|ifdef|ifndef|endif)\b", puchi_h[start:], re.M):
        tok = m.group(1)
        if tok in ("if", "ifdef", "ifndef"):
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                end = start + m.start()
                break
    body = puchi_h[start:end]
    live = set(
        re.findall(
            r"^[ \t]*(?:static\s+|SEXP_API\s+|inline\s+)*"
            r"[\w\s\*]+\b(sexp_\w+)\s*\([^;{]*\)\s*\{",
            body,
            re.M,
        )
    )
    hand = {
        "puchi_TEST_add_static_libraries",
        "puchi_TEST_load_op",
        "puchi_TEST_current_module_path_op",
        "puchi_TEST_load_module_file_op",
        "puchi_TEST_add_module_directory_op",
    }

    def keep_test_name(tname: str) -> bool:
        if tname in hand:
            return True
        if not tname.startswith("puchi_TEST_"):
            return True
        stem = tname[len("puchi_TEST_") :]
        return f"sexp_{stem}" in live

    def matching_endif(src: str, if_pos: int) -> int:
        depth_b = 0
        for m in re.finditer(r"^[ \t]*#(if|ifdef|ifndef|endif)\b", src[if_pos:], re.M):
            tok = m.group(1)
            if tok in ("if", "ifdef", "ifndef"):
                depth_b += 1
            else:
                depth_b -= 1
                if depth_b == 0:
                    return if_pos + m.start()
        return -1

    def filter_test_api_chunk(chunk: str) -> str:
        parts = re.split(r"(?=^PUCHI_API\b|^#if\b|^#endif\b)", chunk, flags=re.M)
        kept: list[str] = [parts[0]] if parts else []
        i = 1
        while i < len(parts):
            part = parts[i]
            block = part
            if part.startswith("#if"):
                j = i + 1
                depth_b = 1
                while j < len(parts) and depth_b:
                    if parts[j].startswith("#if"):
                        depth_b += 1
                    elif parts[j].startswith("#endif"):
                        depth_b -= 1
                    block += parts[j]
                    j += 1
                i = j
            else:
                i += 1
            m = re.search(r"\b(puchi_TEST_\w+)\s*\(", block)
            if m and not keep_test_name(m.group(1)):
                continue
            kept.append(block)
        return "".join(kept)

    # Remove auto wrapper definitions (between markers).
    wrap_start = puchi_h.find(
        "/* ==== auto puchi_TEST_* wrappers -> sexp_* (generated) ===="
    )
    if wrap_start >= 0:
        region_if = puchi_h.rfind("#if defined(PUCHI_TEST)", 0, wrap_start)
        region_end = matching_endif(puchi_h, region_if) if region_if >= 0 else -1
        if region_if >= 0 and region_end > wrap_start:
            chunk = puchi_h[wrap_start:region_end]
            puchi_h = (
                puchi_h[:wrap_start]
                + filter_test_api_chunk(chunk)
                + puchi_h[region_end:]
            )

    # Remove auto decls for dead stems (same #if PUCHI_TEST as hand decls).
    decl_mark = (
        "/* ==== auto puchi_TEST_* decls for non-HOST SEXP_API (generated) ===="
    )
    decl_start = puchi_h.find(decl_mark)
    if decl_start >= 0:
        # Auto decls sit inside an open #if PUCHI_TEST; rewrite until that endif.
        region_if = puchi_h.rfind("#if defined(PUCHI_TEST)", 0, decl_start)
        decl_end = matching_endif(puchi_h, region_if) if region_if >= 0 else -1
        if decl_end > decl_start:
            chunk = puchi_h[decl_start:decl_end]
            puchi_h = (
                puchi_h[:decl_start]
                + filter_test_api_chunk(chunk)
                + puchi_h[decl_end:]
            )

    # Drop TEST_CLIB aliases pointing at removed TEST wrappers.
    alias_mark = (
        "/* ==== TEST_CLIB: sexp_* -> puchi_* / puchi_TEST_* (generated) ===="
    )
    alias_start = puchi_h.find(alias_mark)
    if alias_start < 0:
        alias_start = puchi_h.find(
            "/* ==== TEST_CLIB sexp_* -> puchi_* / puchi_TEST_* aliases ===="
        )
    if alias_start >= 0:
        region_if = puchi_h.find("#if defined(PUCHI_TEST_CLIB)", alias_start)
        if region_if < 0:
            region_if = puchi_h.rfind("#if defined(PUCHI_TEST_CLIB)", 0, alias_start + 200)
        alias_end = matching_endif(puchi_h, region_if) if region_if >= 0 else -1
        if alias_end > alias_start:
            chunk = puchi_h[alias_start:alias_end]
            out_lines: list[str] = []
            lines = chunk.splitlines(keepends=True)
            i = 0
            while i < len(lines):
                head = lines[i].lstrip()
                gated = head.startswith("#ifndef sexp_") or head.startswith(
                    "#if !defined(sexp_"
                )
                if (
                    gated
                    and i + 2 < len(lines)
                    and "puchi_TEST_" in lines[i + 1]
                    and lines[i + 2].lstrip().startswith("#endif")
                ):
                    m = re.search(r"\b(puchi_TEST_\w+)\b", lines[i + 1])
                    if m and not keep_test_name(m.group(1)):
                        i += 3
                        continue
                out_lines.append(lines[i])
                i += 1
            puchi_h = (
                puchi_h[:alias_start] + "".join(out_lines) + puchi_h[alias_end:]
            )

    return puchi_h


def assert_no_external_sexp_funcs(puchi_h: str) -> None:
    """Under IMPLEMENTATION bodies, sexp_* funcs/objects must not be External.

    Uses the same multi-line / Allman / object recognition as
    make_sexp_funcs_static (lazy-imported to avoid a circular import).
    """
    # Lazy import: puchi_amalgamate_helpers imports this module at load time.
    from puchi_amalgamate_helpers import find_external_sexp_linkage

    gate = "#if defined(PUCHI_IMPLEMENTATION) && !defined(PUCHI_TEST_CLIB)"
    start = puchi_h.find(gate)
    if start < 0:
        raise SystemExit(
            "puchi.h: missing IMPLEMENTATION && !PUCHI_TEST_CLIB body region"
        )
    # Match the closing #endif by nesting (comment on endif is optional).
    depth = 0
    end = -1
    for m in re.finditer(r"^[ \t]*#(if|ifdef|ifndef|endif)\b", puchi_h[start:], re.M):
        tok = m.group(1)
        if tok in ("if", "ifdef", "ifndef"):
            depth += 1
        else:
            depth -= 1
            if depth == 0:
                end = start + m.start()
                break
    if end < 0:
        raise SystemExit(
            "puchi.h: unclosed IMPLEMENTATION && !PUCHI_TEST_CLIB body region"
        )
    body = puchi_h[start:end]
    leaks = find_external_sexp_linkage(body)
    if leaks:
        uniq = sorted(set(leaks))
        raise SystemExit(
            "puchi.h: non-static sexp_* linkage under IMPLEMENTATION: "
            + ", ".join(uniq[:30])
            + ("…" if len(uniq) > 30 else "")
        )


def assert_no_enum_tag_typedef_aliases(puchi_h: str) -> None:
    """Enum-tag typedef aliases collide with globals (e.g. sexp_opcode_names)."""
    gate = "#if defined(PUCHI_IMPLEMENTATION)"
    # Prefer the sexp decl surface marker comment if present.
    i = puchi_h.find("#endif /* PUCHI_IMPLEMENTATION (sexp decl surface) */")
    if i < 0:
        i = puchi_h.find(gate)
        if i < 0:
            return
        j = puchi_h.find("#endif", i + len(gate))
        if j < 0:
            return
        block = puchi_h[i:j]
    else:
        # Walk back to the matching #if for the sexp decl surface block.
        start = puchi_h.rfind("#if defined(PUCHI_IMPLEMENTATION)", 0, i)
        if start < 0:
            return
        block = puchi_h[start:i]
    if re.search(r"^\s*typedef\s+enum\b", block, re.M):
        raise SystemExit(
            "puchi.h sexp surface: typedef enum … sexp_* aliases are forbidden"
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
    return puchi_h


def _drop_define_lines(src: str, names: tuple[str, ...]) -> str:
    for name in names:
        src = re.sub(rf"#\s*define\s+{name}\b[^\n]*\n", "", src)
    return src


def _puchi_macro_or_enum_names(src: str) -> set[str]:
    """PUCHI_* names defined as #define or enum members in this header."""
    names = set(re.findall(r"^\s*#\s*define\s+(PUCHI_[A-Z0-9_]+)\b", src, re.M))
    # Enum rows may be bare or prefixed with a /* n hex */ comment.
    names |= set(
        re.findall(
            r"^\s*(?:/\*[^*]*\*/\s*)?(PUCHI_[A-Z0-9_]+)\s*(?:,|=|/\*|$)",
            src,
            re.M,
        )
    )
    return names


def _scrub_dangling_sexp_aliases(src: str) -> str:
    """Drop SEXP_* → PUCHI_* aliases whose PUCHI_* target no longer exists.

    Aliases are generated before strip-dead-backends removes DL / promises /
    green-threads / etc. SEXP_TEST is always dropped: it collides with the
    PUCHI_TEST feature gate and is not a type tag in the host ABI.
    """
    defined = _puchi_macro_or_enum_names(src)
    out: list[str] = []
    for line in src.splitlines(keepends=True):
        m = re.match(
            r"#\s*define\s+(SEXP_[A-Z0-9_]+)\s+(PUCHI_[A-Z0-9_]+)\s*$",
            line,
        )
        if m:
            sexp_name, puchi_name = m.group(1), m.group(2)
            if sexp_name == "SEXP_TEST" or puchi_name not in defined:
                continue
        out.append(line)
    return "".join(out)


def _drop_prototype_lines(src: str, names: tuple[str, ...]) -> str:
    for name in names:
        src = re.sub(rf"^SEXP_API[^\n]*\b{name}\b[^\n]*;\n", "", src, flags=re.M)
        src = re.sub(rf"^(?:static\s+)?[^\n]*\b{name}\s*\([^;]*\);\n", "", src, flags=re.M)
    return src


def _drop_empty_macro_calls(src: str, names: tuple[str, ...]) -> str:
    """Remove statement-level calls to empty macros (and the empty #defines)."""
    for name in names:
        src = re.sub(rf"#\s*define\s+{name}\b[^\n]*\n", "", src)
        src = re.sub(rf"^[ \t]*{name}\s*\([^;]*\);\n", "", src, flags=re.M)
    return src


def _scrub_dl_fields(src: str) -> str:
    """Remove dl members from type/opcode structs and matching initializer slots."""
    # Host ABI may use puchi_* names; .c bodies still use sexp_*/SEXP_*.
    replaced_type = False
    for st, ty in (("puchi_type_struct", "puchi"), ("sexp_type_struct", "sexp")):
        old_type = (
            f"struct {st} {{\n"
            f"  {ty} name, cpl, slots, getters, setters, id, print, dl, finalize_name;\n"
        )
        new_type = (
            f"struct {st} {{\n"
            f"  {ty} name, cpl, slots, getters, setters, id, print, finalize_name;\n"
        )
        if old_type in src:
            src = src.replace(old_type, new_type, 1)
            replaced_type = True
            break
    if not replaced_type:
        raise SystemExit("scrub_amalgamation_residue: type_struct dl field not found")

    replaced_op = False
    for st, ty in (("puchi_opcode_struct", "puchi"), ("sexp_opcode_struct", "sexp")):
        old_op = (
            f"struct {st} {{\n"
            f"  {ty} name, data, data2, proc, ret_type, arg1_type, arg2_type, arg3_type,\n"
            f"    argn_type, methods, dl;\n"
        )
        new_op = (
            f"struct {st} {{\n"
            f"  {ty} name, data, data2, proc, ret_type, arg1_type, arg2_type, arg3_type,\n"
            f"    argn_type, methods;\n"
        )
        if old_op in src:
            src = src.replace(old_op, new_op, 1)
            replaced_op = True
            break
    if not replaced_op:
        raise SystemExit("scrub_amalgamation_residue: opcode_struct dl field not found")

    src = _drop_define_lines(
        src,
        (
            "sexp_opcode_dl",
            "sexp_type_dl",
            "sexp_context_dl",
            "puchi_opcode_dl",
            "puchi_type_dl",
            "puchi_context_dl",
        ),
    )

    src = src.replace(
        "NULL, NULL, SEXP_FALSE, c, o, n, m, i, f}",
        "NULL, NULL, c, o, n, m, i, f}",
    )
    src = src.replace(
        "NULL, NULL, SEXP_FALSE, SEXP_OPC_GETTER, SEXP_OP_SLOT_REF, 1, 0, 0, NULL}",
        "NULL, NULL, SEXP_OPC_GETTER, SEXP_OP_SLOT_REF, 1, 0, 0, NULL}",
    )
    src = src.replace(
        "NULL, NULL, SEXP_FALSE, SEXP_OPC_SETTER, SEXP_OP_SLOT_SET, 2, 0, 0, NULL}",
        "NULL, NULL, SEXP_OPC_SETTER, SEXP_OP_SLOT_SET, 2, 0, 0, NULL}",
    )
    src = src.replace(
        "NULL, NULL, SEXP_FALSE, SEXP_OPC_FOREIGN, o, n, m, 0, (sexp_proc1)f}",
        "NULL, NULL, SEXP_OPC_FOREIGN, o, n, m, 0, (sexp_proc1)f}",
    )

    src = src.replace(
        "SEXP_TYPE, sexp_offsetof(type, name), 9, 9,",
        "SEXP_TYPE, sexp_offsetof(type, name), 8, 8,",
    )
    src = src.replace(
        "PUCHI_TYPE, puchi_offsetof(type, name), 9, 9,",
        "PUCHI_TYPE, puchi_offsetof(type, name), 8, 8,",
    )
    src = src.replace(
        "SEXP_OPCODE, sexp_offsetof(opcode, name), 11, 11,",
        "SEXP_OPCODE, sexp_offsetof(opcode, name), 10, 10,",
    )
    src = src.replace(
        "PUCHI_OPCODE, puchi_offsetof(opcode, name), 11, 11,",
        "PUCHI_OPCODE, puchi_offsetof(opcode, name), 10, 10,",
    )

    src = src.replace(
        "SEXP_FALSE, SEXP_FALSE, SEXP_FALSE, SEXP_FALSE, SEXP_FALSE, NULL, NULL, NULL, SEXP_",
        "SEXP_FALSE, SEXP_FALSE, SEXP_FALSE, SEXP_FALSE, SEXP_FALSE, NULL, NULL, SEXP_",
    )
    src = src.replace(
        "PUCHI_FALSE, PUCHI_FALSE, PUCHI_FALSE, PUCHI_FALSE, PUCHI_FALSE, NULL, NULL, NULL, PUCHI_",
        "PUCHI_FALSE, PUCHI_FALSE, PUCHI_FALSE, PUCHI_FALSE, PUCHI_FALSE, NULL, NULL, PUCHI_",
    )
    src = re.sub(
        r"(SEXP_FALSE, SEXP_FALSE, SEXP_FALSE, SEXP_FALSE, SEXP_FALSE, "
        r"\(sexp\)[A-Za-z0-9_]+), NULL, (NULL|(?:sexp)?\"[^\"]*\"|SEXP_FINALIZE_[A-Z0-9_]+), (SEXP_[A-Z0-9_]+)",
        r"\1, \2, \3",
        src,
    )
    src = re.sub(
        r"(PUCHI_FALSE, PUCHI_FALSE, PUCHI_FALSE, PUCHI_FALSE, PUCHI_FALSE, "
        r"\(puchi\)[A-Za-z0-9_]+), NULL, (NULL|(?:puchi)?\"[^\"]*\"|PUCHI_FINALIZE_[A-Z0-9_]+), (PUCHI_[A-Z0-9_]+)",
        r"\1, \2, \3",
        src,
    )
    src = src.replace(
        "SEXP_FALSE, SEXP_FALSE, SEXP_FALSE, SEXP_FALSE, SEXP_FALSE, NULL, NULL, SEXP_FINALIZE_",
        "SEXP_FALSE, SEXP_FALSE, SEXP_FALSE, SEXP_FALSE, SEXP_FALSE, NULL, SEXP_FINALIZE_",
    )
    src = src.replace(
        "PUCHI_FALSE, PUCHI_FALSE, PUCHI_FALSE, PUCHI_FALSE, PUCHI_FALSE, NULL, NULL, PUCHI_FINALIZE_",
        "PUCHI_FALSE, PUCHI_FALSE, PUCHI_FALSE, PUCHI_FALSE, PUCHI_FALSE, NULL, PUCHI_FINALIZE_",
    )
    src = re.sub(
        r"(SEXP_FALSE, SEXP_FALSE, SEXP_FALSE, SEXP_FALSE, SEXP_FALSE, "
        r"\(sexp\)sexp_write_uvector), NULL, (\(sexp\)\"[^\"]+\"), (SEXP_UNIFORM_VECTOR)",
        r"\1, \2, \3",
        src,
    )

    if re.search(r"print, dl, finalize_name", src) or re.search(
        r"argn_type, methods, dl", src
    ):
        raise SystemExit("scrub_amalgamation_residue: dl field still present in struct")
    return src


def _scrub_opcodes_and_vm(src: str) -> str:
    for name in ("SEXP_OP_RESERVE", "SEXP_OP_YIELD", "SEXP_OP_FORCE"):
        src = re.sub(rf"^[ \t]*/\*[^*]*\*/[ \t]*{name},?\n", "", src, flags=re.M)
        src = re.sub(rf"^[ \t]*{name},?\n", "", src, flags=re.M)
    src = re.sub(
        r"[ \t]*case SEXP_OP_YIELD:\s*\n[ \t]*break;\s*\n",
        "",
        src,
    )
    src = re.sub(
        r"[ \t]*case SEXP_OP_FORCE:\s*\n[ \t]*break;\s*\n",
        "",
        src,
    )
    src = re.sub(
        r"[ \t]*case SEXP_OP_RESERVE:\s*\n[ \t]*break;\s*\n",
        "",
        src,
    )
    return src


def _scrub_gc_pad(src: str) -> str:
    src = re.sub(
        r"#\s*if\s*!defined\(SEXP_GC_PAD\)\n#define SEXP_GC_PAD 0\n#endif\n",
        "",
        src,
    )
    src = re.sub(r"#\s*define\s+SEXP_GC_PAD\s+0\n", "", src)
    src = src.replace(" + SEXP_GC_PAD", "")
    src = src.replace("+ SEXP_GC_PAD", "")
    return src


def _unwrap_include_guard(src: str, guard: str) -> str:
    """Remove #ifndef GUARD / #define GUARD … #endif, keeping the body."""
    lines = src.splitlines(keepends=True)
    out: list[str] = []
    i = 0
    open_re = re.compile(
        rf"^\s*#\s*(?:ifndef\s+{guard}|if\s*!defined\s*\(\s*{guard}\s*\))\s*$"
    )
    define_re = re.compile(rf"^\s*#\s*define\s+{guard}\s*$")
    while i < len(lines):
        if not open_re.match(lines[i]):
            out.append(lines[i])
            i += 1
            continue
        i += 1
        if i < len(lines) and define_re.match(lines[i]):
            i += 1
        depth = 1
        while i < len(lines) and depth > 0:
            s = lines[i].lstrip()
            if s.startswith("#if"):
                depth += 1
                out.append(lines[i])
            elif s.startswith("#endif"):
                depth -= 1
                if depth > 0:
                    out.append(lines[i])
            else:
                out.append(lines[i])
            i += 1
    return "".join(out)


def _scrub_nested_guards_and_banners(src: str) -> str:
    """Drop nested include guards / Alex Shinn banners; keep product extern C."""
    for guard in ("SEXP_H", "SEXP_EVAL_H", "SEXP_BIGNUM_H", "SEXP_FEATURES_H"):
        src = _unwrap_include_guard(src, guard)

    # Old layout: sexp.h bundled extern "C" with FLEXIBLE_ARRAY.
    # New stb layout: host ABI already has PUCHI_FLEXIBLE_ARRAY without extern.
    flex_bundled = re.compile(
        r"#\s*if(?:def|\s+defined\s*\(\s*__cplusplus\s*\))\s*\n"
        r"extern\s+\"C\"\s*\{\s*\n"
        r"(#\s*define\s+(?:SEXP|PUCHI)_FLEXIBLE_ARRAY\s+\[[A-Z_]+_FLEXIBLE_ARRAY_SIZE\]\s*\n)"
        r"#\s*else\s*\n"
        r"(#\s*define\s+(?:SEXP|PUCHI)_FLEXIBLE_ARRAY\s+\[\]\s*\n)"
        r"#\s*endif\s*\n",
    )
    src, n_flex = flex_bundled.subn(
        r"#if defined(__cplusplus)\n\1#else\n\2#endif\n",
        src,
        count=1,
    )
    if n_flex == 0:
        if not re.search(
            r"#\s*define\s+PUCHI_FLEXIBLE_ARRAY\s+\[",
            src,
        ):
            raise SystemExit(
                "scrub: sexp.h extern+FLEXIBLE_ARRAY block not found "
                f"(matches={n_flex})"
            )
    elif n_flex != 1:
        raise SystemExit(
            "scrub: sexp.h extern+FLEXIBLE_ARRAY block not found "
            f"(matches={n_flex})"
        )

    # Drop amalgamated-header closes: "} /* extern \"C\" */" only.
    # Keep product close: "} /* extern \"C\" implementation */".
    close_inner = re.compile(
        r"#\s*if(?:def|\s+defined\s*\(\s*__cplusplus\s*\))\s*\n"
        r"\}\s*/\*\s*extern\s+\"C\"\s*\*/\s*\n"
        r"#\s*endif\s*\n",
    )
    src, n_close = close_inner.subn("", src)
    if n_close < 1:
        raise SystemExit(
            f"scrub: inner extern \"C\" close not found (matches={n_close})"
        )

    # Drop broken/empty inner opens left after ABI extraction, e.g.
    #   #if defined(__cplusplus)\nextern "C" {\n#else\n#endif
    # and plain empty opens from eval.h. Keep the banner open (first).
    broken_open = re.compile(
        r"#\s*if(?:def|\s+defined\s*\(\s*__cplusplus\s*\))\s*\n"
        r"extern\s+\"C\"\s*\{\s*\n"
        r"(?:#\s*else\s*\n)?"
        r"#\s*endif\s*\n",
    )
    matches = list(broken_open.finditer(src))
    if not matches:
        raise SystemExit("scrub: banner extern \"C\" open missing")
    # Keep first (banner); remove the rest that are empty/broken opens.
    for m in reversed(matches[1:]):
        # Only remove if the match has no real body (already constrained by regex)
        src = src[: m.start()] + src[m.end() :]

    # Banner open is `#if __cplusplus / extern "C" { / #endif` (close at footer).
    # Remove any additional empty opens (eval.h / leftover stripped sexp.h).
    empty_open = re.compile(
        r"#\s*if(?:def|\s+defined\s*\(\s*__cplusplus\s*\))\s*\n"
        r"extern\s+\"C\"\s*\{\s*\n"
        r"#\s*endif\s*\n",
    )
    ms = list(empty_open.finditer(src))
    if not ms:
        raise SystemExit("scrub: banner extern \"C\" open missing")
    for m in reversed(ms[1:]):
        src = src[: m.start()] + src[m.end() :]

    if not re.search(
        r"\}\s*/\*\s*extern\s+\"C\"\s+implementation\s*\*/",
        src,
    ):
        raise SystemExit("scrub: footer extern \"C\" close missing")
    if re.search(
        r'extern\s+"C"\s*\{\s*\n#\s*define\s+(?:SEXP|PUCHI)_FLEXIBLE_ARRAY',
        src,
    ):
        raise SystemExit("scrub: FLEXIBLE_ARRAY still bundled with extern \"C\"")
    if close_inner.search(src):
        raise SystemExit("scrub: inner extern \"C\" close still present")
    n_banner_open = len(empty_open.findall(src))
    if n_banner_open != 1:
        raise SystemExit(
            f"scrub: expected 1 product extern \"C\" open, got {n_banner_open}"
        )

    src = re.sub(
        r"/\*  [a-z0-9_.]+ --[^*]*\*/\n"
        r"/\*  Copyright \(c\) [0-9\-]+ Alex Shinn\.  All rights reserved\. \*/\n"
        r"/\*  BSD-style license: http://synthcode.com/license.txt\s+\*/\n",
        "",
        src,
    )
    src = re.sub(
        r"/\*\s+Copyright \(c\) [0-9\-]+ Alex Shinn\.  All rights reserved\. \*/\n"
        r"/\*\s+BSD-style license: http://synthcode.com/license.txt\s+\*/\n",
        "",
        src,
    )
    return src


def scrub_amalgamation_residue(src: str) -> str:
    """Hard scrub of dead macros, bodiless prototypes, empty calls, opcodes, dl."""
    dead_macros = (
        "sexp_flags",
        "sexp_pointer_magic",
        "sexp_string_charlens",
        "sexp_context_refuel",
        "sexp_context_ip",
        "sexp_context_timeval",
        "sexp_context_dl",
        # sexp_context_gc_usecs kept as 0 — harness lib/chibi/ast.c calls it.
        "sexp_promisep",
        "sexp_promise_donep",
        "sexp_promise_value",
        "SEXP_COPY_DEFAULT",
        "SEXP_COPY_FREEP",
        "SEXP_COPY_LOADP",
        "SEXP_BANNER",
        "sexp_valid_object_p",
        "sexp_in_heap_p",
        "sexp_valid_header_magic_p",
        "sexp_valid_object_type_p",
    )

    # Tolerate `static` from make_sexp_funcs_static (otherwise leaves `static #define`).
    src = re.sub(
        r"[ \t]*(?:static\s+)?int sexp_valid_object_p\s*\(sexp ctx, sexp x\)\s*\{[^}]*\}\n",
        "",
        src,
    )

    src = _drop_define_lines(src, dead_macros)

    for name in (
        "sexp_valid_object_p",
        "sexp_in_heap_p",
        "sexp_valid_header_magic_p",
        "sexp_valid_object_type_p",
    ):
        src = re.sub(rf"\b{name}\s*\([^)]*\)", "1", src)

    src = _drop_prototype_lines(
        src,
        (
            "sexp_debug_heap_stats",
            "sexp_debug_alloc_times",
            "sexp_debug_alloc_sizes",
            "sexp_copy_context",
            "sexp_gc_init",
            "sexp_valid_object_p",
        ),
    )

    # Drop call sites from the amalgamation; keep empty #defines that harness
    # clibs (io stubs, etc.) still expand when compiling against the header.
    empty_macros_keep_defs = (
        "sexp_maybe_block_port",
        "sexp_maybe_unblock_port",
        "sexp_check_block_port",
    )
    empty_macros_drop = (
        "sexp_debug_printf",
        "sexp_conservative_mark",
        "sexp_update_string_index_lookup",
        "sexp_emit_enter",
        "sexp_bless_bytecode",
    )
    for name in empty_macros_keep_defs:
        src = re.sub(rf"^[ \t]*{name}\s*\([^;]*\);\n", "", src, flags=re.M)
    src = _drop_empty_macro_calls(src, empty_macros_drop)

    # Ensure harness-facing empty stubs exist (puchi_* body and/or sexp_* alias).
    if "#define puchi_context_gc_usecs" not in src and "#define sexp_context_gc_usecs" not in src:
        anchor = "#define puchi_context_params(x)" if "#define puchi_context_params(x)" in src else "#define sexp_context_params(x)"
        src = src.replace(
            anchor,
            "#define puchi_context_gc_usecs(x) 0\n#define sexp_context_gc_usecs puchi_context_gc_usecs\n"
            + anchor,
            1,
        )
    for pname, sname in (
        ("puchi_maybe_block_port", "sexp_maybe_block_port"),
        ("puchi_maybe_unblock_port", "sexp_maybe_unblock_port"),
        ("puchi_check_block_port", "sexp_check_block_port"),
    ):
        if f"#define {pname}" not in src and f"#define {sname}" not in src:
            raise SystemExit(
                f"scrub_amalgamation_residue: missing harness stub #{pname}"
            )

    # Upstream sexp.h forward-declares sexp_alloc for separate gc.c / sexp.c
    # TUs. Amalgamation defines it static in gc.c before all callers — the bare
    # extern prototype only triggers C4211 (extern decl, static def). Drop it.
    src = re.sub(
        r"^[ \t]*void\*\s*sexp_alloc\s*\(\s*sexp\s+ctx\s*,\s*size_t\s+size\s*\)\s*;\n",
        "",
        src,
        flags=re.M,
    )

    src = re.sub(r"^[ \t]*sexp_gc_init\s*\(\s*\)\s*;\n", "", src, flags=re.M)
    # Bodies may be static after make_sexp_funcs_static; drop empty stubs.
    src = re.sub(
        r"^[ \t]*(?:static\s+)?void sexp_gc_init\s*\(\s*void\s*\)\s*\{[^\n]*\}\n",
        "",
        src,
        flags=re.M,
    )
    # Drop non-empty sexp_gc_init (GLOBAL_HEAP / conservative arms already folded).
    src = re.sub(
        r"^[ \t]*(?:static\s+)?void sexp_gc_init\s*\(\s*void\s*\)\s*\{.*?\n\}\n",
        "",
        src,
        flags=re.M | re.S,
    )
    # Stray storage-class left if a later scrub ate the rest of a decl line.
    src = re.sub(r"^[ \t]*static[ \t]*\n(?=[ \t]*/\*)", "", src, flags=re.M)
    src = re.sub(r"^[ \t]*static[ \t]*\n(?=[ \t]*#)", "", src, flags=re.M)
    src = re.sub(r"^[ \t]*static[ \t]+(?=#define\b)", "", src, flags=re.M)

    src = _scrub_opcodes_and_vm(src)
    src = _scrub_dl_fields(src)
    src = _scrub_gc_pad(src)
    src = _scrub_nested_guards_and_banners(src)
    src = _scrub_huff_isymbol_minifloat(src)
    src = _scrub_misc_comments_and_gates(src)
    src = _scrub_dangling_sexp_aliases(src)

    src = src.replace(
        "/* ==== sexp.h (bignum.h inlined mid-file under SEXP_USE_BIGNUMS) ==== */",
        "/* ==== sexp.h (bignum.h inlined mid-file under PUCHI_ENABLE_NUMERICAL_TOWER) ==== */",
    )
    src = src.replace(
        "/* ==== bignum.c (active only if PUCHI_ENABLE_NUMERICAL_TOWER / SEXP_USE_BIGNUMS) ==== */",
        "/* ==== bignum.c (active only if PUCHI_ENABLE_NUMERICAL_TOWER) ==== */",
    )

    # Warning hygiene that spans .c bodies (sexp.c / eval.c / vm.c).
    src = src.replace("_sexp_type_specs", "puchi_type_specs")
    src = src.replace(
        "static void sexp_add_path (",
        "static inline void sexp_add_path (",
    )
    src = src.replace(
        "static void sexp_add_path(",
        "static inline void sexp_add_path(",
    )
    # C++ keywords used as C identifiers (Clang -Wc++-keyword).
    src = src.replace("char class;", "char infnan_kind;")
    src = src.replace(
        "(class = classify_infnan(str))",
        "(infnan_kind = classify_infnan(str))",
    )
    src = src.replace("class == 'n'", "infnan_kind == 'n'")
    # Rename param `new` (C++ keyword). Tolerate static/whitespace from the
    # make_sexp_funcs_static pass.
    thread_m = re.search(
        r"^((?:static\s+)?)sexp\s+sexp_thread_parameters_set\s*\(\s*"
        r"sexp\s+ctx,\s*sexp\s+self,\s*sexp_sint_t\s+n,\s*sexp\s+"
        r"new(\s*\)\s*\{)\n(\s*)sexp_context_params\(ctx\)\s*=\s*new;",
        src,
        re.M,
    )
    if not thread_m:
        raise SystemExit(
            "scrub_amalgamation_residue: sexp_thread_parameters_set not found"
        )
    src = (
        src[: thread_m.start()]
        + f"{thread_m.group(1)}sexp sexp_thread_parameters_set ("
        f"sexp ctx, sexp self, sexp_sint_t n, sexp new_params"
        f"{thread_m.group(2)}\n"
        f"{thread_m.group(3)}sexp_context_params(ctx) = new_params;"
        + src[thread_m.end() :]
    )

    src = _scrub_vm_reserved_macros(src)
    src = _scrub_statement_macros_extra_semi(src)

    for name in empty_macros_drop + dead_macros:
        if re.search(rf"#\s*define\s+{name}\b", src):
            raise SystemExit(f"scrub_amalgamation_residue: leftover #define {name}")

    # Hard-fail if deleted surfaces reappear.
    for pat, label in (
        (r"struct\s+(?:sexp|puchi)_huff_entry", "sexp_huff_entry"),
        (r"\b(?:sexp|puchi)_isymbolp\b", "sexp_isymbolp"),
        (r"\b(?:SEXP|PUCHI)_ISYMBOL_TAG\b", "SEXP_ISYMBOL_TAG"),
        (r"\b(?:SEXP|PUCHI)_IFLONUM_TAG\b", "SEXP_IFLONUM_TAG"),
        (r"\b(?:SEXP|PUCHI)_F8\b", "SEXP_F8"),
        (r"\b(?:SEXP|PUCHI)_F16\b", "SEXP_F16"),
        (r"\b(?:sexp|puchi)_f8vectorp\b", "sexp_f8vectorp"),
        (r"\b(?:sexp|puchi)_f16vectorp\b", "sexp_f16vectorp"),
        (r'clibs\.c', "clibs.c mention"),
        (r'"RESERVE"', "opcode name RESERVE"),
        (r'"YIELD"', "opcode name YIELD"),
        (r'"FORCE"', "opcode name FORCE"),
        (r"#\s*define\s+SEXP_DL\b", "SEXP_DL alias"),
        (r"#\s*define\s+SEXP_PROMISE\b", "SEXP_PROMISE alias"),
        (r"#\s*define\s+SEXP_TEST\s+PUCHI_TEST\b", "SEXP_TEST→PUCHI_TEST alias"),
        (r"#\s*define\s+SEXP_G_THREADS_", "SEXP_G_THREADS_* alias"),
        (r"#\s*define\s+SEXP_G_THREAD_TERMINATE_ERROR\b", "thread-terminate alias"),
        (r"#\s*define\s+SEXP_G_IO_BLOCK_(?:ONCE_)?ERROR\b", "IO_BLOCK alias"),
        (r"#\s*define\s+SEXP_G_ATOMIC_P\b", "SEXP_G_ATOMIC_P alias"),
    ):
        if re.search(pat, src):
            raise SystemExit(f"scrub_amalgamation_residue: leftover {label}")

    defined = _puchi_macro_or_enum_names(src)
    for m in re.finditer(
        r"#\s*define\s+(SEXP_[A-Z0-9_]+)\s+(PUCHI_[A-Z0-9_]+)\s*$",
        src,
        re.M,
    ):
        if m.group(2) not in defined:
            raise SystemExit(
                f"scrub_amalgamation_residue: dangling alias "
                f"{m.group(1)} → {m.group(2)}"
            )

    return src


def _scrub_vm_reserved_macros(src: str) -> str:
    """Rename vm.c / fcall.c _ARG/_PUSH/_A… macros (Clang reserved-macro)."""
    for old, new in (
        ("_ALIGN_IP", "PUCHI_ALIGN_IP"),
        ("_UWORD0", "PUCHI_UWORD0"),
        ("_UWORD1", "PUCHI_UWORD1"),
        ("_SWORD0", "PUCHI_SWORD0"),
        ("_SWORD1", "PUCHI_SWORD1"),
        ("_WORD0", "PUCHI_WORD0"),
        ("_WORD1", "PUCHI_WORD1"),
        ("_WORD2", "PUCHI_WORD2"),
        ("_ARG1", "PUCHI_ARG1"),
        ("_ARG2", "PUCHI_ARG2"),
        ("_ARG3", "PUCHI_ARG3"),
        ("_ARG4", "PUCHI_ARG4"),
        ("_ARG5", "PUCHI_ARG5"),
        ("_ARG6", "PUCHI_ARG6"),
        ("_PUSH", "PUCHI_PUSH"),
        ("_POP", "PUCHI_POP"),
        ("_A", "PUCHI_A"),
    ):
        src = re.sub(rf"\b{re.escape(old)}\b", new, src)
    return src


def _scrub_statement_macros_extra_semi(src: str) -> str:
    """Wrap statement macros in do-while(0) so caller ';' is not empty."""

    def _wrap_or_die(src: str, old: str, new: str, label: str) -> str:
        if old in src:
            return src.replace(old, new, 1)
        raise SystemExit(f"scrub_amalgamation_residue: {label} macro not found")

    # Prefer puchi_* host ABI names; fall back to sexp_* if present.
    if "#define puchi_negate_exact" in src:
        pref = "puchi"
    else:
        pref = "sexp"

    exact_old = (
        f"#define {pref}_negate_exact(x)                            \\\n"
        f"  if ({pref}_bignump(x))                                  \\\n"
        f"    {pref}_bignum_sign(x) = -{pref}_bignum_sign(x);         \\\n"
        f"  else if ({pref}_fixnump(x))                             \\\n"
        f"    x = {pref}_fx_neg(x);\n"
    )
    exact_new = (
        f"#define {pref}_negate_exact(x) do {{                       \\\n"
        f"  if ({pref}_bignump(x))                                  \\\n"
        f"    {pref}_bignum_sign(x) = -{pref}_bignum_sign(x);         \\\n"
        f"  else if ({pref}_fixnump(x))                             \\\n"
        f"    x = {pref}_fx_neg(x);                                 \\\n"
        f"}} while (0)\n"
    )
    src = _wrap_or_die(src, exact_old, exact_new, f"{pref}_negate_exact")

    neg_old = (
        f"#define {pref}_negate(x)                                  \\\n"
        f"  if ({pref}_flonump(x))                                  \\\n"
        f"    {pref}_negate_flonum(x);                              \\\n"
        f"  else                                                  \\\n"
        f"    {pref}_negate_exact(x)\n"
    )
    neg_new = (
        f"#define {pref}_negate(x) do {{                             \\\n"
        f"  if ({pref}_flonump(x))                                  \\\n"
        f"    {pref}_negate_flonum(x);                              \\\n"
        f"  else                                                  \\\n"
        f"    {pref}_negate_exact(x);                               \\\n"
        f"}} while (0)\n"
    )
    src = _wrap_or_die(src, neg_old, neg_new, f"{pref}_negate")

    ratio_old = (
        f"#define {pref}_negate_maybe_ratio(x)                      \\\n"
        f"  if ({pref}_ratiop(x)) {{                                 \\\n"
        f"    {pref}_negate_exact({pref}_ratio_numerator(x));         \\\n"
        f"  }} else {{                                              \\\n"
        f"    {pref}_negate(x);                                     \\\n"
        f"  }}\n"
    )
    ratio_new = (
        f"#define {pref}_negate_maybe_ratio(x) do {{                 \\\n"
        f"  if ({pref}_ratiop(x)) {{                                 \\\n"
        f"    {pref}_negate_exact({pref}_ratio_numerator(x));         \\\n"
        f"  }} else {{                                              \\\n"
        f"    {pref}_negate(x);                                     \\\n"
        f"  }}                                                     \\\n"
        f"}} while (0)\n"
    )
    src = _wrap_or_die(src, ratio_old, ratio_new, f"{pref}_negate_maybe_ratio")

    # sexp_ensure_stack: ends with '}' then caller ';' → empty statement.
    # Runs after _scrub_vm_reserved_macros so _ARG1 is already PUCHI_ARG1.
    ens_old = (
        "#define sexp_ensure_stack(n)                                            \\\n"
        "  if (top+(n) >= sexp_stack_length(sexp_context_stack(ctx))) {          \\\n"
        "    sexp_context_top(ctx) = top;                                        \\\n"
        "    if (sexp_grow_stack(ctx, (n))) {                                    \\\n"
        "      stack = sexp_stack_data(sexp_context_stack(ctx));                 \\\n"
        "    } else {                                                            \\\n"
        "      PUCHI_ARG1 = sexp_global(ctx, SEXP_G_OOS_ERROR);                  \\\n"
        "      goto end_loop;                                                    \\\n"
        "    }                                                                   \\\n"
        "  }\n"
    )
    ens_new = (
        "#define sexp_ensure_stack(n) do {                                       \\\n"
        "  if (top+(n) >= sexp_stack_length(sexp_context_stack(ctx))) {          \\\n"
        "    sexp_context_top(ctx) = top;                                        \\\n"
        "    if (sexp_grow_stack(ctx, (n))) {                                    \\\n"
        "      stack = sexp_stack_data(sexp_context_stack(ctx));                 \\\n"
        "    } else {                                                            \\\n"
        "      PUCHI_ARG1 = sexp_global(ctx, SEXP_G_OOS_ERROR);                  \\\n"
        "      goto end_loop;                                                    \\\n"
        "    }                                                                   \\\n"
        "  }                                                                     \\\n"
        "} while (0)\n"
    )
    if ens_old not in src:
        # Spacing may differ on the PUCHI_ARG1 line after rename.
        ens_old2 = ens_old.replace(
            "      PUCHI_ARG1 = sexp_global(ctx, SEXP_G_OOS_ERROR);                  \\\n",
            "      PUCHI_ARG1 = sexp_global(ctx, SEXP_G_OOS_ERROR);                       \\\n",
        )
        # Match whatever spaces the rename left on that line.
        ens_re = re.compile(
            r"#define sexp_ensure_stack\(n\)\s*\\\n"
            r"  if \(top\+\(n\) >= sexp_stack_length\(sexp_context_stack\(ctx\)\)\) \{\s*\\\n"
            r"    sexp_context_top\(ctx\) = top;\s*\\\n"
            r"    if \(sexp_grow_stack\(ctx, \(n\)\)\) \{\s*\\\n"
            r"      stack = sexp_stack_data\(sexp_context_stack\(ctx\)\);\s*\\\n"
            r"    \} else \{\s*\\\n"
            r"      PUCHI_ARG1 = sexp_global\(ctx, SEXP_G_OOS_ERROR\);\s*\\\n"
            r"      goto end_loop;\s*\\\n"
            r"    \}\s*\\\n"
            r"  \}\n"
        )
        m = ens_re.search(src)
        if not m:
            raise SystemExit(
                "scrub_amalgamation_residue: sexp_ensure_stack macro not found"
            )
        src = src[: m.start()] + ens_new + src[m.end() :]
    else:
        src = src.replace(ens_old, ens_new, 1)
    return src


def _scrub_huff_isymbol_minifloat(src: str) -> str:
    """Remove ungated HUFF / immediate-symbol / mini-float declarations."""
    huff_re = re.compile(
        r"/\* optional huffman-compressed immediate symbols \*/\n"
        r"struct (?:sexp|puchi)_huff_entry \{\n"
        r"  unsigned char len;\n"
        r"  unsigned short bits;\n"
        r"\};\n",
    )
    src2, n = huff_re.subn("", src, count=1)
    if n != 1:
        raise SystemExit("scrub: sexp_huff_entry block not found")
    src = src2

    src = src.replace(
        " *                0110:  immediate symbol (optional)\n"
        " *            00001110:  immediate flonum (optional)\n",
        "",
    )
    src = re.sub(r"#\s*define\s+(?:SEXP|PUCHI)_ISYMBOL_TAG\s+\d+\n", "", src)
    src = re.sub(r"#\s*define\s+(?:SEXP|PUCHI)_IFLONUM_TAG\s+\d+\n", "", src)
    src = re.sub(
        r"#\s*define\s+(?:sexp|puchi)_isymbolp\(x\)\s+[^\n]+\n",
        "",
        src,
    )
    # Drop aliases that pointed at removed tags/predicates.
    src = re.sub(r"#\s*define\s+SEXP_ISYMBOL_TAG\s+PUCHI_ISYMBOL_TAG\n", "", src)
    src = re.sub(r"#\s*define\s+SEXP_IFLONUM_TAG\s+PUCHI_IFLONUM_TAG\n", "", src)
    src = re.sub(r"#\s*define\s+sexp_isymbolp\s+puchi_isymbolp\n", "", src)

    # Mini-float uniform vector surface (always-off).
    src = re.sub(
        r"#\s*define\s+(?:sexp|puchi)_f8vectorp\(x\)\s+[^\n]+\n",
        "",
        src,
    )
    src = re.sub(
        r"#\s*define\s+(?:sexp|puchi)_f16vectorp\(x\)\s+[^\n]+\n",
        "",
        src,
    )
    src = re.sub(r"#\s*define\s+sexp_f8vectorp\s+puchi_f8vectorp\n", "", src)
    src = re.sub(r"#\s*define\s+sexp_f16vectorp\s+puchi_f16vectorp\n", "", src)
    old_sizes = (
        "static const unsigned char sexp_uvector_sizes[] = {\n"
        "  0, 1, 8, 8, 16, 16, 32, 32, 64, 64, 32, 64, 64, 128, 8, 16};\n"
        'static const unsigned char sexp_uvector_chars[] = "#ususususuffccff";\n'
    )
    new_sizes = (
        "static const unsigned char puchi_uvector_sizes[] = {\n"
        "  0, 1, 8, 8, 16, 16, 32, 32, 64, 64, 32, 64, 64, 128};\n"
        'static const unsigned char puchi_uvector_chars[] = "#ususususuffcc";\n'
        "#define sexp_uvector_sizes puchi_uvector_sizes\n"
        "#define sexp_uvector_chars puchi_uvector_chars\n"
    )
    if old_sizes not in src:
        raise SystemExit("scrub: uvector sizes/chars (with f8/f16) not found")
    src = src.replace(old_sizes, new_sizes, 1)
    src = src.replace("  SEXP_C128,\n  SEXP_F8,\n  SEXP_F16,\n", "  SEXP_C128,\n")
    src = src.replace("  PUCHI_C128,\n  PUCHI_F8,\n  PUCHI_F16,\n", "  PUCHI_C128,\n")
    src = re.sub(r"#\s*define\s+SEXP_F8\s+PUCHI_F8\n", "", src)
    src = re.sub(r"#\s*define\s+SEXP_F16\s+PUCHI_F16\n", "", src)

    return src


def _scrub_misc_comments_and_gates(src: str) -> str:
    """Drop stale clibs comments, collapse duplicate PUCHI_TEST, fix opcode names."""
    src = re.sub(
        r"/\* don't include clibs\.c - include separately or link \*/\n",
        "",
        src,
    )

    # Opcode names were wrapped twice (#if STATIC_LIBS → PUCHI_TEST, plus EMPTY).
    old_names = (
        "#if defined(PUCHI_TEST)\n"
        "#if defined(PUCHI_TEST)\n"
        "/* ---- opt/opcode_names.h (amalgamated; harness) ---- */\n"
    )
    new_names = (
        "#if defined(PUCHI_TEST)\n"
        "/* ---- opt/opcode_names.h (amalgamated; harness) ---- */\n"
    )
    if old_names in src:
        src = src.replace(old_names, new_names, 1)
        # Drop the extra #endif that closed the inner gate (right after names = ...).
        src = src.replace(
            "const char** sexp_opcode_names = sexp_opcode_names_;\n"
            "#endif\n"
            "#endif\n",
            "const char** sexp_opcode_names = sexp_opcode_names_;\n"
            "#endif\n",
            1,
        )

    # Opcode name table: drop RESERVE / YIELD / FORCE (enum entries are gone).
    src = src.replace('"PUSH", "RESERVE", "DROP"', '"PUSH", "DROP"')
    src = src.replace(
        '"WRITE-CHAR", "WRITE-STRING", "READ-CHAR", "PEEK-CHAR",\n'
        '   "YIELD", "FORCE", "RET", "DONE", "SC?", "SC<", "SC<="',
        '"WRITE-CHAR", "WRITE-STRING", "READ-CHAR", "PEEK-CHAR",\n'
        '   "RET", "DONE", "SC?", "SC<", "SC<="',
    )

    # SEXP_API → static makes the decl internal; the definition must match
    # (Clang errors on static decl + non-static object def; MSVC is softer).
    src = re.sub(
        r"^(?![ \t]*static\b)([ \t]*)const char\*\*[ \t]+sexp_opcode_names[ \t]*=",
        r"\1static const char** sexp_opcode_names =",
        src,
        count=1,
        flags=re.M,
    )

    return src
