/* ---- module ops + sexp_enable_modules (host-owned I/O) ---- */
static puchi_module_ops puchi_g_module_ops;
static int puchi_g_module_ops_set;

static int puchi_module_join_path(char *out, size_t out_sz, const char *dir, const char *file) {
  size_t dlen, flen, need;
  int slash;
  if (!dir || !file) return -1;
  dlen = PUCHI_STRLEN(dir);
  flen = PUCHI_STRLEN(file);
  slash = (dlen > 0 && (dir[dlen - 1] == '/' || dir[dlen - 1] == '\\')) ? 1 : 0;
  need = dlen + flen + (slash ? 1 : 2);
  if (need > out_sz) return -1;
  PUCHI_MEMCPY(out, dir, dlen);
  if (!slash) out[dlen++] = '/';
  PUCHI_MEMCPY(out + dlen, file, flen + 1);
  return 0;
}

static sexp puchi_module_eval_source(sexp ctx, const char *text, size_t len, sexp env) {
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

static sexp puchi_module_find_file_f(sexp ctx, sexp self, sexp_sint_t n, sexp file) {
  sexp ls;
  char path[4096];
  const char *fname;
  (void)n;
  if (!puchi_g_module_ops_set || !puchi_g_module_ops.exists)
    return sexp_global(ctx, SEXP_G_OOM_ERROR);
  sexp_assert_type(ctx, sexp_stringp, SEXP_STRING, file);
  fname = sexp_string_data(file);
  if (puchi_g_module_ops.exists(puchi_g_module_ops.userdata, fname))
    return sexp_c_string(ctx, fname, -1);
  ls = sexp_global(ctx, SEXP_G_MODULE_PATH);
  for (; sexp_pairp(ls); ls = sexp_cdr(ls)) {
    if (!sexp_stringp(sexp_car(ls))) continue;
    if (puchi_module_join_path(path, sizeof path, sexp_string_data(sexp_car(ls)), fname) != 0)
      continue;
    if (puchi_g_module_ops.exists(puchi_g_module_ops.userdata, path))
      return sexp_c_string(ctx, path, -1);
  }
  return SEXP_FALSE;
}

static sexp puchi_module_open_input_f(sexp ctx, sexp self, sexp_sint_t n, sexp path) {
  char *buf;
  size_t len = 0;
  sexp res;
  (void)n;
  if (!puchi_g_module_ops_set || !puchi_g_module_ops.read || !puchi_g_module_ops.free_buf)
    return sexp_global(ctx, SEXP_G_OOM_ERROR);
  sexp_assert_type(ctx, sexp_stringp, SEXP_STRING, path);
  buf = puchi_g_module_ops.read(puchi_g_module_ops.userdata, sexp_string_data(path), &len);
  if (!buf)
    return sexp_file_exception(ctx, self, "couldn't open input file", path);
  {
    sexp_gc_var1(s);
    sexp_gc_preserve1(ctx, s);
    s = sexp_c_string(ctx, buf, (sexp_sint_t)len);
    puchi_g_module_ops.free_buf(puchi_g_module_ops.userdata, buf);
    res = sexp_open_input_string(ctx, s);
    sexp_gc_release1(ctx);
  }
  if (sexp_portp(res)) {
    sexp_port_name(res) = path;
    sexp_port_sourcep(res) = 1;
  }
  return res;
}

static sexp puchi_module_load_f(sexp ctx, sexp self, sexp_sint_t n, sexp source, sexp env) {
  char *buf;
  size_t len = 0;
  sexp res;
  if (!env) env = sexp_context_env(ctx);
  sexp_assert_type(ctx, sexp_envp, SEXP_ENV, env);
  if (sexp_iportp(source))
    return sexp_load_op(ctx, self, n, source, env);
  if (!puchi_g_module_ops_set || !puchi_g_module_ops.read || !puchi_g_module_ops.free_buf)
    return sexp_global(ctx, SEXP_G_OOM_ERROR);
  sexp_assert_type(ctx, sexp_stringp, SEXP_STRING, source);
  buf = puchi_g_module_ops.read(puchi_g_module_ops.userdata, sexp_string_data(source), &len);
  if (!buf)
    return sexp_file_exception(ctx, self, "couldn't open input file", source);
  res = puchi_module_eval_source(ctx, buf, len, env);
  puchi_g_module_ops.free_buf(puchi_g_module_ops.userdata, buf);
  return res;
}

static void puchi_module_install_foreigns(sexp ctx, sexp env) {
  sexp_define_foreign(ctx, env, "find-module-file", 1, puchi_module_find_file_f);
  sexp_define_foreign(ctx, env, "open-input-file", 1, puchi_module_open_input_f);
  sexp_define_foreign(ctx, env, "open-binary-input-file", 1, puchi_module_open_input_f);
  sexp_define_foreign_opt(ctx, env, "load", 2, puchi_module_load_f, SEXP_FALSE);
  sexp_define_foreign_opt(ctx, env, "%load", 2, puchi_module_load_f, SEXP_FALSE);
#if SEXP_USE_MODULES
  sexp_define_foreign_opt(ctx, env, "current-module-path", 1, sexp_current_module_path_op, SEXP_FALSE);
  sexp_define_foreign(ctx, env, "load-module-file", 2, sexp_load_module_file_op);
  sexp_define_foreign(ctx, env, "add-module-directory", 2, sexp_add_module_directory_op);
#endif
}

static sexp puchi_module_restore_library_cond_expand(sexp ctx, sexp env) {
  static const char restore_library_ce[] =
    "(define-syntax cond-expand"
    "  (er-macro-transformer"
    "   (lambda (expr rename compare)"
    "     (define (check x)"
    "       (if (pair? x)"
    "           (case (car x)"
    "             ((and) (every check (cdr x)))"
    "             ((or) (any check (cdr x)))"
    "             ((not) (not (check (cadr x))))"
    "             ((library) (eval `(find-module ',(cadr x)) (%meta-env)))"
    "             (else (error \"cond-expand: bad feature\" x)))"
    "           (memq (identifier->symbol x) *features*)))"
    "     (let expand ((ls (cdr expr)))"
    "       (cond"
    "        ((null? ls))"
    "        ((not (pair? (car ls))) (error \"cond-expand: bad clause\" (car ls)))"
    "        ((eq? 'else (identifier->symbol (caar ls)))"
    "         (if (pair? (cdr ls))"
    "             (error \"cond-expand: else in non-final position\")"
    "             `(,(rename 'begin) ,@(cdar ls))))"
    "        ((check (caar ls)) `(,(rename 'begin) ,@(cdar ls)))"
    "        (else (expand (cdr ls))))))))";
  return sexp_eval_string(ctx, restore_library_ce, -1, env);
}

static int puchi_modules_enabled_p(sexp ctx) {
  sexp meta, sym, tmp;
  meta = sexp_global(ctx, SEXP_G_META_ENV);
  if (!sexp_envp(meta)) return 0;
  sym = sexp_intern(ctx, "repl-import", -1);
  tmp = sexp_env_ref(ctx, meta, sym, SEXP_VOID);
  return tmp != SEXP_VOID;
}

sexp sexp_enable_modules(sexp ctx, const puchi_module_ops *ops) {
  sexp env, meta, tmp, sym;
  sexp_gc_var3(meta_gc, tmp_gc, sym_gc);
  if (!ctx || sexp_exceptionp(ctx)) return ctx;
  if (!ops || !ops->exists || !ops->read || !ops->free_buf)
    return sexp_user_exception(ctx, NULL, "sexp_enable_modules: incomplete puchi_module_ops", SEXP_FALSE);

  puchi_g_module_ops = *ops;
  puchi_g_module_ops_set = 1;

  tmp = sexp_load_default_libs(ctx);
  if (sexp_exceptionp(tmp)) return tmp;
  env = sexp_context_env(ctx);

  sexp_gc_preserve3(ctx, meta_gc, tmp_gc, sym_gc);

  meta = sexp_global(ctx, SEXP_G_META_ENV);
  if (!sexp_envp(meta)) {
    meta = sexp_make_env(ctx);
    if (sexp_exceptionp(meta)) {
      sexp_gc_release3(ctx);
      return meta;
    }
    sexp_global(ctx, SEXP_G_META_ENV) = meta;
    sexp_env_parent(meta) = env;
  }
  meta_gc = meta;

  puchi_module_install_foreigns(ctx, env);
  puchi_module_install_foreigns(ctx, meta);

  if (puchi_modules_enabled_p(ctx)) {
    sexp_gc_release3(ctx);
    return ctx;
  }

  {
    sexp old = sexp_context_env(ctx);
    sexp_context_env(ctx) = meta;
    tmp = puchi_module_eval_source(ctx, puchi_meta7_scm, PUCHI_STRLEN(puchi_meta7_scm), meta);
    sexp_context_env(ctx) = old;
  }
  tmp_gc = tmp;
  if (sexp_exceptionp(tmp)) {
    sexp_gc_release3(ctx);
    return tmp;
  }

  /* Splice import from repl-import into interaction env */
  sym = sexp_intern(ctx, "repl-import", -1);
  tmp = sexp_env_ref(ctx, meta, sym, SEXP_VOID);
  if (tmp != SEXP_VOID) {
    sym = sexp_intern(ctx, "import", -1);
    tmp = sexp_cons(ctx, sym, tmp);
    sexp_env_next_cell(tmp) = sexp_env_next_cell(sexp_env_bindings(env));
    sexp_env_next_cell(sexp_env_bindings(env)) = tmp;
  }

  {
    sexp old = sexp_context_env(ctx);
    sexp_context_env(ctx) = env;
    tmp = puchi_module_restore_library_cond_expand(ctx, env);
    sexp_context_env(ctx) = old;
    (void)tmp; /* non-fatal if some libs fall back */
  }

  sexp_gc_release3(ctx);
  return ctx;
}
