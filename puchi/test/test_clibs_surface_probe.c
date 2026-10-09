/* Compile-only: PUCHI_TEST without PUCHI_IMPLEMENTATION must see sexp decls
 * (harness clibs TU). Must not require linking VM bodies from this file. */
#define PUCHI_TEST 1
#define PUCHI_ENABLE_NUMERICAL_TOWER
#include "../puchi.h"
#include "harness-include/chibi/eval.h"

void puchi_test_clibs_surface_probe(void) {
  sexp x = SEXP_NULL;
  (void)sexp_car(x);
  (void)sizeof(sexp_uint_t);
  (void)&sexp_load_op;
}
