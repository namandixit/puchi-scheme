/* puchi_impl.c - the implementation section of puchi.h.  tools/amalgamate.py
 * inlines every #include "..." below; this file also compiles as is with
 * -I puchi/src -I puchi/build/gen -I puchi/build/src/include -I puchi/build/src
 * (that is how the gates build it). */

#if defined(__GNUC__) && defined(PUCHI_AMALGAMATED)
#pragma GCC system_header      /* upstream is not warning-free; gate G9 checks puchi's own code */
#endif
#ifdef _MSC_VER
#pragma warning(push, 0)
#endif

#include "puchi_config.h"
#include "chibi/eval.h"
#include "chibi/bignum.h"
#include "puchi_api.h"

/* Every system header any compiled upstream file includes, BEFORE the
 * redirects (a redirect macro must never be expanded inside a system
 * header).  Gate G6 fails if this list is incomplete. */
#include <ctype.h>
#include <errno.h>
#include <float.h>
#include <limits.h>
#include <math.h>
#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <fcntl.h>
#ifdef _WIN32
#include <io.h>
#else
#include <poll.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>
#endif

#include "puchi_redirect.h"

/* Chibi core, in the order of upstream's Makefile.  Three file-static names
 * are defined twice in the amalgamation; rename them around the file that
 * is included second. */
#include "gc.c"
#define sexp_string_hash sexp_symbol_string_hash   /* also in srfi/69/hash.c */
#include "sexp.c"
#undef sexp_string_hash
#define digit_value bignum_digit_value             /* also in sexp.c */
#define hex_digit bignum_hex_digit                 /* also in sexp.c */
#define log2i bignum_log2i                         /* also in srfi/151/bit.c */
#include "bignum.c"
#undef digit_value
#undef hex_digit
#undef log2i
#include "opcodes.c"
#include "vm.c"
#include "simplify.c"
/* last: eval.c #includes the generated clibs.c (the bundled C libraries),
 * whose macros must not leak into the other upstream files */
#include "eval.c"

#include "puchi_unredirect.h"
#include "puchi_glue.c"

#ifdef _MSC_VER
#pragma warning(pop)
#endif
