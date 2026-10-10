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
