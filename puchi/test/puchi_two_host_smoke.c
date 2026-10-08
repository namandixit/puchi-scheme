/* Two contexts, two hosts — allocators must not cross. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "puchi_test_diagnostics.h"
#ifndef PUCHI_ENABLE_NUMERICAL_TOWER
#define PUCHI_ENABLE_NUMERICAL_TOWER
#endif
#define PUCHI_IMPLEMENTATION
#include "../puchi.h"

PUCHI_DIAG_HARNESS_PEDANTIC_OFF

typedef struct {
  const char *tag;
  size_t allocs;
  size_t frees;
} host_stats;

static void *stats_alloc(void *ud, size_t n) {
  host_stats *s = (host_stats *)ud;
  void *p = malloc(n);
  if (p) s->allocs++;
  return p;
}
static void stats_free(void *ud, void *p) {
  host_stats *s = (host_stats *)ud;
  if (p) s->frees++;
  free(p);
}
static void stats_diag(void *ud, int c, const char *m) {
  (void)ud; (void)c; (void)m;
}
static PUCHI_NORETURN void stats_fatal(void *ud, int c, const char *m) {
  host_stats *s = (host_stats *)ud;
  fprintf(stderr, "fatal[%s] %d: %s\n", s ? s->tag : "?", c, m ? m : "");
  exit(70);
}

static int run_ctx(host_stats *st, const char *expr, long expect) {
  puchi_host host = { st, stats_alloc, stats_free, stats_diag, stats_fatal };
  sexp ctx, res;
  size_t before = st->allocs;
  ctx = sexp_create_context((size_t)0, (size_t)0, &host);
  if (!ctx || sexp_exceptionp(ctx)) {
    fprintf(stderr, "[%s] create_context failed\n", st->tag);
    return 1;
  }
  if (st->allocs <= before) {
    fprintf(stderr, "[%s] create did not use host alloc\n", st->tag);
    return 2;
  }
  res = sexp_load_default_libs(ctx);
  if (sexp_exceptionp(res)) {
    fprintf(stderr, "[%s] load_default_libs failed\n", st->tag);
    return 3;
  }
  res = sexp_eval_string(ctx, expr, (sexp_sint_t)-1, NULL);
  if (sexp_exceptionp(res) || !sexp_fixnump(res) ||
      (long)sexp_unbox_fixnum(res) != expect) {
    fprintf(stderr, "[%s] eval failed\n", st->tag);
    return 4;
  }
  sexp_delete_context(ctx);
  return 0;
}

int main(void) {
  host_stats a = { "A", 0, 0 };
  host_stats b = { "B", 0, 0 };
  size_t a_allocs, b_allocs;
  int rc;

  rc = run_ctx(&a, "(+ 10 20)", 30);
  if (rc) return rc;
  a_allocs = a.allocs;

  rc = run_ctx(&b, "(+ 1 2 3)", 6);
  if (rc) return rc;
  b_allocs = b.allocs;

  if (a.allocs != a_allocs) {
    fprintf(stderr, "host A allocs changed while creating B (%zu -> %zu)\n",
            a_allocs, a.allocs);
    return 5;
  }
  if (b_allocs == 0) {
    fprintf(stderr, "host B never allocated\n");
    return 6;
  }
  printf("ok A.allocs=%zu B.allocs=%zu A.frees=%zu B.frees=%zu\n",
         a.allocs, b.allocs, a.frees, b.frees);
  return 0;
}
