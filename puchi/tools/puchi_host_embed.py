"""Host-owned embed surface patches for puchi amalgamation.

Applied by amalgamate.sh after the basic platform/file stubs. Documents and
enforces: CPU/memory only in core; host owns OS via puchi_host + stream_ops;
ALWAYS_ZERO_STRIP flags deleted by strip_dead_backends; libc only via PUCHI_*.
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
        # Always-off feature bodies (force 0 + delete)
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
        # No ABI freeze / no global heap-or-symbols tables in single-header embed
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


def features_force_extra() -> str:
    """Appended inside puchi_features_force.h after numeric modes.

    ALWAYS_ZERO_STRIP bodies are deleted by strip_dead_backends using the
    Python name set — they are not emitted as #define 0 into the ship file.
    """
    return (
        "\n"
        "/* OS/debug/ABI backends listed in ALWAYS_ZERO_STRIP are deleted from\n"
        " * this amalgamation by strip-dead-backends. Do not re-enable them.\n"
        " * STATIC_LIBS* stay #if-gated: off unless PUCHI_TEST (harness only). */\n"
        "\n"
        "/* Host testsuite may enable static include-shared tables. */\n"
        "#if defined(PUCHI_TEST)\n"
        "#ifndef SEXP_USE_STATIC_LIBS\n"
        "#define SEXP_USE_STATIC_LIBS 1\n"
        "#endif\n"
        "#ifndef SEXP_USE_STATIC_LIBS_EMPTY\n"
        "#define SEXP_USE_STATIC_LIBS_EMPTY 1\n"
        "#endif\n"
        "#else\n"
        "#undef SEXP_USE_STATIC_LIBS\n"
        "#define SEXP_USE_STATIC_LIBS 0\n"
        "#undef SEXP_USE_STATIC_LIBS_EMPTY\n"
        "#define SEXP_USE_STATIC_LIBS_EMPTY 0\n"
        "#endif\n"
        "\n"
    )


def patch_sexp_h_host(sexp_h: str) -> str:
    """Replace FILE* port surface with puchi_stream_ops; drop leftover stdio."""
    # Portable block already injected; remove any remaining #include <stdio.h>
    sexp_h = sexp_h.replace("#include <stdio.h>\n", "/* puchi: no stdio.h */\n")

    sexp_h = sexp_h.replace(
        "      FILE *stream;\n",
        "      const puchi_stream_ops *stream_ops;\n"
        "      void *stream_udata;\n",
    )

    sexp_h = sexp_h.replace(
        "#define sexp_stream_portp(x) (sexp_port_stream(x) != NULL)",
        "#define sexp_stream_portp(x) (sexp_port_stream_ops(x) != NULL)",
    )
    sexp_h = sexp_h.replace(
        "#define sexp_port_stream(p)     (sexp_pred_field(p, port, sexp_portp, stream))",
        "#define sexp_port_stream_ops(p)   (sexp_pred_field(p, port, sexp_portp, stream_ops))\n"
        "#define sexp_port_stream_udata(p) (sexp_pred_field(p, port, sexp_portp, stream_udata))\n"
        "/* truthy alias used by upstream conditions */\n"
        "#define sexp_port_stream(p)       sexp_port_stream_ops(p)",
    )

    old_macros = """#define sexp_read_char(x, p) (sexp_port_buf(p) ? ((sexp_port_offset(p) < sexp_port_size(p)) ? ((unsigned char*)sexp_port_buf(p))[sexp_port_offset(p)++] : sexp_buffered_read_char(x, p)) : getc(sexp_port_stream(p)))
#define sexp_push_char(x, c, p) ((c!=EOF) && (sexp_port_buf(p) ? (sexp_port_buf(p)[--sexp_port_offset(p)] = ((char)(c))) : ungetc(c, sexp_port_stream(p))))
#define sexp_write_char(x, c, p) (sexp_port_buf(p) ? ((sexp_port_offset(p) < sexp_port_size(p)) ? ((((sexp_port_buf(p))[sexp_port_offset(p)++]) = (char)(c)), 0) : sexp_buffered_write_char(x, c, p)) : putc(c, sexp_port_stream(p)))
#define sexp_write_string(x, s, p) (sexp_port_buf(p) ? sexp_buffered_write_string(x, s, p) : fputs(s, sexp_port_stream(p)))
#define sexp_write_string_n(x, s, n, p) (sexp_port_buf(p) ? sexp_buffered_write_string_n(x, s, n, p) : fwrite(s, 1, n, sexp_port_stream(p)))
#define sexp_flush(x, p) (sexp_port_buf(p) ? sexp_buffered_flush(x, p, 0) : fflush(sexp_port_stream(p)))
#define sexp_flush_forced(x, p) (sexp_port_buf(p) ? sexp_buffered_flush(x, p, 1) : fflush(sexp_port_stream(p)))
"""
    new_macros = """#define sexp_read_char(x, p) (sexp_port_buf(p) ? ((sexp_port_offset(p) < sexp_port_size(p)) ? ((unsigned char*)sexp_port_buf(p))[sexp_port_offset(p)++] : sexp_buffered_read_char(x, p)) : (sexp_port_stream_ops(p) && sexp_port_stream_ops(p)->read_char ? sexp_port_stream_ops(p)->read_char(sexp_port_stream_udata(p)) : EOF))
#define sexp_push_char(x, c, p) ((c!=EOF) && (sexp_port_buf(p) ? (sexp_port_buf(p)[--sexp_port_offset(p)] = ((char)(c))) : (sexp_port_stream_ops(p) && sexp_port_stream_ops(p)->unget_char ? sexp_port_stream_ops(p)->unget_char(sexp_port_stream_udata(p), c) : 0)))
#define sexp_write_char(x, c, p) (sexp_port_buf(p) ? ((sexp_port_offset(p) < sexp_port_size(p)) ? ((((sexp_port_buf(p))[sexp_port_offset(p)++]) = (char)(c)), 0) : sexp_buffered_write_char(x, c, p)) : (sexp_port_stream_ops(p) && sexp_port_stream_ops(p)->write_char ? sexp_port_stream_ops(p)->write_char(sexp_port_stream_udata(p), c) : -1))
#define sexp_write_string(x, s, p) (sexp_port_buf(p) ? sexp_buffered_write_string(x, s, p) : (sexp_port_stream_ops(p) && sexp_port_stream_ops(p)->write ? (int)sexp_port_stream_ops(p)->write(sexp_port_stream_udata(p), (const void*)(s), PUCHI_STRLEN(s)) : -1))
#define sexp_write_string_n(x, s, n, p) (sexp_port_buf(p) ? sexp_buffered_write_string_n(x, s, n, p) : (sexp_port_stream_ops(p) && sexp_port_stream_ops(p)->write ? sexp_port_stream_ops(p)->write(sexp_port_stream_udata(p), (const void*)(s), (size_t)(n)) : 0))
#define sexp_flush(x, p) (sexp_port_buf(p) ? sexp_buffered_flush(x, p, 0) : (sexp_port_stream_ops(p) && sexp_port_stream_ops(p)->flush ? sexp_port_stream_ops(p)->flush(sexp_port_stream_udata(p)) : 0))
#define sexp_flush_forced(x, p) (sexp_port_buf(p) ? sexp_buffered_flush(x, p, 1) : (sexp_port_stream_ops(p) && sexp_port_stream_ops(p)->flush ? sexp_port_stream_ops(p)->flush(sexp_port_stream_udata(p)) : 0))
"""
    if old_macros not in sexp_h:
        raise SystemExit("sexp.h I/O macros not found for host patch")
    sexp_h = sexp_h.replace(old_macros, new_macros)

    sexp_h = sexp_h.replace(
        "#define sexp_at_eofp(p)      (feof(sexp_port_stream(p)))",
        "#define sexp_at_eofp(p)      (sexp_port_stream_ops(p) && sexp_port_stream_ops(p)->eof_p ? sexp_port_stream_ops(p)->eof_p(sexp_port_stream_udata(p)) : 0)",
    )
    # ---- fileno / fd: harness only (PUCHI_TEST); absent from production embeds ----
    sexp_h = sexp_h.replace("  SEXP_FILENO,\n", "#if defined(PUCHI_TEST)\n  SEXP_FILENO,\n#endif\n")
    sexp_h = sexp_h.replace(
        "#define sexp_oportp(x)      (sexp_check_tag(x, SEXP_OPORT) || (sexp_check_tag(x, SEXP_IPORT) && sexp_port_bidirp(x)))",
        "#if defined(PUCHI_TEST)\n"
        "#define sexp_oportp(x)      (sexp_check_tag(x, SEXP_OPORT) || (sexp_check_tag(x, SEXP_IPORT) && sexp_port_bidirp(x)))\n"
        "#else\n"
        "#define sexp_oportp(x)      (sexp_check_tag(x, SEXP_OPORT))\n"
        "#endif",
    )
    sexp_h = sexp_h.replace(
        "#define sexp_filenop(x)     (sexp_check_tag(x, SEXP_FILENO))\n",
        "#if defined(PUCHI_TEST)\n"
        "#define sexp_filenop(x)     (sexp_check_tag(x, SEXP_FILENO))\n"
        "#endif\n",
    )
    # Port: fd / bidirp / shutdownp / blockedp only for harness
    sexp_h = re.sub(
        r"      sexp fd;\n",
        "#if defined(PUCHI_TEST)\n      sexp fd;\n#endif\n",
        sexp_h,
        count=1,
    )
    sexp_h = re.sub(
        r"      char openp, bidirp, binaryp, shutdownp, no_closep, sourcep,\n"
        r"        blockedp, fold_casep;\n",
        "      char openp,\n"
        "#if defined(PUCHI_TEST)\n"
        "        bidirp,\n"
        "#endif\n"
        "        binaryp,\n"
        "#if defined(PUCHI_TEST)\n"
        "        shutdownp,\n"
        "#endif\n"
        "        no_closep, sourcep,\n"
        "#if defined(PUCHI_TEST)\n"
        "        blockedp,\n"
        "#endif\n"
        "        fold_casep;\n",
        sexp_h,
        count=1,
    )
    sexp_h = re.sub(
        r"    struct \{\n"
        r"      char openp, no_closep;\n"
        r"      sexp_sint_t fd, count;\n"
        r"#ifdef _WIN32\s*\n"
        r"      SOCKET_TYPE sock;\n"
        r"#endif\s*\n"
        r"    \} fileno;\n",
        "#if defined(PUCHI_TEST)\n"
        "    struct {\n"
        "      char openp, no_closep;\n"
        "      sexp_sint_t fd, count;\n"
        "#ifdef _WIN32\n"
        "      SOCKET_TYPE sock;\n"
        "#endif\n"
        "    } fileno;\n"
        "#endif\n",
        sexp_h,
        count=1,
    )
    # Keep SOCKET_TYPE for harness Win32 fileno; production never uses it
    for macro, gated in (
        (
            "#define sexp_port_bidirp(p)     (sexp_pred_field(p, port, sexp_portp, bidirp))\n",
            True,
        ),
        (
            "#define sexp_port_shutdownp(p)  (sexp_pred_field(p, port, sexp_portp, shutdownp))\n",
            True,
        ),
        (
            "#define sexp_port_blockedp(p)   (sexp_pred_field(p, port, sexp_portp, blockedp))\n",
            True,
        ),
        (
            "#define sexp_port_fd(p)         (sexp_pred_field(p, port, sexp_portp, fd))\n",
            True,
        ),
        (
            "#define sexp_fileno_fd(f)        (sexp_pred_field(f, fileno, sexp_filenop, fd))\n",
            True,
        ),
        (
            "#define sexp_fileno_count(f)     (sexp_pred_field(f, fileno, sexp_filenop, count))\n",
            True,
        ),
        (
            "#define sexp_fileno_openp(f)     (sexp_pred_field(f, fileno, sexp_filenop, openp))\n",
            True,
        ),
        (
            "#define sexp_fileno_no_closep(f) (sexp_pred_field(f, fileno, sexp_filenop, no_closep))\n",
            True,
        ),
    ):
        if gated and macro in sexp_h:
            sexp_h = sexp_h.replace(
                macro, f"#if defined(PUCHI_TEST)\n{macro}#endif\n"
            )
    sexp_h = re.sub(
        r"#if defined\(_WIN32\)\n#define sexp_fileno_sock\(f\).*?\n#else\n#define sexp_fileno_sock\(f\).*?\n#endif\n",
        "#if defined(PUCHI_TEST)\n"
        "#ifdef _WIN32\n"
        "#define sexp_fileno_sock(f)      (sexp_pred_field(f, fileno, sexp_filenop, sock))\n"
        "#else\n"
        "#define sexp_fileno_sock(f)      (sexp_fileno_fd(f))\n"
        "#endif\n"
        "#endif\n",
        sexp_h,
        flags=re.DOTALL,
    )
    sexp_h = re.sub(
        r"#ifdef _WIN32\n#define sexp_fileno_sock\(f\).*?\n#else\n#define sexp_fileno_sock\(f\).*?\n#endif\n",
        "#if defined(PUCHI_TEST)\n"
        "#ifdef _WIN32\n"
        "#define sexp_fileno_sock(f)      (sexp_pred_field(f, fileno, sexp_filenop, sock))\n"
        "#else\n"
        "#define sexp_fileno_sock(f)      (sexp_fileno_fd(f))\n"
        "#endif\n"
        "#endif\n",
        sexp_h,
        flags=re.DOTALL,
    )
    # port_fileno / port_sock: harness may use; production has no fd
    sexp_h = sexp_h.replace(
        "#define sexp_port_fileno(p)  (sexp_port_stream(p) ? fileno(sexp_port_stream(p)) : sexp_filenop(sexp_port_fd(p)) ? sexp_fileno_fd(sexp_port_fd(p)) : -1)",
        "#if defined(PUCHI_TEST)\n"
        "#define sexp_port_fileno(p)  (sexp_filenop(sexp_port_fd(p)) ? sexp_fileno_fd(sexp_port_fd(p)) : -1)\n"
        "#else\n"
        "#define sexp_port_fileno(p)  (-1)\n"
        "#endif",
    )
    sexp_h = sexp_h.replace(
        "#define sexp_port_sock(p)  (sexp_port_stream(p) ? -1 : sexp_filenop(sexp_port_fd(p)) ? sexp_fileno_sock(sexp_port_fd(p)) : -1)",
        "#if defined(PUCHI_TEST)\n"
        "#define sexp_port_sock(p)  (sexp_filenop(sexp_port_fd(p)) ? sexp_fileno_sock(sexp_port_fd(p)) : -1)\n"
        "#else\n"
        "#define sexp_port_sock(p)  (-1)\n"
        "#endif",
    )
    # FINALIZE_FILENO: harness only (AUTOCLOSE strip leaves NULL — override after)
    sexp_h = re.sub(
        r"#if SEXP_USE_AUTOCLOSE_PORTS\n"
        r"#define SEXP_FINALIZE_PORT.*?\n"
        r"#define SEXP_FINALIZE_PORTN.*?\n"
        r"#define SEXP_FINALIZE_FILENO.*?\n"
        r"#define SEXP_FINALIZE_FILENON.*?\n"
        r"#else\n"
        r"#define SEXP_FINALIZE_PORT NULL\n"
        r"#define SEXP_FINALIZE_PORTN NULL\n"
        r"#define SEXP_FINALIZE_FILENO NULL\n"
        r"#define SEXP_FINALIZE_FILENON NULL\n"
        r"#endif\n",
        "#define SEXP_FINALIZE_PORT NULL\n"
        "#define SEXP_FINALIZE_PORTN NULL\n"
        "#if defined(PUCHI_TEST)\n"
        "#define SEXP_FINALIZE_FILENO sexp_finalize_fileno\n"
        '#define SEXP_FINALIZE_FILENON (sexp)"sexp_finalize_fileno"\n'
        "#else\n"
        "#define SEXP_FINALIZE_FILENO NULL\n"
        "#define SEXP_FINALIZE_FILENON NULL\n"
        "#endif\n",
        sexp_h,
        count=1,
    )
    sexp_h = sexp_h.replace(
        "SEXP_API sexp sexp_make_fileno_op (sexp ctx, sexp self, sexp_sint_t n, sexp fd, sexp no_closep);\n",
        "#if defined(PUCHI_TEST)\n"
        "SEXP_API sexp sexp_make_fileno_op (sexp ctx, sexp self, sexp_sint_t n, sexp fd, sexp no_closep);\n"
        "#endif\n",
    )
    sexp_h = sexp_h.replace(
        "SEXP_API sexp sexp_open_input_file_descriptor (sexp ctx, sexp self, sexp_sint_t n, sexp fileno, sexp socketp);\n",
        "#if defined(PUCHI_TEST)\n"
        "SEXP_API sexp sexp_open_input_file_descriptor (sexp ctx, sexp self, sexp_sint_t n, sexp fileno, sexp socketp);\n"
        "#endif\n",
    )
    sexp_h = sexp_h.replace(
        "SEXP_API sexp sexp_open_output_file_descriptor (sexp ctx, sexp self, sexp_sint_t n, sexp fileno, sexp socketp);\n",
        "#if defined(PUCHI_TEST)\n"
        "SEXP_API sexp sexp_open_output_file_descriptor (sexp ctx, sexp self, sexp_sint_t n, sexp fileno, sexp socketp);\n"
        "#endif\n",
    )
    sexp_h = sexp_h.replace(
        "#define sexp_make_fileno(ctx, fd, no_closep) sexp_make_fileno_op(ctx, NULL, 2, fd, no_closep)\n",
        "#if defined(PUCHI_TEST)\n"
        "#define sexp_make_fileno(ctx, fd, no_closep) sexp_make_fileno_op(ctx, NULL, 2, fd, no_closep)\n"
        "#endif\n",
    )
    # Static-lib init types only for harness (need abi_identifier_t)
    sexp_h = sexp_h.replace(
        "typedef sexp (*sexp_init_proc)(sexp, sexp, sexp_sint_t, sexp, const char*, const sexp_abi_identifier_t);\n"
        "SEXP_API sexp sexp_init_library(sexp, sexp, sexp_sint_t, sexp, const char*, const sexp_abi_identifier_t);\n",
        "#if defined(PUCHI_TEST)\n"
        "typedef sexp (*sexp_init_proc)(sexp, sexp, sexp_sint_t, sexp, const char*, const sexp_abi_identifier_t);\n"
        "SEXP_API sexp sexp_init_library(sexp, sexp, sexp_sint_t, sexp, const char*, const sexp_abi_identifier_t);\n"
        "#endif\n",
    )
    sexp_h = re.sub(
        r"struct sexp_library_entry_t \{.*?};\n",
        "#if defined(PUCHI_TEST)\n"
        "struct sexp_library_entry_t {   /* harness static include-shared */\n"
        "  const char *name;\n"
        "  sexp_init_proc init;\n"
        "};\n"
        "#endif\n",
        sexp_h,
        count=1,
        flags=re.DOTALL,
    )
    sexp_h = sexp_h.replace(
        "SEXP_API void sexp_add_static_libraries(struct sexp_library_entry_t* libraries);\n",
        "#if defined(PUCHI_TEST)\n"
        "SEXP_API void sexp_add_static_libraries(struct sexp_library_entry_t* libraries);\n"
        "#endif\n",
    )

    for old, new in (
        (
            "SEXP_API sexp sexp_make_input_port (sexp ctx, FILE* in, sexp name);",
            "SEXP_API sexp sexp_make_input_port (sexp ctx, const puchi_stream_ops *ops, void *udata, sexp name);",
        ),
        (
            "SEXP_API sexp sexp_make_output_port (sexp ctx, FILE* out, sexp name);",
            "SEXP_API sexp sexp_make_output_port (sexp ctx, const puchi_stream_ops *ops, void *udata, sexp name);",
        ),
        (
            "SEXP_API sexp sexp_make_non_null_input_port (sexp ctx, FILE* in, sexp name);",
            "SEXP_API sexp sexp_make_non_null_input_port (sexp ctx, const puchi_stream_ops *ops, void *udata, sexp name);",
        ),
        (
            "SEXP_API sexp sexp_make_non_null_output_port (sexp ctx, FILE* out, sexp name);",
            "SEXP_API sexp sexp_make_non_null_output_port (sexp ctx, const puchi_stream_ops *ops, void *udata, sexp name);",
        ),
        (
            "SEXP_API sexp sexp_make_non_null_input_output_port (sexp ctx, FILE* io, sexp name);",
            "SEXP_API sexp sexp_make_non_null_input_output_port (sexp ctx, const puchi_stream_ops *ops, void *udata, sexp name);",
        ),
    ):
        if old not in sexp_h:
            raise SystemExit(f"missing decl: {old}")
        sexp_h = sexp_h.replace(old, new)

    return sexp_h


def patch_eval_h_host(eval_h: str) -> str:
    old = "SEXP_API sexp sexp_load_standard_ports (sexp context, sexp env, FILE* in, FILE* out, FILE* err, int no_close);"
    new = (
        "SEXP_API sexp sexp_set_standard_ports (sexp context, sexp env, sexp in, sexp out, sexp err);\n"
        "/* legacy name: install already-built ports (not FILE*) */\n"
        "#define sexp_load_standard_ports(ctx, env, in, out, err, no_close) \\\n"
        "  ((void)(no_close), sexp_set_standard_ports((ctx), (env), (in), (out), (err)))"
    )
    if old not in eval_h:
        raise SystemExit("sexp_load_standard_ports decl not found in eval.h")
    eval_h = eval_h.replace(old, new)
    for decl in (
        "SEXP_API sexp sexp_open_input_file_op(sexp ctx, sexp self, sexp_sint_t n, sexp x);\n",
        "SEXP_API sexp sexp_open_output_file_op(sexp ctx, sexp self, sexp_sint_t n, sexp x);\n",
        "SEXP_API sexp sexp_open_binary_input_file(sexp ctx, sexp self, sexp_sint_t n, sexp x);\n",
        "SEXP_API sexp sexp_open_binary_output_file(sexp ctx, sexp self, sexp_sint_t n, sexp x);\n",
        "#define sexp_open_input_file(ctx, x) sexp_open_input_file_op(ctx, NULL, 1, x)\n",
        "#define sexp_open_output_file(ctx, x) sexp_open_output_file_op(ctx, NULL, 1, x)\n",
    ):
        eval_h = eval_h.replace(decl, "")
    eval_h = eval_h.replace(
        "SEXP_API sexp sexp_get_port_fileno (sexp ctx, sexp self, sexp_sint_t n, sexp port);\n",
        "#if defined(PUCHI_TEST)\n"
        "SEXP_API sexp sexp_get_port_fileno (sexp ctx, sexp self, sexp_sint_t n, sexp port);\n"
        "#endif\n",
    )
    return eval_h


def patch_sexp_c_host(sexp_c: str) -> str:
    """Rewrite port constructors, buffered stream I/O, finalize, exception fallback."""
    # finalize: call stream_ops->close instead of fclose stub
    sexp_c = sexp_c.replace(
        "    if (sexp_port_stream(port) && ! sexp_port_no_closep(port))\n"
        "      /* close the stream */\n"
        "      /* puchi: no fclose; stream ports unsupported */ (void)port;",
        "    if (sexp_port_stream_ops(port) && ! sexp_port_no_closep(port)) {\n"
        "      if (sexp_port_stream_ops(port)->close)\n"
        "        sexp_port_stream_ops(port)->close(sexp_port_stream_udata(port));\n"
        "      sexp_port_stream_ops(port) = NULL;\n"
        "      sexp_port_stream_udata(port) = NULL;\n"
        "    }",
    )
    # Also handle unpatched fclose form if stub didn't apply
    sexp_c = sexp_c.replace(
        "    if (sexp_port_stream(port) && ! sexp_port_no_closep(port))\n"
        "      /* close the stream */\n"
        "      fclose(sexp_port_stream(port));",
        "    if (sexp_port_stream_ops(port) && ! sexp_port_no_closep(port)) {\n"
        "      if (sexp_port_stream_ops(port)->close)\n"
        "        sexp_port_stream_ops(port)->close(sexp_port_stream_udata(port));\n"
        "      sexp_port_stream_ops(port) = NULL;\n"
        "      sexp_port_stream_udata(port) = NULL;\n"
        "    }",
    )

    # buffered read/write stream arms
    sexp_c = sexp_c.replace(
        "    res = fread(sexp_port_buf(p) + BUF_START, 1, SEXP_PORT_BUFFER_SIZE - BUF_START, sexp_port_stream(p));",
        "    res = (sexp_port_stream_ops(p) && sexp_port_stream_ops(p)->read)\n"
        "      ? (int)sexp_port_stream_ops(p)->read(sexp_port_stream_udata(p), sexp_port_buf(p) + BUF_START, SEXP_PORT_BUFFER_SIZE - BUF_START)\n"
        "      : -1;",
    )
    sexp_c = sexp_c.replace(
        "    if (off > 0) fwrite(sexp_port_buf(p), 1, off, sexp_port_stream(p));\n"
        "    res = fflush(sexp_port_stream(p));",
        "    if (off > 0 && sexp_port_stream_ops(p) && sexp_port_stream_ops(p)->write)\n"
        "      sexp_port_stream_ops(p)->write(sexp_port_stream_udata(p), sexp_port_buf(p), (size_t)off);\n"
        "    res = (sexp_port_stream_ops(p) && sexp_port_stream_ops(p)->flush)\n"
        "      ? sexp_port_stream_ops(p)->flush(sexp_port_stream_udata(p)) : 0;",
    )

    # Delete OS fileno read/write arms (POSIX read/write).
    sexp_c = re.sub(
        r"  \} else if \(sexp_filenop\(sexp_port_fd\(p\)\)\) \{\n"
        r"    res = read\(sexp_port_fileno\(p\), sexp_port_buf\(p\) \+ BUF_START, SEXP_PORT_BUFFER_SIZE - BUF_START\);\n"
        r"    if \(res >= 0\) \{\n"
        r"      sexp_port_offset\(p\) = BUF_START;\n"
        r"      sexp_port_size\(p\) = res \+ BUF_START;\n"
        r"      res = \(\(sexp_port_offset\(p\) < sexp_port_size\(p\)\)\n"
        r"             \? \(\(unsigned char\*\)sexp_port_buf\(p\)\)\[sexp_port_offset\(p\)\+\+\] : EOF\);\n"
        r"    \}\n",
        "  ",
        sexp_c,
        count=1,
    )
    sexp_c = re.sub(
        r"  \} else if \(sexp_filenop\(sexp_port_fd\(p\)\)\) \{\n"
        r"    if \(off > 0\)\n"
        r"      res = write\(sexp_fileno_fd\(sexp_port_fd\(p\)\), sexp_port_buf\(p\), off\);\n"
        r"    if \(res < off\) \{\n"
        r"      if \(res > 0\) \{\n"
        r"        memmove\(sexp_port_buf\(p\), sexp_port_buf\(p\) \+ res, off - res\);\n"
        r"        sexp_port_offset\(p\) = off - res;\n"
        r"        res = 0;\n"
        r"      \} else \{\n"
        r"        res = -1;\n"
        r"      \}\n"
        r"    \} else \{\n"
        r"      sexp_port_offset\(p\) = 0;\n"
        r"      res = 0;\n"
        r"    \}\n",
        "  ",
        sexp_c,
        count=1,
    )

    # Fileno APIs / type row: harness only
    def _gate_test(body: str) -> str:
        return f"#if defined(PUCHI_TEST)\n{body}#endif\n"

    m = re.search(
        r"sexp sexp_finalize_fileno \(sexp ctx, sexp self, sexp_sint_t n, sexp fileno\) \{.*?\n\}\n+",
        sexp_c,
        flags=re.DOTALL,
    )
    if m:
        sexp_c = sexp_c[: m.start()] + _gate_test(m.group(0)) + sexp_c[m.end() :]
    # finalize_port fileno branch — harness only
    sexp_c = re.sub(
        r"#ifndef PLAN9\n"
        r"(    if \(sexp_filenop\(sexp_port_fd\(port\)\)\n"
        r"        && sexp_fileno_openp\(sexp_port_fd\(port\)\)\) \{.*?\n"
        r"    \}\n)"
        r"#endif\n",
        lambda mo: _gate_test(mo.group(1)),
        sexp_c,
        count=1,
        flags=re.DOTALL,
    )
    sexp_c = re.sub(
        r"(    if \(sexp_filenop\(sexp_port_fd\(port\)\)\n"
        r"        && sexp_fileno_openp\(sexp_port_fd\(port\)\)\) \{.*?\n"
        r"    \}\n)",
        lambda mo: (
            mo.group(0)
            if "defined(PUCHI_TEST)" in sexp_c[max(0, mo.start() - 60) : mo.start()]
            else _gate_test(mo.group(1))
        ),
        sexp_c,
        count=1,
        flags=re.DOTALL,
    )
    sexp_c = re.sub(
        r"(  \{\(sexp\)\"File-Descriptor\".*?\},\n)",
        lambda mo: _gate_test(mo.group(1)),
        sexp_c,
        count=1,
    )
    for fname in (
        "sexp_open_input_file_descriptor",
        "sexp_open_output_file_descriptor",
        "sexp_make_fileno_op",
    ):
        m = re.search(
            rf"sexp {fname} \(sexp ctx, sexp self, sexp_sint_t n,.*?\n" + r"\}\n+",
            sexp_c,
            flags=re.DOTALL,
        )
        if m:
            sexp_c = sexp_c[: m.start()] + _gate_test(m.group(0)) + sexp_c[m.end() :]
    sexp_c = re.sub(
        r"(    case SEXP_FILENO:\n"
        r"      sexp_write_string\(ctx, \"#<fileno \", out\);\n"
        r"      sexp_write\(ctx, sexp_make_fixnum\(sexp_fileno_fd\(obj\)\), out\);\n"
        r"      sexp_write_char\(ctx, '>', out\);\n"
        r"      break;\n)",
        lambda mo: _gate_test(mo.group(1)),
        sexp_c,
        count=1,
    )
    # make_input_port
    old_make = """sexp sexp_make_input_port (sexp ctx, FILE* in, sexp name) {
  sexp p = sexp_alloc_type(ctx, port, SEXP_IPORT);
  if (sexp_exceptionp(p)) return p;
  sexp_port_stream(p) = in;
"""
    new_make = """sexp sexp_make_input_port (sexp ctx, const puchi_stream_ops *ops, void *udata, sexp name) {
  sexp p = sexp_alloc_type(ctx, port, SEXP_IPORT);
  if (sexp_exceptionp(p)) return p;
  sexp_port_stream_ops(p) = ops;
  sexp_port_stream_udata(p) = udata;
"""
    if old_make not in sexp_c:
        raise SystemExit("sexp_make_input_port body not found")
    sexp_c = sexp_c.replace(old_make, new_make)
    # Port fd-era field inits: harness only
    for dead_init in (
        "  sexp_port_fd(p) = SEXP_FALSE;\n",
        "  sexp_port_bidirp(p) = 0;\n",
        "  sexp_port_shutdownp(p) = 0;\n",
        "  sexp_port_blockedp(p) = 0;\n",
    ):
        if dead_init in sexp_c:
            sexp_c = sexp_c.replace(
                dead_init, f"#if defined(PUCHI_TEST)\n{dead_init}#endif\n"
            )

    sexp_c = sexp_c.replace(
        "sexp sexp_make_output_port (sexp ctx, FILE* out, sexp name) {\n"
        "  sexp p = sexp_make_input_port(ctx, out, name);\n",
        "sexp sexp_make_output_port (sexp ctx, const puchi_stream_ops *ops, void *udata, sexp name) {\n"
        "  sexp p = sexp_make_input_port(ctx, ops, udata, name);\n",
    )
    sexp_c = sexp_c.replace(
        "sexp sexp_make_non_null_input_port (sexp ctx, FILE* in, sexp name) {\n"
        "  if (!in) return sexp_user_exception(ctx, SEXP_FALSE, \"null input-port\", name);\n"
        "  return sexp_make_input_port(ctx, in, name);\n"
        "}\n",
        "sexp sexp_make_non_null_input_port (sexp ctx, const puchi_stream_ops *ops, void *udata, sexp name) {\n"
        "  if (!ops) return sexp_user_exception(ctx, SEXP_FALSE, \"null input-port\", name);\n"
        "  return sexp_make_input_port(ctx, ops, udata, name);\n"
        "}\n",
    )
    sexp_c = sexp_c.replace(
        "sexp sexp_make_non_null_output_port (sexp ctx, FILE* out, sexp name) {\n"
        "  if (!out) return sexp_user_exception(ctx, SEXP_FALSE, \"null output-port\", name);\n"
        "  return sexp_make_output_port(ctx, out, name);\n"
        "}\n",
        "sexp sexp_make_non_null_output_port (sexp ctx, const puchi_stream_ops *ops, void *udata, sexp name) {\n"
        "  if (!ops) return sexp_user_exception(ctx, SEXP_FALSE, \"null output-port\", name);\n"
        "  return sexp_make_output_port(ctx, ops, udata, name);\n"
        "}\n",
    )

    # string ports pass NULL stream
    sexp_c = sexp_c.replace(
        "sexp_make_input_port(ctx, NULL, SEXP_FALSE)",
        "sexp_make_input_port(ctx, NULL, NULL, SEXP_FALSE)",
    )
    sexp_c = sexp_c.replace(
        "sexp_make_output_port(ctx, NULL, SEXP_FALSE)",
        "sexp_make_output_port(ctx, NULL, NULL, SEXP_FALSE)",
    )

    # exception print fallback: string port + diagnose, never stderr
    sexp_c = sexp_c.replace(
        "  if (! sexp_oportp(out))\n"
        "    out = tmp = sexp_make_output_port(ctx, stderr, SEXP_FALSE);\n",
        "  if (! sexp_oportp(out)) {\n"
        "    out = tmp = sexp_open_output_string(ctx);\n"
        "  }\n",
    )

    # ferror/clearerr on stream ports
    sexp_c = re.sub(
        r"ferror\(sexp_port_stream\(([^)]+)\)\)",
        r"(sexp_port_stream_ops(\1) && sexp_port_stream_ops(\1)->error_p ? sexp_port_stream_ops(\1)->error_p(sexp_port_stream_udata(\1)) : 0)",
        sexp_c,
    )
    sexp_c = re.sub(
        r"clearerr\(sexp_port_stream\(([^)]+)\)\)",
        r"do { if (sexp_port_stream_ops(\1) && sexp_port_stream_ops(\1)->clear_error) sexp_port_stream_ops(\1)->clear_error(sexp_port_stream_udata(\1)); } while (0)",
        sexp_c,
    )

    # ungetc on stream in push_utf8 if any remain
    sexp_c = re.sub(
        r"ungetc\(([^,]+),\s*sexp_port_stream\(([^)]+)\)\)",
        r"(sexp_port_stream_ops(\2) && sexp_port_stream_ops(\2)->unget_char ? sexp_port_stream_ops(\2)->unget_char(sexp_port_stream_udata(\2), (\1)) : EOF)",
        sexp_c,
    )

    # char_ready_p: fileno check only in harness
    sexp_c = sexp_c.replace(
        "  if (sexp_port_buf(in))\n"
        "    if (sexp_port_offset(in) < sexp_port_size(in)\n"
        "        || (!sexp_filenop(sexp_port_fd(in)) && !sexp_port_stream(in)))\n"
        "      return SEXP_TRUE;\n",
        "  if (sexp_port_buf(in)) {\n"
        "    if (sexp_port_offset(in) < sexp_port_size(in))\n"
        "      return SEXP_TRUE;\n"
        "#if defined(PUCHI_TEST)\n"
        "    if (!sexp_filenop(sexp_port_fd(in)) && !sexp_port_stream(in))\n"
        "      return SEXP_TRUE;\n"
        "#endif\n"
        "  }\n",
    )

    return sexp_c


def patch_eval_c_host(eval_c: str) -> str:
    eval_c = eval_c.replace("if (strictp) abort();", "if (strictp) puchi_fatal(ctx, PUCHI_FATAL_STRICT, msg);")
    eval_c = eval_c.replace(
        "if (strictp) exit(1);",
        "if (strictp) puchi_fatal(ctx, PUCHI_FATAL_STRICT, msg);",
    )

    # warn fallback
    eval_c = eval_c.replace(
        "  if (sexp_not(out)) {          /* generate a throw-away port */\n"
        "    out = sexp_make_output_port(ctx, stderr, SEXP_FALSE);\n"
        "    sexp_port_no_closep(out) = 1;\n"
        "  }\n",
        "  if (sexp_not(out) || !sexp_oportp(out)) {\n"
        "    out = sexp_open_output_string(ctx);\n"
        "  }\n",
    )

    # After warn writes, if we used a string portfolio for diagnose — patch end of sexp_warn
    # Original ends with: if (strictp) abort/puchi_fatal
    # Add diagnose of string port content when current-error-port was missing.
    # Simpler: after writing to out, if out is string port, diagnose get-output-string.
    warn_tail = """  if (sexp_oportp(out)) {
    sexp_write_string(ctx, strictp ? "ERROR: " : "WARNING: ", out);
    sexp_write_string(ctx, msg, out);
    if (x != SEXP_UNDEF) {
      sexp_write(ctx, x, out);
    }
    sexp_write_char(ctx, '\\n', out);
    if (strictp) sexp_stack_trace(ctx, out);
  }
  sexp_gc_release1(ctx);
  if (strictp) puchi_fatal(ctx, PUCHI_FATAL_STRICT, msg);
"""
    warn_new = """  if (sexp_oportp(out)) {
    sexp_write_string(ctx, strictp ? "ERROR: " : "WARNING: ", out);
    sexp_write_string(ctx, msg, out);
    if (x != SEXP_UNDEF) {
      sexp_write(ctx, x, out);
    }
    sexp_write_char(ctx, '\\n', out);
    if (strictp) sexp_stack_trace(ctx, out);
    {
      sexp s = sexp_get_output_string(ctx, out);
      if (sexp_stringp(s))
        puchi_diagnose(ctx, strictp ? PUCHI_DIAG_EXCEPTION : PUCHI_DIAG_WARN,
                       sexp_string_data(s));
    }
  }
  sexp_gc_release1(ctx);
  if (strictp) puchi_fatal(ctx, PUCHI_FATAL_STRICT, msg);
"""
    if warn_tail in eval_c:
        eval_c = eval_c.replace(warn_tail, warn_new)

    old_ports = """sexp sexp_load_standard_ports (sexp ctx, sexp env, FILE* in, FILE* out,
                               FILE* err, int no_close) {
  sexp_gc_var1(p);
  sexp_gc_preserve1(ctx, p);
  if (!env) env = sexp_context_env(ctx);
  if (in) {
    p = sexp_make_input_port(ctx, in, SEXP_FALSE);
    sexp_port_no_closep(p) = no_close;
    sexp_set_parameter(ctx, env, sexp_global(ctx, SEXP_G_CUR_IN_SYMBOL), p);
  }
  if (out) {
    p = sexp_make_output_port(ctx, out, SEXP_FALSE);
    sexp_port_no_closep(p) = no_close;
    sexp_set_parameter(ctx, env, sexp_global(ctx, SEXP_G_CUR_OUT_SYMBOL), p);
  }
  if (err) {
    p = sexp_make_output_port(ctx, err, SEXP_FALSE);
    sexp_port_no_closep(p) = no_close;
    sexp_set_parameter(ctx, env, sexp_global(ctx, SEXP_G_CUR_ERR_SYMBOL), p);
  }
  sexp_gc_release1(ctx);
  return SEXP_VOID;
}
"""
    new_ports = """sexp sexp_set_standard_ports (sexp ctx, sexp env, sexp in, sexp out, sexp err) {
  if (!env) env = sexp_context_env(ctx);
  if (sexp_portp(in))
    sexp_set_parameter(ctx, env, sexp_global(ctx, SEXP_G_CUR_IN_SYMBOL), in);
  if (sexp_portp(out))
    sexp_set_parameter(ctx, env, sexp_global(ctx, SEXP_G_CUR_OUT_SYMBOL), out);
  if (sexp_portp(err))
    sexp_set_parameter(ctx, env, sexp_global(ctx, SEXP_G_CUR_ERR_SYMBOL), err);
  return SEXP_VOID;
}
"""
    if old_ports not in eval_c:
        # try already-stubbed variant or looser match
        m = re.search(
            r"sexp sexp_load_standard_ports \(sexp ctx, sexp env, FILE\* in, FILE\* out,\s*"
            r"FILE\* err, int no_close\) \{.*?\n\}",
            eval_c,
            flags=re.DOTALL,
        )
        if not m:
            raise SystemExit("sexp_load_standard_ports body not found")
        eval_c = eval_c[: m.start()] + new_ports + eval_c[m.end() :]
    else:
        eval_c = eval_c.replace(old_ports, new_ports)

    # ungetc in eval push_utf8
    eval_c = re.sub(
        r"ungetc\(([^,]+),\s*sexp_port_stream\(([^)]+)\)\)",
        r"(sexp_port_stream_ops(\2) && sexp_port_stream_ops(\2)->unget_char ? sexp_port_stream_ops(\2)->unget_char(sexp_port_stream_udata(\2), (\1)) : EOF)",
        eval_c,
    )

    # get_port_fileno: harness only; keep stream_portp_op always
    eval_c = re.sub(
        r"#ifndef PLAN9\n"
        r"(sexp sexp_get_port_fileno \(sexp ctx, sexp self, sexp_sint_t n, sexp port\) \{.*?\n\}\n)"
        r"(sexp sexp_stream_portp_op \(sexp ctx, sexp self, sexp_sint_t n, sexp port\) \{.*?\n\}\n)"
        r"#endif\n",
        r"#if defined(PUCHI_TEST)\n\1#endif\n\2",
        eval_c,
        count=1,
        flags=re.DOTALL,
    )

    # Path load: no open-*-file; return exception directly
    eval_c = eval_c.replace(
        "  if (sexp_iportp(source)) {\n"
        "    in = source;\n"
        "  } else {\n"
        "    sexp_assert_type(ctx, sexp_stringp, SEXP_STRING, source);\n"
        "    in = sexp_open_input_file(ctx, source);\n"
        "  }\n",
        "  if (sexp_iportp(source)) {\n"
        "    in = source;\n"
        "  } else {\n"
        "    sexp_assert_type(ctx, sexp_stringp, SEXP_STRING, source);\n"
        "    in = sexp_file_exception(ctx, self,\n"
        '      "load: file paths not available in puchi core (host may redefine)", source);\n'
        "  }\n",
    )

    # find_module_file: path always NULL — drop free(path)
    eval_c = re.sub(
        r"\s*if \(path\) free\(path\);",
        "",
        eval_c,
    )
    eval_c = re.sub(
        r"\s*if \(path\) SEXP_FREE\(NULL, path\);",
        "",
        eval_c,
    )

    return eval_c


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
    # Ternary function pointers: (? strcasecmp : strcmp) — no call paren.
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


def trim_init7_load_port(src: str) -> str:
    """After trim_init7 file stubs, restore load that accepts ports."""
    # Replace the puchi load stub with a port-aware version.
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
    return src
