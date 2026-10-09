/* Compile-only: bare include must not introduce sexp_/SEXP_ macros. */
#include "../puchi.h"

#ifdef sexp_car
#error "bare puchi.h must not expose sexp_car"
#endif
#ifdef SEXP_NULL
#error "bare puchi.h must not expose SEXP_NULL"
#endif
#ifdef sexp_load_op
#error "bare puchi.h must not expose sexp_load_op"
#endif

static void puchi_test_host_isolation_bare(void) {
  (void)sizeof(puchi);
  (void)sizeof(puchi_uint_t);
}
