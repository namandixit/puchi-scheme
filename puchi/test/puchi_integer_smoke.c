/* Integer-only: fixnums only. Scheme libs on disk often contain float
 * literals the reader rejects without flonums, so this is a C-side suite
 * against the embedded init (no module imports). */
#include <stdio.h>
#include <string.h>
#define PUCHI_INTEGER_ONLY
#define PUCHI_IMPLEMENTATION
#include "../puchi.h"

static int fail(const char *msg) {
  fprintf(stderr, "FAIL: %s\n", msg);
  return 1;
}

static int expect_fix(sexp ctx, const char *expr, long want) {
  sexp res = sexp_eval_string(ctx, expr, -1, NULL);
  if (sexp_exceptionp(res)) {
    fprintf(stderr, "FAIL eval %s: exception\n", expr);
    sexp_print_exception(ctx, res, sexp_current_error_port(ctx));
    return 1;
  }
  if (!sexp_fixnump(res) || sexp_unbox_fixnum(res) != want) {
    fprintf(stderr, "FAIL %s => expected %ld\n", expr, want);
    return 1;
  }
  return 0;
}

static int expect_true(sexp ctx, const char *expr) {
  sexp res = sexp_eval_string(ctx, expr, -1, NULL);
  if (sexp_exceptionp(res) || res == SEXP_FALSE) {
    fprintf(stderr, "FAIL expect true: %s\n", expr);
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

#if SEXP_USE_FLONUMS
  return fail("FLONUMS should be off");
#endif
#if SEXP_USE_BIGNUMS
  return fail("BIGNUMS should be off");
#endif

  nfail += expect_fix(ctx, "(+ 40 2)", 42);
  nfail += expect_fix(ctx, "(- 40 2)", 38);
  nfail += expect_fix(ctx, "(* 40 2)", 80);
  nfail += expect_fix(ctx, "(quotient 41 2)", 20);
  nfail += expect_fix(ctx, "(remainder 41 2)", 1);
  nfail += expect_fix(ctx, "(apply + '(1 2 3 4))", 10);
  nfail += expect_fix(ctx, "(let fact ((n 5)) (if (zero? n) 1 (* n (fact (- n 1)))))", 120);
  nfail += expect_fix(ctx, "(length '(a b c))", 3);
  nfail += expect_fix(ctx, "(vector-ref (vector 10 20 30) 1)", 20);
  nfail += expect_true(ctx, "(odd? 3)");
  nfail += expect_true(ctx, "(even? 4)");
  nfail += expect_true(ctx, "(= (+ 1 2) 3)");
  nfail += expect_true(ctx, "(< 1 2 3)");

  /* No bignum promotion — result stays an exact integer (wrapped fixnum). */
  nfail += expect_true(ctx, "(exact-integer? (* 1000000000 1000000000))");

  if (nfail) {
    fprintf(stderr, "%d integer-only checks failed\n", nfail);
    return 1;
  }
  printf("integer-only ok (%d checks)\n", 14);
  sexp_delete_context(ctx);
  return 0;
}
