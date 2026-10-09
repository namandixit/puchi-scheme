/* PUCHI_IMPLEMENTATION helpers — math constants, IEEE bit-cast for
 * sexp_pos_infinity/nan, default host callbacks, SEXP_MALLOC.
 * CRT includes: puchi_crt_includes.inc (IMPLEMENTATION || TEST). */
#ifndef M_LN10
#define M_LN10 2.30258509299404568402
#endif
#ifndef M_PI
#define M_PI 3.14159265358979323846
#endif

static inline double puchi_f64_from_bits(uint64_t u) {
  double d;
  PUCHI_MEMCPY(&d, &u, sizeof(d));
  return d;
}

static void puchi_default_diagnose(void *ud, int code, const char *msg) {
  (void)ud;
  (void)code;
  (void)msg;
}
PUCHI_NORETURN static void puchi_default_fatal(void *ud, int code, const char *msg) {
  (void)ud;
  (void)code;
  (void)msg;
  for (;;) {
  }
}

/* Defined in puchi_impl_host.inc (need sexp_context_heap). */
static void *puchi_host_alloc(void *ctx, size_t size);
static void puchi_host_free(void *ctx, void *ptr);
static void puchi_diagnose(void *ctx, int code, const char *msg);
PUCHI_NORETURN static void puchi_fatal(void *ctx, int code, const char *msg);

#ifndef SEXP_MALLOC
#define SEXP_MALLOC(ctx, size) puchi_host_alloc((void *)(ctx), (size))
#endif
#ifndef SEXP_FREE
#define SEXP_FREE(ctx, ptr) puchi_host_free((void *)(ctx), (ptr))
#endif
