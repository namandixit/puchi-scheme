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
| Generated `puchi.h`: impl TU with gcc and clang `-O2 -Wall -Wextra` | 0 warnings; all suites above pass against the single header |
| Generator determinism | identical sha256 on two runs |
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

---

## Part 6 - Phase 3: the profile (`puchi/src/puchi_config.h`)

One header, included first by both sections of `puchi.h`, sets every
`SEXP_USE_*` switch that matters. Never rely on an upstream default for a
switch that touches the OS or global state.

Why each group:

- `SEXP_USE_HEAP_ALLOCATOR`, `SEXP_USE_HOST_FILES`: the two patches.
- `SEXP_USE_GREEN_THREADS 1`: gives `vm.c` its periodic call of the
  scheduler slot every `SEXP_DEFAULT_QUANTUM` (500) instructions - puchi's
  interrupt hook. No threads are created. Cost measured: ~3-6% on `fib 30`.
  It adds `fcntl`, `ferror`, `poll` references, all stubbed (unreachable:
  only for fd and `FILE*` ports).
- `DL`, `IMAGE_LOADING`, `MMAP_GC`, `TIME_GC`, `GC_FILE_DESCRIPTORS`,
  `STRING_STREAMS` (fmemopen/fopencookie), `NTP_GETTIME`, `SEND_FILE`,
  `NATIVE_X86`, `LIMITED_MALLOC` (global byte counter + getenv): all OFF.
- `GLOBAL_HEAP`, `GLOBAL_SYMBOLS`, `BOEHM`, `MALLOC`, `HUFF_SYMS` (writable
  tables): OFF - one heap and one symbol table per VM, no shared state.
- `STATIC_LIBS 1`, `STATIC_LIBS_NO_INCLUDE 0`, `STATIC_LIBS_EMPTY 0`:
  `eval.c` `#include`s the generated `clibs.c`.
- `ALIGNED_BYTECODE 1`: no unaligned loads (portable, sanitizer-clean).
- Windows: `SEXP_STATIC_LIBRARY` or `SEXP_API` becomes `dllimport` and the
  build fails (`gc.c: dllimport cannot be applied to non-inline function
  definition`).

```c
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
```

**Gate G2 (profile)**: nothing to run yet; G6 (symbols) and G2b (writable
data) in Part 12 are the real checks of the profile.

---

## Part 7 - Phase 4: the redirect layer

### 7.1 What it is

`puchi_impl.c` includes, in this order: the profile and Chibi's headers,
**every system header upstream uses**, then `puchi_redirect.h`, then the
upstream `.c` files, then `puchi_unredirect.h`, then puchi's glue. Inside
that window, every OS-facing C library name upstream uses is a macro.

The three kinds, and the only three:

| Kind | Meaning | Implementation |
|---|---|---|
| STUB | the call can only run on a `FILE*`, fd, socket or missing error port; puchi never creates one, so it is unreachable | typed helper returning a failure value; calls `puchi_os_unreachable(name)`, which aborts only when `PUCHI_CHECK_UNREACHABLE` is defined (test builds) |
| DENY | the capability is removed from the sandbox | typed helper returning failure (`-1`, `NULL`) |
| ROUTE | a one-sentence contract | function taking `ctx`, served by the VM (`puchi_os_*` in the glue) |

Which functions are which (Linux list; Windows differences in 7.4):

- STUB: `getc ungetc putc fputc fputs fflush fclose clearerr ferror fgets
  fileno fseek ftell fread fwrite fopen select usleep poll fcntl shutdown
  stderr` and the `FD_ZERO/FD_SET/FD_ISSET` macros (removes glibc's
  `__fdelt_chk`).
- DENY: `getenv setenv unsetenv strerror read write close lseek fstat`.
  `fstat` must also zero its `struct stat`: `sexp_is_a_socket_p` (io.c)
  reads `st_mode` without checking the result (found by gcc
  `-Wmaybe-uninitialized` at `-O2` on the amalgamated header).
- ROUTE: `stat` (exists?), `snprintf` (host `format`), `sscanf` ("%lg" only:
  host `parse_double`), `exit` (host `on_exit`), `malloc calloc free` (VM
  allocator), and locale-free ASCII replacements for `isalpha isdigit
  isxdigit isspace tolower toupper strcasecmp strncasecmp`.

### 7.2 Rules for the macros

- **Function-like** (`#define getc(f) ...`) wherever possible: such a macro
  only expands when the name is followed by `(`, so the struct member
  `fileno` (`x->value.fileno.fd`), the parameters `read/write/close` in
  `io.c` and the locals `free`, `sin`, `cos` stay untouched.
- **Object-like** only where upstream uses the name as a value:
  `stderr`, `strcasecmp` (used as a function pointer in `sexp.c`), and on
  Windows `getenv_s`/`_putenv_s` (declared by `ast.c`).
- ROUTE macros pass the `ctx` that is in scope at the call site
  (`#define malloc(n) puchi_os_malloc(ctx, n)`). If some call site has no
  `ctx`, compilation fails - that is the check. (272 of 275 sites have one;
  the 3 others are fixed by patch 0001 or are not routed.)
- Each name is saved with `#pragma push_macro("name")` + `#undef` before it
  is redefined, and `puchi_unredirect.h` does `#undef` +
  `#pragma pop_macro`. This restores the host's own macros afterwards (MSVC's
  `stderr` is a macro; glibc defines `getc`, `putc`, `tolower` ... as macros).
- Never redirect a name that upstream *defines* (Windows `ast.c` defines
  `setenv`/`unsetenv`; there `_putenv_s`/`getenv_s` are redirected instead).
  Gate G5 finds such cases.
- The helpers are `static` and marked `SEXP_NO_WARN_UNUSED` (from `sexp.h`),
  because the configuration decides which ones are used.
- STUBs use typed helper functions, not comma expressions: a call used as a
  statement draws no `-Wunused-value` warning.

### 7.3 `puchi/src/puchi_redirect.h`

```c
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
/* fstat: upstream (io.c, sexp_is_a_socket_p) reads st_mode without checking
 * the result, so the buffer must be filled even when the call is denied. */
SEXP_NO_WARN_UNUSED static int puchi_deny_fstat(struct stat *buf) {
  memset(buf, 0, sizeof *buf);
  puchi_os_denied("fstat");
  return -1;
}

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
#define fstat(fd, b)          puchi_deny_fstat(b)

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
```

### 7.4 `puchi/src/puchi_unredirect.h`

It is mechanical: for every name the redirect header saved, `#undef NAME`
then `#pragma pop_macro("NAME")`; the three Windows constants are restored
under `#ifdef _WIN32`. Generate it from the redirect header (the reference
file was generated with a short script) so that the two lists can never
differ. First and last lines of the reference file:

```c
/* puchi_unredirect.h - included by puchi_impl.c right after the last upstream
 * .c file.  Removes every redirect and restores whatever the host's headers
 * had defined under those names (e.g. MSVC's stderr macro). */
#undef getc
#pragma pop_macro("getc")
#undef ungetc
#pragma pop_macro("ungetc")
#undef putc
...
#ifdef _WIN32
#undef F_GETFL
#pragma pop_macro("F_GETFL")
#undef F_SETFL
#pragma pop_macro("F_SETFL")
#undef O_NONBLOCK
#pragma pop_macro("O_NONBLOCK")
#endif
```

### 7.5 Windows notes (compile-verified with clang + MinGW headers; MSVC not verified)

- `sexp.h` includes `<winsock2.h>` and `<windows.h>` on `_WIN32`; they come
  in before the redirects through the Chibi headers.
- `features.h` maps `strcasecmp` to `_stricmp` on MSVC; the redirect header
  `#undef`s and replaces it.
- `ast.c` defines `setenv`/`unsetenv` with `getenv_s` and `_putenv_s`; the
  redirect header leaves `setenv`/`unsetenv` alone on `_WIN32` and turns
  `getenv_s`/`_putenv_s` into deny functions with object-like macros.
- Green-thread code names `F_GETFL`, `F_SETFL`, `O_NONBLOCK`, which Windows
  lacks; the redirect header defines them on `_WIN32` (the code using them
  never runs). Upstream itself never compiles green threads on Windows.
- `features.h` defines `_USE_MATH_DEFINES` for `M_PI`; on MSVC this only
  works if no `<math.h>` was included before. If the host includes
  `<math.h>` first, `M_PI` may be missing - see Part 14.

**Gate G3 (redirect)**: covered by G5 (collisions), G6 (symbols) and G7
(trap build) in Part 12.

---

## Part 8 - Phase 5: the implementation file and the glue

### 8.1 `puchi/src/puchi_impl.c` - the order matters

1. `#pragma GCC system_header` when amalgamated (upstream is not
   warning-free; puchi's own code is checked separately by gate G9), and
   `#pragma warning(push, 0)` for MSVC.
2. `puchi_config.h`, `chibi/eval.h`, `chibi/bignum.h`, `puchi_api.h`.
3. **Every system header any compiled upstream file includes** - before the
   redirects, so that no redirect macro is ever expanded inside a system
   header. (List derived with `grep -h '#include <'` over the compiled
   files, minus those only used by disabled features.)
4. `puchi_redirect.h`.
5. Upstream `.c` files in upstream's Makefile order. Three file-static names
   are defined twice in the single translation unit; rename them with
   `#define` around the file included second:
   `sexp_string_hash` (sexp.c vs srfi/69/hash.c), `digit_value`,
   `hex_digit` (sexp.c vs bignum.c), `log2i` (bignum.c vs srfi/151/bit.c).
   These were all the collisions found; a new one shows up as a
   "redefinition" compile error - fix it the same way.
6. `eval.c` **last**: it `#include`s the generated `clibs.c` (the bundled
   C libraries), whose macros (`_I`, `FNV_OFFSET_BASIS`, ...) must not leak
   into other upstream files.
7. `puchi_unredirect.h`, then `puchi_glue.c` (no redirect is active there).

```c
/* puchi_impl.c - the implementation section of puchi.h.  tools/amalgamate.py
 * inlines every #include "..." below; this file also compiles as is with
 * -I puchi/src -I puchi/build/gen -I puchi/build/src/include -I puchi/build/src
 * (that is how the gates build it). */

#if defined(__GNUC__) && defined(PUCHI_AMALGAMATED)
#pragma GCC system_header      /* upstream is not warning-free; gate G9 checks puchi's own code */
#endif
#ifdef _MSC_VER
#pragma warning(push, 0)
#endif

#include "puchi_config.h"
#include "chibi/eval.h"
#include "chibi/bignum.h"
#include "puchi_api.h"

/* Every system header any compiled upstream file includes, BEFORE the
 * redirects (a redirect macro must never be expanded inside a system
 * header).  Gate G6 fails if this list is incomplete. */
#include <ctype.h>
#include <errno.h>
#include <float.h>
#include <limits.h>
#include <math.h>
#include <stdarg.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <fcntl.h>
#ifdef _WIN32
#include <io.h>
#else
#include <poll.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>
#endif

#include "puchi_redirect.h"

/* Chibi core, in the order of upstream's Makefile.  Three file-static names
 * are defined twice in the amalgamation; rename them around the file that
 * is included second. */
#include "gc.c"
#define sexp_string_hash sexp_symbol_string_hash   /* also in srfi/69/hash.c */
#include "sexp.c"
#undef sexp_string_hash
#define digit_value bignum_digit_value             /* also in sexp.c */
#define hex_digit bignum_hex_digit                 /* also in sexp.c */
#define log2i bignum_log2i                         /* also in srfi/151/bit.c */
#include "bignum.c"
#undef digit_value
#undef hex_digit
#undef log2i
#include "opcodes.c"
#include "vm.c"
#include "simplify.c"
/* last: eval.c #includes the generated clibs.c (the bundled C libraries),
 * whose macros must not leak into the other upstream files */
#include "eval.c"

#include "puchi_unredirect.h"
#include "puchi_glue.c"

#ifdef _MSC_VER
#pragma warning(pop)
#endif
```

### 8.2 `puchi/src/puchi_glue.c` - what it contains, and why

- **`puchi_vm`**: copy of the host callbacks, the `sexp_allocator_t` given to
  Chibi (its `data` points back to the `puchi_vm`, so
  `sexp_context_heap(ctx)->allocator->data` finds the VM from any `ctx`),
  the C type of stream boxes, the three standard ports.
- **ROUTE targets** `puchi_os_*`: allocator, `format`, `parse_double`,
  `exists`, `on_exit`; `puchi_os_unreachable` (aborts only under
  `PUCHI_CHECK_UNREACHABLE`).
- **Embedded files**: `puchi_files.c` is a sorted table of
  `{"lib/scheme/base.sld", chunks}`; lookup is a binary search; an embedded
  file is opened as a Chibi string port. Embedded files are found before
  the host's `open_file` is asked (so the host cannot shadow the standard
  library, and the standard library works with no file system at all).
- **Ports**: every port over a host stream is a Chibi custom port
  (`sexp_make_custom_input_port` / `..._output_port`, defined in
  `lib/chibi/io/port.c`, compiled in through `(chibi io)`). Its read/write
  procedures are C functions (`sexp_make_foreign`) whose opcode data is a
  **stream box**: a C pointer, of a type registered with
  `sexp_register_c_type` **with a finalizer**, to a heap copy of the
  `puchi_stream`. Protocol (from `sexp.c`): read is called as
  `(buffer start end)` and returns the new end index (returning `start`
  means end of file); write is called as `(buffer 0 count)` and returns the
  count written (> 0 means success). The finalizer closes the stream if
  Scheme never called `close-port` and frees the box - this is what makes
  stream ownership leak-free (verified: dropped port, exit, interrupt).
- **`sexp_host_open_file`**: the hook of patch 0002 (embedded file, else the
  host's `open_file`).
- **Interrupts**: `puchi_scheduler` is stored in
  `sexp_global(ctx, SEXP_G_THREADS_SCHEDULER)`; it calls
  `host.poll_interrupt`; a return of 1 sets `sexp_context_interruptp(ctx)`,
  and `vm.c` raises the catchable `"interrupt"` error at its next check; a
  host that wants a hard stop longjmps from inside `poll_interrupt`.
- **`(puchi host)`**: `%puchi-exit`, `current-second`, `current-jiffy`,
  `jiffies-per-second`, `get-environment-variable`, `file-exists?`,
  `delete-file`, registered as static library `lib/puchi/host`.
- **`puchi_open`**: validate the host (allocate, release, format,
  parse_double are required); allocate the `puchi_vm` from the host;
  `sexp_make_eval_context_with_allocator`; install the scheduler; register
  the stream-box type; make the three standard ports **before**
  `sexp_load_standard_env` (they must exist when the environment loads);
  load the standard environment; set the three port parameters; build the
  interaction environment `(mutable-environment '(scheme small))` plus
  `import`/`cond-expand` (copied from chibi-scheme's `main.c`, where it is
  `static`). On failure: print the exception to the error port, close.
- **`puchi_close`**: `sexp_destroy_context` (finalizes every object, closing
  remaining streams), then release the `puchi_vm`.
- **`puchi_eval_string`**: read and evaluate every form (Chibi's
  `sexp_eval_string` only evaluates the first), flush output.

Root every temporary with `sexp_gc_var`/`sexp_gc_preserve` across any call
that can allocate (Chibi's GC is precise: an unrooted value can be freed;
`NULL` counts as a pointer for `sexp_pairp`, so test `x && sexp_pairp(x)`).

Cast C primitives to `sexp_proc1` through `void (*)(void)`
(`puchi_proc(f)`), which gcc exempts from `-Wcast-function-type`.

```c
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
/* Test builds only (see GUIDE.md, gate G4): a STUB was reached. */
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
```

**Gate G4 (implementation compiles)**: with the build tree from Part 11
(`puchi/build/src`, `puchi/build/gen`),
`gcc -std=gnu11 -c -Ipuchi/src -Ipuchi/build/gen -Ipuchi/build/src/include -Ipuchi/build/src puchi/src/puchi_impl.c`
compiles with no error. (The implementation needs C99 or later in GNU or
POSIX mode for `M_PI`/`strcasecmp` declarations in upstream code; the
*public* section works in C89 and C++98.)

---

## Part 9 - Phase 6: Scheme library overrides (`puchi/lib/`)

Upstream R7RS libraries that touch the OS get replaced by puchi's own
`.sld` files of the same name. The generator looks in `puchi/lib` before
the upstream `lib/`, so these win, and only they are embedded.

| Library | Upstream depends on | puchi's version |
|---|---|---|
| `(scheme process-context)` | `(chibi process)` (fork, exit, signals) | `exit` = unwind dynamic-wind via a continuation captured at load time (same trick as upstream `lib/chibi/process.scm`), then `%puchi-exit` -> host `on_exit`; `emergency-exit` skips the unwind; `command-line` is Chibi's core parameter; `get-environment-variables` = `'()` |
| `(scheme time)` | `(chibi time)` | from `(puchi host)`: host `current_second` |
| `(scheme file)` | `(chibi filesystem)` | `file-exists?`, `delete-file` from `(puchi host)`; the `open-*-file` procedures are core opcodes, routed by patch 0002 |
| `(puchi host)` | - | `(include-shared "host")` -> static library `lib/puchi/host` in the glue |

R7RS C library dependencies that are kept (they need no OS once the
redirect layer is in place): `srfi/69/hash`, `chibi/ast`, `srfi/151/bit`,
`chibi/io/io` (generated from `io.stub` by chibi-ffi), `srfi/39/param`.

#### `puchi/lib/scheme/process-context.sld`

```scheme
;; puchi replacement for upstream lib/scheme/process-context.sld (which
;; imports exit from the OS library (chibi process)).  exit runs the
;; outstanding dynamic-wind "after" thunks by jumping to a continuation
;; captured when this library was loaded (as upstream's lib/chibi/process.scm
;; does), then calls the host's on_exit callback through %puchi-exit.
(define-library (scheme process-context)
  (import (chibi) (puchi host))
  (export get-environment-variable get-environment-variables
          command-line exit emergency-exit)
  (begin
    (define (get-environment-variables) '())
    (define (exit-code o)
      (cond ((null? o) 0)
            ((eq? #t (car o)) 0)
            ((exact-integer? (car o)) (car o))
            (else 1)))
    (define (emergency-exit . o) (%puchi-exit (exit-code o)))
    (define unwind #f)
    ((call-with-current-continuation
      (lambda (k)
        (set! unwind k)
        (lambda () #f))))
    (define (exit . o)
      (unwind (lambda () (apply emergency-exit o))))))
```

#### `puchi/lib/scheme/time.sld`

```scheme
;; puchi replacement for upstream lib/scheme/time.sld (which uses the OS
;; library (chibi time)): the clock is the host's current_second callback.
(define-library (scheme time)
  (import (only (puchi host) current-second current-jiffy jiffies-per-second))
  (export current-second current-jiffy jiffies-per-second))
```

#### `puchi/lib/scheme/file.sld`

```scheme
;; puchi replacement for upstream lib/scheme/file.sld (which uses the OS
;; library (chibi filesystem)): file-exists? and delete-file go to the host.
;; The open-*-file procedures are core opcodes; patch 0002 sends them to the
;; host's open_file callback.
(define-library (scheme file)
  (import (chibi) (only (puchi host) delete-file file-exists?))
  (export
   call-with-input-file call-with-output-file
   delete-file file-exists?
   open-binary-input-file open-binary-output-file
   open-input-file open-output-file
   with-input-from-file with-output-to-file))
```

#### `puchi/lib/puchi/host.sld`

```scheme
;; Host services.  The C side is puchi_init_host_library in puchi_glue.c,
;; registered by the generated clibs.c as the static library "lib/puchi/host".
(define-library (puchi host)
  (export %puchi-exit current-second current-jiffy jiffies-per-second
          get-environment-variable file-exists? delete-file)
  (include-shared "host"))
```

---

## Part 10 - Phase 7: public API (`puchi_api.h`) and `puchi.h.in`

### 10.1 What is public

- Everything Chibi's headers declare: `sexp_eval`, `sexp_apply`,
  `sexp_define_foreign`, `sexp_gc_var`/`sexp_gc_preserve`,
  `sexp_preserve_object`, value constructors and predicates ... Chibi's
  headers were verified to compile cleanly as public API in C89/C99/C11 and
  C++98/11/17 with `-pedantic -Wall -Wextra -Werror` (they already have
  `extern "C"`). Host-side bindings can be written exactly as for Chibi
  (even generated with chibi-ffi).
- The thin `puchi_*` layer below, which is only what Chibi lacks: creating
  a VM whose every outside contact goes through host callbacks.

Rules for the host (also in the header comments):

- `allocate`, `release`, `format`, `parse_double` are required. `format` has
  the contract of `vsnprintf` in the "C" locale, `parse_double` of `strtod`
  in the "C" locale (puchi formats floats with `%.15lg`/`%.16lg`/`%.17lg`
  and checks each by parsing it back).
- All allocations of a VM happen on the thread currently running that VM;
  a non-thread-safe per-thread allocator is fine. There are no global
  allocations at all.
- `on_exit` and a hard-interrupting `poll_interrupt` must not return
  (longjmp / stack switch); afterwards only `puchi_close` is legal. Do not
  let them jump before your jump point exists (arm them after `puchi_open`
  returns).
- No member is named like a C library function (`on_read`, not `read`).

```c
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
```

### 10.2 `puchi/src/puchi.h.in`

The public section is: `#pragma GCC system_header` (silences upstream
header warnings such as `-Wundef` on `PLAN9` in host code), the profile,
`chibi/eval.h`, `puchi_api.h`. The implementation section includes
`puchi_impl.c` once, and only from C.

```c
/* puchi.h - Chibi Scheme @VERSION@ as a single-header, sandboxed, embeddable
 * library.  Generated by puchi/tools/amalgamate.py; do not edit.
 *
 * In exactly one C (not C++) source file:
 *     #define PUCHI_IMPLEMENTATION
 *     #include "puchi.h"
 * Everywhere else (C or C++): #include "puchi.h".
 * API: puchi_api.h section below, plus Chibi's own sexp_* API. */
#ifndef PUCHI_H
#define PUCHI_H
#if defined(__GNUC__)
#pragma GCC system_header
#endif
#include "puchi_config.h"
#include "chibi/eval.h"
#include "puchi_api.h"
#endif /* PUCHI_H */

#if defined(PUCHI_IMPLEMENTATION) && !defined(PUCHI_IMPLEMENTATION_DONE)
#define PUCHI_IMPLEMENTATION_DONE
#ifdef __cplusplus
#error "puchi: define PUCHI_IMPLEMENTATION in a C source file, not in C++"
#endif
#define PUCHI_AMALGAMATED 1
#include "puchi_impl.c"
#endif
```

`puchi/src/install.h.in` (upstream's Makefile normally generates
`chibi/install.h`; no `sexp_architecture`, so the build machine's CPU name
does not leak into `(features)`):

```c
/* Generated from puchi/src/install.h.in (upstream's Makefile writes this file
 * for normal builds).  No sexp_architecture: it would leak the build
 * machine's CPU name into *features*. */
#define sexp_so_extension ".so"
#define sexp_default_module_path "@MODULE_DIR@"
#define sexp_platform "puchi"
#define sexp_version "@VERSION@"
#define sexp_release_name "@RELEASE@"
```

---

## Part 11 - Phase 8: the generator (`puchi/tools/amalgamate.py`)

The reference file is `puchi/guide/tools/amalgamate.py` (verified: it
produced a 1.1 MB `puchi.h` with 54 embedded files in 0.3 s from upstream
`c4e7367`). What each step does and the traps it avoids:

1. **copy_upstream**: copy only `git ls-files` output (not `puchi/`) to
   `puchi/build/src`. Never copy the work tree: stale build products
   (`clibs.c`, generated `lib/**/*.c`, `install.h`) would leak in.
2. **apply_patches**: `git apply -p1 --whitespace=nowarn
   --directory=puchi/build/src puchi/patches/NNNN.patch`, in sorted order,
   run from the fork root.
3. **write_install_h**: `install.h.in` with `@VERSION@`, `@RELEASE@` (from
   upstream's `VERSION`/`RELEASE` files) and `@MODULE_DIR@` = `lib`.
4. **build_host_chibi**: stock `make chibi-scheme` in `puchi/build/host`
   (unpatched copy), or `--chibi PATH`.
5. **run_chibi_ffi**: `chibi-scheme -q tools/chibi-ffi lib/chibi/io/io.stub`
   in `puchi/build/src` -> `lib/chibi/io/io.c`.
6. **collect_files**: walk `.sld` files from `ROOT_LIBRARIES` (R7RS-small,
   `(scheme small)`, `(puchi host)`), following `import`, `include`,
   `include-ci`, `include-library-declarations`, `include-shared` and the
   first true `cond-expand` clause (features: `chibi puchi r7rs
   full-unicode ratios exact-closed exact-complex ieee-float modules uvector
   little-endian big-endian else`; `(library X)` is true iff X's `.sld`
   exists). `(chibi)` and `(meta)` are built in. Look in `puchi/lib` first.
   Always add `init-7.scm` and `meta-7.scm`. Every `include-shared` reached
   must be in `C_LIBRARIES` or `PUCHI_C_LIBRARIES`, else fail.
7. **write_clibs_c**: for each C library: a `static` prototype of a unique
   init function, `#define sexp_init_library <unique>`, `#include` the C
   file, `#undef`; then the table `sexp_static_libraries_array` with entries
   `{"lib/<name>", init}`, including `{"lib/puchi/host",
   puchi_init_host_library}`.
8. **write_files_c**: each embedded file as an array of C string literals of
   **at most ~4000 bytes each**, split at line ends (MSVC rejects a literal
   over 16380 bytes, C2026, and concatenations over 65535); escape `\`,
   `"`, newline, tab, `?` (trigraphs) and non-ASCII as octal; table sorted
   by path (binary search at run time). Normalize CRLF to LF.
9. **inline**: expand `puchi.h.in`: replace every `#include "..."` and
   `#include <chibi/...>` with the file's contents, recursively; a file with
   an include guard is inlined only the first time; system headers stay as
   `#include` lines; `NOT_INLINED` names (`opt/x86.c`,
   `opt/plan9-opcodes.c`, Huffman symbol headers, `gc/gc.h`) become `#error`
   so a configuration change that makes them live fails loudly. Search
   path: `build/src/include`, `build/src`, `src`, `build/gen`.
10. Output must be **deterministic** (same input -> identical bytes): sort
    everything, no timestamps.

**Gate G10 (generator)**: run it twice; `sha256sum puchi/puchi.h` is the
same both times (verified); `grep -c -E '^\s*#\s*include\s*"' puchi/puchi.h`
prints `0` (the text `#include "` still appears inside comments - fine).
