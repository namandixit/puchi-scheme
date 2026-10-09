/* Host accessor bodies — IMPLEMENTATION && !PUCHI_TEST_CLIB. */

PUCHI_API puchi puchi_port_name(puchi p) {
  return sexp_port_name(p);
}

PUCHI_API void puchi_port_set_name(puchi p, puchi name) {
  sexp_port_name(p) = name;
}

PUCHI_API void puchi_port_set_sourcep(puchi p, int v) {
  sexp_port_sourcep(p) = v;
}

PUCHI_API void puchi_port_set_no_close(puchi p, int v) {
  sexp_port_no_closep(p) = v;
}

PUCHI_API puchi puchi_context_parent(puchi ctx) {
  return sexp_context_parent(ctx);
}

PUCHI_API void puchi_context_set_parent(puchi ctx, puchi parent) {
  sexp_context_parent(ctx) = parent;
}

PUCHI_API void puchi_context_set_tailp(puchi ctx, int v) {
  sexp_context_tailp(ctx) = v;
}

PUCHI_API void puchi_context_set_env(puchi ctx, puchi env) {
  sexp_context_env(ctx) = env;
}

PUCHI_API void puchi_set_global(puchi ctx, int idx, puchi val) {
  sexp_global(ctx, idx) = val;
}

PUCHI_API puchi puchi_set_standard_ports(puchi ctx, puchi env, puchi in, puchi out, puchi err) {
  return sexp_set_standard_ports(ctx, env, in, out, err);
}

PUCHI_API void puchi_stack_trace(puchi ctx, puchi out) {
  sexp_stack_trace(ctx, out);
}
