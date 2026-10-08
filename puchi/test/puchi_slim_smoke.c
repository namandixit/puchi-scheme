/* Default config: fixnums + IEEE flonums (no numerical tower).
 * Scheme libs on disk contain complex literals, so this is a C-side suite
 * against embedded init — same approach as integer-only. */
#include <stdio.h>
#include <math.h>
#define PUCHI_IMPLEMENTATION
#include "../puchi.h"

static int fail(const char *msg) {
  fprintf(stderr, "FAIL: %s\n", msg);
  return 1;
}

static int expect_fix(sexp ctx, const char *expr, long want) {
  sexp res = sexp_eval_string(ctx, expr, -1, NULL);
  if (sexp_exceptionp(res) || !sexp_fixnump(res) || sexp_unbox_fixnum(res) != want) {
    fprintf(stderr, "FAIL fixnum %s\n", expr);
    return 1;
  }
  return 0;
}

static int expect_flo(sexp ctx, const char *expr, double want) {
  sexp res = sexp_eval_string(ctx, expr, -1, NULL);
  if (sexp_exceptionp(res) || !sexp_flonump(res) ||
      fabs(sexp_flonum_value(res) - want) > 1e-9) {
    fprintf(stderr, "FAIL flonum %s\n", expr);
    return 1;
  }
  return 0;
}

static int expect_true(sexp ctx, const char *expr) {
  sexp res = sexp_eval_string(ctx, expr, -1, NULL);
  if (sexp_exceptionp(res) || res == SEXP_FALSE) {
    fprintf(stderr, "FAIL true %s\n", expr);
    return 1;
  }
  return 0;
}

int main(void) {
  sexp ctx = sexp_create_context(0, 0, NULL);
  sexp res;
  int nfail = 0;

  if (!ctx || sexp_exceptionp(ctx)) return fail("create_context");
  res = sexp_load_default_libs(ctx);
  if (sexp_exceptionp(res)) return fail("load_default_libs");

#if !SEXP_USE_FLONUMS
  return fail("FLONUMS should be on");
#endif
#if SEXP_USE_BIGNUMS
  return fail("BIGNUMS should be off by default");
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
  sexp_delete_context(ctx);
  return 0;
}
