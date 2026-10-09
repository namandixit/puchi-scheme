/* Single-TU PUCHI_STATIC smoke: host entrypoints are static in this TU. */
#include <stdio.h>
#include <stdlib.h>

#define PUCHI_STATIC
#define PUCHI_IMPLEMENTATION
#include "../puchi.h"

static void *smoke_alloc(void *ud, size_t n) {
  (void)ud;
  return malloc(n);
}
static void smoke_free(void *ud, void *p) {
  (void)ud;
  free(p);
}
static void smoke_diagnose(void *ud, int c, const char *m) {
  (void)ud;
  (void)c;
  (void)m;
}
static PUCHI_NORETURN void smoke_fatal(void *ud, int c, const char *m) {
  (void)ud;
  fprintf(stderr, "fatal %d: %s\n", c, m ? m : "");
  exit(70);
}

int main(void) {
  puchi_host host = {0};
  puchi ctx;

  host.alloc = smoke_alloc;
  host.free = smoke_free;
  host.diagnose = smoke_diagnose;
  host.fatal = smoke_fatal;

  ctx = puchi_create_context((puchi_uint_t)0, (puchi_uint_t)0, &host);
  if (!ctx || puchi_exceptionp(ctx)) {
    fprintf(stderr, "FAIL: create_context\n");
    return 1;
  }
  puchi_delete_context(ctx);
  return 0;
}
