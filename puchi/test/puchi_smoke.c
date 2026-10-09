/* Tower build: bignums + ratios + complex. */
#include <stdio.h>
#include <stdlib.h>
#include "puchi_test_diagnostics.h"
#ifndef PUCHI_ENABLE_NUMERICAL_TOWER
#define PUCHI_ENABLE_NUMERICAL_TOWER
#endif
#include "../puchi.h"

PUCHI_DIAG_HARNESS_PEDANTIC_OFF

static void *smoke_alloc(void *ud, size_t n) { (void)ud; return malloc(n); }
static void smoke_free(void *ud, void *p) { (void)ud; free(p); }
static void smoke_diag(void *ud, int c, const char *m) { (void)ud; (void)c; (void)m; }
static PUCHI_NORETURN void smoke_fatal(void *ud, int c, const char *m) {
  (void)ud; fprintf(stderr, "fatal %d: %s\n", c, m ? m : ""); exit(70);
}
static const puchi_host smoke_host = { NULL, smoke_alloc, smoke_free, smoke_diag, smoke_fatal };

int main(void) {
  puchi ctx, res;
  ctx = puchi_create_context((size_t)0, (size_t)0, &smoke_host);
  if (!ctx || puchi_exceptionp(ctx)) {
    fprintf(stderr, "create_context failed\n");
    return 1;
  }
  res = puchi_load_default_libs(ctx);
  if (puchi_exceptionp(res)) {
    fprintf(stderr, "load_default_libs failed\n");
    puchi_print_exception(ctx, res, puchi_current_error_port(ctx));
    return 2;
  }
  res = puchi_eval_string(ctx, "(+ 1 2 3)", (puchi_sint_t)-1, NULL);
  if (puchi_exceptionp(res)) {
    fprintf(stderr, "eval failed\n");
    return 3;
  }
  printf("ok %ld\n", (long)puchi_unbox_fixnum(res));
  puchi_delete_context(ctx);
  return 0;
}
