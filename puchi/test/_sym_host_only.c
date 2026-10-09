#include <stdio.h>
#include "../puchi.h"
puchi (*fp)(puchi_uint_t, puchi_uint_t, const puchi_host *);
void host_probe(void) { fp = puchi_create_context; }
