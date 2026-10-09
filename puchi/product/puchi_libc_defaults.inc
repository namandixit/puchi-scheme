/* Portable strcasecmp / strncasecmp (not ISO C). Emitted under
 * PUCHI_IMPLEMENTATION || PUCHI_TEST after diag push. Uses PUCHI_TOLOWER. */
static inline int puchi_strcasecmp(const char *a, const char *b) {
  unsigned char ca, cb;
  for (;;) {
    ca = (unsigned char)PUCHI_TOLOWER((unsigned char)*a++);
    cb = (unsigned char)PUCHI_TOLOWER((unsigned char)*b++);
    if (ca != cb) return (int)ca - (int)cb;
    if (ca == 0) return 0;
  }
}
static inline int puchi_strncasecmp(const char *a, const char *b, size_t n) {
  unsigned char ca, cb;
  if (n == 0) return 0;
  do {
    ca = (unsigned char)PUCHI_TOLOWER((unsigned char)*a++);
    cb = (unsigned char)PUCHI_TOLOWER((unsigned char)*b++);
    if (ca != cb) return (int)ca - (int)cb;
    if (ca == 0) return 0;
  } while (--n != 0);
  return 0;
}
