/* Static include-shared stubs linked only into the puchi harness.
 * Minimal set for r7rs/syntax/division/unicode tests.
 * Numeric mode (/DPUCHI_*) must match puchi_harness.c.
 */
#ifndef PUCHI_TEST
#define PUCHI_TEST 1
#endif

#include <stdio.h>
#include <sys/types.h>
#include <sys/stat.h>
#include <fcntl.h>
#ifdef _WIN32
#include <io.h>
#include <direct.h>
#endif

#include "puchi_test_diagnostics.h"
#include "../puchi.h"

/* Upstream chibi-ffi lib stub bodies only — silence every warning in this
 * span. Does not affect other TUs (harness, smokes, or product hosts). */
#if defined(__clang__)
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Weverything"
#elif defined(_MSC_VER)
#pragma warning(push, 0)
/* Optimizer/level-4 codes that warning(push, 0) alone may still emit. */
#pragma warning(disable : 4701 4702 4703)
#endif

#define sexp_init_library sexp_init_lib_srfi_98
#include "../../lib/srfi/98/env.c"
#undef sexp_init_library

#define sexp_init_library sexp_init_lib_srfi_69
#include "../../lib/srfi/69/hash.c"
#undef sexp_init_library

#define sexp_init_library sexp_init_lib_srfi_39
#include "../../lib/srfi/39/param.c"
#undef sexp_init_library

#define sexp_init_library sexp_init_lib_srfi_151
#include "../../lib/srfi/151/bit.c"
#undef sexp_init_library

#define sexp_init_library sexp_init_lib_scheme_time
#include "../../lib/scheme/time.c"
#undef sexp_init_library

/* These four are generated into lib/ from *.stub by chibi-ffi (gitignored).
 * Regenerate with: puchi/tools/generate_harness_stubs.sh <chibi-scheme> */
#define sexp_init_library sexp_init_lib_scheme_bytevector
#include "../../lib/scheme/bytevector.c"
#undef sexp_init_library

#define sexp_init_library sexp_init_lib_chibi_win32_process_win32
#include "../../lib/chibi/win32/process-win32.c"
#undef sexp_init_library

/* chibi-ffi io.c still passes sexp_port_stream() to FILE* APIs
 * (clearerr/fseek/ftell/fgets). Harness file ports store the FILE*
 * in stream_udata; ops live in stream_ops. Restore the puchi macro
 * after this include so later stubs keep the ops pointer. */
#undef sexp_port_stream
#define sexp_port_stream(p) ((FILE *)sexp_port_stream_udata(p))
#define sexp_init_library sexp_init_lib_chibi_io
#include "../../lib/chibi/io/io.c"
#undef sexp_init_library
#undef sexp_port_stream
/* Later stubs use stream_ops; restore puchi's meaning of sexp_port_stream. */
#define sexp_port_stream(p) sexp_port_stream_ops(p)

#define sexp_init_library sexp_init_lib_chibi_filesystem
#include "../../lib/chibi/filesystem.c"
#undef sexp_init_library

#define sexp_init_library sexp_init_lib_chibi_ast
#include "../../lib/chibi/ast.c"
#undef sexp_init_library

extern struct puchi_library_entry_t puchi_harness_static_libraries[];
struct puchi_library_entry_t puchi_harness_static_libraries[] = {
  { "lib/srfi/98/env", sexp_init_lib_srfi_98 },
  { "lib/srfi/69/hash", sexp_init_lib_srfi_69 },
  { "lib/srfi/39/param", sexp_init_lib_srfi_39 },
  { "lib/srfi/151/bit", sexp_init_lib_srfi_151 },
  { "lib/scheme/time", sexp_init_lib_scheme_time },
  { "lib/scheme/bytevector", sexp_init_lib_scheme_bytevector },
  { "lib/chibi/win32/process-win32", sexp_init_lib_chibi_win32_process_win32 },
  { "lib/chibi/io/io", sexp_init_lib_chibi_io },
  { "lib/chibi/filesystem", sexp_init_lib_chibi_filesystem },
  { "lib/chibi/ast", sexp_init_lib_chibi_ast },
  { NULL, NULL }
};

#if defined(__clang__)
#pragma clang diagnostic pop
#elif defined(_MSC_VER)
#pragma warning(pop)
#endif
