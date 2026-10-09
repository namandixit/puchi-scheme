/* Sole body TU for puchi tests (stb bodies + wrappers).
 * Numeric mode comes from the compiler (-DPUCHI_INTEGER_ONLY /
 * -DPUCHI_ENABLE_NUMERICAL_TOWER). Define PUCHI_TEST so STATIC_LIBS /
 * opcode_names paths inside Chibi .c compile; do not set PUCHI_TEST_CLIB
 * (that suppresses bodies for harness clibs). */
#include <stdio.h>
#include <stdlib.h>
#define PUCHI_IMPLEMENTATION
#define PUCHI_TEST 1
#include "../puchi.h"
