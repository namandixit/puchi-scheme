static sexp puchi_eval_scheme_text(sexp ctx, const char *text, sexp_sint_t len, sexp env,
                                   int mark_source) {
  sexp res;
  sexp_gc_var4(ctx2, x, in, s);
  sexp_gc_preserve4(ctx, ctx2, x, in, s);
  res = SEXP_VOID;
  s = sexp_c_string(ctx, text, len);
  in = sexp_open_input_string(ctx, s);
  if (sexp_exceptionp(in)) {
    sexp_gc_release4(ctx);
    return in;
  }
  if (mark_source)
    sexp_port_sourcep(in) = 1;
  ctx2 = sexp_make_eval_context(ctx, NULL, env, 0, 0);
  sexp_context_parent(ctx2) = ctx;
  sexp_context_tailp(ctx2) = 0;
  while ((x = sexp_read(ctx2, in)) != (sexp)SEXP_EOF) {
    res = sexp_exceptionp(x) ? x : sexp_eval(ctx2, x, env);
    if (sexp_exceptionp(res)) {
      sexp_close_port(ctx, in);
      sexp_gc_release4(ctx);
      return res;
    }
  }
  sexp_close_port(ctx, in);
  sexp_gc_release4(ctx);
  return SEXP_VOID;
}

static sexp puchi_load_init7_into_env(sexp ctx, sexp env) {
  sexp res;
  sexp sym;
  if (!ctx || sexp_exceptionp(ctx)) return ctx;
  if (!env) env = sexp_context_env(ctx);
  sym = sexp_intern(ctx, "*puchi-default-libs*", -1);
  if (sexp_env_ref(ctx, env, sym, SEXP_FALSE) != SEXP_FALSE)
    return env;
  {
    sexp fsym = sexp_intern(ctx, "*features*", -1);
    sexp_env_define(ctx, env, fsym, sexp_global(ctx, SEXP_G_FEATURES));
  }
  res = puchi_eval_scheme_text(ctx, puchi_init7_scm, -1, env, 0);
  if (sexp_exceptionp(res)) return res;
  {
    sexp esym = sexp_intern(ctx, "current-exception-handler", -1);
    sexp_global(ctx, SEXP_G_ERR_HANDLER) = sexp_env_ref(ctx, env, esym, SEXP_FALSE);
  }
  sexp_set_parameter(ctx, env, sexp_global(ctx, SEXP_G_INTERACTION_ENV_SYMBOL), env);
  sexp_env_define(ctx, env, sym, SEXP_TRUE);
  return env;
}

sexp sexp_create_context(sexp_uint_t heap_size, sexp_uint_t heap_max_size, const puchi_host *host) {
  puchi_host_init(host);
  sexp_scheme_init();
  return sexp_make_eval_context(NULL, NULL, NULL, heap_size, heap_max_size);
}

sexp sexp_delete_context(sexp ctx) {
  return sexp_destroy_context(ctx);
}

sexp sexp_load_default_libs(sexp ctx) {
  if (!ctx || sexp_exceptionp(ctx)) return ctx;
  return puchi_load_init7_into_env(ctx, sexp_context_env(ctx));
}
