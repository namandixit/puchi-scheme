/* Product-owned PUCHI_TEST API (harness STATIC_LIBS / include-shared).
 * Visible under #if PUCHI_TEST only. Prefix: puchi_TEST_*.
 * No Chibi sexp names here — those aliases live under PUCHI_IMPLEMENTATION.
 * Function decls are in puchi_test_api_decls.inc (after host ABI types). */
#if !defined(puchi_TEST_so_extension)
#define puchi_TEST_so_extension ".so"
#endif
typedef char puchi_TEST_abi_identifier_t[8];
typedef puchi_TEST_abi_identifier_t puchi_abi_identifier_t;
#define PUCHI_TEST_ABI_IDENTIFIER "--------"
#define puchi_TEST_version_compatible(ctx, subver, genver) 1
#define puchi_TEST_abi_compatible(ctx, subabi, genabi) 1
typedef struct puchi_library_entry_t puchi_TEST_library_entry_t;
