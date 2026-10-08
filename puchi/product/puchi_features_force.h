/* Forced by amalgamate.sh. Set PUCHI_* macros before including puchi.h.
 *
 * Default:           fixnums + IEEE flonums (overflow wraps; no bignums).
 * PUCHI_INTEGER_ONLY: fixnums only (no floats, no tower).
 * PUCHI_ENABLE_NUMERICAL_TOWER: bignums + ratios + complex (implies flonums).
 *
 * There are no SEXP_USE_* knobs. Amalgamate folds them out of puchi.h.
 */
#if defined(PUCHI_INTEGER_ONLY) && defined(PUCHI_ENABLE_NUMERICAL_TOWER)
#error "PUCHI_INTEGER_ONLY and PUCHI_ENABLE_NUMERICAL_TOWER are mutually exclusive"
#endif
