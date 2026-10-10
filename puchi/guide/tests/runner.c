/* runner.c - test host for puchi: runs a Scheme file in a VM, the way an
 * embedder would, using only puchi_api.h and Chibi's own API.
 *
 *   runner [-x LIBRARY] [-j N] [--interrupt N] [--expect FILE] SCRIPT
 *
 * Files: library files come from the embedded set; every other path is
 * opened with fopen relative to the current directory (run it from the
 * root of an upstream checkout to reach tests/).  stdout and stderr of the
 * VM are captured in memory and printed afterwards.
 * Exit status: the program's (exit) code, 0 at normal end, 70 on an uncaught
 * error, 99 when --interrupt stopped it.  -j N runs the program again in N
 * VMs on N threads that all start at once, and requires identical output.
 * After every run the VM's allocator must be back at 0 bytes. */
#include <pthread.h>
#include <setjmp.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "puchi.h"

typedef struct { char *data; size_t len, cap; } buffer;

typedef struct job {
  const char *script, *library;
  long interrupt_after, polls;
  long bytes, blocks;            /* outstanding allocations of this VM */
  buffer out;
  int code;
  jmp_buf jump;
} job;

static void buf_add(buffer *b, const char *s, size_t n) {
  if (b->len + n + 1 > b->cap) {
    size_t cap = b->cap ? b->cap * 2 : 4096;
    while (cap < b->len + n + 1) cap *= 2;
    b->data = (char*)realloc(b->data, cap);
    if (!b->data) abort();
    b->cap = cap;
  }
  memcpy(b->data + b->len, s, n);
  b->len += n;
  b->data[b->len] = '\0';
}

/* ---- the host callbacks ---- */
static void *h_allocate(void *ud, size_t n) {
  job *j = (job*)ud;
  size_t *p = (size_t*)malloc(n + 2 * sizeof(size_t));
  if (!p) return NULL;
  p[0] = n;
  j->bytes += (long)n;
  j->blocks++;
  return p + 2;
}
static void h_release(void *ud, void *ptr) {
  job *j = (job*)ud;
  size_t *p = (size_t*)ptr - 2;
  j->bytes -= (long)p[0];
  j->blocks--;
  free(p);
}
static int h_format(void *ud, char *buf, size_t n, const char *fmt, va_list ap) {
  (void)ud;
  return vsnprintf(buf, n, fmt, ap);      /* this test host runs in the "C" locale */
}
static double h_parse_double(void *ud, const char *s, char **end) { (void)ud; return strtod(s, end); }
static ptrdiff_t file_read(void *ud, char *buf, size_t n) {
  size_t r = fread(buf, 1, n, (FILE*)ud);
  return r > 0 ? (ptrdiff_t)r : (ferror((FILE*)ud) ? -1 : 0);
}
static ptrdiff_t file_write(void *ud, const char *buf, size_t n) { return (ptrdiff_t)fwrite(buf, 1, n, (FILE*)ud); }
static void file_close(void *ud) { fclose((FILE*)ud); }
static int h_open_file(void *ud, const char *path, int for_writing, puchi_stream *s) {
  FILE *f = fopen(path, for_writing ? "wb" : "rb");
  (void)ud;
  if (!f) return -1;
  s->userdata = f;
  s->on_read = for_writing ? NULL : file_read;
  s->on_write = for_writing ? file_write : NULL;
  s->on_close = file_close;
  return 0;
}
static int h_file_exists(void *ud, const char *path) {
  FILE *f = fopen(path, "rb");
  (void)ud;
  if (!f) return 0;
  fclose(f);
  return 1;
}
static int h_delete_file(void *ud, const char *path) { (void)ud; return remove(path); }
static void h_on_exit(void *ud, int code) { job *j = (job*)ud; j->code = code; longjmp(j->jump, 1); }
static int h_poll_interrupt(void *ud) {
  job *j = (job*)ud;
  if (j->interrupt_after && ++j->polls >= j->interrupt_after) { j->code = 99; longjmp(j->jump, 1); }
  return 0;
}
static double h_current_second(void *ud) { (void)ud; return (double)time(NULL); }
/* the test programs check that PATH is visible; a real host decides */
static const char *h_get_env(void *ud, const char *name) { (void)ud; return getenv(name); }
static ptrdiff_t out_write(void *ud, const char *s, size_t n) { buf_add(&((job*)ud)->out, s, n); return (ptrdiff_t)n; }

static void run(job *j) {
  puchi_host host;
  sexp ctx;
  long interrupt_after = j->interrupt_after;
  j->interrupt_after = 0;   /* no callback may jump before the jump point exists */
  memset(&host, 0, sizeof host);
  host.userdata = j;
  host.allocate = h_allocate;
  host.release = h_release;
  host.format = h_format;
  host.parse_double = h_parse_double;
  host.open_file = h_open_file;
  host.file_exists = h_file_exists;
  host.delete_file = h_delete_file;
  host.on_exit = h_on_exit;
  host.poll_interrupt = h_poll_interrupt;
  host.current_second = h_current_second;
  host.get_env = h_get_env;
  host.std_out.userdata = j;
  host.std_out.on_write = out_write;
  host.std_err.userdata = j;
  host.std_err.on_write = out_write;
  ctx = puchi_open(&host, 0, 0);
  if (!ctx) { j->code = 71; return; }
  if (setjmp(j->jump) == 0) {
    sexp_gc_var3(env, res, tmp);
    sexp_gc_preserve3(ctx, env, res, tmp);
    /* (command-line) is a core parameter; set it with Chibi's API */
    tmp = sexp_c_string(ctx, j->script, -1);
    tmp = sexp_list1(ctx, tmp);
    sexp_set_parameter(ctx, sexp_global(ctx, SEXP_G_META_ENV),
                       sexp_intern(ctx, "command-line", -1), tmp);
    if (j->library) {
      char expr[256];
      snprintf(expr, sizeof expr, "(mutable-environment '%s)", j->library);
      env = sexp_eval_string(ctx, expr, -1, sexp_global(ctx, SEXP_G_META_ENV));
    } else {
      env = sexp_context_env(ctx);      /* the interaction environment */
    }
    j->polls = 0;                       /* the jump point exists: arm */
    j->interrupt_after = interrupt_after;
    tmp = sexp_c_string(ctx, j->script, -1);
    res = sexp_exceptionp(env) ? env : sexp_load(ctx, tmp, env);
    j->code = 0;
    if (sexp_exceptionp(res)) {
      sexp_print_exception(ctx, res, sexp_current_error_port(ctx));
      j->code = 70;
    }
    puchi_flush(ctx);
    sexp_gc_release3(ctx);
  }
  /* after a jump only puchi_close is legal */
  j->interrupt_after = 0;
  puchi_close(ctx);
}

static void *run_thread(void *arg) { run((job*)arg); return NULL; }

/* (chibi test) prints "in N seconds"; drop it so runs compare */
static void drop_timings(buffer *b) {
  size_t i = 0, k = 0;
  while (i < b->len) {
    if (!strncmp(b->data + i, " in ", 4)) {
      size_t e = i + 4;
      while (e < b->len && ((b->data[e] >= '0' && b->data[e] <= '9') || b->data[e] == '.')) e++;
      if (e > i + 4 && !strncmp(b->data + e, " seconds", 8)) { i = e + 8; continue; }
    }
    b->data[k++] = b->data[i++];
  }
  b->len = k;
  if (b->data) b->data[k] = '\0';
}

int main(int argc, char **argv) {
  int i, n = 0, status;
  const char *expect = NULL;
  job first;
  memset(&first, 0, sizeof first);
  for (i = 1; i < argc; i++) {
    if (!strcmp(argv[i], "-x") && i + 1 < argc) first.library = argv[++i];
    else if (!strcmp(argv[i], "-j") && i + 1 < argc) n = atoi(argv[++i]);
    else if (!strcmp(argv[i], "--interrupt") && i + 1 < argc) first.interrupt_after = atol(argv[++i]);
    else if (!strcmp(argv[i], "--expect") && i + 1 < argc) expect = argv[++i];
    else first.script = argv[i];
  }
  if (!first.script) { fprintf(stderr, "usage: runner [-x LIB] [-j N] [--interrupt N] [--expect FILE] SCRIPT\n"); return 2; }
  if (n > 0) {                          /* threads first: every VM starts cold */
    pthread_t *t = (pthread_t*)calloc((size_t)n, sizeof *t);
    job *jobs = (job*)calloc((size_t)n, sizeof *jobs);
    for (i = 0; i < n; i++) {
      jobs[i].script = first.script;
      jobs[i].library = first.library;
      if (pthread_create(&t[i], NULL, run_thread, &jobs[i]) != 0) abort();
    }
    for (i = 0; i < n; i++) pthread_join(t[i], NULL);
    for (i = 1; i < n; i++) {
      drop_timings(&jobs[0].out);
      drop_timings(&jobs[i].out);
      if (jobs[i].code != jobs[0].code || jobs[i].out.len != jobs[0].out.len
          || memcmp(jobs[i].out.data, jobs[0].out.data, jobs[0].out.len)) {
        fprintf(stderr, "runner: thread %d differs\n", i);
        return 1;
      }
    }
    for (i = 0; i < n; i++)
      if (jobs[i].bytes || jobs[i].blocks) { fprintf(stderr, "runner: thread %d leaked %ld bytes\n", i, jobs[i].bytes); return 1; }
    fprintf(stderr, "runner: %d VMs on %d threads: identical, exit %d\n", n, n, jobs[0].code);
    for (i = 0; i < n; i++) free(jobs[i].out.data);
    free(jobs);
    free(t);
  }
  run(&first);
  fwrite(first.out.data ? first.out.data : "", 1, first.out.len, stdout);
  status = first.code;
  fprintf(stderr, "runner: exit %d, outstanding %ld bytes in %ld blocks\n", first.code, first.bytes, first.blocks);
  if (first.bytes || first.blocks) status = status ? status : 1;
  free(first.out.data);
  if (expect) {
    FILE *f = fopen(expect, "rb");
    char *want;
    long len;
    if (!f) return 2;
    fseek(f, 0, SEEK_END); len = ftell(f); fseek(f, 0, SEEK_SET);
    want = (char*)malloc((size_t)len + 1);
    if (fread(want, 1, (size_t)len, f) != (size_t)len || (size_t)len != first.out.len
        || memcmp(want, first.out.data, (size_t)len)) {
      fprintf(stderr, "runner: output differs from %s\n", expect);
      status = status ? status : 1;
    }
    fclose(f);
    free(want);
  }
  return status;
}
