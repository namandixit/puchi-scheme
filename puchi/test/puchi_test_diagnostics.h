/* puchi_test_diagnostics.h — test-only helpers (not part of amalgamated puchi.h).
 * Noreturn + Clang -Weverything ignores for unavoidable puchi.h API noise. */
#ifndef PUCHI_TEST_DIAGNOSTICS_H
#define PUCHI_TEST_DIAGNOSTICS_H

#if defined(__GNUC__) || defined(__clang__)
#define PUCHI_NORETURN __attribute__((noreturn))
#elif defined(_MSC_VER)
#define PUCHI_NORETURN __declspec(noreturn)
#else
#define PUCHI_NORETURN
#endif

#if defined(__clang__)
/* Apply once after includes in a harness/smoke TU. Covers:
 * - sexp_define_foreign → sexp_proc1 casts
 * - sexp_gc_var* / preserve (__sexp_gc_preserverN)
 * - sexp cons/list macros (char* → sexp*)
 * - idiomatic C path/buffer code under -Wunsafe-buffer-usage
 * - common size_t/int churn at sexp_* call sites
 */
#define PUCHI_DIAG_HARNESS_PEDANTIC_OFF                                \
  _Pragma("clang diagnostic ignored \"-Wunsafe-buffer-usage\"")        \
  _Pragma("clang diagnostic ignored \"-Wcast-align\"")                 \
  _Pragma("clang diagnostic ignored \"-Wcast-function-type-strict\"")  \
  _Pragma("clang diagnostic ignored \"-Wcast-function-type-mismatch\"") \
  _Pragma("clang diagnostic ignored \"-Wreserved-identifier\"")        \
  _Pragma("clang diagnostic ignored \"-Wextra-semi-stmt\"")            \
  _Pragma("clang diagnostic ignored \"-Wsign-conversion\"")            \
  _Pragma("clang diagnostic ignored \"-Wpadded\"")                     \
  _Pragma("clang diagnostic ignored \"-Wunused-macros\"")              \
  _Pragma("clang diagnostic ignored \"-Wnonportable-system-include-path\"")
#else
#define PUCHI_DIAG_HARNESS_PEDANTIC_OFF
#endif

#endif /* PUCHI_TEST_DIAGNOSTICS_H */
