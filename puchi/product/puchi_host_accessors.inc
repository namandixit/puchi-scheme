/* Host get/set accessors — always-visible decls; bodies under IMPL && !PUCHI_TEST_CLIB. */

PUCHI_API puchi puchi_port_name(puchi p);
PUCHI_API void puchi_port_set_name(puchi p, puchi name);
PUCHI_API void puchi_port_set_sourcep(puchi p, int v);
PUCHI_API void puchi_port_set_no_close(puchi p, int v);

PUCHI_API puchi puchi_context_parent(puchi ctx);
PUCHI_API void puchi_context_set_parent(puchi ctx, puchi parent);
PUCHI_API void puchi_context_set_tailp(puchi ctx, int v);
PUCHI_API void puchi_context_set_env(puchi ctx, puchi env);
PUCHI_API void puchi_set_global(puchi ctx, int idx, puchi val);

PUCHI_API puchi puchi_set_standard_ports(puchi ctx, puchi env, puchi in, puchi out, puchi err);
PUCHI_API void puchi_stack_trace(puchi ctx, puchi out);

/* Checked integer conversion for host code. Return 1 and store *out when x is
 * an exact integer (fixnum or bignum) that fits; otherwise return 0 and leave
 * *out unchanged. Prefer these to puchi_bignum_to_sint / puchi_bignum_to_uint,
 * which only read a bignum's low 64 bits (raw bits, no range check). */
PUCHI_API int puchi_integer_to_sint64(puchi x, int64_t *out);
PUCHI_API int puchi_integer_to_uint64(puchi x, uint64_t *out);

#ifndef puchi_opcodep
#define puchi_opcodep(x) (puchi_check_tag((x), PUCHI_OPCODE))
#endif
