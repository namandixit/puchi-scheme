/* Integer-only: fixnums only. Scheme libs on disk often contain float
 * literals the reader rejects without flonums, so this is a C-side suite
 * against the embedded init (no module imports). */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "puchi_test_diagnostics.h"
#ifndef PUCHI_INTEGER_ONLY
#define PUCHI_INTEGER_ONLY
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

static int fail(const char *msg) {
  fprintf(stderr, "FAIL: %s\n", msg);
  return 1;
}

static int expect_fix(puchi ctx, const char *expr, long want) {
  puchi res = puchi_eval_string(ctx, expr, (puchi_sint_t)-1, NULL);
  if (puchi_exceptionp(res)) {
    fprintf(stderr, "FAIL eval %s: exception\n", expr);
    puchi_print_exception(ctx, res, puchi_current_error_port(ctx));
    return 1;
  }
  if (!puchi_fixnump(res) || (long)puchi_unbox_fixnum(res) != want) {
    fprintf(stderr, "FAIL %s => expected %ld\n", expr, want);
    return 1;
  }
  return 0;
}

static int expect_true(puchi ctx, const char *expr) {
  puchi res = puchi_eval_string(ctx, expr, (puchi_sint_t)-1, NULL);
  if (puchi_exceptionp(res) || res == PUCHI_FALSE) {
    fprintf(stderr, "FAIL expect true: %s\n", expr);
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

#if !defined(PUCHI_INTEGER_ONLY)
  return fail("PUCHI_INTEGER_ONLY should be set");
#endif
#if defined(PUCHI_ENABLE_NUMERICAL_TOWER)
  return fail("tower should be off");
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
  puchi_delete_context(ctx);
  return 0;
}
