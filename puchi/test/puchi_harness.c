/* puchi_harness.c — OS-facing test runner for amalgamated puchi.h
 *
 * Owns CRT file I/O via puchi_module_ops (sexp_enable_modules), plus
 * harness-only extras: output ports, delete-file, static include-shared
 * stubs (see puchi_harness_clibs.c).
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

#define PUCHI_TEST 1
#define PUCHI_IMPLEMENTATION
#include "../puchi.h"

/* ---- host callbacks + FILE* stream adapters (harness-owned CRT) ---- */
static void *puchi_host_alloc(void *ud, size_t n) {
  (void)ud;
  return malloc(n);
}
static void puchi_host_free(void *ud, void *p) {
  (void)ud;
  free(p);
}
static void puchi_host_diagnose(void *ud, int code, const char *msg) {
  (void)ud;
  fprintf(stderr, "[puchi diag %d] %s", code, msg ? msg : "");
  if (msg && msg[0] && msg[strlen(msg) - 1] != '\n') fputc('\n', stderr);
}
static void puchi_host_fatal(void *ud, int code, const char *msg) {
  puchi_host_diagnose(ud, code, msg);
  exit(70);
}

static int puchi_file_read_char(void *ud) { return getc((FILE *)ud); }
static int puchi_file_write_char(void *ud, int c) { return putc(c, (FILE *)ud); }
static int puchi_file_unget_char(void *ud, int c) { return ungetc(c, (FILE *)ud); }
static size_t puchi_file_read(void *ud, void *buf, size_t n) {
  return fread(buf, 1, n, (FILE *)ud);
}
static size_t puchi_file_write(void *ud, const void *buf, size_t n) {
  return fwrite(buf, 1, n, (FILE *)ud);
}
static int puchi_file_flush(void *ud) { return fflush((FILE *)ud); }
static void puchi_file_close(void *ud) { (void)ud; /* no_close for stdio */ }
static int puchi_file_eof(void *ud) { return feof((FILE *)ud); }
static int puchi_file_error(void *ud) { return ferror((FILE *)ud); }
static void puchi_file_clearerr(void *ud) { clearerr((FILE *)ud); }

static const puchi_stream_ops puchi_file_ops = {
  puchi_file_read_char,
  puchi_file_write_char,
  puchi_file_unget_char,
  puchi_file_read,
  puchi_file_write,
  puchi_file_flush,
  puchi_file_close,
  puchi_file_eof,
  puchi_file_error,
  puchi_file_clearerr
};

static sexp puchi_make_stdio_port(sexp ctx, FILE *fp, int input) {
  sexp p = input ? sexp_make_input_port(ctx, &puchi_file_ops, fp, SEXP_FALSE)
                 : sexp_make_output_port(ctx, &puchi_file_ops, fp, SEXP_FALSE);
  if (sexp_portp(p)) sexp_port_no_closep(p) = 1;
  return p;
}

static void puchi_install_stdio_ports(sexp ctx, sexp env) {
  sexp in = puchi_make_stdio_port(ctx, stdin, 1);
  sexp out = puchi_make_stdio_port(ctx, stdout, 0);
  sexp err = puchi_make_stdio_port(ctx, stderr, 0);
  sexp_set_standard_ports(ctx, env, in, out, err);
}

static const puchi_host puchi_test_host = {
  NULL, puchi_host_alloc, puchi_host_free, puchi_host_diagnose, puchi_host_fatal
};

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
  sexp_assert_type(ctx, sexp_stringp, SEXP_STRING, path);
  return puchi_path_exists(sexp_string_data(path)) ? SEXP_TRUE : SEXP_FALSE;
}

static sexp puchi_delete_file_f(sexp ctx, sexp self, sexp_sint_t n, sexp path) {
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

static void puchi_install_foreigns(sexp ctx, sexp env) {
  sexp_define_foreign(ctx, env, "open-input-file", 1, puchi_open_input_file_f);
  sexp_define_foreign(ctx, env, "open-binary-input-file", 1, puchi_open_input_file_f);
  sexp_define_foreign(ctx, env, "open-output-file", 1, puchi_open_output_file_f);
  sexp_define_foreign(ctx, env, "open-binary-output-file", 1, puchi_open_output_file_f);
  sexp_define_foreign(ctx, env, "close-port", 1, puchi_close_port_f);
  sexp_define_foreign(ctx, env, "close-input-port", 1, puchi_close_port_f);
  sexp_define_foreign(ctx, env, "close-output-port", 1, puchi_close_port_f);
  sexp_define_foreign(ctx, env, "file-exists?", 1, puchi_file_exists_f);
  sexp_define_foreign(ctx, env, "delete-file", 1, puchi_delete_file_f);
  sexp_define_foreign(ctx, env, "find-module-file", 1, puchi_find_module_file_f);
  /* Module-path registry: core no longer registers these opcodes. */
  sexp_define_foreign_opt(ctx, env, "current-module-path", 1, sexp_current_module_path_op, SEXP_FALSE);
  sexp_define_foreign(ctx, env, "load-module-file", 2, sexp_load_module_file_op);
  sexp_define_foreign(ctx, env, "add-module-directory", 2, sexp_add_module_directory_op);
  sexp_define_foreign_opt(ctx, env, "load", 2, puchi_load_f, SEXP_FALSE);
  sexp_define_foreign_opt(ctx, env, "%load", 2, puchi_load_f, SEXP_FALSE);
}

static sexp puchi_check(sexp ctx, sexp x) {
  if (sexp_exceptionp(x)) {
    sexp_print_exception(ctx, x, sexp_current_error_port(ctx));
    sexp_stack_trace(ctx, sexp_current_error_port(ctx));
    exit(70);
  }
  return x;
}

static void usage(void) {
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

int main(int argc, char **argv) {
  sexp ctx, env, tmp, sym, args;
  int i, script_i = -1;
  const char *script;
  const char *x_module = NULL;
  char *impmod = NULL;

  if (argc < 2) usage();

  ctx = sexp_create_context(0, 0, &puchi_test_host);
  if (!ctx || sexp_exceptionp(ctx)) {
    fprintf(stderr, "sexp_create_context failed\n");
    return 1;
  }
  env = sexp_context_env(ctx);

  sexp_add_static_libraries(puchi_harness_static_libraries);

  /* Upstream (scheme process-context) cond-expands on windows. Keep that
   * string out of sexp_initial_features; only the Win32 harness adds it. */
#if defined(_WIN32)
  {
    sexp win = sexp_intern(ctx, "windows", -1);
    sexp_global(ctx, SEXP_G_FEATURES) =
      sexp_cons(ctx, win, sexp_global(ctx, SEXP_G_FEATURES));
  }
#endif

  /* Boots init-7 (once) + embedded meta-7 via CRT module ops. */
  tmp = sexp_enable_modules(ctx, &puchi_crt_module_ops);
  puchi_check(ctx, tmp);
  env = sexp_context_env(ctx);

  /* Harness extras: output/delete + static-lib-aware find/load (overrides core). */
  puchi_install_foreigns(ctx, env);
  {
    sexp meta = sexp_global(ctx, SEXP_G_META_ENV);
    if (sexp_envp(meta)) puchi_install_foreigns(ctx, meta);
  }

  /* Default module path includes ./lib */
  sexp_add_module_directory(ctx, sexp_c_string(ctx, "lib", -1), SEXP_FALSE);

  for (i = 1; i < argc; i++) {
    if (strcmp(argv[i], "-I") == 0) {
      if (++i >= argc) usage();
      sexp_add_module_directory(ctx, sexp_c_string(ctx, argv[i], -1), SEXP_FALSE);
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
  script = argv[script_i];

  puchi_install_stdio_ports(ctx, env);

  if (x_module) {
    /* Like chibi-scheme -xMODULE: run script in that module's env. */
    impmod = puchi_make_environment(x_module);
    if (!impmod) { fprintf(stderr, "oom\n"); return 1; }
    tmp = sexp_eval_string(ctx, impmod, -1, sexp_global(ctx, SEXP_G_META_ENV));
    free(impmod);
    puchi_check(ctx, tmp);
    if (!sexp_envp(tmp)) {
      fprintf(stderr, "puchi_harness: -x%s did not produce an environment\n", x_module);
      return 1;
    }
    env = tmp;
    sexp_set_parameter(ctx, sexp_global(ctx, SEXP_G_META_ENV),
                       sexp_global(ctx, SEXP_G_INTERACTION_ENV_SYMBOL), env);
    sexp_context_env(ctx) = env;
    /* Ensure import is available */
    sym = sexp_intern(ctx, "repl-import", -1);
    tmp = sexp_env_ref(ctx, sexp_global(ctx, SEXP_G_META_ENV), sym, SEXP_VOID);
    sym = sexp_intern(ctx, "import", -1);
    puchi_check(ctx, sexp_env_define(ctx, env, sym, tmp));
    puchi_install_foreigns(ctx, env);
    {
      sexp outp = sexp_env_ref(ctx, env, sexp_global(ctx, SEXP_G_CUR_OUT_SYMBOL), SEXP_FALSE);
      if (sexp_opcodep(outp)) outp = sexp_parameter_ref(ctx, outp);
      if (!sexp_oportp(outp))
        puchi_install_stdio_ports(ctx, env);
    }
  } else {
    /* Fresh script env with import + cond-expand from meta */
    env = sexp_make_env(ctx);
    puchi_check(ctx, env);
    sexp_set_parameter(ctx, sexp_global(ctx, SEXP_G_META_ENV),
                       sexp_global(ctx, SEXP_G_INTERACTION_ENV_SYMBOL), env);
    sexp_context_env(ctx) = env;
    sym = sexp_intern(ctx, "repl-import", -1);
    tmp = sexp_env_ref(ctx, sexp_global(ctx, SEXP_G_META_ENV), sym, SEXP_VOID);
    sym = sexp_intern(ctx, "import", -1);
    puchi_check(ctx, sexp_env_define(ctx, env, sym, tmp));
    sym = sexp_intern(ctx, "cond-expand", -1);
    tmp = sexp_env_cell(ctx, sexp_global(ctx, SEXP_G_META_ENV), sym, 0);
    if (tmp) {
      sexp_env_rename(ctx, env, sym, tmp);
      sexp_env_define(ctx, env, sym, sexp_cdr(tmp));
    }
    puchi_install_foreigns(ctx, env);
  }

  /* command-line */
  args = SEXP_NULL;
  for (i = argc - 1; i >= script_i; i--)
    args = sexp_cons(ctx, sexp_c_string(ctx, argv[i], -1), args);
  sexp_set_parameter(ctx, sexp_global(ctx, SEXP_G_META_ENV),
                     sexp_intern(ctx, "command-line", -1), args);
  sexp_env_define(ctx, sexp_global(ctx, SEXP_G_META_ENV),
                  sexp_intern(ctx, "raw-script-file", -1),
                  sexp_c_string(ctx, script, -1));

  /* Prefer meta load for stack traces */
  sym = sexp_intern(ctx, "load", -1);
  tmp = sexp_env_ref(ctx, sexp_global(ctx, SEXP_G_META_ENV), sym, SEXP_FALSE);
  if (sexp_procedurep(tmp) || sexp_opcodep(tmp)) {
    sym = sexp_list2(ctx, sexp_c_string(ctx, script, -1), env);
    puchi_check(ctx, sexp_apply(ctx, tmp, sym));
  } else {
    puchi_check(ctx, puchi_load_f(ctx, NULL, 2, sexp_c_string(ctx, script, -1), env));
  }

  sexp_delete_context(ctx);
  return 0;
}
