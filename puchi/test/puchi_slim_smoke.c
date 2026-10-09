/* Default config: fixnums + IEEE flonums (no numerical tower).
 * Scheme libs on disk contain complex literals, so this is a C-side suite
 * against embedded init — same approach as integer-only. */
#include <stdio.h>
#include <stdlib.h>
#include <math.h>
#include "puchi_test_diagnostics.h"
#define PUCHI_IMPLEMENTATION
#include "../puchi.h"

PUCHI_DIAG_HARNESS_PEDANTIC_OFF

static void *smoke_alloc(void *ud, size_t n) { (void)ud; return malloc(n); }
static void smoke_free(void *ud, void *p) { (void)ud; free(p); }
static void smoke_diag(void *ud, int c, const char *m) { (void)ud; (void)c; (void)m; }
static PUCHI_NORETURN void smoke_fatal(void *ud, int c, const char *m) {
  (void)ud; fprintf(stderr, "fatal %d: %s\n", c, m ? m : ""); exit(70);
}
static const puchi_host smoke_host = { NULL, smoke_alloc, smoke_free, smoke_diag, smoke_fatal };

static int fail(const char *msg) {
  fprintf(stderr, "FAIL: %s\n", msg);
  return 1;
}

static int expect_fix(puchi ctx, const char *expr, long want) {
  puchi res = puchi_eval_string(ctx, expr, (puchi_sint_t)-1, NULL);
  if (puchi_exceptionp(res) || !puchi_fixnump(res) ||
      (long)puchi_unbox_fixnum(res) != want) {
    fprintf(stderr, "FAIL fixnum %s\n", expr);
    return 1;
  }
  return 0;
}

static int expect_flo(puchi ctx, const char *expr, double want) {
  puchi res = puchi_eval_string(ctx, expr, (puchi_sint_t)-1, NULL);
  if (puchi_exceptionp(res) || !puchi_flonump(res) ||
      fabs(puchi_flonum_value(res) - want) > 1e-9) {
    fprintf(stderr, "FAIL flonum %s\n", expr);
    return 1;
  }
  return 0;
}

static int expect_true(puchi ctx, const char *expr) {
  puchi res = puchi_eval_string(ctx, expr, (puchi_sint_t)-1, NULL);
  if (puchi_exceptionp(res) || res == PUCHI_FALSE) {
    fprintf(stderr, "FAIL true %s\n", expr);
    return 1;
  }
  return 0;
}

int main(void) {
  puchi ctx = puchi_create_context((size_t)0, (size_t)0, &smoke_host);
  puchi res;
  int nfail = 0;

  if (!ctx || puchi_exceptionp(ctx)) return fail("create_context");
  res = puchi_load_default_libs(ctx);
  if (puchi_exceptionp(res)) return fail("load_default_libs");

#if defined(PUCHI_INTEGER_ONLY)
  return fail("default config should not be INTEGER_ONLY");
#endif
#if defined(PUCHI_ENABLE_NUMERICAL_TOWER)
  return fail("default config should not enable the tower");
#endif

  nfail += expect_fix(ctx, "(+ 40 2)", 42);
  nfail += expect_fix(ctx, "(* 6 7)", 42);
  nfail += expect_fix(ctx, "(let fact ((n 5)) (if (zero? n) 1 (* n (fact (- n 1)))))", 120);
  nfail += expect_flo(ctx, "(+ 1.5 2.25)", 3.75);
  nfail += expect_flo(ctx, "(* 2.0 3.0)", 6.0);
  nfail += expect_flo(ctx, "(/ 9.0 2.0)", 4.5);
  nfail += expect_flo(ctx, "(+ 2 3.5)", 5.5);
  nfail += expect_flo(ctx, "(sqrt 4.0)", 2.0);
  nfail += expect_flo(ctx, "(sin 0.0)", 0.0);
  nfail += expect_true(ctx, "(inexact? 1.5)");
  nfail += expect_true(ctx, "(exact? 3)");
  nfail += expect_true(ctx, "(exact-integer? (* 1000000000 1000000000))");

  if (nfail) {
    fprintf(stderr, "%d default-config checks failed\n", nfail);
    return 1;
  }
  printf("default ok (%d checks)\n", 12);
  puchi_delete_context(ctx);
  return 0;
}
