/* puchi_redirect.h - included by puchi_impl.c after every system header and
 * before the first upstream .c file.  Every OS-facing function that the
 * upstream sources call is redirected here.  A redirect may only
 *   (1) STUB    - the call sits on a path that cannot run in puchi (it needs
 *                 a FILE*, a file descriptor, a socket or a missing error
 *                 port, and puchi never creates any of those);
 *   (2) DENY    - the capability is removed; the failure value is the answer;
 *   (3) ROUTE   - a one-sentence contract served by the VM's host/allocator.
 * It must never EMULATE an OS API.  Function-like macros are used so that
 * struct members and parameters with the same names are untouched.
 * puchi_impl.c defines the puchi_os_* functions after the upstream sources. */

#ifndef PUCHI_REDIRECT_H
#define PUCHI_REDIRECT_H

static void *puchi_os_malloc(sexp ctx, size_t size);
static void *puchi_os_calloc(sexp ctx, size_t n, size_t size);
static void puchi_os_free(sexp ctx, void *ptr);
static int puchi_os_snprintf(sexp ctx, char *buf, size_t size, const char *fmt, ...);
static int puchi_os_sscanf_double(sexp ctx, const char *str, const char *fmt, double *out);
static int puchi_os_stat(sexp ctx, const char *path);
static void puchi_os_exit(sexp ctx, int code);
static void puchi_os_unreachable(const char *name);
static void puchi_os_denied(const char *name);

/* ASCII replacements: the C library versions depend on the process locale. */
SEXP_NO_WARN_UNUSED static int puchi_ascii_isalpha(int c) { return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z'); }
SEXP_NO_WARN_UNUSED static int puchi_ascii_isdigit(int c) { return c >= '0' && c <= '9'; }
SEXP_NO_WARN_UNUSED static int puchi_ascii_isxdigit(int c) {
  return puchi_ascii_isdigit(c) || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F');
}
SEXP_NO_WARN_UNUSED static int puchi_ascii_isspace(int c) { return c == ' ' || (c >= '\t' && c <= '\r'); }
SEXP_NO_WARN_UNUSED static int puchi_ascii_tolower(int c) { return (c >= 'A' && c <= 'Z') ? c + ('a' - 'A') : c; }
SEXP_NO_WARN_UNUSED static int puchi_ascii_toupper(int c) { return (c >= 'a' && c <= 'z') ? c - ('a' - 'A') : c; }
SEXP_NO_WARN_UNUSED static int puchi_ascii_strncasecmp(const char *a, const char *b, size_t n) {
  for (; n > 0; a++, b++, n--) {
    int d = puchi_ascii_tolower((unsigned char)*a) - puchi_ascii_tolower((unsigned char)*b);
    if (d != 0 || *a == '\0') return d;
  }
  return 0;
}
SEXP_NO_WARN_UNUSED static int puchi_ascii_strcasecmp(const char *a, const char *b) {
  return puchi_ascii_strncasecmp(a, b, (size_t)-1);
}

#ifdef _WIN32
SEXP_NO_WARN_UNUSED static int puchi_win_getenv_s(size_t *len, char *buf, size_t size, const char *name) {
  (void)buf; (void)size; (void)name;
  puchi_os_denied("getenv_s");
  if (len) *len = 0;
  return 0;                                /* "not set" */
}
SEXP_NO_WARN_UNUSED static int puchi_win_putenv_s(const char *name, const char *value) {
  (void)name; (void)value;
  puchi_os_denied("_putenv_s");
  return 22;                               /* EINVAL */
}
#endif

/* puchi_os_* are defined in puchi_glue.c.  The helpers below are marked
 * SEXP_NO_WARN_UNUSED (sexp.h) because the configuration decides which are used. */

/* Typed helpers: a function call used as a statement draws no warning.
 * puchi_os_unreachable aborts in test builds (PUCHI_CHECK_UNREACHABLE) and
 * does nothing otherwise; puchi_os_denied does nothing. */
SEXP_NO_WARN_UNUSED static int puchi_stub_int(const char *name, int value) { puchi_os_unreachable(name); return value; }
SEXP_NO_WARN_UNUSED static long puchi_stub_long(const char *name, long value) { puchi_os_unreachable(name); return value; }
SEXP_NO_WARN_UNUSED static size_t puchi_stub_size(const char *name) { puchi_os_unreachable(name); return 0; }
SEXP_NO_WARN_UNUSED static void *puchi_stub_ptr(const char *name) { puchi_os_unreachable(name); return NULL; }
SEXP_NO_WARN_UNUSED static int puchi_deny_int(const char *name, int value) { puchi_os_denied(name); return value; }
SEXP_NO_WARN_UNUSED static void *puchi_deny_ptr(const char *name) { puchi_os_denied(name); return NULL; }

/* save the host's definitions; puchi_unredirect.h restores them */
#pragma push_macro("getc")
#undef getc
#pragma push_macro("ungetc")
#undef ungetc
#pragma push_macro("putc")
#undef putc
#pragma push_macro("fputc")
#undef fputc
#pragma push_macro("fputs")
#undef fputs
#pragma push_macro("fflush")
#undef fflush
#pragma push_macro("fclose")
#undef fclose
#pragma push_macro("clearerr")
#undef clearerr
#pragma push_macro("ferror")
#undef ferror
#pragma push_macro("fgets")
#undef fgets
#pragma push_macro("fileno")
#undef fileno
#pragma push_macro("fseek")
#undef fseek
#pragma push_macro("ftell")
#undef ftell
#pragma push_macro("fread")
#undef fread
#pragma push_macro("fwrite")
#undef fwrite
#pragma push_macro("fopen")
#undef fopen
#pragma push_macro("select")
#undef select
#pragma push_macro("usleep")
#undef usleep
#pragma push_macro("poll")
#undef poll
#pragma push_macro("fcntl")
#undef fcntl
#pragma push_macro("shutdown")
#undef shutdown
#pragma push_macro("stderr")
#undef stderr
#pragma push_macro("FD_ZERO")
#undef FD_ZERO
#pragma push_macro("FD_SET")
#undef FD_SET
#pragma push_macro("FD_ISSET")
#undef FD_ISSET
#pragma push_macro("getenv")
#undef getenv
#pragma push_macro("setenv")
#undef setenv
#pragma push_macro("unsetenv")
#undef unsetenv
#pragma push_macro("strerror")
#undef strerror
#pragma push_macro("read")
#undef read
#pragma push_macro("write")
#undef write
#pragma push_macro("close")
#undef close
#pragma push_macro("lseek")
#undef lseek
#pragma push_macro("fstat")
#undef fstat
#pragma push_macro("stat")
#undef stat
#pragma push_macro("snprintf")
#undef snprintf
#pragma push_macro("sscanf")
#undef sscanf
#pragma push_macro("exit")
#undef exit
#pragma push_macro("malloc")
#undef malloc
#pragma push_macro("calloc")
#undef calloc
#pragma push_macro("free")
#undef free
#pragma push_macro("isalpha")
#undef isalpha
#pragma push_macro("isdigit")
#undef isdigit
#pragma push_macro("isxdigit")
#undef isxdigit
#pragma push_macro("isspace")
#undef isspace
#pragma push_macro("tolower")
#undef tolower
#pragma push_macro("toupper")
#undef toupper
#pragma push_macro("strcasecmp")
#undef strcasecmp
#pragma push_macro("strncasecmp")
#undef strncasecmp
#pragma push_macro("getenv_s")
#undef getenv_s
#pragma push_macro("_putenv_s")
#undef _putenv_s

/* ---- (1) STUB ---- */
#define getc(f)               puchi_stub_int("getc", EOF)
#define ungetc(c, f)          puchi_stub_int("ungetc", EOF)
#define putc(c, f)            puchi_stub_int("putc", EOF)
#define fputc(c, f)           puchi_stub_int("fputc", EOF)
#define fputs(s, f)           puchi_stub_int("fputs", EOF)
#define fflush(f)             puchi_stub_int("fflush", EOF)
#define fclose(f)             puchi_stub_int("fclose", EOF)
#define clearerr(f)           ((void)puchi_stub_int("clearerr", 0))
#define ferror(f)             puchi_stub_int("ferror", 0)
#define fgets(b, n, f)        ((char*)puchi_stub_ptr("fgets"))
#define fileno(f)             puchi_stub_int("fileno", -1)
#define fseek(f, o, w)        puchi_stub_int("fseek", -1)
#define ftell(f)              puchi_stub_long("ftell", -1L)
#define fread(p, s, n, f)     puchi_stub_size("fread")
#define fwrite(p, s, n, f)    puchi_stub_size("fwrite")
#define fopen(p, m)           ((FILE*)puchi_stub_ptr("fopen"))
#define select(n, r, w, e, t) puchi_stub_int("select", -1)
#define usleep(u)             puchi_stub_int("usleep", -1)
#define poll(f, n, t)         puchi_stub_int("poll", -1)
#define fcntl(...)            puchi_stub_int("fcntl", -1)
#define shutdown(s, h)        puchi_stub_int("shutdown", -1)
#define stderr                ((FILE*)puchi_stub_ptr("stderr"))
#define FD_ZERO(set)          ((void)0)
#define FD_SET(fd, set)       ((void)0)
#define FD_ISSET(fd, set)     0
#ifdef _WIN32                 /* green-thread code names these; never runs */
#pragma push_macro("F_GETFL")
#pragma push_macro("F_SETFL")
#pragma push_macro("O_NONBLOCK")
#undef F_GETFL
#undef F_SETFL
#undef O_NONBLOCK
#define F_GETFL 3
#define F_SETFL 4
#define O_NONBLOCK 04000
#endif

/* ---- (2) DENY ---- */
#define getenv(n)             ((char*)puchi_deny_ptr("getenv"))
#ifndef _WIN32
#define setenv(n, v, o)       puchi_deny_int("setenv", -1)
#define unsetenv(n)           puchi_deny_int("unsetenv", -1)
#else
/* Windows: lib/chibi/ast.c DEFINES setenv/unsetenv on top of getenv_s and
 * _putenv_s, so those two are redirected instead, with object-like macros
 * (ast.c also declares getenv_s, which a function-like macro would break). */
#define getenv_s              puchi_win_getenv_s
#define _putenv_s             puchi_win_putenv_s
#endif
#define strerror(e)           ((char*)"system error")
#define read(fd, b, n)        puchi_deny_int("read", -1)
#define write(fd, b, n)       puchi_deny_int("write", -1)
#define close(fd)             puchi_deny_int("close", -1)
#define lseek(fd, o, w)       puchi_deny_int("lseek", -1)
#define fstat(fd, b)          puchi_deny_int("fstat", -1)

/* ---- (3) ROUTE ---- */
#define stat(p, b)            puchi_os_stat(ctx, p)
#define snprintf(...)         puchi_os_snprintf(ctx, __VA_ARGS__)
#define sscanf(s, fmt, out)   puchi_os_sscanf_double(ctx, s, fmt, out)
#define exit(c)               puchi_os_exit(ctx, c)
#define malloc(n)             puchi_os_malloc(ctx, n)
#define calloc(n, s)          puchi_os_calloc(ctx, n, s)
#define free(p)               puchi_os_free(ctx, p)
#define isalpha(c)            puchi_ascii_isalpha(c)
#define isdigit(c)            puchi_ascii_isdigit(c)
#define isxdigit(c)           puchi_ascii_isxdigit(c)
#define isspace(c)            puchi_ascii_isspace(c)
#define tolower(c)            puchi_ascii_tolower(c)
#define toupper(c)            puchi_ascii_toupper(c)
#define strcasecmp            puchi_ascii_strcasecmp
#define strncasecmp           puchi_ascii_strncasecmp

#endif /* PUCHI_REDIRECT_H */
