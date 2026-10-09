/* sexp_* aliases for puchi_TEST_* — only when both IMPLEMENTATION and TEST
 * (clibs stubs). Do not emit under IMPLEMENTATION alone. */
#define sexp_so_extension puchi_TEST_so_extension
typedef puchi_abi_identifier_t sexp_abi_identifier_t;
#define SEXP_ABI_IDENTIFIER PUCHI_TEST_ABI_IDENTIFIER
#define sexp_version_compatible puchi_TEST_version_compatible
#define sexp_abi_compatible puchi_TEST_abi_compatible
