"""Fold every SEXP_USE_* out of the amalgamated header.

Extends the dead-backend preprocessor folder: always-on keeps the true arm,
always-off drops the true arm, numeric names rewrite to PUCHI_*, and
#ifdef / #ifndef / defined() of SEXP_USE_* defaulting blocks are deleted.
"""
from __future__ import annotations

import re

from puchi_host_embed import (
    ALL_SEXP_USE_NAMES,
    ALWAYS_ONE_STRIP,
    ALWAYS_ZERO_STRIP,
    SEXP_USE_REWRITE,
)

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
        for op in ("&&", "||", "==", "!=", "<=", ">="):
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


def _simplify_pp_text(text: str) -> str:
    """Normalize rewritten PUCHI_* conditions."""
    t = text
    # Collapse duplicate OR/AND of the same defined(...)
    t = re.sub(
        r"defined\(PUCHI_ENABLE_NUMERICAL_TOWER\)\s*\|\|\s*"
        r"defined\(PUCHI_ENABLE_NUMERICAL_TOWER\)",
        "defined(PUCHI_ENABLE_NUMERICAL_TOWER)",
        t,
    )
    t = re.sub(
        r"!defined\(PUCHI_INTEGER_ONLY\)\s*\|\|\s*"
        r"defined\(PUCHI_ENABLE_NUMERICAL_TOWER\)",
        "!defined(PUCHI_INTEGER_ONLY)",
        t,
    )
    t = re.sub(
        r"defined\(PUCHI_ENABLE_NUMERICAL_TOWER\)\s*\|\|\s*"
        r"!defined\(PUCHI_INTEGER_ONLY\)",
        "!defined(PUCHI_INTEGER_ONLY)",
        t,
    )
    # !(!defined(X)) → defined(X)
    t = re.sub(r"!\s*\(\s*!defined\(([^)]+)\)\s*\)", r"defined(\1)", t)
    t = re.sub(r"!\s*!defined\(([^)]+)\)", r"defined(\1)", t)
    return t


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
            r"[A-Za-z_][A-Za-z0-9_]*|defined\([^)]*\)|!defined\([^)]*\)|"
            r"0[xX][0-9A-Fa-f]+[uUlL]*|\d+[uUlL]*",
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
        if name in ALWAYS_ZERO_STRIP or name in _DEAD_UNDEF:
            return _Pv(0, "0")
        if name in ALWAYS_ONE_STRIP:
            return _Pv(1, "1")
        if name in SEXP_USE_REWRITE:
            return _Pv(None, SEXP_USE_REWRITE[name])
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
            # Defaulting / ifdef of any SEXP_USE_* is a false region.
            if name in ALL_SEXP_USE_NAMES or name.startswith("SEXP_USE_"):
                return _Pv(0, "0")
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
            # !(!defined(X)) → defined(X); !(defined(X)) → !defined(X)
            m = re.fullmatch(r"!defined\(([^)]+)\)", v.text)
            if m:
                return _Pv(None, f"defined({m.group(1)})")
            m = re.fullmatch(r"defined\(([^)]+)\)", v.text)
            if m:
                return _Pv(None, f"!defined({m.group(1)})")
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
                v = _Pv(None, _simplify_pp_text(f"{spell(v)} && {spell(r)}"))
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
                v = _Pv(None, _simplify_pp_text(f"{spell(v)} || {spell(r)}"))
        return v

    v = or_expr()
    if pos != len(toks):
        return _Pv(None, " ".join(toks))
    if v.const is None:
        v = _Pv(None, _simplify_pp_text(v.text))
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
        # ifdef SEXP_USE_* → false (drop); including always-one names.
        if name in ALL_SEXP_USE_NAMES or name.startswith("SEXP_USE_"):
            return _Pv(0, "0")
        if name in _DEAD_UNDEF:
            return _Pv(0, "0")
        return _Pv(None, f"defined({name})")
    if word == "ifndef":
        name = rest.split()[0]
        # ifndef SEXP_USE_* → false region (drop the defaulting #define).
        if name in ALL_SEXP_USE_NAMES or name.startswith("SEXP_USE_"):
            return _Pv(0, "0")
        if name in _DEAD_UNDEF:
            return _Pv(1, "1")
        return _Pv(None, f"!defined({name})")
    return _pp_eval(rest)


def _reenables_dead_backend(line: str) -> bool:
    s = "".join(line.split())
    return s in ("#undefSEXP_USE_BOEHM", "#defineSEXP_USE_BOEHM1")


def strip_dead_backends(src: str, _tested: bool = False) -> str:
    """Fold ALWAYS_ZERO / ALWAYS_ONE / numeric SEXP_USE_* and PLAN9."""
    if not _tested:
        _self_test_fold()

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
        raise SystemExit("strip_dead_backends: unmatched #if")
    return "".join(out)


def fix_sexp_use_c_rvalues(src: str) -> str:
    """Rewrite SEXP_USE_* tokens that appear as C expressions, not #if."""
    # Bytevector hex follows always-on bytevector literals.
    src = src.replace(
        "#define SEXP_BYTEVECTOR_HEX_LITERALS SEXP_USE_BYTEVECTOR_LITERALS\n",
        "#define SEXP_BYTEVECTOR_HEX_LITERALS 1\n",
    )

    # Number-type count: ratios+complex only under the tower.
    old_num = "#define SEXP_NUM_NUMBER_TYPES (4 + SEXP_USE_RATIOS + SEXP_USE_COMPLEX)\n"
    new_num = (
        "#if defined(PUCHI_ENABLE_NUMERICAL_TOWER)\n"
        "#define SEXP_NUM_NUMBER_TYPES 6\n"
        "#else\n"
        "#define SEXP_NUM_NUMBER_TYPES 4\n"
        "#endif\n"
    )
    if old_num not in src:
        raise SystemExit("fix_sexp_use_c_rvalues: SEXP_NUM_NUMBER_TYPES not found")
    src = src.replace(old_num, new_num, 1)

    # exact_negativep / exact_positivep (host ABI uses puchi_*; aliases keep sexp_*)
    old_neg_puchi = (
        "#define puchi_exact_negativep(x) (puchi_fixnump(x) ? (puchi_unbox_fixnum(x) < 0) \\\n"
        "                                 : ((SEXP_USE_BIGNUMS && puchi_bignump(x)) \\\n"
        "                                    && (puchi_bignum_sign(x) < 0)))\n"
        "#define puchi_exact_positivep(x) (puchi_fixnump(x) ? (puchi_unbox_fixnum(x) > 0) \\\n"
        "                                 : ((SEXP_USE_BIGNUMS && puchi_bignump(x)) \\\n"
        "                                    && (puchi_bignum_sign(x) > 0)))\n"
    )
    new_neg_puchi = (
        "#if defined(PUCHI_ENABLE_NUMERICAL_TOWER)\n"
        "#define puchi_exact_negativep(x) (puchi_fixnump(x) ? (puchi_unbox_fixnum(x) < 0) \\\n"
        "                                 : (puchi_bignump(x) && (puchi_bignum_sign(x) < 0)))\n"
        "#define puchi_exact_positivep(x) (puchi_fixnump(x) ? (puchi_unbox_fixnum(x) > 0) \\\n"
        "                                 : (puchi_bignump(x) && (puchi_bignum_sign(x) > 0)))\n"
        "#else\n"
        "#define puchi_exact_negativep(x) (puchi_fixnump(x) && (puchi_unbox_fixnum(x) < 0))\n"
        "#define puchi_exact_positivep(x) (puchi_fixnump(x) && (puchi_unbox_fixnum(x) > 0))\n"
        "#endif\n"
    )
    old_neg = (
        "#define sexp_exact_negativep(x) (sexp_fixnump(x) ? (sexp_unbox_fixnum(x) < 0) \\\n"
        "                                 : ((SEXP_USE_BIGNUMS && sexp_bignump(x)) \\\n"
        "                                    && (sexp_bignum_sign(x) < 0)))\n"
        "#define sexp_exact_positivep(x) (sexp_fixnump(x) ? (sexp_unbox_fixnum(x) > 0) \\\n"
        "                                 : ((SEXP_USE_BIGNUMS && sexp_bignump(x)) \\\n"
        "                                    && (sexp_bignum_sign(x) > 0)))\n"
    )
    new_neg = (
        "#if defined(PUCHI_ENABLE_NUMERICAL_TOWER)\n"
        "#define sexp_exact_negativep(x) (sexp_fixnump(x) ? (sexp_unbox_fixnum(x) < 0) \\\n"
        "                                 : (sexp_bignump(x) && (sexp_bignum_sign(x) < 0)))\n"
        "#define sexp_exact_positivep(x) (sexp_fixnump(x) ? (sexp_unbox_fixnum(x) > 0) \\\n"
        "                                 : (sexp_bignump(x) && (sexp_bignum_sign(x) > 0)))\n"
        "#else\n"
        "#define sexp_exact_negativep(x) (sexp_fixnump(x) && (sexp_unbox_fixnum(x) < 0))\n"
        "#define sexp_exact_positivep(x) (sexp_fixnump(x) && (sexp_unbox_fixnum(x) > 0))\n"
        "#endif\n"
    )
    if old_neg_puchi in src:
        src = src.replace(old_neg_puchi, new_neg_puchi, 1)
    elif old_neg in src:
        src = src.replace(old_neg, new_neg, 1)
    else:
        raise SystemExit("fix_sexp_use_c_rvalues: exact_negativep/positivep not found")

    # packed-string C rvalues (flag is always 0 → !flag is 1)
    src = src.replace(
        "sexp_port_binaryp(p) && !SEXP_USE_PACKED_STRINGS ?",
        "sexp_port_binaryp(p) ?",
    )
    src = src.replace(
        "!sexp_port_binaryp(p) && !SEXP_USE_PACKED_STRINGS",
        "!sexp_port_binaryp(p)",
    )

    # read_symbol infinity intern flag
    old_rs = "res = sexp_read_symbol(ctx, in, c1, !SEXP_USE_INFINITIES);"
    new_rs = (
        "#if defined(PUCHI_INTEGER_ONLY)\n"
        "      res = sexp_read_symbol(ctx, in, c1, 1);\n"
        "#else\n"
        "      res = sexp_read_symbol(ctx, in, c1, 0);\n"
        "#endif"
    )
    if old_rs not in src:
        raise SystemExit("fix_sexp_use_c_rvalues: sexp_read_symbol INFINITIES call not found")
    src = src.replace(old_rs, new_rs, 1)

    # Any remaining bare always-0 / always-1 as C tokens on non-directive lines
    lines = src.splitlines(keepends=True)
    out = []
    for line in lines:
        s = line.lstrip()
        if s.startswith("#"):
            out.append(line)
            continue
        for name in sorted(ALWAYS_ZERO_STRIP, key=len, reverse=True):
            line = re.sub(rf"\b{name}\b", "0", line)
        for name in sorted(ALWAYS_ONE_STRIP, key=len, reverse=True):
            line = re.sub(rf"\b{name}\b", "1", line)
        out.append(line)
    return "".join(out)


def scrub_sexp_use_defines(src: str) -> str:
    """Remove every remaining #define / #undef of SEXP_USE_*."""
    lines = src.splitlines(keepends=True)
    out = []
    for line in lines:
        s = line.lstrip()
        if re.match(r"#\s*define\s+SEXP_USE_", s) or re.match(r"#\s*undef\s+SEXP_USE_", s):
            continue
        out.append(line)
    src = "".join(out)
    # Collapse empty #if … #endif left after define scrub inside live regions.
    prev = None
    while prev != src:
        prev = src
        src = re.sub(
            r"#if[^\n]*\n(?:\s*\n)*#endif\n",
            "",
            src,
        )
    return src


def scrub_sexp_use_comments(src: str) -> str:
    """Rewrite comments that still mention SEXP_USE_* so the assert can pass."""
    src = src.replace(
        "Chibi's 'uncomment to #define SEXP_USE_*' notes",
        "Chibi's 'uncomment to #define feature' notes",
    )
    src = src.replace(
        "(do not set SEXP_USE_FLONUMS/BIGNUMS by hand).",
        "(set at most one of PUCHI_INTEGER_ONLY / PUCHI_ENABLE_NUMERICAL_TOWER).",
    )
    src = src.replace(
        "/* ---- bignum.h (amalgamated; active only if SEXP_USE_BIGNUMS) ---- */",
        "/* ---- bignum.h (amalgamated; active only under PUCHI_ENABLE_NUMERICAL_TOWER) ---- */",
    )
    src = src.replace(
        "/* ==== bignum.c (active only if PUCHI_ENABLE_NUMERICAL_TOWER / SEXP_USE_BIGNUMS) ==== */",
        "/* ==== bignum.c (active only if PUCHI_ENABLE_NUMERICAL_TOWER) ==== */",
    )
    src = src.replace(
        "/* puchi: always portable 128-bit limb pair (SEXP_USE_CUSTOM_LONG_LONGS) */",
        "/* puchi: always portable 128-bit limb pair */",
    )
    src = src.replace(
        "OS/debug backends listed in ALWAYS_ZERO_STRIP are deleted by\n"
        " * strip-dead-backends (puchi_amalgamate_helpers.py). Do not re-enable them.\n",
        "Feature toggles are folded out of this header by amalgamate.\n",
    )
    # Catch-all: blank any remaining SEXP_USE_ in comments
    def _blank_in_comment(m: re.Match[str]) -> str:
        return m.group(0).replace("SEXP_USE_", "FEATURE_")

    src = re.sub(r"/\*.*?\*/", _blank_in_comment, src, flags=re.DOTALL)
    src = re.sub(r"//.*?$", _blank_in_comment, src, flags=re.MULTILINE)
    return src


def assert_no_sexp_use(src: str) -> None:
    if "SEXP_USE_" in src:
        # Show a few contexts
        hits = []
        for i, line in enumerate(src.splitlines(), 1):
            if "SEXP_USE_" in line:
                hits.append(f"  {i}: {line[:120]}")
                if len(hits) >= 12:
                    break
        raise SystemExit(
            "puchi.h still contains SEXP_USE_:\n" + "\n".join(hits)
        )


def _self_test_fold() -> None:
    assert _pp_eval("SEXP_USE_DL").const == 0
    assert _pp_eval("SEXP_USE_UTF8_STRINGS").const == 1
    assert _pp_eval("!SEXP_USE_CUSTOM_LONG_LONGS").const == 0
    assert _pp_eval("SEXP_USE_HUFF_SYMS").const == 0
    v = _pp_eval("SEXP_USE_FLONUMS && !SEXP_USE_BIGNUMS")
    assert v.const is None
    assert v.render() == (
        "!defined(PUCHI_INTEGER_ONLY) && !defined(PUCHI_ENABLE_NUMERICAL_TOWER)"
    )
    v = _pp_eval("!SEXP_USE_FLONUMS")
    assert v.render() == "defined(PUCHI_INTEGER_ONLY)"
    v = _pp_eval("SEXP_USE_FLONUMS || SEXP_USE_BIGNUMS")
    assert v.render() == "!defined(PUCHI_INTEGER_ONLY)"
    v = _pp_eval("SEXP_USE_RATIOS || !SEXP_USE_FLONUMS")
    assert v.render() == (
        "defined(PUCHI_ENABLE_NUMERICAL_TOWER) || defined(PUCHI_INTEGER_ONLY)"
    )
    assert _cond("ifndef", "SEXP_USE_UTF8_STRINGS").const == 0
    assert _cond("ifdef", "SEXP_USE_INTTYPES").const == 0
    assert _pp_eval("defined(SEXP_USE_INTTYPES)").const == 0
    assert _cond("if", "SEXP_USE_STATIC_LIBS").render() == "defined(PUCHI_TEST)"

    src = (
        "#ifndef SEXP_USE_UTF8_STRINGS\n"
        "#define SEXP_USE_UTF8_STRINGS 1\n"
        "#endif\n"
        "#if SEXP_USE_UTF8_STRINGS\n"
        "keep_utf8\n"
        "#else\n"
        "drop_utf8\n"
        "#endif\n"
        "#if SEXP_USE_HUFF_SYMS\n"
        "drop_huff\n"
        "#endif\n"
        "#if SEXP_USE_FLONUMS && !SEXP_USE_BIGNUMS\n"
        "default_mode\n"
        "#endif\n"
        "#if SEXP_USE_STATIC_LIBS\n"
        "test_static\n"
        "#endif\n"
        "#define SEXP_USE_BIGNUMS 1\n"
    )
    out = strip_dead_backends(src, _tested=True)
    assert "keep_utf8" in out and "drop_utf8" not in out
    assert "drop_huff" not in out
    assert "#if !defined(PUCHI_INTEGER_ONLY) && !defined(PUCHI_ENABLE_NUMERICAL_TOWER)" in out
    assert "default_mode" in out
    assert "#if defined(PUCHI_TEST)" in out and "test_static" in out
    assert "#define SEXP_USE_UTF8_STRINGS" not in out
    # define still present until scrub
    assert "#define SEXP_USE_BIGNUMS 1" in out
    out2 = scrub_sexp_use_defines(out)
    assert "SEXP_USE_" not in out2
    assert "keep_utf8" in out2
