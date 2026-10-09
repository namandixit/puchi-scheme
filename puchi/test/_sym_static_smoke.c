#include <stdio.h>
#include <stdlib.h>
#define PUCHI_STATIC
#define PUCHI_IMPLEMENTATION
#include "../puchi.h"
static void *a(void *u, size_t n) { (void)u; return malloc(n); }
static void fr(void *u, void *p) { (void)u; free(p); }
static void d(void *u, int c, const char *m) { (void)u;(void)c;(void)m; }
static void fatal(void *u, int c, const char *m) { (void)u;(void)c;(void)m; abort(); }
int main(void) {
  puchi_host h = {0};
  h.alloc = a; h.free = fr; h.diagnose = d; h.fatal = fatal;
  puchi ctx = puchi_create_context(0, 0, &h);
  if (!ctx) return 1;
  puchi_delete_context(ctx);
  return 0;
}
