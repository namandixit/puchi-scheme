/* puchi_glue.c - puchi's own code.  Included by puchi_impl.c AFTER
 * puchi_unredirect.h, so no redirect macro is active here.  Rules:
 *   - all state lives in the puchi_vm reachable from ctx (no globals);
 *   - every contact with the outside world goes through vm->host;
 *   - no C library function that touches the OS is called. */

/* ---- per-VM state ----------------------------------------------------- */

typedef struct puchi_vm {
  puchi_host host;              /* copy of the host's callbacks */
  sexp_allocator_t allocator;   /* given to Chibi; .data points back here */
  sexp stream_box_type;         /* C type of stream boxes (has a finalizer) */
  sexp std_port[3];             /* in, out, err (preserved) */
} puchi_vm;

static puchi_vm *puchi_vm_of(sexp ctx) {
  return (puchi_vm*)sexp_context_heap(ctx)->allocator->data;
}

static void *puchi_vm_allocate(void *data, size_t size) {
  puchi_vm *vm = (puchi_vm*)data;
  return vm->host.allocate(vm->host.userdata, size);
}

static void puchi_vm_release(void *data, void *ptr) {
  puchi_vm *vm = (puchi_vm*)data;
  if (ptr) vm->host.release(vm->host.userdata, ptr);
}

/* ---- targets of the ROUTE redirects (declared in puchi_redirect.h) ---- */

static void *puchi_os_malloc(sexp ctx, size_t size) {
  return puchi_vm_allocate(puchi_vm_of(ctx), size);
}

static void *puchi_os_calloc(sexp ctx, size_t n, size_t size) {
  void *p = puchi_os_malloc(ctx, n * size);
  if (p) memset(p, 0, n * size);
  return p;
}

static void puchi_os_free(sexp ctx, void *ptr) {
  puchi_vm_release(puchi_vm_of(ctx), ptr);
}

static int puchi_os_snprintf(sexp ctx, char *buf, size_t size, const char *fmt, ...) {
  puchi_vm *vm = puchi_vm_of(ctx);
  va_list args;
  int res;
  va_start(args, fmt);
  res = vm->host.format(vm->host.userdata, buf, size, fmt, args);
  va_end(args);
  return res;
}

/* Upstream calls sscanf(str, "%lg", &d) only to check that a printed
 * flonum reads back as the same value (sexp.c, sexp_write_one). */
static int puchi_os_sscanf_double(sexp ctx, const char *str, const char *fmt, double *out) {
  puchi_vm *vm = puchi_vm_of(ctx);
  char *end;
  if (strcmp(fmt, "%lg") != 0) {
    puchi_os_unreachable("sscanf with a format other than %lg");
    return 0;
  }
  *out = vm->host.parse_double(vm->host.userdata, str, &end);
  return end != str;
}

static int puchi_file_exists(sexp ctx, const char *path);

static int puchi_os_stat(sexp ctx, const char *path) {
  return puchi_file_exists(ctx, path) ? 0 : -1;
}

/* exit() in upstream C code: only sexp_warn in strict mode */
static void puchi_os_exit(sexp ctx, int code) {
  puchi_vm *vm = puchi_vm_of(ctx);
  puchi_flush(ctx);
  if (vm->host.on_exit) vm->host.on_exit(vm->host.userdata, code);
}

#ifdef PUCHI_CHECK_UNREACHABLE
/* Test builds only (see GUIDE.md, gate G7): a STUB was reached. */
#include <stdio.h>
#include <stdlib.h>
static void puchi_os_unreachable(const char *name) {
  fprintf(stderr, "\npuchi: unreachable stub reached: %s\n", name);
  abort();
}
#else
static void puchi_os_unreachable(const char *name) { (void)name; }
#endif

static void puchi_os_denied(const char *name) { (void)name; }

/* ---- embedded library files (generated puchi_files.c) ------------------ */

struct puchi_embedded_file {
  const char *name;              /* "lib/scheme/base.sld" */
  const char *const *chunks;     /* NULL-terminated */
};

#include "puchi_files.c"

#define puchi_num_embedded_files \
  (sizeof(puchi_embedded_files) / sizeof(puchi_embedded_files[0]))

static const struct puchi_embedded_file *puchi_find_embedded(const char *path) {
  size_t lo = 0, hi = puchi_num_embedded_files;
  if (path[0] == '.' && path[1] == '/') path += 2;
  while (lo < hi) {
    size_t mid = lo + (hi - lo) / 2;
    int c = strcmp(path, puchi_embedded_files[mid].name);
    if (c == 0) return &puchi_embedded_files[mid];
    if (c < 0) hi = mid; else lo = mid + 1;
  }
  return NULL;
}

static sexp puchi_open_embedded(sexp ctx, const struct puchi_embedded_file *f, sexp path) {
  size_t len = 0, i;
  char *buf, *p;
  sexp_gc_var2(str, res);
  for (i = 0; f->chunks[i]; i++) len += strlen(f->chunks[i]);
  buf = (char*)puchi_os_malloc(ctx, len + 1);
  if (!buf) return sexp_global(ctx, SEXP_G_OOM_ERROR);
  for (p = buf, i = 0; f->chunks[i]; i++) {
    size_t n = strlen(f->chunks[i]);
    memcpy(p, f->chunks[i], n);
    p += n;
  }
  sexp_gc_preserve2(ctx, str, res);
  str = sexp_c_string(ctx, buf, (sexp_sint_t)len);
  puchi_os_free(ctx, buf);
  res = sexp_exceptionp(str) ? str : sexp_open_input_string(ctx, str);
  if (sexp_portp(res)) sexp_port_name(res) = path;
  sexp_gc_release2(ctx);
  return res;
}

static int puchi_file_exists(sexp ctx, const char *path) {
  puchi_vm *vm = puchi_vm_of(ctx);
  if (puchi_find_embedded(path)) return 1;
  return vm->host.file_exists ? vm->host.file_exists(vm->host.userdata, path) != 0 : 0;
}

/* ---- ports over host streams: Chibi custom ports ------------------------
 * A custom port calls a read or write procedure to refill or drain its
 * buffer (sexp.c, sexp_buffered_read_char / sexp_buffered_flush).  Here
 * those procedures are C functions whose opcode data is a "stream box": a
 * C pointer of type stream_box_type to a heap copy of the puchi_stream.
 * The box's finalizer closes the stream if Scheme never did, because Chibi
 * runs a custom port's close procedure only on an explicit close-port. */

typedef struct puchi_stream_box {
  puchi_stream stream;
  int open;
} puchi_stream_box;

/* cast a C primitive to sexp_proc1 (through void(*)(void): no -Wcast-function-type) */
#define puchi_proc(f) ((sexp_proc1)(void (*)(void))(f))

#define puchi_box_of(self) ((puchi_stream_box*)sexp_cpointer_value(sexp_opcode_data(self)))

static char *puchi_buffer_data(sexp buf) {
  return sexp_bytesp(buf) ? (char*)sexp_bytes_data(buf) : sexp_string_data(buf);
}

/* (read buffer start end) -> new end; returning start means end of file */
static sexp puchi_port_read(sexp ctx, sexp self, sexp_sint_t n, sexp buf, sexp start, sexp end) {
  puchi_stream_box *b = puchi_box_of(self);
  sexp_sint_t s = sexp_unbox_fixnum(start), e = sexp_unbox_fixnum(end);
  ptrdiff_t got = 0;
  (void)ctx; (void)n;
  if (b->open && b->stream.on_read)
    got = b->stream.on_read(b->stream.userdata, puchi_buffer_data(buf) + s, (size_t)(e - s));
  return sexp_make_fixnum(got > 0 ? s + got : s);
}

/* (write buffer start end) -> count; <= 0 is an error */
static sexp puchi_port_write(sexp ctx, sexp self, sexp_sint_t n, sexp buf, sexp start, sexp end) {
  puchi_stream_box *b = puchi_box_of(self);
  sexp_sint_t s = sexp_unbox_fixnum(start), e = sexp_unbox_fixnum(end);
  ptrdiff_t put = -1;
  (void)ctx; (void)n;
  if (b->open && b->stream.on_write)
    put = b->stream.on_write(b->stream.userdata, puchi_buffer_data(buf) + s, (size_t)(e - s));
  return sexp_make_fixnum(put);
}

static void puchi_box_close(puchi_stream_box *b) {
  if (b->open) {
    b->open = 0;
    if (b->stream.on_close) b->stream.on_close(b->stream.userdata);
  }
}

/* (close port) - called by close-port */
static sexp puchi_port_close(sexp ctx, sexp self, sexp_sint_t n, sexp port) {
  (void)ctx; (void)n; (void)port;
  puchi_box_close(puchi_box_of(self));
  return SEXP_VOID;
}

/* finalizer of a stream box: when the port is garbage, and for every box
 * left at puchi_close (sexp_destroy_context finalizes everything) */
static sexp puchi_stream_box_finalize(sexp ctx, sexp self, sexp_sint_t n, sexp box) {
  puchi_stream_box *b = (puchi_stream_box*)sexp_cpointer_value(box);
  (void)self; (void)n;
  if (b) {
    puchi_box_close(b);
    sexp_cpointer_value(box) = NULL;
    puchi_os_free(ctx, b);
  }
  return SEXP_VOID;
}

sexp puchi_make_port(sexp ctx, const puchi_stream *stream, int for_writing, sexp name) {
  puchi_vm *vm = puchi_vm_of(ctx);
  puchi_stream_box *b;
  sexp_gc_var5(nm, box, rw, cl, res);
  b = (puchi_stream_box*)puchi_os_malloc(ctx, sizeof *b);
  if (!b) {
    if (stream->on_close) stream->on_close(stream->userdata);
    return sexp_global(ctx, SEXP_G_OOM_ERROR);
  }
  b->stream = *stream;
  b->open = 1;
  sexp_gc_preserve5(ctx, nm, box, rw, cl, res);
  nm = name;
  box = sexp_make_cpointer(ctx, sexp_type_tag(vm->stream_box_type), b, SEXP_FALSE, 0);
  if (sexp_exceptionp(box)) {
    puchi_box_close(b);
    puchi_os_free(ctx, b);
    res = box;
  } else {
    /* from here on the box's finalizer owns b */
    rw = for_writing
      ? sexp_make_foreign(ctx, "puchi-write", 3, 0, NULL, puchi_proc(puchi_port_write), box)
      : sexp_make_foreign(ctx, "puchi-read", 3, 0, NULL, puchi_proc(puchi_port_read), box);
    cl = sexp_exceptionp(rw) ? rw
      : sexp_make_foreign(ctx, "puchi-close", 1, 0, NULL, puchi_proc(puchi_port_close), box);
    if (sexp_exceptionp(cl))
      res = cl;
    else
      res = for_writing ? sexp_make_custom_output_port(ctx, NULL, rw, SEXP_FALSE, cl)
                        : sexp_make_custom_input_port(ctx, NULL, rw, SEXP_FALSE, cl);
    if (sexp_portp(res)) sexp_port_name(res) = nm;
  }
  sexp_gc_release5(ctx);
  return res;
}

/* the hook of patch 0002: every file open in Chibi lands here */
sexp sexp_host_open_file (sexp ctx, sexp self, sexp path, int outputp) {
  puchi_vm *vm = puchi_vm_of(ctx);
  const struct puchi_embedded_file *f;
  puchi_stream stream;
  if (!outputp && (f = puchi_find_embedded(sexp_string_data(path))) != NULL)
    return puchi_open_embedded(ctx, f, path);
  memset(&stream, 0, sizeof stream);
  if (!vm->host.open_file
      || vm->host.open_file(vm->host.userdata, sexp_string_data(path), outputp, &stream) != 0)
    return sexp_file_exception(ctx, self, outputp ? "couldn't open output file"
                               : "couldn't open input file", path);
  return puchi_make_port(ctx, &stream, outputp, path);
}

void puchi_flush(sexp ctx) {
  puchi_vm *vm = puchi_vm_of(ctx);
  int i;
  for (i = 1; i <= 2; i++)
    if (sexp_oportp(vm->std_port[i])) sexp_flush_output(ctx, vm->std_port[i]);
}

/* ---- interrupts: the green-thread scheduler slot ------------------------
 * vm.c calls sexp_global(ctx, SEXP_G_THREADS_SCHEDULER) every
 * SEXP_DEFAULT_QUANTUM instructions and continues with the context it
 * returns.  Setting interruptp makes vm.c raise the "interrupt" error. */

static sexp puchi_scheduler(sexp ctx, sexp self, sexp_sint_t n, sexp root) {
  puchi_vm *vm = puchi_vm_of(ctx);
  (void)self; (void)n; (void)root;
  if (vm->host.poll_interrupt && vm->host.poll_interrupt(vm->host.userdata))
    sexp_context_interruptp(ctx) = 1;
  return ctx;
}

/* ---- (puchi host): the C library behind puchi's own .sld files ----------
 * Registered in the generated clibs.c as the static library "lib/puchi/host". */

static sexp puchi_exit_op(sexp ctx, sexp self, sexp_sint_t n, sexp code) {
  puchi_vm *vm = puchi_vm_of(ctx);
  (void)n;
  puchi_flush(ctx);
  if (vm->host.on_exit)
    vm->host.on_exit(vm->host.userdata, sexp_fixnump(code) ? (int)sexp_unbox_fixnum(code) : 1);
  return sexp_user_exception(ctx, self, "exit is not available in this host", code);
}

static sexp puchi_current_second_op(sexp ctx, sexp self, sexp_sint_t n) {
  puchi_vm *vm = puchi_vm_of(ctx);
  (void)self; (void)n;
  return sexp_make_flonum(ctx, vm->host.current_second
                          ? vm->host.current_second(vm->host.userdata) : 0.0);
}

static sexp puchi_current_jiffy_op(sexp ctx, sexp self, sexp_sint_t n) {
  puchi_vm *vm = puchi_vm_of(ctx);
  double t = vm->host.current_second ? vm->host.current_second(vm->host.userdata) : 0.0;
  (void)self; (void)n;
  return sexp_make_integer(ctx, (sexp_sint_t)(t * 1e6));
}

static sexp puchi_jiffies_per_second_op(sexp ctx, sexp self, sexp_sint_t n) {
  (void)ctx; (void)self; (void)n;
  return sexp_make_fixnum(1000000);
}

static sexp puchi_get_env_op(sexp ctx, sexp self, sexp_sint_t n, sexp name) {
  puchi_vm *vm = puchi_vm_of(ctx);
  const char *v;
  (void)n;
  sexp_assert_type(ctx, sexp_stringp, SEXP_STRING, name);
  v = vm->host.get_env ? vm->host.get_env(vm->host.userdata, sexp_string_data(name)) : NULL;
  return v ? sexp_c_string(ctx, v, -1) : SEXP_FALSE;
}

static sexp puchi_file_exists_op(sexp ctx, sexp self, sexp_sint_t n, sexp path) {
  (void)n;
  sexp_assert_type(ctx, sexp_stringp, SEXP_STRING, path);
  return sexp_make_boolean(puchi_file_exists(ctx, sexp_string_data(path)));
}

static sexp puchi_delete_file_op(sexp ctx, sexp self, sexp_sint_t n, sexp path) {
  puchi_vm *vm = puchi_vm_of(ctx);
  (void)n;
  sexp_assert_type(ctx, sexp_stringp, SEXP_STRING, path);
  if (!vm->host.delete_file
      || vm->host.delete_file(vm->host.userdata, sexp_string_data(path)) != 0)
    return sexp_file_exception(ctx, self, "couldn't delete file", path);
  return SEXP_VOID;
}

static sexp puchi_init_host_library(sexp ctx, sexp self, sexp_sint_t n, sexp env,
                                    const char *version, const sexp_abi_identifier_t abi) {
  (void)self; (void)n; (void)version; (void)abi;
  sexp_define_foreign(ctx, env, "%puchi-exit", 1, puchi_exit_op);
  sexp_define_foreign(ctx, env, "current-second", 0, puchi_current_second_op);
  sexp_define_foreign(ctx, env, "current-jiffy", 0, puchi_current_jiffy_op);
  sexp_define_foreign(ctx, env, "jiffies-per-second", 0, puchi_jiffies_per_second_op);
  sexp_define_foreign(ctx, env, "get-environment-variable", 1, puchi_get_env_op);
  sexp_define_foreign(ctx, env, "file-exists?", 1, puchi_file_exists_op);
  sexp_define_foreign(ctx, env, "delete-file", 1, puchi_delete_file_op);
  return SEXP_VOID;
}

/* ---- VM lifetime ---------------------------------------------------------- */

/* bind import and cond-expand in env, as chibi-scheme's main.c does */
static void puchi_add_import(sexp ctx, sexp env) {
  sexp_gc_var2(sym, tmp);
  sexp_gc_preserve2(ctx, sym, tmp);
  sym = sexp_intern(ctx, "repl-import", -1);
  tmp = sexp_env_ref(ctx, sexp_global(ctx, SEXP_G_META_ENV), sym, SEXP_VOID);
  sym = sexp_intern(ctx, "import", -1);
  sexp_env_define(ctx, env, sym, tmp);
  sym = sexp_intern(ctx, "cond-expand", -1);
  tmp = sexp_env_cell(ctx, sexp_global(ctx, SEXP_G_META_ENV), sym, 0);
  if (tmp && sexp_pairp(tmp)) {   /* NULL counts as a pointer: test it first */
#if SEXP_USE_RENAME_BINDINGS
    sexp_env_rename(ctx, env, sym, tmp);
#endif
    sexp_env_define(ctx, env, sym, sexp_cdr(tmp));
  }
  sexp_gc_release2(ctx);
}

sexp puchi_open(const puchi_host *host, size_t heap_size, size_t heap_max) {
  puchi_vm *vm;
  sexp ctx;
  int i;
  const puchi_stream *std[3];
  sexp_gc_var3(env, tmp, err);
  if (!host || !host->allocate || !host->release || !host->format || !host->parse_double)
    return NULL;
  vm = (puchi_vm*)host->allocate(host->userdata, sizeof *vm);
  if (!vm) return NULL;
  memset(vm, 0, sizeof *vm);
  vm->host = *host;
  vm->allocator.allocate = puchi_vm_allocate;
  vm->allocator.release = puchi_vm_release;
  vm->allocator.data = vm;
  vm->stream_box_type = SEXP_FALSE;
  for (i = 0; i < 3; i++) vm->std_port[i] = SEXP_FALSE;
  ctx = sexp_make_eval_context_with_allocator(NULL, NULL, NULL, heap_size, heap_max, &vm->allocator);
  if (!ctx || sexp_exceptionp(ctx)) {
    /* a half-made VM cannot be destroyed (no context); hosts that need
     * exact accounting on this out-of-memory path should use an arena */
    if (!ctx) host->release(host->userdata, vm);
    return NULL;
  }
  sexp_gc_preserve3(ctx, env, tmp, err);
  err = SEXP_FALSE;
  sexp_global(ctx, SEXP_G_THREADS_SCHEDULER) =
    sexp_make_foreign(ctx, "puchi-scheduler", 1, 0, NULL, puchi_proc(puchi_scheduler), NULL);
  tmp = sexp_c_string(ctx, "puchi-stream", -1);
  if (sexp_exceptionp(tmp)) { err = tmp; goto fail; }
  vm->stream_box_type = sexp_register_c_type(ctx, tmp, puchi_stream_box_finalize);
  if (sexp_exceptionp(vm->stream_box_type)) { err = vm->stream_box_type; goto fail; }
  sexp_preserve_object(ctx, vm->stream_box_type);
  std[0] = &host->std_in; std[1] = &host->std_out; std[2] = &host->std_err;
  for (i = 0; i < 3; i++) {
    tmp = puchi_make_port(ctx, std[i], i > 0, SEXP_FALSE);
    if (sexp_exceptionp(tmp)) { err = tmp; goto fail; }
    vm->std_port[i] = tmp;
    sexp_preserve_object(ctx, tmp);
  }
  env = sexp_load_standard_env(ctx, NULL, SEXP_SEVEN);
  if (sexp_exceptionp(env)) { err = env; goto fail; }
  sexp_set_parameter(ctx, env, sexp_global(ctx, SEXP_G_CUR_IN_SYMBOL), vm->std_port[0]);
  sexp_set_parameter(ctx, env, sexp_global(ctx, SEXP_G_CUR_OUT_SYMBOL), vm->std_port[1]);
  sexp_set_parameter(ctx, env, sexp_global(ctx, SEXP_G_CUR_ERR_SYMBOL), vm->std_port[2]);
  /* the interaction environment: what chibi-scheme's REPL uses */
  env = sexp_eval_string(ctx, "(mutable-environment '(scheme small))", -1,
                         sexp_global(ctx, SEXP_G_META_ENV));
  if (sexp_exceptionp(env)) { err = env; goto fail; }
  puchi_add_import(ctx, env);
  sexp_set_parameter(ctx, sexp_global(ctx, SEXP_G_META_ENV),
                     sexp_global(ctx, SEXP_G_INTERACTION_ENV_SYMBOL), env);
  sexp_context_env(ctx) = env;
  sexp_gc_release3(ctx);
  return ctx;
 fail:
  if (sexp_oportp(vm->std_port[2])) {
    sexp_print_exception(ctx, err, vm->std_port[2]);
    sexp_flush_output(ctx, vm->std_port[2]);
  }
  sexp_gc_release3(ctx);
  puchi_close(ctx);
  return NULL;
}

void puchi_close(sexp ctx) {
  puchi_vm *vm;
  if (!ctx) return;
  vm = puchi_vm_of(ctx);
  sexp_destroy_context(ctx);    /* finalizes everything: closes open streams */
  vm->host.release(vm->host.userdata, vm);
}

sexp puchi_eval_string(sexp ctx, sexp env_arg, const char *src, size_t len) {
  sexp_gc_var4(env, in, x, res);
  sexp_gc_preserve4(ctx, env, in, x, res);
  env = env_arg ? env_arg : sexp_context_env(ctx);
  res = sexp_c_string(ctx, src, len == (size_t)-1 ? -1 : (sexp_sint_t)len);
  in = sexp_exceptionp(res) ? res : sexp_open_input_string(ctx, res);
  res = sexp_exceptionp(in) ? in : SEXP_VOID;
  if (sexp_portp(in)) sexp_port_sourcep(in) = 1;
  while (sexp_portp(in)) {
    x = sexp_read(ctx, in);
    if (x == SEXP_EOF) break;
    if (sexp_exceptionp(x)) { res = x; break; }
    res = sexp_eval(ctx, x, env);
    if (sexp_exceptionp(res)) break;
  }
  puchi_flush(ctx);
  sexp_gc_release4(ctx);
  return res;
}
