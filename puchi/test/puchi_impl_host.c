/* Body TU as an embedder builds it: PUCHI_IMPLEMENTATION only, no PUCHI_TEST.
 * Numeric mode comes from the compiler (-DPUCHI_INTEGER_ONLY /
 * -DPUCHI_ENABLE_NUMERICAL_TOWER), like puchi_impl.c.
 *
 * The smoke tests (puchi_smoke, puchi_slim_smoke, puchi_integer_smoke,
 * puchi_two_host_smoke) include puchi.h without PUCHI_TEST, so they must link
 * against a body built the same way. puchi.h's type numbering and struct
 * layouts depend on PUCHI_TEST; mixing the two corrupts type checks (for
 * example puchi_exceptionp never matched). The harness and its clibs define
 * PUCHI_TEST everywhere and use puchi_impl.c instead. */
#include <stdio.h>
#include <stdlib.h>
#define PUCHI_IMPLEMENTATION
#include "../puchi.h"
