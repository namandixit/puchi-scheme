/* Compile-only: PUCHI_TEST without IMPLEMENTATION — puchi_TEST_* only, no sexp macros. */
#define PUCHI_TEST 1
#include "../puchi.h"

#ifdef sexp_car
#error "PUCHI_TEST-only include must not expose sexp_car"
#endif
#ifdef SEXP_NULL
#error "PUCHI_TEST-only include must not expose SEXP_NULL"
#endif
#ifdef sexp_load_op
#error "PUCHI_TEST-only include must not expose sexp_load_op"
#endif
#ifdef sexp_add_static_libraries
#error "PUCHI_TEST-only include must not expose sexp_add_static_libraries"
#endif

static void puchi_test_host_isolation_test_only(void) {
  (void)sizeof(puchi);
  (void)puchi_TEST_so_extension;
  (void)&puchi_TEST_add_static_libraries;
}
