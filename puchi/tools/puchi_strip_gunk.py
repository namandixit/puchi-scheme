"""Extra strip passes for sandboxed puchi amalgamation (plan: strip dead gunk)."""
from __future__ import annotations

import re

from puchi_host_embed import ALWAYS_ZERO_STRIP

DEAD_KNOB_BLOCKS = [
    r"#if !defined\(SEXP_DEFAULT_QUANTUM\)\n#define SEXP_DEFAULT_QUANTUM 500\n#endif\n",
    r"#ifndef SEXP_DEFAULT_QUANTUM\n#define SEXP_DEFAULT_QUANTUM 500\n#endif\n",
    r"#if !defined\(SEXP_POLL_SLEEP_TIME\)\n#define SEXP_POLL_SLEEP_TIME 5000\n#define SEXP_POLL_SLEEP_TIME_MS 5\n#endif\n",
    r"#ifndef SEXP_POLL_SLEEP_TIME\n#define SEXP_POLL_SLEEP_TIME 5000\n#define SEXP_POLL_SLEEP_TIME_MS 5\n#endif\n",
    r"#if !defined\(SEXP_ALLOC_HISTOGRAM_BUCKETS\)\n#define SEXP_ALLOC_HISTOGRAM_BUCKETS 32\n#endif\n",
    r"#ifndef SEXP_ALLOC_HISTOGRAM_BUCKETS\n#define SEXP_ALLOC_HISTOGRAM_BUCKETS 32\n#endif\n",
    r"#if !defined\(SEXP_BACKTRACE_SIZE\)\n#define SEXP_BACKTRACE_SIZE 3\n#endif\n",
    r"#ifndef SEXP_BACKTRACE_SIZE\n#define SEXP_BACKTRACE_SIZE 3\n#endif\n",
    r"#if !defined\(SEXP_STRING_INDEX_TABLE_CHUNK_SIZE\)\n#define SEXP_STRING_INDEX_TABLE_CHUNK_SIZE 64\n#endif\n",
    r"#ifndef SEXP_STRING_INDEX_TABLE_CHUNK_SIZE\n#define SEXP_STRING_INDEX_TABLE_CHUNK_SIZE 64\n#endif\n",
    r"#if !defined\(sexp_default_user_module_path\)\n#define sexp_default_user_module_path \"./lib:.\"\n#endif\n",
    r"#ifndef sexp_default_user_module_path\n#define sexp_default_user_module_path \"./lib:.\"\n#endif\n",
]


def scrub_dead_feature_knobs(features_h: str) -> str:
    """Remove unused Chibi config knobs from amalgamated features.h."""
    for pat in DEAD_KNOB_BLOCKS:
        features_h = re.sub(pat, "", features_h)
    # OS detection nest only fed *features* / TIME_GC — force portable zeros.
    bsd_start = features_h.find("#if defined(__APPLE__) || defined(__FreeBSD__)")
    if bsd_start < 0:
        bsd_start = features_h.find("#if (((defined(__APPLE__)")
    if bsd_start >= 0:
        marker = "/* Detect specific BSD */\n"
        mid = features_h.find(marker, bsd_start)
        if mid < 0:
            raise SystemExit("BSD detect marker not found in features.h")
        # End of nested #if SEXP_BSD ... #endif after the specific-BSD block
        rest = features_h[mid + len(marker) :]
        if not rest.lstrip().startswith("#if SEXP_BSD"):
            raise SystemExit("expected #if SEXP_BSD after detect marker")
        # Find matching endif for #if SEXP_BSD (depth starting at 1)
        depth = 0
        i = 0
        lines = rest.splitlines(keepends=True)
        end_i = None
        for j, line in enumerate(lines):
            if re.match(r"\s*#\s*if(n?def)?\b", line):
                depth += 1
            elif re.match(r"\s*#\s*endif\b", line):
                depth -= 1
                if depth == 0:
                    end_i = j
                    break
        if end_i is None:
            raise SystemExit("unclosed #if SEXP_BSD in features.h")
        end = mid + len(marker) + sum(len(lines[k]) for k in range(end_i + 1))
        repl = (
            "/* puchi: no host-OS feature probe; platform is \"puchi\"/\"portable\" */\n"
            "#define SEXP_BSD 0\n"
            "#define SEXP_DARWIN 0\n"
            "#define SEXP_FREEBSD 0\n"
            "#define SEXP_NETBSD 0\n"
            "#define SEXP_DRAGONFLY 0\n"
            "#define SEXP_OPENBSD 0\n"
        )
        features_h = features_h[:bsd_start] + repl + features_h[end:]
    # Epoch offset block (two variants inside #ifndef)
    features_h = re.sub(
        r"#if !defined\(SEXP_EPOCH_OFFSET\)\n"
        r"(?:#if[^\n]+\n#define SEXP_EPOCH_OFFSET [^\n]+\n#else\n)?#define SEXP_EPOCH_OFFSET [^\n]+\n"
        r"(?:#endif\n)?#endif\n",
        "",
        features_h,
    )
    features_h = re.sub(
        r"#ifndef SEXP_EPOCH_OFFSET\n"
        r"(?:#if[^\n]+\n#define SEXP_EPOCH_OFFSET [^\n]+\n#else\n)?#define SEXP_EPOCH_OFFSET [^\n]+\n"
        r"(?:#endif\n)?#endif\n",
        "",
        features_h,
    )
    features_h = features_h.replace(
        "/*         DEFAULTS - DO NOT MODIFY ANYTHING BELOW THIS LINE            */\n",
        "/* puchi: defaults (dead OS backends stripped by amalgamate) */\n",
    )
    # CHIBI env var names — often near module path
    features_h = re.sub(
        r"#if !defined\(SEXP_MODULE_PATH_VAR\)\n#define SEXP_MODULE_PATH_VAR \"[^\"]+\"\n#endif\n",
        "",
        features_h,
    )
    features_h = re.sub(
        r"#ifndef SEXP_MODULE_PATH_VAR\n#define SEXP_MODULE_PATH_VAR \"[^\"]+\"\n#endif\n",
        "",
        features_h,
    )
    features_h = re.sub(
        r"#if !defined\(SEXP_NO_SYSTEM_PATH_VAR\)\n#define SEXP_NO_SYSTEM_PATH_VAR \"[^\"]+\"\n#endif\n",
        "",
        features_h,
    )
    features_h = re.sub(
        r"#ifndef SEXP_NO_SYSTEM_PATH_VAR\n#define SEXP_NO_SYSTEM_PATH_VAR \"[^\"]+\"\n#endif\n",
        "",
        features_h,
    )
    return features_h


def scrub_sexp_h_gunk(sexp_h: str) -> str:
    """Remove DL union, green-thread context fields, orphan globals, epoch macros."""
    sexp_h = sexp_h.replace(
        '#define SEXP_MODULE_PATH_VAR "CHIBI_MODULE_PATH"\n'
        '#define SEXP_NO_SYSTEM_PATH_VAR "CHIBI_IGNORE_SYSTEM_PATH"\n',
        "/* puchi: no CHIBI_* getenv names */\n",
    )
    # Banner already includes stdint.h (also covers bignum CUSTOM_LONG_LONGS).
    sexp_h = sexp_h.replace("#include <stdint.h>\n", "/* puchi: stdint.h in banner */\n")
    sexp_h = sexp_h.replace("# include <stdint.h>\n", "/* puchi: stdint.h in banner */\n")
    # Immediate ABI sentinel: harness clibs only (core dlopen arms are stripped).
    sexp_h = sexp_h.replace(
        "#define SEXP_ABI_ERROR    SEXP_MAKE_IMMEDIATE(11) /* internal use */\n",
        "#if defined(PUCHI_TEST)\n"
        "#define SEXP_ABI_ERROR    SEXP_MAKE_IMMEDIATE(11) /* internal use */\n"
        "#endif\n",
    )
    # DL union arm
    sexp_h = re.sub(
        r"    struct \{\n"
        r"      sexp file;\n"
        r"      void\* handle;\n"
        r"    \} dl;\n",
        "    /* puchi: SEXP_DL removed */\n",
        sexp_h,
        count=1,
    )
    sexp_h = re.sub(
        r"#define sexp_dlp\(x\)\s+\(sexp_check_tag\(x, SEXP_DL\)\)\n",
        "",
        sexp_h,
    )
    sexp_h = re.sub(
        r"#define sexp_dl_file\(x\)\s+\(sexp_field\(x, dl, SEXP_DL, file\)\)\n",
        "",
        sexp_h,
    )
    sexp_h = re.sub(
        r"#define sexp_dl_handle\(x\)\s+\(sexp_field\(x, dl, SEXP_DL, handle\)\)\n",
        "",
        sexp_h,
    )
    sexp_h = re.sub(
        r"#if SEXP_USE_DL\n"
        r"#define SEXP_FINALIZE_DL[^\n]+\n"
        r"#define SEXP_FINALIZE_DLN[^\n]+\n"
        r"#else\n"
        r"#define SEXP_FINALIZE_DL NULL\n"
        r"#define SEXP_FINALIZE_DLN NULL\n"
        r"#endif\n",
        "",
        sexp_h,
    )
    sexp_h = re.sub(
        r"#define SEXP_FINALIZE_DL NULL\n"
        r"#define SEXP_FINALIZE_DLN NULL\n",
        "",
        sexp_h,
    )

    # Context: drop green-thread wait/timeout/event; keep interruptp for
    # harness chibi/ast.c (PUCHI_TEST). Production gets a dummy non-lvalue.
    sexp_h = sexp_h.replace(
        "        globals, dk, params, proc, name, specific, event, result;\n",
        "        globals, dk, params, proc, name, specific, result;\n",
    )
    sexp_h = sexp_h.replace(
        "      char tailp, tracep, timeoutp, waitp, errorp, interruptp;\n",
        "      char tailp, tracep, errorp;\n"
        "#if defined(PUCHI_TEST)\n"
        "      char interruptp;\n"
        "#endif\n",
    )
    for mac in (
        r"#define sexp_context_timeoutp\(x\)[^\n]+\n",
        r"#define sexp_context_waitp\(x\)[^\n]+\n",
        r"#define sexp_context_event\(x\)[^\n]+\n",
    ):
        sexp_h = re.sub(mac, "", sexp_h)
    sexp_h = re.sub(
        r"#define sexp_context_interruptp\(x\)[^\n]+\n",
        "#if defined(PUCHI_TEST)\n"
        "#define sexp_context_interruptp(x) (sexp_field(x, context, SEXP_CONTEXT, interruptp))\n"
        "#endif\n",
        sexp_h,
    )

    # Orphan globals — ABI_ERROR only for harness (scheme/time.c).
    for line in (
        "  SEXP_G_INTERRUPT_ERROR,       /* C-c in the repl */\n",
        "  SEXP_G_SIGNAL_HANDLERS,\n",
        "  SEXP_G_RANDOM_SOURCE,\n",
    ):
        sexp_h = sexp_h.replace(line, "")
    sexp_h = sexp_h.replace(
        "  SEXP_G_ABI_ERROR,             /* incompatible ABI loading library */\n",
        "#if defined(PUCHI_TEST)\n"
        "  SEXP_G_ABI_ERROR,             /* incompatible ABI loading library */\n"
        "#endif\n",
    )
    # FILE_DESCRIPTORS under weak — remove even when weak is on
    sexp_h = re.sub(
        r"  SEXP_G_WEAK_OBJECTS_PRESENT,\n"
        r"  SEXP_G_FILE_DESCRIPTORS,\n"
        r"  SEXP_G_NUM_FILE_DESCRIPTORS,\n",
        "  SEXP_G_WEAK_OBJECTS_PRESENT,\n",
        sexp_h,
    )

    # Epoch macros → identity, harness-only (io/filesystem call them)
    epoch_id = (
        "#if defined(PUCHI_TEST)\n"
        "#define sexp_shift_epoch(x) (x)\n"
        "#define sexp_unshift_epoch(x) (x)\n"
        "#endif\n"
    )
    sexp_h = re.sub(
        r"#define sexp_shift_epoch\(x\)[^\n]+\n"
        r"#define sexp_unshift_epoch\(x\)[^\n]+\n",
        epoch_id,
        sexp_h,
    )
    if "sexp_shift_epoch" not in sexp_h:
        pass
    elif "#if defined(PUCHI_TEST)\n#define sexp_shift_epoch" not in sexp_h:
        sexp_h = re.sub(
            r"#define sexp_shift_epoch\(x\)[^\n]+\n",
            "#if defined(PUCHI_TEST)\n#define sexp_shift_epoch(x) (x)\n",
            sexp_h,
            count=1,
        )
        sexp_h = re.sub(
            r"#define sexp_unshift_epoch\(x\)[^\n]+\n",
            "#define sexp_unshift_epoch(x) (x)\n#endif\n",
            sexp_h,
            count=1,
        )

    # Fold type-spec ALWAYS_ZERO arithmetic (C, not preprocessor)
    sexp_h = sexp_h.replace(
        "1+SEXP_USE_STRING_INDEX_TABLE",
        "1",
    )
    sexp_h = sexp_h.replace(
        "3+(SEXP_USE_STABLE_ABI||SEXP_USE_RENAME_BINDINGS)",
        "3+(SEXP_USE_RENAME_BINDINGS)",
    )
    sexp_h = sexp_h.replace(
        "12+(SEXP_USE_STABLE_ABI||SEXP_USE_DL)",
        "12",
    )
    return sexp_h


def scrub_eval_h_gunk(eval_h: str) -> str:
    eval_h = re.sub(
        r"#define sexp_init_file \"init-\"\n"
        r"#define sexp_init_file_suffix \"\.scm\"\n"
        r"#define sexp_meta_file \"meta-7\.scm\"\n"
        r"#define sexp_leap_seconds_file \"leap\.txt\"\n",
        "/* puchi: no disk init/meta/leap file names in core */\n",
        eval_h,
    )
    return eval_h


def scrub_sexp_c_gunk(sexp_c: str) -> str:
    # Features list: drop OS probes; brand puchi
    old_feat = """static const char* sexp_initial_features[] = {
#ifdef sexp_architecture
  sexp_architecture,
#endif
#ifdef sexp_platform
  sexp_platform,
#endif
#if SEXP_BSD
  "bsd",
#endif
#if SEXP_DARWIN
  "darwin",
#endif
#if SEXP_OPENBSD
  "openbsd",
#endif
#if SEXP_FREEBSD
  "freebsd",
#endif
#if SEXP_NETBSD
  "netbsd",
#endif
#if SEXP_DRAGONFLY
  "dragonfly",
#endif
#if defined(_WIN32)
  "windows",
#endif
#if SEXP_USE_DL
  "dynamic-loading",
#endif
#if SEXP_USE_BIDIRECTIONAL_PORTS
  "bidir-ports",
#endif
#if SEXP_USE_MODULES
  "modules",
#endif
#if SEXP_USE_BOEHM
  "boehm-gc",
#endif
#if SEXP_USE_UTF8_STRINGS
  "full-unicode",
#endif
#if SEXP_USE_STRING_INDEX_TABLE
  "string-index",
#endif
#if SEXP_USE_STRING_REF_CACHE
  "string-ref-cache",
#endif
#if SEXP_USE_GREEN_THREADS
  "threads",
#endif
#if SEXP_USE_NTP_GETTIME
  "ntp",
#endif
#if SEXP_USE_AUTO_FORCE
  "auto-force",
#endif
#if SEXP_USE_UNIFORM_VECTOR_LITERALS
  "uvector",
#endif
#if SEXP_USE_MINI_FLOAT_UNIFORM_VECTORS
  "mini-float",
#endif
#if SEXP_USE_COMPLEX
  "complex",
#endif
#if SEXP_USE_RATIOS
  "ratios",
#endif
  "r7rs",
  "chibi-" sexp_version,
  "chibi",
  NULL,
};
"""
    new_feat = """static const char* sexp_initial_features[] = {
#ifdef sexp_architecture
  sexp_architecture,
#endif
#ifdef sexp_platform
  sexp_platform,
#endif
#if SEXP_USE_MODULES
  "modules",
#endif
#if SEXP_USE_UTF8_STRINGS
  "full-unicode",
#endif
#if SEXP_USE_UNIFORM_VECTOR_LITERALS
  "uvector",
#endif
#if SEXP_USE_MINI_FLOAT_UNIFORM_VECTORS
  "mini-float",
#endif
#if SEXP_USE_COMPLEX
  "complex",
#endif
#if SEXP_USE_RATIOS
  "ratios",
#endif
  "r7rs",
  "puchi-" sexp_version,
  "puchi",
  NULL,
};
"""
    if old_feat in sexp_c:
        sexp_c = sexp_c.replace(old_feat, new_feat, 1)
    else:
        # Fall back: just rebrand chibi strings
        sexp_c = sexp_c.replace('"chibi-" sexp_version', '"puchi-" sexp_version')
        sexp_c = sexp_c.replace('\n  "chibi",\n', '\n  "puchi",\n')

    sexp_c = sexp_c.replace(
        '  sexp_global(ctx, SEXP_G_INTERRUPT_ERROR) = sexp_user_exception(ctx, SEXP_FALSE, "interrupt", SEXP_NULL);\n',
        "",
    )
    sexp_c = sexp_c.replace(
        '  sexp_global(ctx, SEXP_G_ABI_ERROR) = sexp_user_exception(ctx, SEXP_FALSE, "incompatible ABI", SEXP_NULL);\n',
        "#if defined(PUCHI_TEST)\n"
        '  sexp_global(ctx, SEXP_G_ABI_ERROR) = sexp_user_exception(ctx, SEXP_FALSE, "incompatible ABI", SEXP_NULL);\n'
        "#endif\n",
    )
    sexp_c = sexp_c.replace(
        "  sexp_global(ctx, SEXP_G_FILE_DESCRIPTORS) = SEXP_FALSE;\n",
        "",
    )
    sexp_c = re.sub(
        r"  sexp_global\(ctx, SEXP_G_NUM_FILE_DESCRIPTORS\) =[^\n]+\n",
        "",
        sexp_c,
    )
    sexp_c = sexp_c.replace("  sexp_context_timeoutp(res) = 0;\n", "")
    sexp_c = sexp_c.replace("  sexp_context_waitp(res) = 0;\n", "")
    sexp_c = sexp_c.replace("  sexp_context_interruptp(res) = 0;\n", "")
    sexp_c = sexp_c.replace("  sexp_context_event(res) = SEXP_FALSE;\n", "")

    # Fold residual ALWAYS_ZERO C exprs
    sexp_c = sexp_c.replace("1+SEXP_USE_STRING_INDEX_TABLE", "1")
    sexp_c = sexp_c.replace(
        "3+(SEXP_USE_STABLE_ABI||SEXP_USE_RENAME_BINDINGS)",
        "3+(SEXP_USE_RENAME_BINDINGS)",
    )
    sexp_c = sexp_c.replace("12+(SEXP_USE_STABLE_ABI||SEXP_USE_DL)", "12")
    return sexp_c


def scrub_eval_c_disk_boot(eval_c: str) -> str:
    """Empty module path; fix find_module; diskless load_standard_env."""
    # init globals — leave MODULE_PATH null
    old_init = """void sexp_init_eval_context_globals (sexp ctx) {
  const char* no_sys_path;
  const char* user_path;
  ctx = sexp_make_child_context(ctx, NULL);
#if ! SEXP_USE_NATIVE_X86
  sexp_init_eval_context_bytecodes(ctx);
#endif
  sexp_global(ctx, SEXP_G_MODULE_PATH) = SEXP_NULL;
  user_path = getenv(SEXP_MODULE_PATH_VAR);
  if (!user_path) user_path = sexp_default_user_module_path;
  sexp_add_path(ctx, user_path);
  no_sys_path = getenv(SEXP_NO_SYSTEM_PATH_VAR);
  if (!no_sys_path || strcmp(no_sys_path, "0")==0)
    sexp_add_path(ctx, sexp_default_module_path);
#if SEXP_USE_GREEN_THREADS
  sexp_global(ctx, SEXP_G_IO_BLOCK_ERROR)
    = sexp_user_exception(ctx, SEXP_FALSE, "I/O would block", SEXP_NULL);
  sexp_global(ctx, SEXP_G_IO_BLOCK_ONCE_ERROR)
    = sexp_user_exception(ctx, SEXP_FALSE, "I/O would block once", SEXP_NULL);
  sexp_global(ctx, SEXP_G_THREAD_TERMINATE_ERROR)
    = sexp_user_exception(ctx, SEXP_FALSE, "thread terminated", SEXP_NULL);
  sexp_global(ctx, SEXP_G_THREADS_FRONT) = SEXP_NULL;
  sexp_global(ctx, SEXP_G_THREADS_BACK) = SEXP_NULL;
  sexp_global(ctx, SEXP_G_THREADS_SIGNALS) = SEXP_ZERO;
  sexp_global(ctx, SEXP_G_THREADS_SIGNAL_RUNNER) = SEXP_FALSE;
  sexp_global(ctx, SEXP_G_ATOMIC_P) = SEXP_FALSE;
#endif
}
"""
    # After earlier patches getenv is already stubbed — match both forms
    new_init = """void sexp_init_eval_context_globals (sexp ctx) {
  ctx = sexp_make_child_context(ctx, NULL);
  sexp_init_eval_context_bytecodes(ctx);
  /* Host/harness fills module path via add-module-directory foreigns. */
  sexp_global(ctx, SEXP_G_MODULE_PATH) = SEXP_NULL;
}
"""
    if old_init in eval_c:
        eval_c = eval_c.replace(old_init, new_init, 1)
    else:
        # Already partially patched by stub_file_ops
        patched = """void sexp_init_eval_context_globals (sexp ctx) {
  const char* no_sys_path;
  const char* user_path;
  ctx = sexp_make_child_context(ctx, NULL);
  sexp_init_eval_context_bytecodes(ctx);
  sexp_global(ctx, SEXP_G_MODULE_PATH) = SEXP_NULL;
  user_path = NULL; /* puchi: no getenv */
  if (!user_path) user_path = sexp_default_user_module_path;
  sexp_add_path(ctx, user_path);
  no_sys_path = (char*)"1"; /* puchi: never use system module path */
  if (!no_sys_path || PUCHI_STRCMP(no_sys_path, "0")==0)
    sexp_add_path(ctx, sexp_default_module_path);
}
"""
        if patched in eval_c:
            eval_c = eval_c.replace(patched, new_init, 1)
        else:
            # Broader regex fallback
            eval_c = re.sub(
                r"void sexp_init_eval_context_globals \(sexp ctx\) \{.*?\n\}\n",
                new_init,
                eval_c,
                count=1,
                flags=re.DOTALL,
            )

    # find_module_file — FALSE on NULL (raw already stubbed to NULL by helpers)
    eval_c = re.sub(
        r"sexp sexp_find_module_file \(sexp ctx, const char \*file\) \{\n"
        r"  char\* path = sexp_find_module_file_raw\(ctx, file\);\n"
        r"  sexp res = sexp_c_string\(ctx, path, -1\);\n"
        r"(?:  if \(path\) (?:free|SEXP_FREE\(NULL, )path\);?\n)?"
        r"  return res;\n"
        r"\}",
        "sexp sexp_find_module_file (sexp ctx, const char *file) {\n"
        "  char* path = sexp_find_module_file_raw(ctx, file);\n"
        "  if (!path) return SEXP_FALSE;\n"
        "  return sexp_c_string(ctx, path, -1);\n"
        "}",
        eval_c,
        count=1,
    )

    # load_standard_env — embed via helper; no disk meta
    new_std = """sexp sexp_load_standard_env (sexp ctx, sexp e, sexp version) {
  sexp_gc_var3(op, tmp, sym);
  sexp_gc_preserve3(ctx, op, tmp, sym);
  (void)version;
  if (!e) e = sexp_context_env(ctx);
#if defined(PUCHI_TEST)
  sexp_env_define(ctx, e, sym=sexp_intern(ctx, "*shared-object-extension*", -1),
                  tmp=sexp_c_string(ctx, sexp_so_extension, -1));
#endif
  sexp_env_define(ctx, e, sym=sexp_intern(ctx, "*features*", -1), sexp_global(ctx, SEXP_G_FEATURES));
  sexp_global(ctx, SEXP_G_OPTIMIZATIONS) = SEXP_NULL;
#if SEXP_USE_SIMPLIFY
  op = sexp_make_foreign(ctx, "sexp_simplify", 1, 0,
                         NULL, (sexp_proc1)sexp_simplify, SEXP_VOID);
  tmp = sexp_cons(ctx, sexp_make_fixnum(500), op);
  sexp_push(ctx, sexp_global(ctx, SEXP_G_OPTIMIZATIONS), tmp);
#endif
  tmp = puchi_load_init7_into_env(ctx, e);
  if (sexp_exceptionp(tmp)) {
    sexp_gc_release3(ctx);
    return tmp;
  }
  sexp_global(ctx, SEXP_G_ERR_HANDLER)
    = sexp_env_ref(ctx, e, sym=sexp_intern(ctx, "current-exception-handler", -1), SEXP_FALSE);
  sexp_set_parameter(ctx, e, sexp_global(ctx, SEXP_G_INTERACTION_ENV_SYMBOL), e);
#if SEXP_USE_MODULES
  /* Host boots meta; splice import if already present. */
  tmp = sexp_global(ctx, SEXP_G_META_ENV);
  if (sexp_envp(tmp)) {
    sym = sexp_intern(ctx, "repl-import", -1);
    tmp = sexp_env_ref(ctx, tmp, sym, SEXP_VOID);
    if (tmp != SEXP_VOID) {
      sym = sexp_intern(ctx, "import", -1);
      tmp = sexp_cons(ctx, sym, tmp);
      sexp_env_next_cell(tmp) = sexp_env_next_cell(sexp_env_bindings(e));
      sexp_env_next_cell(sexp_env_bindings(e)) = tmp;
    }
  }
#endif
  sexp_gc_release3(ctx);
  return e;
}
"""
    eval_c = re.sub(
        r"sexp sexp_load_standard_env \(sexp ctx, sexp e, sexp version\) \{.*?\n  return sexp_exceptionp\(tmp\) \? tmp : e;\n\}",
        new_std.rstrip() + "\n",
        eval_c,
        count=1,
        flags=re.DOTALL,
    )

    # Residual ALWAYS_ZERO C
    eval_c = re.sub(
        r"  if \(SEXP_USE_FLAT_SYNTACTIC_CLOSURES && sexp_synclop\(expr\)\) \{.*?\n  \}\n",
        "",
        eval_c,
        count=1,
        flags=re.DOTALL,
    )
    eval_c = eval_c.replace(
        "    if (trailing_non_procs || !SEXP_USE_UNBOXED_LOCALS)",
        "    if (trailing_non_procs)",
    )
    return eval_c


def scrub_portable_poll_stubs(sexp_h: str) -> str:
    sexp_h = sexp_h.replace(
        "#define SEXP_USE_POLL_PORT 0\n"
        "#define sexp_poll_input(ctx, port) ((void)(ctx), (void)(port), 0)\n"
        "#define sexp_poll_output(ctx, port) ((void)(ctx), (void)(port), 0)\n\n",
        "",
    )
    return sexp_h


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
    # amalgamate.sh short forces
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
