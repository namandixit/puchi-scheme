"""Post-amalgamation scrub: ALWAYS_ZERO define cleanup, residue, asserts.

C body forks live in puchi/patches/; feature scrubbing is mechanical
(scrub_features_h). This module runs after strip-dead-backends.
"""
from __future__ import annotations

import re

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
    if '".so"' in without_test or "sexp_so_extension" in without_test:
        hits.append('".so" outside PUCHI_TEST')
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
    return puchi_h


def _drop_define_lines(src: str, names: tuple[str, ...]) -> str:
    for name in names:
        src = re.sub(rf"#\s*define\s+{name}\b[^\n]*\n", "", src)
    return src


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
    old_type = (
        "struct sexp_type_struct {\n"
        "  sexp name, cpl, slots, getters, setters, id, print, dl, finalize_name;\n"
    )
    new_type = (
        "struct sexp_type_struct {\n"
        "  sexp name, cpl, slots, getters, setters, id, print, finalize_name;\n"
    )
    if old_type not in src:
        raise SystemExit("scrub_amalgamation_residue: type_struct dl field not found")
    src = src.replace(old_type, new_type, 1)

    old_op = (
        "struct sexp_opcode_struct {\n"
        "  sexp name, data, data2, proc, ret_type, arg1_type, arg2_type, arg3_type,\n"
        "    argn_type, methods, dl;\n"
    )
    new_op = (
        "struct sexp_opcode_struct {\n"
        "  sexp name, data, data2, proc, ret_type, arg1_type, arg2_type, arg3_type,\n"
        "    argn_type, methods;\n"
    )
    if old_op not in src:
        raise SystemExit("scrub_amalgamation_residue: opcode_struct dl field not found")
    src = src.replace(old_op, new_op, 1)

    src = _drop_define_lines(
        src,
        ("sexp_opcode_dl", "sexp_type_dl", "sexp_context_dl"),
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
        "SEXP_OPCODE, sexp_offsetof(opcode, name), 11, 11,",
        "SEXP_OPCODE, sexp_offsetof(opcode, name), 10, 10,",
    )

    src = src.replace(
        "SEXP_FALSE, SEXP_FALSE, SEXP_FALSE, SEXP_FALSE, SEXP_FALSE, NULL, NULL, NULL, SEXP_",
        "SEXP_FALSE, SEXP_FALSE, SEXP_FALSE, SEXP_FALSE, SEXP_FALSE, NULL, NULL, SEXP_",
    )
    src = re.sub(
        r"(SEXP_FALSE, SEXP_FALSE, SEXP_FALSE, SEXP_FALSE, SEXP_FALSE, "
        r"\(sexp\)[A-Za-z0-9_]+), NULL, (NULL|(?:sexp)?\"[^\"]*\"|SEXP_FINALIZE_[A-Z0-9_]+), (SEXP_[A-Z0-9_]+)",
        r"\1, \2, \3",
        src,
    )
    src = src.replace(
        "SEXP_FALSE, SEXP_FALSE, SEXP_FALSE, SEXP_FALSE, SEXP_FALSE, NULL, NULL, SEXP_FINALIZE_",
        "SEXP_FALSE, SEXP_FALSE, SEXP_FALSE, SEXP_FALSE, SEXP_FALSE, NULL, SEXP_FINALIZE_",
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

    # sexp.h opens extern "C" with FLEXIBLE_ARRAY. Keep only the array branch;
    # banner / api_decls / footer own the linkage braces.
    flex_pat = re.compile(
        r"#\s*if(?:def|\s+defined\s*\(\s*__cplusplus\s*\))\s*\n"
        r"extern\s+\"C\"\s*\{\s*\n"
        r"(#\s*define\s+SEXP_FLEXIBLE_ARRAY\s+\[SEXP_FLEXIBLE_ARRAY_SIZE\]\s*\n)"
        r"#\s*else\s*\n"
        r"(#\s*define\s+SEXP_FLEXIBLE_ARRAY\s+\[\]\s*\n)"
        r"#\s*endif\s*\n",
    )
    src, n_flex = flex_pat.subn(
        r"#if defined(__cplusplus)\n\1#else\n\2#endif\n",
        src,
        count=1,
    )
    if n_flex != 1:
        raise SystemExit(
            "scrub: sexp.h extern+FLEXIBLE_ARRAY block not found "
            f"(matches={n_flex})"
        )

    # Drop amalgamated-header closes: "} /* extern \"C\" */" only.
    # Keep product closes: declarations / implementation.
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

    # Drop inner empty opens (eval.h); keep banner (first) and the
    # re-open after "} /* extern \"C\" declarations */".
    empty_open = re.compile(
        r"#\s*if(?:def|\s+defined\s*\(\s*__cplusplus\s*\))\s*\n"
        r"extern\s+\"C\"\s*\{\s*\n"
        r"#\s*endif\s*\n",
    )
    decl_close = re.search(
        r"\}\s*/\*\s*extern\s+\"C\"\s+declarations\s*\*/",
        src,
    )
    decl_pos = decl_close.start() if decl_close else len(src)
    matches = list(empty_open.finditer(src))
    if not matches:
        raise SystemExit("scrub: banner extern \"C\" open missing")
    remove = [m for i, m in enumerate(matches) if i != 0 and m.start() < decl_pos]
    for m in reversed(remove):
        src = src[: m.start()] + src[m.end() :]

    if not re.search(
        r"\}\s*/\*\s*extern\s+\"C\"\s+declarations\s*\*/",
        src,
    ):
        raise SystemExit("scrub: api_decls extern \"C\" close missing")
    if not re.search(
        r"\}\s*/\*\s*extern\s+\"C\"\s+implementation\s*\*/",
        src,
    ):
        raise SystemExit("scrub: footer extern \"C\" close missing")
    if re.search(
        r'extern\s+"C"\s*\{\s*\n#\s*define\s+SEXP_FLEXIBLE_ARRAY',
        src,
    ):
        raise SystemExit("scrub: FLEXIBLE_ARRAY still bundled with extern \"C\"")
    if close_inner.search(src):
        raise SystemExit("scrub: inner extern \"C\" close still present")
    n_empty_open = len(empty_open.findall(src))
    if n_empty_open != 2:
        raise SystemExit(
            f"scrub: expected 2 product extern \"C\" opens, got {n_empty_open}"
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

    src = re.sub(
        r"int sexp_valid_object_p\s*\(sexp ctx, sexp x\)\s*\{[^}]*\}\n",
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

    # Ensure harness-facing empty stubs exist.
    if "#define sexp_context_gc_usecs" not in src:
        src = src.replace(
            "#define sexp_context_params(x)",
            "#define sexp_context_gc_usecs(x) 0\n#define sexp_context_params(x)",
            1,
        )
    for name, args in (
        ("sexp_maybe_block_port", "(ctx, in, forcep)"),
        ("sexp_maybe_unblock_port", "(ctx, in)"),
        ("sexp_check_block_port", "(ctx, in, forcep)"),
    ):
        if f"#define {name}" not in src:
            raise SystemExit(
                f"scrub_amalgamation_residue: missing harness stub #{name}"
            )

    src = re.sub(r"^[ \t]*sexp_gc_init\s*\(\s*\)\s*;\n", "", src, flags=re.M)
    src = re.sub(
        r"void sexp_gc_init\s*\(\s*void\s*\)\s*\{\s*\}\n",
        "",
        src,
    )

    src = _scrub_opcodes_and_vm(src)
    src = _scrub_dl_fields(src)
    src = _scrub_gc_pad(src)
    src = _scrub_nested_guards_and_banners(src)
    src = _scrub_huff_isymbol_minifloat(src)
    src = _scrub_misc_comments_and_gates(src)

    src = src.replace(
        "/* ==== sexp.h (bignum.h inlined mid-file under SEXP_USE_BIGNUMS) ==== */",
        "/* ==== sexp.h (bignum.h inlined mid-file under PUCHI_ENABLE_NUMERICAL_TOWER) ==== */",
    )
    src = src.replace(
        "/* ==== bignum.c (active only if PUCHI_ENABLE_NUMERICAL_TOWER / SEXP_USE_BIGNUMS) ==== */",
        "/* ==== bignum.c (active only if PUCHI_ENABLE_NUMERICAL_TOWER) ==== */",
    )

    for name in empty_macros_drop + dead_macros:
        if re.search(rf"#\s*define\s+{name}\b", src):
            raise SystemExit(f"scrub_amalgamation_residue: leftover #define {name}")

    # Hard-fail if deleted surfaces reappear.
    for pat, label in (
        (r"struct\s+sexp_huff_entry", "sexp_huff_entry"),
        (r"\bsexp_isymbolp\b", "sexp_isymbolp"),
        (r"\bSEXP_ISYMBOL_TAG\b", "SEXP_ISYMBOL_TAG"),
        (r"\bSEXP_IFLONUM_TAG\b", "SEXP_IFLONUM_TAG"),
        (r"\bSEXP_F8\b", "SEXP_F8"),
        (r"\bSEXP_F16\b", "SEXP_F16"),
        (r"\bsexp_f8vectorp\b", "sexp_f8vectorp"),
        (r"\bsexp_f16vectorp\b", "sexp_f16vectorp"),
        (r'clibs\.c', "clibs.c mention"),
        (r'"RESERVE"', "opcode name RESERVE"),
        (r'"YIELD"', "opcode name YIELD"),
        (r'"FORCE"', "opcode name FORCE"),
    ):
        if re.search(pat, src):
            raise SystemExit(f"scrub_amalgamation_residue: leftover {label}")

    return src


def _scrub_huff_isymbol_minifloat(src: str) -> str:
    """Remove ungated HUFF / immediate-symbol / mini-float declarations."""
    huff = (
        "/* optional huffman-compressed immediate symbols */\n"
        "struct sexp_huff_entry {\n"
        "  unsigned char len;\n"
        "  unsigned short bits;\n"
        "};\n"
    )
    if huff not in src:
        # Allow already-scrubbed or whitespace variants
        huff_re = re.compile(
            r"/\* optional huffman-compressed immediate symbols \*/\n"
            r"struct sexp_huff_entry \{\n"
            r"  unsigned char len;\n"
            r"  unsigned short bits;\n"
            r"\};\n",
        )
        src2, n = huff_re.subn("", src, count=1)
        if n != 1:
            raise SystemExit("scrub: sexp_huff_entry block not found")
        src = src2
    else:
        src = src.replace(huff, "", 1)

    src = src.replace(
        " *                0110:  immediate symbol (optional)\n"
        " *            00001110:  immediate flonum (optional)\n",
        "",
    )
    src = re.sub(r"#\s*define\s+SEXP_ISYMBOL_TAG\s+\d+\n", "", src)
    src = re.sub(r"#\s*define\s+SEXP_IFLONUM_TAG\s+\d+\n", "", src)
    src = re.sub(
        r"#\s*define\s+sexp_isymbolp\(x\)\s+[^\n]+\n",
        "",
        src,
    )

    # Mini-float uniform vector surface (always-off).
    src = re.sub(
        r"#\s*define\s+sexp_f8vectorp\(x\)\s+[^\n]+\n",
        "",
        src,
    )
    src = re.sub(
        r"#\s*define\s+sexp_f16vectorp\(x\)\s+[^\n]+\n",
        "",
        src,
    )
    old_sizes = (
        "static const unsigned char sexp_uvector_sizes[] = {\n"
        "  0, 1, 8, 8, 16, 16, 32, 32, 64, 64, 32, 64, 64, 128, 8, 16};\n"
        'static const unsigned char sexp_uvector_chars[] = "#ususususuffccff";\n'
    )
    new_sizes = (
        "static const unsigned char sexp_uvector_sizes[] = {\n"
        "  0, 1, 8, 8, 16, 16, 32, 32, 64, 64, 32, 64, 64, 128};\n"
        'static const unsigned char sexp_uvector_chars[] = "#ususususuffcc";\n'
    )
    if old_sizes not in src:
        raise SystemExit("scrub: uvector sizes/chars (with f8/f16) not found")
    src = src.replace(old_sizes, new_sizes, 1)
    src = src.replace("  SEXP_C128,\n  SEXP_F8,\n  SEXP_F16,\n", "  SEXP_C128,\n")

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

    return src
