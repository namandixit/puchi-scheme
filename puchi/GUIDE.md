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
