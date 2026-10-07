/* Tower build: bignums + ratios + complex. */
#define PUCHI_ENABLE_NUMERICAL_TOWER
#define PUCHI_IMPLEMENTATION
#include "../puchi.h"
#include <stdio.h>

int main(void) {
  sexp ctx, res;
  ctx = sexp_create_context(0, 0);
  if (!ctx || sexp_exceptionp(ctx)) {
    fprintf(stderr, "create_context failed\n");
    return 1;
  }
  res = sexp_load_default_libs(ctx);
  if (sexp_exceptionp(res)) {
    fprintf(stderr, "load_default_libs failed\n");
    sexp_print_exception(ctx, res, sexp_current_error_port(ctx));
    return 2;
  }
  res = sexp_eval_string(ctx, "(+ 1 2 3)", -1, NULL);
  if (sexp_exceptionp(res)) {
    fprintf(stderr, "eval failed\n");
    return 3;
  }
  printf("ok %ld\n", (long)sexp_unbox_fixnum(res));
  sexp_delete_context(ctx);
  return 0;
}
