/* puchi_harness.c — OS-facing test runner for amalgamated puchi.h
 *
 * Owns CRT file I/O via puchi_module_ops (sexp_enable_modules), plus
 * harness-only extras: output ports, delete-file, static include-shared
 * stubs (see puchi_harness_clibs.c).
 *
 * Runs the script once on a single context first. On success, spawns
 * PUCHI_HARNESS_THREADS workers; each creates its own VM context and runs
 * the script top to bottom.
 *
 * Usage:
 *   puchi_harness.exe [-I dir] <script.scm> [args...]
 */
/* Numeric mode comes from the compiler: (default) / PUCHI_INTEGER_ONLY /
 * PUCHI_ENABLE_NUMERICAL_TOWER — see build_puchi_tests.bat. */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <sys/stat.h>
#ifdef _WIN32
#include <io.h>
#ifndef close
#define close _close
#endif
#endif

#include "puchi_threads.h"
#include "puchi_test_diagnostics.h"

#define PUCHI_TEST 1
#define PUCHI_IMPLEMENTATION
#include "../puchi.h"

/* puchi.h API + idiomatic C paths under -Weverything (see header). */
PUCHI_DIAG_HARNESS_PEDANTIC_OFF

#define PUCHI_HARNESS_THREADS 64

/* ---- capture buffer (per-worker stdout/stderr; no tmpfile) ---- */

typedef struct {
  char *data;
  size_t len;
  size_t cap;
} puchi_membuf;

typedef struct {
  char **argv;
  const char *script;
  const char *x_module;
  int argc;
  int script_i;
} puchi_harness_args;

typedef struct {
  const puchi_harness_args *args;
  puchi_membuf capture;
  int index;
  int status;
} puchi_worker;

static int puchi_membuf_grow(puchi_membuf *b, size_t need) {
  char *p;
  size_t ncap;
  if (need <= b->cap) return 0;
  ncap = b->cap ? b->cap : 4096;
  while (ncap < need) ncap *= 2;
  p = (char *)realloc(b->data, ncap);
  if (!p) return -1;
  b->data = p;
  b->cap = ncap;
  return 0;
}

static int puchi_membuf_write(puchi_membuf *b, const void *buf, size_t n) {
  if (!n) return 0;
  if (puchi_membuf_grow(b, b->len + n + 1) != 0) return -1;
  memcpy(b->data + b->len, buf, n);
  b->len += n;
  b->data[b->len] = '\0';
  return 0;
}

static void puchi_membuf_free(puchi_membuf *b) {
  free(b->data);
  b->data = NULL;
  b->len = b->cap = 0;
}

/* ---- host callbacks + stream adapters ---- */

static void *puchi_crt_alloc(void *ud, size_t n) {
  (void)ud;
  return malloc(n);
}
static void puchi_crt_free(void *ud, void *p) {
  (void)ud;
  free(p);
}
static void puchi_crt_diagnose(void *ud, int code, const char *msg) {
  (void)ud;
  fprintf(stderr, "[puchi diag %d] %s", code, msg ? msg : "");
  if (msg && msg[0] && msg[strlen(msg) - 1] != '\n') fputc('\n', stderr);
}
static PUCHI_NORETURN void puchi_crt_fatal(void *ud, int code, const char *msg) {
  puchi_worker *w = (puchi_worker *)ud;
  puchi_crt_diagnose(ud, code, msg);
  if (w) w->status = 70;
  (void)code;
  puchi_thread_exit(70);
}

static int puchi_mem_read_char(void *ud) {
  (void)ud;
  return EOF;
}
static int puchi_mem_write_char(void *ud, int c) {
  unsigned char ch = (unsigned char)c;
  if (puchi_membuf_write((puchi_membuf *)ud, &ch, 1) != 0) return EOF;
  return c;
}
static int puchi_mem_unget_char(void *ud, int c) {
  (void)ud;
  (void)c;
  return EOF;
}
static size_t puchi_mem_read(void *ud, void *buf, size_t n) {
  (void)ud;
  (void)buf;
  (void)n;
  return 0;
}
static size_t puchi_mem_write(void *ud, const void *buf, size_t n) {
  if (puchi_membuf_write((puchi_membuf *)ud, buf, n) != 0) return 0;
  return n;
}
static int puchi_mem_flush(void *ud) {
  (void)ud;
  return 0;
}
static void puchi_mem_close(void *ud) { (void)ud; }
static int puchi_mem_eof(void *ud) {
  (void)ud;
  return 1;
}
static int puchi_mem_error(void *ud) {
  (void)ud;
  return 0;
}
static void puchi_mem_clearerr(void *ud) { (void)ud; }

static const puchi_stream_ops puchi_mem_ops = {
  puchi_mem_read_char,
  puchi_mem_write_char,
  puchi_mem_unget_char,
  puchi_mem_read,
  puchi_mem_write,
  puchi_mem_flush,
  puchi_mem_close,
  puchi_mem_eof,
  puchi_mem_error,
  puchi_mem_clearerr
};

static sexp puchi_make_mem_port(sexp ctx, puchi_membuf *buf, int input) {
  sexp p = input ? sexp_make_input_port(ctx, &puchi_mem_ops, buf, SEXP_FALSE)
                 : sexp_make_output_port(ctx, &puchi_mem_ops, buf, SEXP_FALSE);
  if (sexp_portp(p)) sexp_port_no_closep(p) = 1;
  return p;
}

static void puchi_install_capture_ports(sexp ctx, sexp env, puchi_membuf *buf) {
  sexp in = puchi_make_mem_port(ctx, buf, 1);
  sexp out = puchi_make_mem_port(ctx, buf, 0);
  sexp err = puchi_make_mem_port(ctx, buf, 0);
  sexp_set_standard_ports(ctx, env, in, out, err);
}

#ifdef _WIN32
#include <io.h>
#define puchi_access _access
#ifndef F_OK
#define F_OK 0
#endif
#else
#include <unistd.h>
#define puchi_access access
#endif

extern struct sexp_library_entry_t puchi_harness_static_libraries[];

/* ---- file helpers (CRT owned by harness) ---- */

static char *puchi_read_file(const char *path, size_t *out_len) {
  FILE *fp;
  long sz;
  char *buf;
  size_t n;
  fp = fopen(path, "rb");
  if (!fp) return NULL;
  if (fseek(fp, 0, SEEK_END) != 0) { fclose(fp); return NULL; }
  sz = ftell(fp);
  if (sz < 0) { fclose(fp); return NULL; }
  if (fseek(fp, 0, SEEK_SET) != 0) { fclose(fp); return NULL; }
  buf = (char *)malloc((size_t)sz + 1);
  if (!buf) { fclose(fp); return NULL; }
  n = fread(buf, 1, (size_t)sz, fp);
  fclose(fp);
  buf[n] = '\0';
  if (out_len) *out_len = n;
  return buf;
}

static int puchi_ends_with(const char *s, const char *suf) {
  size_t n, m;
  if (!s || !suf) return 0;
  n = strlen(s); m = strlen(suf);
  return n >= m && strcmp(s + n - m, suf) == 0;
}

static int puchi_path_exists(const char *path) {
  return puchi_access(path, F_OK) == 0;
}

/* ---- puchi_module_ops (CRT-backed VFS for sexp_enable_modules) ---- */

static int puchi_mod_exists(void *ud, const char *name) {
  (void)ud;
  return name && puchi_path_exists(name);
}

static char *puchi_mod_read(void *ud, const char *name, size_t *len) {
  (void)ud;
  return puchi_read_file(name, len);
}

static void puchi_mod_free(void *ud, char *buf) {
  (void)ud;
  free(buf);
}

static const puchi_module_ops puchi_crt_module_ops = {
  NULL, puchi_mod_exists, puchi_mod_read, puchi_mod_free
};

/* Build dir/file into out (out_sz). Returns 0 on success. */
static int puchi_join_path(char *out, size_t out_sz, const char *dir, const char *file) {
  size_t dlen, flen, need;
  int slash;
  if (!dir || !file) return -1;
  dlen = strlen(dir);
  flen = strlen(file);
  slash = (dlen > 0 && (dir[dlen - 1] == '/' || dir[dlen - 1] == '\\')) ? 1 : 0;
  need = dlen + flen + (slash ? 1 : 2);
  if (need > out_sz) return -1;
  memcpy(out, dir, dlen);
  if (!slash) out[dlen++] = '/';
  memcpy(out + dlen, file, flen + 1);
  return 0;
}

/* ---- Scheme foreigns ---- */

static sexp puchi_open_input_file_f(sexp ctx, sexp self, sexp_sint_t n, sexp path) {
  char *buf;
  size_t len;
  sexp res;
  (void)n;
  sexp_assert_type(ctx, sexp_stringp, SEXP_STRING, path);
  buf = puchi_read_file(sexp_string_data(path), &len);
  if (!buf)
    return sexp_file_exception(ctx, self, "couldn't open input file", path);
  {
    sexp_gc_var1(s);
    sexp_gc_preserve1(ctx, s);
    s = sexp_c_string(ctx, buf, (sexp_sint_t)len);
    free(buf);
    res = sexp_open_input_string(ctx, s);
    sexp_gc_release1(ctx);
  }
  if (sexp_portp(res)) {
    sexp_port_name(res) = path;
    sexp_port_sourcep(res) = 1;
  }
  return res;
}

static sexp puchi_open_output_file_f(sexp ctx, sexp self, sexp_sint_t n, sexp path) {
  sexp res;
  (void)n;
  (void)self;
  sexp_assert_type(ctx, sexp_stringp, SEXP_STRING, path);
  /* String port; harness flushes to disk on close via custom close if needed.
   * For tests, open-output-string + write-back on close is enough for most
   * cases; we store the path in the port name and register a closer below. */
  res = sexp_open_output_string(ctx);
  if (sexp_portp(res))
    sexp_port_name(res) = path;
  return res;
}

static sexp puchi_close_output_file_flush(sexp ctx, sexp port) {
  sexp name, str;
  FILE *fp;
  const char *data;
  size_t len;
  if (!sexp_oportp(port)) return SEXP_VOID;
  name = sexp_port_name(port);
  if (!sexp_stringp(name)) return SEXP_VOID;
  str = sexp_get_output_string(ctx, port);
  if (!sexp_stringp(str)) return SEXP_VOID;
  data = sexp_string_data(str);
  len = (size_t)sexp_string_size(str);
  fp = fopen(sexp_string_data(name), "wb");
  if (!fp) return sexp_file_exception(ctx, NULL, "couldn't write output file", name);
  if (len) fwrite(data, 1, len, fp);
  fclose(fp);
  return SEXP_VOID;
}

static sexp puchi_close_port_f(sexp ctx, sexp self, sexp_sint_t n, sexp port) {
  if (sexp_oportp(port) && sexp_stringp(sexp_port_name(port))
      && !sexp_port_stream(port)) {
    sexp r = puchi_close_output_file_flush(ctx, port);
    if (sexp_exceptionp(r)) return r;
  }
  return sexp_close_port_op(ctx, self, n, port);
}

static sexp puchi_file_exists_f(sexp ctx, sexp self, sexp_sint_t n, sexp path) {
  (void)n;
  (void)self;
  sexp_assert_type(ctx, sexp_stringp, SEXP_STRING, path);
  return puchi_path_exists(sexp_string_data(path)) ? SEXP_TRUE : SEXP_FALSE;
}

static sexp puchi_delete_file_f(sexp ctx, sexp self, sexp_sint_t n, sexp path) {
  (void)n;
  sexp_assert_type(ctx, sexp_stringp, SEXP_STRING, path);
  if (remove(sexp_string_data(path)) != 0)
    return sexp_file_exception(ctx, self, "couldn't delete file", path);
  return SEXP_VOID;
}

static int puchi_static_lib_match(const char *path) {
  const char *probe = path;
  struct sexp_library_entry_t *e;
  size_t base_len, so_len;
  if (!probe) return 0;
  if (probe[0] == '.' && probe[1] == '/') probe += 2;
  so_len = strlen(sexp_so_extension);
  if (strlen(probe) < so_len || strcmp(probe + strlen(probe) - so_len, sexp_so_extension) != 0)
    return 0;
  base_len = strlen(probe) - so_len;
  for (e = puchi_harness_static_libraries; e && e->name; e++) {
    if (strncmp(probe, e->name, base_len) == 0 && e->name[base_len] == '\0')
      return 1;
  }
  return 0;
}

/* Look for file on module path; also synthesize .so paths for static libs. */
static sexp puchi_find_module_file_f(sexp ctx, sexp self, sexp_sint_t n, sexp file) {
  sexp ls;
  char path[4096];
  const char *fname;
  (void)n;
  (void)self;
  sexp_assert_type(ctx, sexp_stringp, SEXP_STRING, file);
  fname = sexp_string_data(file);

  /* Absolute or relative path that already exists */
  if (puchi_path_exists(fname))
    return sexp_c_string(ctx, fname, -1);
  if (puchi_static_lib_match(fname))
    return sexp_c_string(ctx, fname, -1);

  ls = sexp_global(ctx, SEXP_G_MODULE_PATH);
  for (; sexp_pairp(ls); ls = sexp_cdr(ls)) {
    if (!sexp_stringp(sexp_car(ls))) continue;
    if (puchi_join_path(path, sizeof path, sexp_string_data(sexp_car(ls)), fname) != 0)
      continue;
    if (puchi_path_exists(path))
      return sexp_c_string(ctx, path, -1);
    if (puchi_static_lib_match(path))
      return sexp_c_string(ctx, path, -1);
  }
  return SEXP_FALSE;
}

static sexp puchi_load_source_string(sexp ctx, const char *text, size_t len, sexp env) {
  sexp_gc_var5(ctx2, x, in, res, s);
  sexp_gc_preserve5(ctx, ctx2, x, in, res, s);
  res = SEXP_VOID;
  s = sexp_c_string(ctx, text, (sexp_sint_t)len);
  in = sexp_open_input_string(ctx, s);
  if (sexp_exceptionp(in)) {
    res = in;
  } else {
    sexp_port_sourcep(in) = 1;
    ctx2 = sexp_make_eval_context(ctx, NULL, env, 0, 0);
    sexp_context_parent(ctx2) = ctx;
    sexp_context_tailp(ctx2) = 0;
    while ((x = sexp_read(ctx2, in)) != (sexp)SEXP_EOF) {
      res = sexp_exceptionp(x) ? x : sexp_eval(ctx2, x, env);
      if (sexp_exceptionp(res)) break;
    }
    if (x == SEXP_EOF) res = SEXP_VOID;
    sexp_close_port(ctx, in);
  }
  sexp_gc_release5(ctx);
  return res;
}

static sexp puchi_load_f(sexp ctx, sexp self, sexp_sint_t n, sexp source, sexp env) {
  char *buf;
  size_t len;
  sexp res;
  if (!env) env = sexp_context_env(ctx);
  sexp_assert_type(ctx, sexp_envp, SEXP_ENV, env);
  if (sexp_iportp(source))
    return sexp_load_op(ctx, self, n, source, env);
  sexp_assert_type(ctx, sexp_stringp, SEXP_STRING, source);
  if (puchi_ends_with(sexp_string_data(source), sexp_so_extension))
    return sexp_load_op(ctx, self, n, source, env);
  buf = puchi_read_file(sexp_string_data(source), &len);
  if (!buf)
    return sexp_file_exception(ctx, self, "couldn't open input file", source);
  res = puchi_load_source_string(ctx, buf, len, env);
  free(buf);
  return res;
}

/* Sandbox stubs: bind names Chibi libs still reference; no real fds/threads. */
static sexp puchi_yield_f(sexp ctx, sexp self, sexp_sint_t n) {
  (void)ctx;
  (void)self;
  (void)n;
  return SEXP_VOID;
}

static sexp puchi_port_fileno_f(sexp ctx, sexp self, sexp_sint_t n, sexp port) {
  (void)ctx;
  (void)self;
  (void)n;
  (void)port;
  return SEXP_FALSE;
}

static sexp puchi_open_output_file_descriptor_f(sexp ctx, sexp self, sexp_sint_t n,
                                               sexp fd, sexp o) {
  (void)n;
  (void)fd;
  (void)o;
  return sexp_user_exception(ctx, self,
                             "open-output-file-descriptor: not available in puchi harness",
                             SEXP_FALSE);
}

/* Upstream init-7 file helpers — harness-only, onto *chibi-env* (not amalgamated). */
static const char puchi_file_helpers_scm[] =
  "(begin"
  " (define (call-with-input-file file proc)"
  "   (let* ((in (open-input-file file))"
  "          (res (proc in)))"
  "     (close-input-port in)"
  "     res))"
  " (define (call-with-output-file file proc)"
  "   (let* ((out (open-output-file file))"
  "          (res (proc out)))"
  "     (close-output-port out)"
  "     res))"
  " (define (with-input-from-file file thunk)"
  "   (let ((old-in (current-input-port))"
  "         (tmp-in (open-input-file file)))"
  "     (dynamic-wind"
  "       (lambda () (current-input-port tmp-in))"
  "       (lambda () (let ((res (thunk))) (close-input-port tmp-in) res))"
  "       (lambda () (current-input-port old-in)))))"
  " (define (with-output-to-file file thunk)"
  "   (let ((old-out (current-output-port))"
  "         (tmp-out (open-output-file file)))"
  "     (dynamic-wind"
  "       (lambda () (current-output-port tmp-out))"
  "       (lambda () (let ((res (thunk))) (close-output-port tmp-out) res))"
  "       (lambda () (current-output-port old-out)))))"
  ")";

static sexp puchi_get_chibi_env(sexp ctx) {
  sexp meta = sexp_global(ctx, SEXP_G_META_ENV);
  if (!sexp_envp(meta)) return SEXP_FALSE;
  return sexp_env_ref(ctx, meta, sexp_intern(ctx, "*chibi-env*", (sexp_sint_t)-1), SEXP_FALSE);
}

/* CRT file I/O + stubs. file_ops: also install file-exists?/delete-file.
 * Those must NOT go on *chibi-env* — (scheme file) imports them from
 * (chibi filesystem); duplicating on (chibi) causes already-defined warnings. */
static void puchi_install_chibi_surface(sexp ctx, sexp env, int file_ops) {
  sexp tmp;
  if (!sexp_envp(env)) return;

  sexp_define_foreign(ctx, env, "open-input-file", 1, puchi_open_input_file_f);
  sexp_define_foreign(ctx, env, "open-binary-input-file", 1, puchi_open_input_file_f);
  sexp_define_foreign(ctx, env, "open-output-file", 1, puchi_open_output_file_f);
  sexp_define_foreign(ctx, env, "open-binary-output-file", 1, puchi_open_output_file_f);
  sexp_define_foreign(ctx, env, "close-port", 1, puchi_close_port_f);
  sexp_define_foreign(ctx, env, "close-input-port", 1, puchi_close_port_f);
  sexp_define_foreign(ctx, env, "close-output-port", 1, puchi_close_port_f);
  if (file_ops) {
    sexp_define_foreign(ctx, env, "file-exists?", 1, puchi_file_exists_f);
    sexp_define_foreign(ctx, env, "delete-file", 1, puchi_delete_file_f);
  }
  sexp_define_foreign(ctx, env, "find-module-file", 1, puchi_find_module_file_f);
  sexp_define_foreign_opt(ctx, env, "current-module-path", 1, sexp_current_module_path_op, SEXP_FALSE);
  sexp_define_foreign(ctx, env, "load-module-file", 2, sexp_load_module_file_op);
  sexp_define_foreign(ctx, env, "add-module-directory", 2, sexp_add_module_directory_op);
  sexp_define_foreign_opt(ctx, env, "load", 2, puchi_load_f, SEXP_FALSE);
  sexp_define_foreign_opt(ctx, env, "%load", 2, puchi_load_f, SEXP_FALSE);

  /* Names stripped from core / missing on Windows — bind so libs compile. */
  sexp_define_foreign(ctx, env, "yield!", 0, puchi_yield_f);
  sexp_define_foreign(ctx, env, "port-fileno", 1, puchi_port_fileno_f);
  sexp_env_define(ctx, env, sexp_intern(ctx, "open/non-block", -1), SEXP_ZERO);
  sexp_define_foreign_opt(ctx, env, "open-output-file-descriptor", 2,
                          puchi_open_output_file_descriptor_f, SEXP_FALSE);

  tmp = sexp_eval_string(ctx, puchi_file_helpers_scm, (sexp_sint_t)-1, env);
  if (sexp_exceptionp(tmp)) {
    sexp_print_exception(ctx, tmp, sexp_current_error_port(ctx));
  }
}

/* After meta-7 snapshot: patch *chibi-env* so (scheme file)/(chibi io) import
 * real CRT foreigns. Also refresh interaction + meta for load/module path.
 * Do NOT install open/close on the empty script env before import. */
static void puchi_install_harness_surface(sexp ctx) {
  sexp meta, interaction, chibi;
  meta = sexp_global(ctx, SEXP_G_META_ENV);
  interaction = sexp_context_env(ctx);
  chibi = puchi_get_chibi_env(ctx);
  if (sexp_envp(chibi)) puchi_install_chibi_surface(ctx, chibi, 0);
  if (sexp_envp(interaction)) puchi_install_chibi_surface(ctx, interaction, 1);
  if (sexp_envp(meta) && meta != interaction && meta != chibi)
    puchi_install_chibi_surface(ctx, meta, 1);
}

/* Returns 0 on success, 70 on Scheme exception (prints into capture ports). */
static int puchi_check(sexp ctx, sexp x) {
  if (sexp_exceptionp(x)) {
    sexp_print_exception(ctx, x, sexp_current_error_port(ctx));
    sexp_stack_trace(ctx, sexp_current_error_port(ctx));
    return 70;
  }
  return 0;
}

static PUCHI_NORETURN void usage(void) {
  fprintf(stderr, "usage: puchi_harness [-I dir] [-x module] <script.scm> [args...]\n");
  exit(1);
}

/* Convert dotted module name "chibi.foo" to "(mutable-environment '(chibi foo))" */
static char *puchi_make_environment(const char *mod) {
  size_t n = strlen(mod) + 48;
  char *buf = (char *)malloc(n);
  char *p;
  if (!buf) return NULL;
  snprintf(buf, n, "(mutable-environment '(");
  p = buf + strlen(buf);
  for (; *mod; mod++) {
    if (*mod == '.') *p++ = ' ';
    else *p++ = *mod;
  }
  strcpy(p, "))");
  return buf;
}

static int puchi_capture_failed(const puchi_membuf *b) {
  if (!b->data || !b->len) return 0;
  return strstr(b->data, " failure") != NULL || strstr(b->data, " error") != NULL;
}

/* One script run on a fresh root context. No exit(). */
static int puchi_harness_run(puchi_worker *w) {
  const puchi_harness_args *a = w->args;
  puchi_host host;
  sexp ctx = NULL, env, tmp, sym, args;
  int i, status = 0;
  char *impmod = NULL;

  memset(&w->capture, 0, sizeof(w->capture));
  w->status = 0;

  host.userdata = w;
  host.alloc = puchi_crt_alloc;
  host.free = puchi_crt_free;
  host.diagnose = puchi_crt_diagnose;
  host.fatal = puchi_crt_fatal;

  ctx = sexp_create_context((size_t)0, (size_t)0, &host);
  if (!ctx || sexp_exceptionp(ctx)) {
    fprintf(stderr, "[worker %d] sexp_create_context failed\n", w->index);
    return 1;
  }
  env = sexp_context_env(ctx);

  sexp_add_static_libraries(ctx, puchi_harness_static_libraries);

#if defined(_WIN32)
  {
    sexp win = sexp_intern(ctx, "windows", -1);
    sexp_global(ctx, SEXP_G_FEATURES) =
      sexp_cons(ctx, win, sexp_global(ctx, SEXP_G_FEATURES));
  }
#endif

  tmp = sexp_enable_modules(ctx, &puchi_crt_module_ops);
  if (puchi_check(ctx, tmp)) { status = 70; goto done; }
  env = sexp_context_env(ctx);

  /* Patch *chibi-env* (+ interaction/meta). Script env gets open/close via import. */
  puchi_install_harness_surface(ctx);

  sexp_add_module_directory(ctx, sexp_c_string(ctx, "lib", -1), SEXP_FALSE);

  for (i = 1; i < a->script_i; i++) {
    if (strcmp(a->argv[i], "-I") == 0) {
      i++;
      if (i < a->script_i)
        sexp_add_module_directory(ctx, sexp_c_string(ctx, a->argv[i], -1), SEXP_FALSE);
    }
  }

  puchi_install_capture_ports(ctx, env, &w->capture);

  if (a->x_module) {
    impmod = puchi_make_environment(a->x_module);
    if (!impmod) { status = 1; goto done; }
    tmp = sexp_eval_string(ctx, impmod, -1, sexp_global(ctx, SEXP_G_META_ENV));
    free(impmod);
    impmod = NULL;
    if (puchi_check(ctx, tmp)) { status = 70; goto done; }
    if (!sexp_envp(tmp)) {
      fprintf(stderr, "[worker %d] -x%s did not produce an environment\n",
              w->index, a->x_module);
      status = 1;
      goto done;
    }
    env = tmp;
    sexp_set_parameter(ctx, sexp_global(ctx, SEXP_G_META_ENV),
                       sexp_global(ctx, SEXP_G_INTERACTION_ENV_SYMBOL), env);
    sexp_context_env(ctx) = env;
    sym = sexp_intern(ctx, "repl-import", -1);
    tmp = sexp_env_ref(ctx, sexp_global(ctx, SEXP_G_META_ENV), sym, SEXP_VOID);
    sym = sexp_intern(ctx, "import", -1);
    if (puchi_check(ctx, sexp_env_define(ctx, env, sym, tmp))) { status = 70; goto done; }
    {
      sexp outp = sexp_env_ref(ctx, env, sexp_global(ctx, SEXP_G_CUR_OUT_SYMBOL), SEXP_FALSE);
      if (sexp_opcodep(outp)) outp = sexp_parameter_ref(ctx, outp);
      if (!sexp_oportp(outp))
        puchi_install_capture_ports(ctx, env, &w->capture);
    }
  } else {
    env = sexp_make_env(ctx);
    if (puchi_check(ctx, env)) { status = 70; goto done; }
    sexp_set_parameter(ctx, sexp_global(ctx, SEXP_G_META_ENV),
                       sexp_global(ctx, SEXP_G_INTERACTION_ENV_SYMBOL), env);
    sexp_context_env(ctx) = env;
    sym = sexp_intern(ctx, "repl-import", -1);
    tmp = sexp_env_ref(ctx, sexp_global(ctx, SEXP_G_META_ENV), sym, SEXP_VOID);
    sym = sexp_intern(ctx, "import", -1);
    if (puchi_check(ctx, sexp_env_define(ctx, env, sym, tmp))) { status = 70; goto done; }
    sym = sexp_intern(ctx, "cond-expand", -1);
    tmp = sexp_env_cell(ctx, sexp_global(ctx, SEXP_G_META_ENV), sym, 0);
    if (tmp) {
      sexp_env_rename(ctx, env, sym, tmp);
      sexp_env_define(ctx, env, sym, sexp_cdr(tmp));
    }
    /* No open/close on empty script env — import pulls harness cells from (chibi). */
  }

  args = SEXP_NULL;
  for (i = a->argc - 1; i >= a->script_i; i--)
    args = sexp_cons(ctx, sexp_c_string(ctx, a->argv[i], -1), args);
  sexp_set_parameter(ctx, sexp_global(ctx, SEXP_G_META_ENV),
                     sexp_intern(ctx, "command-line", -1), args);
  sexp_env_define(ctx, sexp_global(ctx, SEXP_G_META_ENV),
                  sexp_intern(ctx, "raw-script-file", -1),
                  sexp_c_string(ctx, a->script, -1));

  sym = sexp_intern(ctx, "load", -1);
  tmp = sexp_env_ref(ctx, sexp_global(ctx, SEXP_G_META_ENV), sym, SEXP_FALSE);
  if (sexp_procedurep(tmp) || sexp_opcodep(tmp)) {
    sym = sexp_list2(ctx, sexp_c_string(ctx, a->script, -1), env);
    if (puchi_check(ctx, sexp_apply(ctx, tmp, sym))) { status = 70; goto done; }
  } else {
    if (puchi_check(ctx, puchi_load_f(ctx, NULL, 2, sexp_c_string(ctx, a->script, -1), env))) {
      status = 70;
      goto done;
    }
  }

  if (puchi_capture_failed(&w->capture))
    status = 70;

done:
  if (status != 0 && w->capture.data && w->capture.len) {
    fprintf(stderr, "===== [worker %d] begin capture =====\n", w->index);
    fwrite(w->capture.data, 1, w->capture.len, stderr);
    if (w->capture.data[w->capture.len - 1] != '\n') fputc('\n', stderr);
    fprintf(stderr, "===== [worker %d] end capture =====\n", w->index);
  }
  if (ctx && !sexp_exceptionp(ctx))
    sexp_delete_context(ctx);
  puchi_membuf_free(&w->capture);
  w->status = status;
  return status;
}

static int puchi_worker_main(void *arg) {
  return puchi_harness_run((puchi_worker *)arg);
}

int main(int argc, char **argv) {
  puchi_harness_args args;
  puchi_worker workers[PUCHI_HARNESS_THREADS];
  puchi_thread threads[PUCHI_HARNESS_THREADS];
  int i, script_i = -1, passed = 0, failed = 0;
  const char *x_module = NULL;

  if (argc < 2) usage();

  for (i = 1; i < argc; i++) {
    if (strcmp(argv[i], "-I") == 0) {
      if (++i >= argc) usage();
    } else if (strcmp(argv[i], "-x") == 0 ||
               (argv[i][0] == '-' && argv[i][1] == 'x' && argv[i][2] != '\0')) {
      if (argv[i][2] == '\0') {
        if (++i >= argc) usage();
        x_module = argv[i];
      } else {
        x_module = argv[i] + 2;
      }
    } else if (argv[i][0] == '-' && argv[i][1] != '\0') {
      fprintf(stderr, "unknown option: %s\n", argv[i]);
      usage();
    } else {
      script_i = i;
      break;
    }
  }
  if (script_i < 0) usage();

  args.argc = argc;
  args.argv = argv;
  args.script_i = script_i;
  args.script = argv[script_i];
  args.x_module = x_module;

  /* Single-threaded first: easier to debug; skip parallel on failure. */
  {
    puchi_worker solo;
    int st;
    memset(&solo, 0, sizeof(solo));
    solo.index = -1;
    solo.args = &args;
    fprintf(stderr, "puchi_harness: single-threaded run on %s\n", args.script);
    st = puchi_harness_run(&solo);
    if (st != 0) {
      fprintf(stderr, "puchi_harness: single-threaded run failed (status %d); "
              "skipping parallel\n", st);
      return st;
    }
    fprintf(stderr, "puchi_harness: single-threaded run passed\n");
  }

  fprintf(stderr, "puchi_harness: %d parallel contexts on %s\n",
          PUCHI_HARNESS_THREADS, args.script);

  for (i = 0; i < PUCHI_HARNESS_THREADS; i++) {
    memset(&workers[i], 0, sizeof(workers[i]));
    workers[i].index = i;
    workers[i].args = &args;
    threads[i] = NULL;
  }

  for (i = 0; i < PUCHI_HARNESS_THREADS; i++) {
    if (puchi_thread_create(&threads[i], puchi_worker_main, &workers[i]) != 0) {
      fprintf(stderr, "puchi_harness: failed to create worker %d\n", i);
      threads[i] = NULL;
      workers[i].status = 1;
    }
  }

  for (i = 0; i < PUCHI_HARNESS_THREADS; i++) {
    int st = 1;
    if (threads[i]) {
      if (puchi_thread_join(threads[i], &st) != 0)
        st = 1;
    } else {
      st = workers[i].status ? workers[i].status : 1;
    }
    if (st == 0) passed++;
    else failed++;
  }

  fprintf(stderr, "puchi_harness: %d/%d workers passed\n",
          passed, PUCHI_HARNESS_THREADS);
  return failed ? 1 : 0;
}
