/* Forced by amalgamate.sh. Set PUCHI_* macros before including puchi.h.
 *
 * Default:           fixnums + IEEE flonums (overflow wraps; no bignums).
 * PUCHI_INTEGER_ONLY: fixnums only (no floats, no tower).
 * PUCHI_ENABLE_NUMERICAL_TOWER: bignums + ratios + complex (implies flonums).
 *
 * OS/debug backends listed in ALWAYS_ZERO_STRIP are deleted by
 * strip-dead-backends (puchi_amalgamate_helpers.py). Do not re-enable them.
 */
#if defined(PUCHI_INTEGER_ONLY) && defined(PUCHI_ENABLE_NUMERICAL_TOWER)
#error "PUCHI_INTEGER_ONLY and PUCHI_ENABLE_NUMERICAL_TOWER are mutually exclusive"
#endif

#define SEXP_USE_MODULES 1

#if defined(PUCHI_INTEGER_ONLY)
#define SEXP_USE_FLONUMS 0
#define SEXP_USE_MATH 0
#define SEXP_USE_BIGNUMS 0
#define SEXP_USE_RATIOS 0
#define SEXP_USE_COMPLEX 0
#elif defined(PUCHI_ENABLE_NUMERICAL_TOWER)
#define SEXP_USE_FLONUMS 1
#define SEXP_USE_MATH 1
#define SEXP_USE_BIGNUMS 1
#define SEXP_USE_RATIOS 1
#define SEXP_USE_COMPLEX 1
#else
/* Default: fast ints + floats */
#define SEXP_USE_FLONUMS 1
#define SEXP_USE_MATH 1
#define SEXP_USE_BIGNUMS 0
#define SEXP_USE_RATIOS 0
#define SEXP_USE_COMPLEX 0
#endif

/* STATIC_LIBS* stay #if-gated: off unless PUCHI_TEST (harness only). */
#if defined(PUCHI_TEST)
#define SEXP_USE_STATIC_LIBS 1
#define SEXP_USE_STATIC_LIBS_EMPTY 1
#else
#undef SEXP_USE_STATIC_LIBS
#define SEXP_USE_STATIC_LIBS 0
#undef SEXP_USE_STATIC_LIBS_EMPTY
#define SEXP_USE_STATIC_LIBS_EMPTY 0
#endif
