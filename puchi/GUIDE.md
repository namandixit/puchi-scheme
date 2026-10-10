# puchi: building a single-header, sandboxed, embeddable Chibi Scheme from scratch

This guide tells an agent how to turn a fresh fork of chibi-scheme into
`puchi.h`, a single-header (stb-style) library that is:

- **embeddable**: one header, `#define PUCHI_IMPLEMENTATION` in one C file;
- **sandboxed**: the compiled code cannot reach the operating system; every
  contact with the outside world goes through callbacks the host supplies;
- **reentrant and thread-safe per VM**: a VM (context) is used by one thread
  at a time, like `lua_State`; different VMs share nothing and run in parallel.

Constraint: **no file outside `puchi/` may be edited**, so that merging a new
upstream chibi-scheme never conflicts.

Every file this guide asks you to create exists, verified, in
`puchi/guide/` next to this file (compiled and tested against upstream
commit `c4e7367`). When the guide shows code, it is copied from there.

---

## Part 1 - Summary of the whole guide (read this first)

### 1.1 The design in ten lines

1. **Amalgamation**: a Python script copies the git-tracked upstream files
   into `puchi/build/src`, applies `puchi/patches/*.patch`, generates two
   files (`clibs.c`: bundled C libraries; `puchi_files.c`: embedded Scheme
   library files), and inlines every `#include "..."` into `puchi/puchi.h`.
2. **One fixed feature profile** (`puchi_config.h`) using Chibi's own
   `SEXP_USE_*` switches: no dynamic loading, no global heap, no global
   symbol table, static C libraries, green threads ON (only for the
   interrupt hook - no threads are ever created).
3. **Two feature patches** (small, opt-in, written to be upstreamable):
   - `0001 SEXP_USE_HEAP_ALLOCATOR` - each context's heaps come from an
     allocator passed to `sexp_make_eval_context_with_allocator` (75 lines).
   - `0002 SEXP_USE_HOST_FILES` - `open-input-file`, `open-output-file`,
     `load` and module loading get their port from `sexp_host_open_file()`
     instead of `fopen()` (18 lines).
   Plus **three upstream bug fixes** (UB in `sexp_read_number`, UB and a
   wrong result in `sexp_make_integer_from_lsint` on 32-bit). Submit all five
   upstream; carry them until merged.
4. **A redirect layer** (`puchi_redirect.h`): every OS-facing C library
   function upstream calls is `#define`d, inside the implementation only, to
   one of three things, never anything else:
   - **STUB** - the call sits on a path that cannot run in puchi (needs a
     `FILE*`, a file descriptor, a socket or a missing error port; puchi
     never creates any). Returns a failure value; aborts in test builds.
   - **DENY** - the capability is removed (`getenv`, `setenv`, fd `read` ...).
     Returns failure.
   - **ROUTE** - a one-sentence contract served by the VM: `malloc/free` ->
     the VM's allocator; `stat` -> "does this path exist"; `snprintf` -> the
     host's `format` (vsnprintf) callback; `sscanf("%lg")` -> the host's
     `parse_double` (strtod) callback; `exit` -> the host's `on_exit`.
   **Never EMULATE an OS API** (no fake stdio, no fd tables). Routing uses
   the `ctx` variable that is in scope at 272 of 275 OS call sites (the other
   three are fixed by patch 0001 or are stubs). Function-like macros so that
   members/parameters with the same names are untouched.
5. **Chibi's own extension points** for everything that must really work:
   - all ports are **Chibi custom ports** (read/write procedures are C
     functions over a host `puchi_stream`) - no `FILE*`, no fd, ever;
   - embedded library files are opened as **string ports**;
   - interrupts use the **green-thread scheduler slot**
     (`SEXP_G_THREADS_SCHEDULER`), called every 500 VM instructions;
   - `exit`, time, environment and file predicates come from puchi's own
     `.sld` files (`(scheme process-context)`, `(scheme time)`,
     `(scheme file)`) backed by a static C library `(puchi host)`.
6. **Public API** = Chibi's own API (`sexp_*`, documented upstream) plus a
   thin `puchi_*` layer: `puchi_open(host, heap, max)`, `puchi_close`,
   `puchi_eval_string`, `puchi_make_port`, `puchi_flush`. The host gives a
   `puchi_host` struct of callbacks: allocate/release, format/parse_double,
   open_file/file_exists/delete_file, on_exit, poll_interrupt,
   current_second, get_env, std_in/std_out/std_err streams.
7. **exit and hard interrupt** are host callbacks that do NOT return
   (longjmp or stack switch). Afterwards the ONLY legal call on that VM is
   `puchi_close` (verified safe; any GC/allocation on it is fatal). Soft
   interrupt (return 1 from `poll_interrupt`) raises a catchable error and
   the VM stays usable.
8. **Streams are owned by puchi**: each port's stream lives in a "box" with a
   C finalizer, so a port that Scheme never closes is closed when collected
   or at `puchi_close` (Chibi only runs a custom port's close procedure on an
   explicit `close-port`).
9. **The sandbox guarantee is a check, not a belief**: the compiled
   implementation's undefined symbols must be a subset of a short allowlist
   (memory/string basics, math, errno, compiler helpers). Any new OS call in
   a future upstream shows up there and fails the build.
10. **Gates** (every phase ends with one; never continue on a failed gate):
    symbols, writable data, exported names, redirect collisions (libclang),
    unreachable-stub trap build + upstream test suites, ASan/UBSan/LSan,
    TSan with N VMs started cold on N threads, abandon tests (exit,
    interrupt, dropped port), allocator balance (0 bytes left), public
    header in C89..C11 and C++98..C++17 with `-pedantic -Werror`, warnings in
    puchi's own code, Windows cross-compile with clang + MinGW headers,
    deterministic output.

### 1.2 Verified results (what the reference files achieved)

| Check | Result |
|---|---|
| Undefined symbols (Linux, gcc -O1) | only `mem*`, `str{len,cmp,ncmp,chr,str,ncpy}`, math, `__errno_location`, `__stack_chk_fail`, `__udivti3` |
| Undefined symbols (Windows target, clang + MinGW headers) | same set plus `___chkstk_ms`, `_errno`, `ceil/floor/trunc` |
| Exported symbols | all start with `sexp_` or `puchi_` |
| Writable data | only upstream tables that are read-only after init; embedded files are in `.data.rel.ro` |
| r7rs-tests | 1233/1233 |
| r5rs-tests (-x (chibi)) | 189/189 |
| syntax / unicode / division | 12/12, 18/18, 304/304 |
| (chibi io-test) | 44/45 - `file-position` unsupported on custom ports (see hazards) |
| tests/basic (byte-identical output) | 10/11 - `test10-unhygiene` fails upstream too |
| Unreachable stubs hit (trap build, all suites) | 0 |
| Deny stubs hit | `getenv` x2 per VM (module-path variables at startup) |
| Allocator balance after every run | 0 bytes, 0 blocks |
| ASan + UBSan + LSan, all suites + exit/interrupt/dropped-port | clean |
| TSan, 8 VMs started cold on 8 threads | clean, identical output |
| Public section, C89/C99/C11, C++98/11/17, gcc+clang, -pedantic -Werror | clean |
| Warnings in puchi's own files (gcc, clang -Wall -Wextra) | none |
| Redirect collision check (libclang) | 0 (Linux); Windows flags ast.c `setenv`/`unsetenv` -> handled |

### 1.3 Facts the design depends on (verified; do not re-investigate)

- Upstream with this profile has no mutable global state at run time; the
  only writes are two init flags that `puchi_open` never triggers.
- 275 OS-facing references in the compiled upstream files; 272 are in a
  function with a `sexp ctx` parameter. The 3 without: `malloc` in
  `sexp_make_heap`, `free` in `sexp_free_heap` (patch 0001), `fstat` in
  `sexp_is_a_socket_p` (deny).
- Upstream never reads inside a `FILE` structure.
- Standard ports are created only by `sexp_load_standard_ports`, with
  `FILE*`s from the caller - puchi does not call it.
- All file opens go through `sexp_open_input_file_op` /
  `sexp_open_output_file_op` (`eval.c`), which call `fopen` - hence patch 0002.
- Custom ports (string streams off) need no OS: buffer + read/write
  procedures; refill returns the new end index (`BUF_START` = 4).
- `sexp_destroy_context` marks only the type table, then finalizes and
  sweeps; it never walks a context's GC root list, so closing a VM whose C
  stack was abandoned is safe. A GC on such a VM is not (ASan proves it).
- No Scheme value can be a context object in this profile (no SRFI 18).
- Upstream's "abort trampoline" (`vm.c`) stops at the first C caller, so it
  cannot replace the non-returning exit callback.
- Float printing tries `%.15lg`, `%.16lg`, `%.17lg` and checks each with
  `sscanf("%lg")` - printing needs a parser, hence `parse_double`.
- `file-position` in this profile only works on fd and `FILE*` ports
  (`io.c`, `sexp_seek`) - never on custom ports.
- Green threads add only `fcntl`/`ferror`/`poll` (stubbed) and cost ~3-6%;
  upstream does not compile green threads on Windows - the redirect header
  supplies the missing names.

### 1.4 Parts of this guide

- Part 2 - Rules for the agent (what never to do; stop conditions)
- Part 3 - Repository layout
- Part 4 - Phase 1: setup and tools
- Part 5 - Phase 2: the patches (workflow, contents, gate)
- Part 6 - Phase 3: the profile
- Part 7 - Phase 4: the redirect layer
- Part 8 - Phase 5: the implementation file and the glue
- Part 9 - Phase 6: Scheme library overrides
- Part 10 - Phase 7: public API and `puchi.h.in`
- Part 11 - Phase 8: the generator (`amalgamate.py`)
- Part 12 - Phase 9: tests and gates (exact commands, expected output)
- Part 13 - Updating to a new upstream
- Part 14 - Known hazards and limitations
- Part 15 - Decisions and why (rejected alternatives)

---

## Part 2 - Rules for the agent

Read these before every phase. They exist because each one was broken by an
earlier attempt and cost days.

### 2.1 Never

1. **Never edit a file outside `puchi/`.** Upstream changes live only in
   `puchi/patches/*.patch`, applied to a *copy* (`puchi/build/src`).
2. **Never emulate an OS API.** A redirect may only STUB, DENY or ROUTE a
   one-sentence contract (Part 7). If making something work seems to need a
   fake `FILE`, a fake file-descriptor table, a fake `errno` protocol or a
   fake `select`, stop: you are on the wrong path. Real I/O goes through
   Chibi custom ports.
3. **Never fold `SEXP_USE_*` flags out of the source, strip code, or
   reformat upstream files.** The profile header selects features; the
   preprocessor removes the rest.
4. **Never add test-only code paths to the library.** The single allowed
   exception is the compile switch `PUCHI_CHECK_UNREACHABLE`, which makes
   STUBs abort; it adds no behaviour, only a check, and is off by default.
   Anything a test needs (counting allocations, capturing output, setting
   `command-line`) belongs in the test host, using the public API.
5. **Never keep state in globals in puchi's code.** All state lives in the
   `puchi_vm` struct reachable from `ctx`
   (`sexp_context_heap(ctx)->allocator->data`).
6. **Never name an identifier after a C library function** (`read`, `write`,
   `close`, `free`, `alloc`, `exit`, `stat`, `getenv` ...) in puchi code or
   in a patch. The redirect macros would rewrite `p->free(x)`. This exact
   bug happened while writing patch 0001 (members were named
   `alloc`/`free`; renamed to `allocate`/`release`). Gate G5 checks it.
7. **Never call any `sexp_*` function on a VM after a host callback did not
   return** (exit or hard interrupt). Only `puchi_close`.
8. **Never let a host callback jump before its jump point exists.** A test
   host that armed its interrupt counter before `puchi_open` returned
   longjmp'd into an unset `jmp_buf` and crashed (happened twice).
9. **Never claim a gate passed without reading its output.** Exit status 0
   from a test runner is not "passed": read the summary lines (`(chibi
   test)` output contains ANSI colour codes when `TERM` is visible to the
   VM; strip them before grepping).
10. **Never add symbol-hiding machinery** (making every upstream function
    `static`, generated linkage headers, `SEXP_API static`). All exported
    names already start with `sexp_` or `puchi_`; that is enough.

### 2.2 Stop conditions

Stop and report to the owner, instead of continuing, when:

- a fix would be a workaround on top of a workaround;
- a gate fails twice for reasons you cannot explain from the code;
- upstream changed in a way that needs a third feature patch;
- something in this guide turns out to be false - report which statement,
  with the evidence (command and output).

### 2.3 How to work

- One phase at a time, in order. Each phase ends with a gate.
- Commit after every phase that passes its gate. Push often.
- When a step says "verify", run the command and compare with the expected
  output given here.

---

## Part 3 - Repository layout

```
<fork of chibi-scheme>/          upstream files: NEVER edited
  puchi/
    GUIDE.md                     this guide (optional in the product)
    README.md                    short: what puchi is, how to regenerate
    puchi.h                      GENERATED output, committed
    patches/                     0001..0005 *.patch (git format-patch output)
    src/
      puchi.h.in                 skeleton of puchi.h (public + implementation)
      puchi_config.h             the feature profile
      puchi_api.h                the puchi_* API
      puchi_impl.c               implementation: order of includes
      puchi_redirect.h           STUB / DENY / ROUTE macros
      puchi_unredirect.h         undoes them, restores host macros
      puchi_glue.c               puchi's own code (VM, ports, hooks, open/close)
      install.h.in               template for chibi/install.h
    lib/
      scheme/process-context.sld replaces upstream's (exit via host)
      scheme/time.sld            replaces upstream's (clock via host)
      scheme/file.sld            replaces upstream's (file-exists?, delete-file)
      puchi/host.sld             the (puchi host) library (include-shared "host")
    tools/
      amalgamate.py              the generator
      check_collisions.py        gate G5 (libclang)
      inventory.py               lists every OS reference + ctx scope (libclang)
    tests/
      runner.c                   test host: runs a .scm file in a VM
      impl.c                     #define PUCHI_IMPLEMENTATION / #include "puchi.h"
      abandon_test.c             stock-Chibi proof that close-after-abandon is safe
      scheme/*.scm               exit / interrupt / dropped-port / io-test drivers
    build/                       GENERATED, not committed (.gitignore)
```

`.gitignore`: add `puchi/build/` to `puchi/.gitignore` (not the root one,
which is upstream's).

---

## Part 4 - Phase 1: setup and tools

1. Fork chibi-scheme on GitHub; clone; create a working branch.
2. Record the upstream commit you start from: `git rev-parse HEAD`
   (the reference files were verified on `c4e7367`).
3. Tools required (all were used in verification):
   - `git`, `python3` (3.8+), `make`, a C compiler (gcc and clang);
   - clang's `libclang` and its Python bindings for gates G5 and the
     inventory tool: `pip install clang==<your clang major>.*` and point the
     tools at the library with `LIBCLANG=/usr/lib/llvm-NN/lib/libclang-NN.so.1`;
   - `llvm-nm` (works on ELF, COFF and Mach-O objects) or `nm`;
   - for the Windows gate on a non-Windows machine: MinGW-w64 headers
     (`apt-get install mingw-w64-x86-64-dev`) used with
     `clang --target=x86_64-w64-windows-gnu`.
4. Build a stock chibi-scheme once (needed only to run `chibi-ffi`, which
   generates `lib/chibi/io/io.c` from `io.stub`):
   `cp -r <fork> /tmp/host && make -C /tmp/host chibi-scheme`.
   The generator can do this itself into `puchi/build/host`, or take
   `--chibi PATH` (then set `LD_LIBRARY_PATH` and `CHIBI_MODULE_PATH` to that
   build's directory and its `lib/`).

**Gate G0**: `make -C /tmp/host chibi-scheme` succeeds and
`/tmp/host/chibi-scheme -q -e '(display 42)'` prints `42` (with
`LD_LIBRARY_PATH=/tmp/host CHIBI_MODULE_PATH=/tmp/host/lib`).

(Use `-q`: `make chibi-scheme` builds only the interpreter, not the library
`.so` files, so without `-q` it fails with `couldn't find include:
"srfi/69/hash.so"` - expected, and irrelevant for running chibi-ffi.)

---

## Part 5 - Phase 2: the patches

### 5.1 Workflow (always the same)

Patches are made in a scratch git repository holding a pristine copy of
upstream, never in the fork's work tree:

```sh
mkdir /tmp/pw && git -C <fork> archive HEAD | tar -x -C /tmp/pw
cd /tmp/pw && git init -q && git add -A && git commit -qm "upstream <sha>"
git am -3 <fork>/puchi/patches/*.patch        # existing patches, if any
# ... edit, then for a new patch:
git commit -am "Add SEXP_USE_...: ..."
git format-patch --zero-commit --no-signature --no-numbered -o <fork>/puchi/patches <upstream-commit>
```

`--zero-commit --no-signature` keep the patch files stable across
regenerations (no hashes or version footers change).

The generator applies them to its copy with
`git apply -p1 --whitespace=nowarn --directory=puchi/build/src <patch>`
run from the fork root (`--directory` makes git apply work on the copy).

### 5.2 The five patches

| File | What | Why it cannot be done without a patch |
|---|---|---|
| `0001-Add-SEXP_USE_HEAP_ALLOCATOR-...` | Each context's heaps come from a `sexp_allocator_t {allocate, release, data}` stored in `struct sexp_heap_t`. New `sexp_make_eval_context_with_allocator`, `sexp_make_context_with_allocator`, `sexp_make_heap_with_allocator`. Under the flag the old entry points pass NULL and fail instead of calling `malloc`. | The first heap is made before any context exists, and `sexp_make_heap`/`sexp_free_heap` take no `ctx`; nothing outside the source can route them. The other 14 allocation sites have `ctx` and are routed by the redirect layer. |
| `0002-Add-SEXP_USE_HOST_FILES-...` | `sexp_open_input_file_op` / `sexp_open_output_file_op` return `sexp_host_open_file(ctx, self, path, outputp)` (defined by the embedder). | Those two functions turn a path into a `FILE*` port; routing `fopen` would require emulating stdio. |
| `0003-Avoid-signed-overflow-...` | `sexp_read_number` checks for overflow before multiplying. | Upstream bug (UBSan). |
| `0004-Negate-in-unsigned-...` | `sexp_make_integer_from_lsint` negates in unsigned arithmetic. | Upstream bug (UBSan on INT64_MIN). |
| `0005-Fix-negative-two-limb-...` | Carry into the high limb when the low limb is 0. | Upstream bug: on 32-bit, `sexp_make_integer(ctx, -2^32)` returned 0. |

Both feature flags default to 0 in `features.h`, so upstream's normal build
is unchanged. **Gate G1 below checks that.**

Rules for patches: minimal; opt-in through a `SEXP_USE_*` flag with a
default in `features.h`; written in upstream's style; no identifier named
after a C library function; each one a separate commit with an explanatory
message, so it can be sent upstream as is.

### 5.3 Patch texts (byte-identical copies are in `puchi/guide/patches/`)

Prefer copying the files. If you must recreate them from this document and
`git am` fails on whitespace, use `git am --ignore-whitespace` or re-make
the edit by hand following the diff.

#### `0001-Add-SEXP_USE_HEAP_ALLOCATOR-per-context-heap-allocat.patch`

```diff
From 0000000000000000000000000000000000000000 Mon Sep 17 00:00:00 2001
From: puchi <puchi@localhost>
Date: Sat, 10 Oct 2026 05:57:26 +0000
Subject: [PATCH] Add SEXP_USE_HEAP_ALLOCATOR: per-context heap allocator

---
 eval.c                   | 10 ++++++++++
 gc.c                     | 15 +++++++++++++++
 include/chibi/eval.h     |  3 +++
 include/chibi/features.h |  7 +++++++
 include/chibi/sexp.h     | 18 ++++++++++++++++++
 sexp.c                   | 26 ++++++++++++++++++++++----
 6 files changed, 75 insertions(+), 4 deletions(-)

diff --git a/eval.c b/eval.c
index 8a7f0de..0e32093 100644
--- a/eval.c
+++ b/eval.c
@@ -530,9 +530,19 @@ void sexp_init_eval_context_globals (sexp ctx) {
 #endif
 }
 
+#if SEXP_USE_HEAP_ALLOCATOR
+sexp sexp_make_eval_context (sexp ctx, sexp stack, sexp env, sexp_uint_t size, sexp_uint_t max_size) {
+  return sexp_make_eval_context_with_allocator(ctx, stack, env, size, max_size, NULL);
+}
+
+sexp sexp_make_eval_context_with_allocator (sexp ctx, sexp stack, sexp env, sexp_uint_t size, sexp_uint_t max_size, sexp_allocator_t *allocator) {
+  sexp_gc_var1(res);
+  res = sexp_make_context_with_allocator(ctx, size, max_size, allocator);
+#else
 sexp sexp_make_eval_context (sexp ctx, sexp stack, sexp env, sexp_uint_t size, sexp_uint_t max_size) {
   sexp_gc_var1(res);
   res = sexp_make_context(ctx, size, max_size);
+#endif
   if (!res || sexp_exceptionp(res))
     return res;
   if (ctx) sexp_gc_preserve1(ctx, res);
diff --git a/gc.c b/gc.c
index da2e179..b1be4df 100644
--- a/gc.c
+++ b/gc.c
@@ -86,6 +86,8 @@ void sexp_debug_alloc_sizes(sexp ctx) {
 void sexp_free_heap (sexp_heap heap) {
 #if SEXP_USE_MMAP_GC
   munmap(heap, sexp_heap_pad_size(heap->size));
+#elif SEXP_USE_HEAP_ALLOCATOR
+  heap->allocator->release(heap->allocator->data, heap);
 #else
   free(heap);
 #endif
@@ -578,13 +580,22 @@ sexp sexp_gc (sexp ctx, size_t *sum_freed) {
   return res;
 }
 
+#if SEXP_USE_HEAP_ALLOCATOR
+sexp_heap sexp_make_heap_with_allocator (size_t size, size_t max_size, size_t chunk_size, sexp_allocator_t *allocator) {
+#else
 sexp_heap sexp_make_heap (size_t size, size_t max_size, size_t chunk_size) {
+#endif
   sexp_free_list free, next;
   sexp_heap h;
 #if SEXP_USE_MMAP_GC
   h =  mmap(NULL, sexp_heap_pad_size(size), PROT_READ|PROT_WRITE,
             MAP_ANON|MAP_PRIVATE, -1, 0);
   if (h == MAP_FAILED) return NULL;
+#elif SEXP_USE_HEAP_ALLOCATOR
+  if (! allocator) return NULL;
+  h = allocator->allocate(allocator->data, sexp_heap_pad_size(size));
+  if (! h) return NULL;
+  h->allocator = allocator;
 #else
   h =  sexp_malloc(sexp_heap_pad_size(size));
   if (! h) return NULL;
@@ -626,7 +637,11 @@ int sexp_grow_heap (sexp ctx, size_t size, size_t chunk_size) {
 #endif
   cur_size = h->size;
   new_size = (size_t) ceil(SEXP_GROW_HEAP_FACTOR * (double) (sexp_heap_align(((cur_size > size) ? cur_size : size))));
+#if SEXP_USE_HEAP_ALLOCATOR
+  tmp = sexp_make_heap_with_allocator(new_size, h->max_size, chunk_size, h->allocator);
+#else
   tmp = sexp_make_heap(new_size, h->max_size, chunk_size);
+#endif
   if (tmp) {
     tmp->next = h->next;
     h->next = tmp;
diff --git a/include/chibi/eval.h b/include/chibi/eval.h
index c2bca62..52c7c45 100644
--- a/include/chibi/eval.h
+++ b/include/chibi/eval.h
@@ -55,6 +55,9 @@ SEXP_API const char** sexp_opcode_names;
 SEXP_API void sexp_warn (sexp ctx, const char *msg, sexp x);
 SEXP_API void sexp_scheme_init (void);
 SEXP_API sexp sexp_make_eval_context (sexp context, sexp stack, sexp env, sexp_uint_t size, sexp_uint_t max_size);
+#if SEXP_USE_HEAP_ALLOCATOR
+SEXP_API sexp sexp_make_eval_context_with_allocator (sexp context, sexp stack, sexp env, sexp_uint_t size, sexp_uint_t max_size, sexp_allocator_t *allocator);
+#endif
 SEXP_API sexp sexp_make_child_context (sexp context, sexp lambda);
 SEXP_API sexp sexp_compile_error (sexp ctx, const char *message, sexp obj);
 SEXP_API sexp sexp_maybe_wrap_error (sexp ctx, sexp obj);
diff --git a/include/chibi/features.h b/include/chibi/features.h
index fee7c1c..90ed861 100644
--- a/include/chibi/features.h
+++ b/include/chibi/features.h
@@ -486,6 +486,13 @@
 #define SEXP_USE_STATIC_LIBS SEXP_USE_STATIC_LIBS_EMPTY
 #endif
 
+/* uncomment this to allocate each context's heaps (and nothing else) */
+/*   through an allocator passed to sexp_make_eval_context_with_allocator */
+/* #define SEXP_USE_HEAP_ALLOCATOR 1 */
+#ifndef SEXP_USE_HEAP_ALLOCATOR
+#define SEXP_USE_HEAP_ALLOCATOR 0
+#endif
+
 /* don't include clibs.c - include separately or link */
 #ifndef SEXP_USE_STATIC_LIBS_NO_INCLUDE
 #if defined(PLAN9) || SEXP_USE_STATIC_LIBS_EMPTY
diff --git a/include/chibi/sexp.h b/include/chibi/sexp.h
index 4f10345..0762eec 100644
--- a/include/chibi/sexp.h
+++ b/include/chibi/sexp.h
@@ -386,10 +386,20 @@ struct sexp_free_list_t {
 };
 
 typedef struct sexp_heap_t *sexp_heap;
+#if SEXP_USE_HEAP_ALLOCATOR
+typedef struct sexp_allocator_t {
+  void *(*allocate)(void *data, size_t size);  /* returns NULL on failure */
+  void (*release)(void *data, void *ptr);
+  void *data;
+} sexp_allocator_t;
+#endif
 struct sexp_heap_t {
   sexp_uint_t size, max_size, chunk_size;
   sexp_free_list free_list;
   sexp_heap next;
+#if SEXP_USE_HEAP_ALLOCATOR
+  sexp_allocator_t *allocator;
+#endif
   /* note this must be aligned on a proper heap boundary, */
   /* so we can't just use char data[] */
   char *data;
@@ -1733,6 +1743,9 @@ SEXP_API void sexp_add_static_libraries(struct sexp_library_entry_t* libraries);
 
 SEXP_API sexp sexp_alloc_tagged_aux(sexp ctx, size_t size, sexp_uint_t tag sexp_current_source_param);
 SEXP_API sexp sexp_make_context(sexp ctx, size_t size, size_t max_size);
+#if SEXP_USE_HEAP_ALLOCATOR
+SEXP_API sexp sexp_make_context_with_allocator(sexp ctx, size_t size, size_t max_size, sexp_allocator_t *allocator);
+#endif
 SEXP_API sexp sexp_cons_op(sexp ctx, sexp self, sexp_sint_t n, sexp head, sexp tail);
 SEXP_API sexp sexp_list2(sexp ctx, sexp a, sexp b);
 SEXP_API sexp sexp_list3(sexp ctx, sexp a, sexp b, sexp c);
@@ -1892,7 +1905,12 @@ SEXP_API void sexp_maybe_unblock_port (sexp ctx, sexp in);
 #if ! SEXP_USE_BOEHM && ! SEXP_USE_MALLOC
 SEXP_API void sexp_gc_init (void);
 SEXP_API int sexp_grow_heap (sexp ctx, size_t size, size_t chunk_size);
+#if SEXP_USE_HEAP_ALLOCATOR
+SEXP_API sexp_heap sexp_make_heap_with_allocator (size_t size, size_t max_size, size_t chunk_size, sexp_allocator_t *allocator);
+#define sexp_make_heap(size, max_size, chunk_size) sexp_make_heap_with_allocator(size, max_size, chunk_size, NULL)
+#else
 SEXP_API sexp_heap sexp_make_heap (size_t size, size_t max_size, size_t chunk_size);
+#endif
 SEXP_API void sexp_mark (sexp ctx, sexp x);
 SEXP_API sexp sexp_sweep (sexp ctx, size_t *sum_freed_ptr);
 #if SEXP_USE_FINALIZERS
diff --git a/sexp.c b/sexp.c
index d4e809d..37da14d 100644
--- a/sexp.c
+++ b/sexp.c
@@ -619,14 +619,20 @@ void sexp_init_context_globals (sexp ctx) {
 }
 
 #if ! SEXP_USE_GLOBAL_HEAP
+#if SEXP_USE_HEAP_ALLOCATOR
+#define sexp_bootstrap_make_heap(size, max_size) sexp_make_heap_with_allocator(size, max_size, 0, allocator)
+static sexp sexp_bootstrap_context_with_allocator (sexp_uint_t size, sexp_uint_t max_size, sexp_allocator_t *allocator) {
+#else
+#define sexp_bootstrap_make_heap(size, max_size) sexp_make_heap(size, max_size, 0)
 sexp sexp_bootstrap_context (sexp_uint_t size, sexp_uint_t max_size) {
+#endif
   sexp ctx;
   sexp_heap heap;
   struct sexp_struct dummy_ctx;
   if (size < SEXP_MINIMUM_HEAP_SIZE) size = SEXP_INITIAL_HEAP_SIZE;
   size = sexp_heap_align(size);
   max_size = sexp_heap_align(max_size);
-  heap = sexp_make_heap(size, max_size, 0);
+  heap = sexp_bootstrap_make_heap(size, max_size);
   if (!heap) return 0;
   sexp_pointer_tag(&dummy_ctx) = SEXP_CONTEXT;
   sexp_context_mark_stack_ptr(&dummy_ctx) = NULL;
@@ -639,13 +645,13 @@ sexp sexp_bootstrap_context (sexp_uint_t size, sexp_uint_t max_size) {
     sexp_context_heap(ctx) = heap;
 #if SEXP_USE_FIXED_CHUNK_SIZE_HEAPS
     heap->chunk_size = sexp_heap_align(1);
-    heap->next = sexp_make_heap(size, max_size, 0);
+    heap->next = sexp_bootstrap_make_heap(size, max_size);
     if (heap->next) {
       heap->next->chunk_size = sexp_heap_align(1 + sexp_heap_align(1));
-      heap->next->next = sexp_make_heap(size, max_size, 0);
+      heap->next->next = sexp_bootstrap_make_heap(size, max_size);
       if (heap->next->next) {
         heap->next->next->chunk_size = sexp_heap_align(1 + sexp_heap_align(1 + sexp_heap_align(1)));
-        heap->next->next->next = sexp_make_heap(size, max_size, 0);
+        heap->next->next->next = sexp_bootstrap_make_heap(size, max_size);
       }
     }
 #endif
@@ -654,12 +660,24 @@ sexp sexp_bootstrap_context (sexp_uint_t size, sexp_uint_t max_size) {
 }
 #endif
 
+#if SEXP_USE_HEAP_ALLOCATOR
 sexp sexp_make_context (sexp ctx, size_t size, size_t max_size) {
+  return sexp_make_context_with_allocator(ctx, size, max_size, NULL);
+}
+
+sexp sexp_make_context_with_allocator (sexp ctx, size_t size, size_t max_size, sexp_allocator_t *allocator) {
+#else
+sexp sexp_make_context (sexp ctx, size_t size, size_t max_size) {
+#endif
   sexp_gc_var1(res);
   if (ctx) sexp_gc_preserve1(ctx, res);
 #if ! SEXP_USE_GLOBAL_HEAP
   if (! ctx) {
+#if SEXP_USE_HEAP_ALLOCATOR
+    res = sexp_bootstrap_context_with_allocator(size, max_size, allocator);
+#else
     res = sexp_bootstrap_context(size, max_size);
+#endif
     if (!res || sexp_exceptionp(res)) return res;
   } else
 #endif
```

#### `0002-Add-SEXP_USE_HOST_FILES-let-the-embedder-supply-file.patch`

```diff
From 0000000000000000000000000000000000000000 Mon Sep 17 00:00:00 2001
From: puchi <puchi@localhost>
Date: Sat, 10 Oct 2026 05:57:27 +0000
Subject: [PATCH] Add SEXP_USE_HOST_FILES: let the embedder supply file ports

---
 eval.c                   | 6 ++++++
 include/chibi/eval.h     | 4 ++++
 include/chibi/features.h | 8 ++++++++
 3 files changed, 18 insertions(+)

diff --git a/eval.c b/eval.c
index 0e32093..0d81c7b 100644
--- a/eval.c
+++ b/eval.c
@@ -1311,6 +1311,9 @@ sexp sexp_open_input_file_op (sexp ctx, sexp self, sexp_sint_t n, sexp path) {
   FILE *in;
   int count = 0;
   sexp_assert_type(ctx, sexp_stringp, SEXP_STRING, path);
+#if SEXP_USE_HOST_FILES
+  return sexp_host_open_file(ctx, self, path, 0);
+#endif
   do {
     if (count != 0) sexp_gc(ctx, NULL);
     in = fopen(sexp_string_data(path), "r");
@@ -1327,6 +1330,9 @@ sexp sexp_open_output_file_op (sexp ctx, sexp self, sexp_sint_t n, sexp path) {
   FILE *out;
   int count = 0;
   sexp_assert_type(ctx, sexp_stringp, SEXP_STRING, path);
+#if SEXP_USE_HOST_FILES
+  return sexp_host_open_file(ctx, self, path, 1);
+#endif
   do {
     if (count != 0) sexp_gc(ctx, NULL);
     out = fopen(sexp_string_data(path), "w");
diff --git a/include/chibi/eval.h b/include/chibi/eval.h
index 52c7c45..27f8894 100644
--- a/include/chibi/eval.h
+++ b/include/chibi/eval.h
@@ -114,6 +114,10 @@ SEXP_API sexp sexp_make_synclo_op(sexp ctx, sexp self, sexp_sint_t n, sexp env,
 SEXP_API sexp sexp_strip_synclos(sexp ctx, sexp self, sexp_sint_t n, sexp x);
 SEXP_API sexp sexp_syntactic_closure_expr_op(sexp ctx, sexp self, sexp_sint_t n, sexp x);
 SEXP_API sexp sexp_open_input_file_op(sexp ctx, sexp self, sexp_sint_t n, sexp x);
+#if SEXP_USE_HOST_FILES
+/* defined by the embedding program: return a port for path, or an exception */
+SEXP_API sexp sexp_host_open_file (sexp ctx, sexp self, sexp path, int outputp);
+#endif
 SEXP_API sexp sexp_open_output_file_op(sexp ctx, sexp self, sexp_sint_t n, sexp x);
 SEXP_API sexp sexp_open_binary_input_file(sexp ctx, sexp self, sexp_sint_t n, sexp x);
 SEXP_API sexp sexp_open_binary_output_file(sexp ctx, sexp self, sexp_sint_t n, sexp x);
diff --git a/include/chibi/features.h b/include/chibi/features.h
index 90ed861..bab9992 100644
--- a/include/chibi/features.h
+++ b/include/chibi/features.h
@@ -493,6 +493,14 @@
 #define SEXP_USE_HEAP_ALLOCATOR 0
 #endif
 
+/* uncomment this to have open-input-file, open-output-file, load and */
+/*   module loading get their ports from sexp_host_open_file(), which */
+/*   the embedding program defines, instead of fopen() */
+/* #define SEXP_USE_HOST_FILES 1 */
+#ifndef SEXP_USE_HOST_FILES
+#define SEXP_USE_HOST_FILES 0
+#endif
+
 /* don't include clibs.c - include separately or link */
 #ifndef SEXP_USE_STATIC_LIBS_NO_INCLUDE
 #if defined(PLAN9) || SEXP_USE_STATIC_LIBS_EMPTY
```

#### `0003-Avoid-signed-overflow-when-reading-integer-literals.patch`

```diff
From 0000000000000000000000000000000000000000 Mon Sep 17 00:00:00 2001
From: Claude <noreply@anthropic.com>
Date: Sat, 10 Oct 2026 04:15:17 +0000
Subject: [PATCH] Avoid signed overflow when reading integer literals

sexp_read_number multiplied before checking for overflow, which is
undefined behavior (UBSan: signed integer overflow).  Check first; without
bignums the value still wraps, as before, but in unsigned arithmetic.
---
 sexp.c | 6 +++---
 1 file changed, 3 insertions(+), 3 deletions(-)

diff --git a/sexp.c b/sexp.c
index 37da14d..82029b8 100644
--- a/sexp.c
+++ b/sexp.c
@@ -3028,14 +3028,14 @@ sexp sexp_read_number (sexp ctx, sexp in, int base, int exactp) {
     digit = digit_value(c);
     if ((digit < 0) || (digit >= base))
       break;
-    tmp = val * base + digit;
 #if SEXP_USE_BIGNUMS
-    if ((SEXP_MAX_FIXNUM / base < val) ||
-        (tmp < val) || (tmp > SEXP_MAX_FIXNUM)) {
+    /* check before multiplying: signed overflow is undefined */
+    if (val > (SEXP_MAX_FIXNUM - digit) / base) {
       sexp_push_char(ctx, c, in);
       return sexp_read_bignum(ctx, in, val, (negativep ? -1 : 1), base);
     }
 #endif
+    tmp = (sexp_sint_t)((sexp_uint_t)val * base + digit);
     val = tmp;
   }
 
```

#### `0004-Negate-in-unsigned-arithmetic-in-sexp_make_integer_f.patch`

```diff
From 0000000000000000000000000000000000000000 Mon Sep 17 00:00:00 2001
From: Claude <noreply@anthropic.com>
Date: Sat, 10 Oct 2026 04:18:39 +0000
Subject: [PATCH] Negate in unsigned arithmetic in sexp_make_integer_from_lsint

Negating the most negative sexp_sint_t is undefined behavior (UBSan);
negating after the conversion to sexp_uint_t gives the same bits.
---
 bignum.c | 4 ++--
 1 file changed, 2 insertions(+), 2 deletions(-)

diff --git a/bignum.c b/bignum.c
index 34ca5c3..7580e30 100644
--- a/bignum.c
+++ b/bignum.c
@@ -43,7 +43,7 @@ sexp sexp_make_integer_from_lsint (sexp ctx, sexp_lsint_t x) {
     res = sexp_make_bignum(ctx, 1);
     if (lsint_lt_0(x)) {
       sexp_bignum_sign(res) = -1;
-      sexp_bignum_data(res)[0] = (sexp_uint_t)-lsint_to_sint(x);
+      sexp_bignum_data(res)[0] = -(sexp_uint_t)lsint_to_sint(x);
     } else {
       sexp_bignum_sign(res) = 1;
       sexp_bignum_data(res)[0] = (sexp_uint_t)lsint_to_sint(x);
@@ -52,7 +52,7 @@ sexp sexp_make_integer_from_lsint (sexp ctx, sexp_lsint_t x) {
     res = sexp_make_bignum(ctx, 2);
     if (lsint_lt_0(x)) {
       sexp_bignum_sign(res) = -1;
-      sexp_bignum_data(res)[0] = (sexp_uint_t)-lsint_to_sint(x);
+      sexp_bignum_data(res)[0] = -(sexp_uint_t)lsint_to_sint(x);
       sexp_bignum_data(res)[1] = (sexp_uint_t)~lsint_to_sint_hi(x);
     } else {
       sexp_bignum_sign(res) = 1;
```

#### `0005-Fix-negative-two-limb-results-of-sexp_make_integer_f.patch`

```diff
From 0000000000000000000000000000000000000000 Mon Sep 17 00:00:00 2001
From: Claude <noreply@anthropic.com>
Date: Sat, 10 Oct 2026 04:25:20 +0000
Subject: [PATCH] Fix negative two-limb results of sexp_make_integer_from_lsint

The high limb of the magnitude was ~hi, which is only right when the low
limb is nonzero; with a zero low limb the +1 of the negation carries into
the high limb.  On 32-bit builds sexp_make_integer(ctx, -2^32) returned 0
and INT64_MIN came out as -(2^63 - 2^32).
---
 bignum.c | 4 +++-
 1 file changed, 3 insertions(+), 1 deletion(-)

diff --git a/bignum.c b/bignum.c
index 7580e30..e406426 100644
--- a/bignum.c
+++ b/bignum.c
@@ -53,7 +53,9 @@ sexp sexp_make_integer_from_lsint (sexp ctx, sexp_lsint_t x) {
     if (lsint_lt_0(x)) {
       sexp_bignum_sign(res) = -1;
       sexp_bignum_data(res)[0] = -(sexp_uint_t)lsint_to_sint(x);
-      sexp_bignum_data(res)[1] = (sexp_uint_t)~lsint_to_sint_hi(x);
+      /* two's complement negation of hi:lo carries into hi when lo is 0 */
+      sexp_bignum_data(res)[1] = (sexp_uint_t)~lsint_to_sint_hi(x)
+        + (lsint_to_sint(x) == 0);
     } else {
       sexp_bignum_sign(res) = 1;
       sexp_bignum_data(res)[0] = (sexp_uint_t)lsint_to_sint(x);
```

### 5.4 Gate G1 - patches

1. In the scratch repo: `git am -3 <fork>/puchi/patches/*.patch` applies all
   five with no conflict.
2. Upstream's default build still compiles (flags off):
   `for f in gc.c sexp.c bignum.c opcodes.c vm.c simplify.c eval.c; do
   gcc -O1 -Iinclude -I. -c $f -o /dev/null || echo FAIL $f; done`
   (needs an `include/chibi/install.h`; copy the one `make` generates).
   Expected: no output.
3. With both flags on, the implementation compiles (this happens in Phase 5).
