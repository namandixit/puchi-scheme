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

#if defined(PUCHI_ENABLE_NUMERICAL_TOWER)
/* Magnitude of a bignum if it fits in one 64-bit limb (higher limbs zero). */
static int puchi_bignum_magnitude64(puchi x, uint64_t *mag) {
  sexp_uint_t i;
  for (i = 1; i < sexp_bignum_length(x); i++)
    if (sexp_bignum_data(x)[i])
      return 0;
  *mag = (uint64_t)sexp_bignum_data(x)[0];
  return 1;
}
#endif

PUCHI_API int puchi_integer_to_sint64(puchi x, int64_t *out) {
#if defined(PUCHI_ENABLE_NUMERICAL_TOWER)
  uint64_t mag;
#endif
  if (sexp_fixnump(x)) {
    if (out) *out = (int64_t)sexp_unbox_fixnum(x);
    return 1;
  }
#if defined(PUCHI_ENABLE_NUMERICAL_TOWER)
  if (sexp_bignump(x) && puchi_bignum_magnitude64(x, &mag)) {
    if (sexp_bignum_sign(x) > 0) {
      if (mag > (uint64_t)INT64_MAX) return 0;
      if (out) *out = (int64_t)mag;
      return 1;
    }
    if (mag > (uint64_t)INT64_MAX + 1u) return 0;
    if (out) *out = (mag == (uint64_t)INT64_MAX + 1u) ? INT64_MIN : -(int64_t)mag;
    return 1;
  }
#endif
  return 0;
}

PUCHI_API int puchi_integer_to_uint64(puchi x, uint64_t *out) {
#if defined(PUCHI_ENABLE_NUMERICAL_TOWER)
  uint64_t mag;
#endif
  if (sexp_fixnump(x)) {
    if (sexp_unbox_fixnum(x) < 0) return 0;
    if (out) *out = (uint64_t)sexp_unbox_fixnum(x);
    return 1;
  }
#if defined(PUCHI_ENABLE_NUMERICAL_TOWER)
  if (sexp_bignump(x) && sexp_bignum_sign(x) > 0 && puchi_bignum_magnitude64(x, &mag)) {
    if (out) *out = mag;
    return 1;
  }
#endif
  return 0;
}
