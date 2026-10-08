/* Shim for compiling Chibi lib stubs against amalgamated puchi.h.
 * Numeric mode is set by the harness TU / compiler -D flags before this. */
#ifndef PUCHI_HARNESS_CHIBI_EVAL_H
#define PUCHI_HARNESS_CHIBI_EVAL_H

#ifndef PUCHI_TEST
#define PUCHI_TEST 1
#endif

/* Stubs such as lib/srfi/151/bit.c still #if SEXP_USE_BIGNUMS. puchi.h has
 * no SEXP_USE_* knobs; bridge tower mode so bitmaps are not fixnum-only.
 * (chibi ast) also #if SEXP_USE_COMPLEX / SEXP_USE_RATIOS for type names. */
#if defined(PUCHI_ENABLE_NUMERICAL_TOWER)
#if !defined(SEXP_USE_BIGNUMS)
#define SEXP_USE_BIGNUMS 1
#endif
#if !defined(SEXP_USE_COMPLEX)
#define SEXP_USE_COMPLEX 1
#endif
#if !defined(SEXP_USE_RATIOS)
#define SEXP_USE_RATIOS 1
#endif
#endif

#include "../../../puchi.h"

#endif /* PUCHI_HARNESS_CHIBI_EVAL_H */
