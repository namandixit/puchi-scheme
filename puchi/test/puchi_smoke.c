/* Tower build: bignums + ratios + complex. */
#include <stdio.h>
#include <stdlib.h>
#define PUCHI_ENABLE_NUMERICAL_TOWER
#define PUCHI_IMPLEMENTATION
#include "../puchi.h"

static void *smoke_alloc(void *ud, size_t n) { (void)ud; return malloc(n); }
static void smoke_free(void *ud, void *p) { (void)ud; free(p); }
static void smoke_diag(void *ud, int c, const char *m) { (void)ud; (void)c; (void)m; }
static void smoke_fatal(void *ud, int c, const char *m) {
  (void)ud; fprintf(stderr, "fatal %d: %s\n", c, m ? m : ""); exit(70);
}
static const puchi_host smoke_host = { NULL, smoke_alloc, smoke_free, smoke_diag, smoke_fatal };

int main(void) {
  sexp ctx, res;
  ctx = sexp_create_context(0, 0, &smoke_host);
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
