/* ---- puchi high-level API ---- */
SEXP_API sexp sexp_create_context(sexp_uint_t heap_size, sexp_uint_t heap_max_size, const puchi_host *host);
SEXP_API sexp sexp_delete_context(sexp ctx);
SEXP_API sexp sexp_load_default_libs(sexp ctx);
SEXP_API sexp sexp_enable_modules(sexp ctx, const puchi_module_ops *ops);
/* Root create only; other callers use sexp_make_eval_context (host = NULL). */
SEXP_API sexp sexp_make_eval_context_host(sexp ctx, sexp stack, sexp env,
                                          sexp_uint_t size, sexp_uint_t max_size,
                                          const puchi_host *host);

#ifdef __cplusplus
} /* extern "C" declarations */
#endif

/* ========================================================================== */
#if defined(PUCHI_IMPLEMENTATION)
/* ========================================================================== */

#ifdef __cplusplus
extern "C" {
#endif

/* Host callbacks live on sexp_context_heap(ctx)->host (set by sexp_make_heap). */
static void *puchi_host_alloc(void *ctx_v, size_t size) {
  sexp ctx = (sexp)ctx_v;
  sexp_heap h;
  if (!ctx || !sexp_pointerp(ctx) || !sexp_contextp(ctx))
    puchi_fatal(NULL, PUCHI_FATAL_INTERNAL, "no host alloc");
  h = sexp_context_heap(ctx);
  if (!h || !h->host.alloc)
    puchi_fatal(ctx, PUCHI_FATAL_INTERNAL, "no host alloc");
  return h->host.alloc(h->host.userdata, size);
}

static void puchi_host_free(void *ctx_v, void *ptr) {
  sexp ctx = (sexp)ctx_v;
  sexp_heap h;
  if (!ctx || !sexp_pointerp(ctx) || !sexp_contextp(ctx))
    puchi_fatal(NULL, PUCHI_FATAL_INTERNAL, "no host free");
  h = sexp_context_heap(ctx);
  if (!h || !h->host.free)
    puchi_fatal(ctx, PUCHI_FATAL_INTERNAL, "no host free");
  h->host.free(h->host.userdata, ptr);
}

static void puchi_diagnose(void *ctx_v, int code, const char *msg) {
  sexp ctx = (sexp)ctx_v;
  sexp_heap h;
  if (!ctx || !sexp_pointerp(ctx) || !sexp_contextp(ctx) ||
      !(h = sexp_context_heap(ctx)) || !h->host.diagnose) {
    puchi_default_fatal(NULL, PUCHI_FATAL_INTERNAL, "puchi_host required");
  }
  h->host.diagnose(h->host.userdata, code, msg ? msg : "");
}

PUCHI_NORETURN static void puchi_fatal(void *ctx_v, int code, const char *msg) {
  sexp ctx = (sexp)ctx_v;
  sexp_heap h;
  if (ctx && sexp_pointerp(ctx) && sexp_contextp(ctx) &&
      (h = sexp_context_heap(ctx)) && h->host.fatal) {
    h->host.fatal(h->host.userdata, code, msg ? msg : "");
  } else {
    puchi_default_fatal(NULL, code, msg ? msg : "");
  }
  for (;;) {
  }
}

/* Forward decl — defined after embedded init-7; used by load_standard_env. */
static sexp puchi_load_init7_into_env(sexp ctx, sexp env);
