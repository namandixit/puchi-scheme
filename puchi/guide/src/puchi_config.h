/* puchi_config.h - the one Chibi feature profile puchi is built with.
 * Included before any Chibi header, by both the public and the
 * implementation sections of puchi.h.  Every switch that matters is set
 * explicitly so that an upstream default change cannot silently turn an OS
 * feature back on.  Do not edit without re-running every gate. */
#ifndef PUCHI_CONFIG_H
#define PUCHI_CONFIG_H

/* puchi's two upstream patches (puchi/patches/0001, 0002) */
#define SEXP_USE_HEAP_ALLOCATOR 1     /* every heap comes from the VM's allocator */
#define SEXP_USE_HOST_FILES 1         /* file opens go to sexp_host_open_file() */

/* the VM calls the scheduler slot every SEXP_DEFAULT_QUANTUM instructions;
 * puchi puts its interrupt hook there (no threads are ever created) */
#define SEXP_USE_GREEN_THREADS 1

/* no OS services */
#define SEXP_USE_DL 0
#define SEXP_USE_IMAGE_LOADING 0
#define SEXP_USE_MMAP_GC 0
#define SEXP_USE_TIME_GC 0
#define SEXP_USE_GC_FILE_DESCRIPTORS 0
#define SEXP_USE_STRING_STREAMS 0
#define SEXP_USE_NTP_GETTIME 0
#define SEXP_USE_SEND_FILE 0
#define SEXP_USE_NATIVE_X86 0
#define SEXP_USE_LIMITED_MALLOC 0

/* no process-global state: one heap and one symbol table per VM */
#define SEXP_USE_GLOBAL_HEAP 0
#define SEXP_USE_GLOBAL_SYMBOLS 0
#define SEXP_USE_BOEHM 0
#define SEXP_USE_MALLOC 0
#define SEXP_USE_HUFF_SYMS 0

/* bundled C libraries are compiled in; eval.c #includes the generated clibs.c */
#define SEXP_USE_STATIC_LIBS 1
#define SEXP_USE_STATIC_LIBS_NO_INCLUDE 0
#define SEXP_USE_STATIC_LIBS_EMPTY 0

/* portable bytecode (no unaligned loads) */
#define SEXP_USE_ALIGNED_BYTECODE 1

/* Windows: not a DLL (otherwise SEXP_API is __declspec(dllimport)) */
#ifdef _WIN32
#define SEXP_STATIC_LIBRARY 1
#endif

#endif /* PUCHI_CONFIG_H */
