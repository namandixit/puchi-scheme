/* puchi_api.h - the public API of puchi.h.
 *
 * puchi is Chibi Scheme, amalgamated and cut off from the operating system.
 * Everything Chibi's own headers declare (sexp_*, SEXP_*) is public API too:
 * use sexp_eval, sexp_apply, sexp_define_foreign, sexp_gc_preserve,
 * sexp_preserve_object ... as documented by Chibi.  This header adds only
 * what Chibi lacks: creating a VM whose every contact with the outside world
 * goes through callbacks the host supplies.
 *
 * Threads: a VM (the sexp returned by puchi_open) may be used by one thread
 * at a time.  Different VMs share nothing and may run in parallel.
 *
 * Names: no member or function here is named like a C library function
 * (read, write, close, free, exit, ...).  puchi_impl.c redirects those names
 * with macros; a member with such a name would be rewritten. */
#ifndef PUCHI_API_H
#define PUCHI_API_H

#include <stdarg.h>
#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/* A byte stream the host provides.  Any callback may be NULL. */
typedef struct puchi_stream {
  void *userdata;
  /* read up to size bytes; return the count, 0 at end of file, <0 on error */
  ptrdiff_t (*on_read)(void *userdata, char *buf, size_t size);
  /* write size bytes; return the count written (<= 0 is an error) */
  ptrdiff_t (*on_write)(void *userdata, const char *buf, size_t size);
  /* called once, when the port is closed or collected, or at puchi_close */
  void (*on_close)(void *userdata);
} puchi_stream;

/* Everything a VM may ask of the outside world.  Copied by puchi_open. */
typedef struct puchi_host {
  void *userdata;                 /* passed to every callback */

  /* REQUIRED.  Every byte the VM uses comes from here, on the thread that
   * is running the VM.  allocate returns NULL on failure. */
  void *(*allocate)(void *userdata, size_t size);
  void (*release)(void *userdata, void *ptr);

  /* REQUIRED.  Number formatting and parsing, independent of any locale:
   * format has the contract of C vsnprintf in the "C" locale (puchi uses
   * "%.15lg", "%.16lg", "%.17lg", "#x%02hhX" and an integer format);
   * parse_double has the contract of C strtod in the "C" locale. */
  int (*format)(void *userdata, char *buf, size_t size, const char *fmt, va_list args);
  double (*parse_double)(void *userdata, const char *str, char **end);

  /* Files.  Paths are what the Scheme program passed.  open_file fills *out
   * and returns 0, or returns nonzero (the program gets a file error).
   * Library files embedded in puchi.h are found before open_file is asked. */
  int (*open_file)(void *userdata, const char *path, int for_writing, puchi_stream *out);
  int (*file_exists)(void *userdata, const char *path);
  int (*delete_file)(void *userdata, const char *path);   /* 0 on success */

  /* (exit code) and (emergency-exit code).  Called after dynamic-wind
   * "after" thunks have run (exit only) and output has been flushed.  It
   * should not return: longjmp out, or switch away from the VM's stack.
   * After it has not returned, the ONLY legal call on the VM is puchi_close.
   * If it returns (or is NULL), exit raises an ordinary Scheme error. */
  void (*on_exit)(void *userdata, int code);

  /* Called every SEXP_DEFAULT_QUANTUM VM instructions.  Return 0 to go on,
   * 1 to raise a catchable "interrupt" error in the program, or do not
   * return (longjmp / stack switch) to stop it for good; then the ONLY
   * legal call on the VM is puchi_close. */
  int (*poll_interrupt)(void *userdata);

  /* (current-second); NULL makes it 0.0.  (get-environment-variable);
   * NULL or a NULL result makes it #f. */
  double (*current_second)(void *userdata);
  const char *(*get_env)(void *userdata, const char *name);

  /* current-input-port, current-output-port, current-error-port */
  puchi_stream std_in, std_out, std_err;
} puchi_host;

/* Create a VM with R7RS-small loaded.  heap_size 0 = Chibi's default;
 * heap_max 0 = no limit.  Returns the context, or NULL (the reason, if any,
 * was written to host->std_err). */
sexp puchi_open(const puchi_host *host, size_t heap_size, size_t heap_max);

/* Destroy the VM: runs finalizers (closing every stream still open), then
 * returns all memory to host->release.  Safe after an abandoning callback. */
void puchi_close(sexp ctx);

/* Read and evaluate every form of src (len bytes, or NUL-terminated if len
 * is (size_t)-1) in env (NULL = the interaction environment, which has all
 * of R7RS-small and import).  Returns the last value or an exception
 * object; flushes the standard output ports.  The result is not rooted. */
sexp puchi_eval_string(sexp ctx, sexp env, const char *src, size_t len);

/* An input or output port over a host stream.  The port owns the stream
 * from now on (on_close is called exactly once).  name may be SEXP_FALSE. */
sexp puchi_make_port(sexp ctx, const puchi_stream *stream, int for_writing, sexp name);

/* Flush current-output-port and current-error-port. */
void puchi_flush(sexp ctx);

#ifdef __cplusplus
}
#endif

#endif /* PUCHI_API_H */
