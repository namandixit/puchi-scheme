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

/* Uniform-vector literal must be accepted (ok=1) or rejected (ok=0).
 * Out-of-range bignums used to slip through and store truncated values.
 * Scheme catches the reader error and returns a fixnum, so this check does
 * not depend on host-side type tags (those shift when only some TUs define
 * PUCHI_TEST, as puchi_impl.c does). */
static int expect_uvector(puchi ctx, const char *lit, int ok) {
  char src[320];
  puchi r;
  snprintf(src, sizeof src,
           "(call-with-current-continuation (lambda (k) (with-exception-handler"
           " (lambda (e) (k 0)) (lambda () (read (open-input-string \"%s\")) 1))))",
           lit);
  r = puchi_eval_string(ctx, src, (puchi_sint_t)-1, NULL);
  if (puchi_fixnump(r) && puchi_unbox_fixnum(r) == (ok ? 1 : 0)) return 0;
  fprintf(stderr, "FAIL: %s should be %s\n", lit, ok ? "accepted" : "rejected");
  return 1;
}

/* puchi_integer_to_sint64 / _uint64 on src: fits (ok=1, value want) or not. */
static int expect_s64(puchi ctx, const char *src, int ok, int64_t want) {
  int64_t v = 12345;
  int got = puchi_integer_to_sint64(puchi_eval_string(ctx, src, (puchi_sint_t)-1, NULL), &v);
  if (got == ok && (!ok ? v == 12345 : v == want)) return 0;
  fprintf(stderr, "FAIL: puchi_integer_to_sint64(%s) -> %d, %lld\n", src, got, (long long)v);
  return 1;
}
static int expect_u64(puchi ctx, const char *src, int ok, uint64_t want) {
  uint64_t v = 12345;
  int got = puchi_integer_to_uint64(puchi_eval_string(ctx, src, (puchi_sint_t)-1, NULL), &v);
  if (got == ok && (!ok ? v == 12345 : v == want)) return 0;
  fprintf(stderr, "FAIL: puchi_integer_to_uint64(%s) -> %d, %llu\n", src, got, (unsigned long long)v);
  return 1;
}

static int bignum_checks(puchi ctx) {
  int nfail = 0;
  nfail += expect_uvector(ctx, "#u64(18446744073709551615)", 1);   /* 2^64-1 */
  nfail += expect_uvector(ctx, "#u64(18446744073709551616)", 0);   /* 2^64 */
  nfail += expect_uvector(ctx, "#u64(-1)", 0);
  nfail += expect_uvector(ctx, "#s64(9223372036854775807)", 1);    /* 2^63-1 */
  nfail += expect_uvector(ctx, "#s64(-9223372036854775808)", 1);   /* -2^63 */
  nfail += expect_uvector(ctx, "#s64(9223372036854775808)", 0);    /* 2^63 */
  nfail += expect_uvector(ctx, "#s64(-9223372036854775809)", 0);   /* -2^63-1 */
  nfail += expect_uvector(ctx, "#u32(18446744073709551617)", 0);   /* 2^64+1 */
  nfail += expect_uvector(ctx, "#u16(18446744073709551617)", 0);
  nfail += expect_uvector(ctx, "#u8(18446744073709551617)", 0);

  nfail += expect_s64(ctx, "5", 1, 5);
  nfail += expect_s64(ctx, "-5", 1, -5);
  nfail += expect_s64(ctx, "9223372036854775807", 1, INT64_MAX);
  nfail += expect_s64(ctx, "-9223372036854775808", 1, INT64_MIN);
  nfail += expect_s64(ctx, "9223372036854775808", 0, 0);
  nfail += expect_s64(ctx, "-9223372036854775809", 0, 0);
  nfail += expect_s64(ctx, "18446744073709551621", 0, 0);         /* 2^64+5 */
  nfail += expect_s64(ctx, "1.5", 0, 0);
  nfail += expect_s64(ctx, "\"5\"", 0, 0);
  nfail += expect_u64(ctx, "5", 1, 5);
  nfail += expect_u64(ctx, "-5", 0, 0);
  nfail += expect_u64(ctx, "18446744073709551615", 1, UINT64_MAX);
  nfail += expect_u64(ctx, "18446744073709551616", 0, 0);
  nfail += expect_u64(ctx, "-9223372036854775808", 0, 0);

  /* Raw converters: non-bignum argument used to segfault; now 0. */
  if (puchi_bignum_to_sint(puchi_make_fixnum(5)) != 0 ||
      puchi_bignum_to_uint(puchi_make_fixnum(5)) != 0) {
    fprintf(stderr, "FAIL: puchi_bignum_to_sint/uint on a fixnum should be 0\n");
    nfail++;
  }
  return nfail;
}

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
  if (bignum_checks(ctx)) {
    fprintf(stderr, "bignum / uniform-vector checks failed\n");
    return 4;
  }
  printf("ok %ld\n", (long)puchi_unbox_fixnum(res));
  puchi_delete_context(ctx);
  return 0;
}
