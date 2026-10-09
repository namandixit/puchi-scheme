/* Compile-only: clibs mode (TEST + IMPL + PUCHI_TEST_CLIB) must see sexp decls
 * without compiling VM bodies in this TU. */
#define PUCHI_TEST 1
#define PUCHI_IMPLEMENTATION 1
#define PUCHI_TEST_CLIB 1
#ifndef PUCHI_ENABLE_NUMERICAL_TOWER
#define PUCHI_ENABLE_NUMERICAL_TOWER
#endif
#include "../puchi.h"

void puchi_test_clibs_surface_probe(void) {
  sexp x = SEXP_NULL;
  (void)sexp_car(x);
  (void)sizeof(sexp_uint_t);
  (void)&sexp_load_op;
}
