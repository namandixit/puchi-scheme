/* Shim for compiling Chibi lib stubs against amalgamated puchi.h.
 * Numeric mode is set by the harness TU / compiler -D flags before this. */
#ifndef PUCHI_HARNESS_CHIBI_EVAL_H
#define PUCHI_HARNESS_CHIBI_EVAL_H

#ifndef SEXP_USE_STATIC_LIBS
#define SEXP_USE_STATIC_LIBS 1
#endif
#ifndef SEXP_USE_STATIC_LIBS_EMPTY
#define SEXP_USE_STATIC_LIBS_EMPTY 1
#endif

#include "../../../puchi.h"

#endif /* PUCHI_HARNESS_CHIBI_EVAL_H */
