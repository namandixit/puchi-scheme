/* Product-owned PUCHI_TEST API (harness STATIC_LIBS / include-shared).
 * Always-visible under #if PUCHI_TEST. Prefix: puchi_TEST_*. */
#if !defined(puchi_TEST_so_extension)
#define puchi_TEST_so_extension ".so"
#endif
/* Chibi sources still use sexp_so_extension under PUCHI_TEST */
#define sexp_so_extension puchi_TEST_so_extension
typedef char puchi_TEST_abi_identifier_t[8];
typedef puchi_TEST_abi_identifier_t puchi_abi_identifier_t;
typedef puchi_abi_identifier_t sexp_abi_identifier_t;
#define PUCHI_TEST_ABI_IDENTIFIER "--------"
#define SEXP_ABI_IDENTIFIER PUCHI_TEST_ABI_IDENTIFIER
#define puchi_TEST_version_compatible(ctx, subver, genver) 1
#define puchi_TEST_abi_compatible(ctx, subabi, genabi) 1
#define sexp_version_compatible puchi_TEST_version_compatible
#define sexp_abi_compatible puchi_TEST_abi_compatible
/* STATIC_LIBS table install (Chibi sexp_add_static_libraries) */
#define puchi_TEST_add_static_libraries sexp_add_static_libraries
typedef struct puchi_library_entry_t puchi_TEST_library_entry_t;
