/* ---- puchi high-level API ---- */
SEXP_API sexp sexp_create_context(sexp_uint_t heap_size, sexp_uint_t heap_max_size, const puchi_host *host);
SEXP_API sexp sexp_delete_context(sexp ctx);
SEXP_API sexp sexp_load_default_libs(sexp ctx);
SEXP_API sexp sexp_enable_modules(sexp ctx, const puchi_module_ops *ops);

#ifdef __cplusplus
} /* extern "C" declarations */
#endif

/* ========================================================================== */
#if defined(PUCHI_IMPLEMENTATION)
/* ========================================================================== */

#ifdef __cplusplus
extern "C" {
#endif

/* Forward decl — defined after embedded init-7; used by load_standard_env. */
static sexp puchi_load_init7_into_env(sexp ctx, sexp env);
