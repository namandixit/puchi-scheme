# puchi — sandboxed single-header Chibi Scheme

`puchi.h` is generated. Do not edit it by hand.

```
bash puchi/tools/amalgamate.sh
```

Requires bash (Git Bash on Windows), `patch` or `git apply`, and Python 3.
Output is deterministic: identical across runs and across `PYTHONHASHSEED`s on Linux. It should match on Windows too; to confirm, run `amalgamate.sh` there and check that `git status puchi/puchi.h` is clean.

## Edit only inside `puchi/` (mandatory)

This is a fork of upstream Chibi Scheme. Every puchi change — sources,
patches, tools, tests, docs — lives under `puchi/`. **Never edit, add or
delete tracked files anywhere else**, so upstream updates merge cleanly. To
change upstream behavior, add a diff to `patches/` (applied to a temp copy
by `amalgamate.sh`), never edit the upstream file itself. Same for the
harness: patch stub copies under `test/clibs/`, never `lib/`.

The only files allowed outside `puchi/` are gitignored build outputs, e.g.
the `lib/**/*.c` FFI stubs from `generate_harness_stubs.sh`; never commit them.
Before pushing, this must print nothing:

```bash
git diff --name-only master...HEAD | grep -v '^puchi/'
```

## Sandbox contract

The amalgamated header is platform-independent for embeds:

- **Host owns memory and I/O.** Pass a `puchi_host` with `alloc` / `free` at context create. Ports use `puchi_stream_ops`. A null or incomplete host does not fall back to CRT `malloc`.
- **Host API surface.** Use always-visible `puchi_*` / `PUCHI_*` entrypoints (`puchi_create_context`, `puchi_eval_string`, …) and symbols listed as HOST in `product/puchi_host_symbols.txt`, plus the HOST accessors in `product/`. Always-visible ABI may include INTERNAL tag/mask macros as glue for HOST accessors — do not treat opcode enums, core-form codes, or GC freelist types as the host contract (those stay under `PUCHI_IMPLEMENTATION` / `PUCHI_TEST`).
- **Converting script integers in host code.** Use `puchi_integer_to_sint64` / `puchi_integer_to_uint64`: they accept fixnums and bignums and return 0 when the value is not an exact integer or does not fit. `puchi_bignum_to_sint` / `_uint` only read a bignum's low 64 bits (raw bits, no range check) and return 0 for a non-bignum.
- **No OS `#if` or syscalls in the header.** No `_WIN32` / `__APPLE__` / … layout forks, no `close` / `fopen` / `dlopen`. Post-amalgamate assert fails if those tokens return.
- **No OS names in `*features*`.** `"chibi"` and `"puchi"` stay; `"windows"` does not. A `PUCHI_TEST` harness may use the CRT and may cons `windows` onto `*features*` at runtime so upstream Chibi libs (e.g. `(scheme process-context)`) load. `puchi_harness.c` does this on Windows only. Elsewhere it puts `test/harness-lib/` first on the module path: its `(chibi process)` stand-in exports just `exit` / `emergency-exit`, built from upstream's `(chibi win32 process-win32)` (plain CRT `exit`), so no OS name is faked.

## Definition of done (mandatory)

After **any** puchi change (patches, `product/`, tools, tests, feature forces, amalgamation inputs), a change is **not done** until:

```bat
puchi\tools\build_puchi_tests.bat
```

(Windows) or

```bash
bash puchi/tools/build_puchi_tests.sh
```

(Linux) exits **0**. That script is the gate. It always:

1. **Amalgamates** (`amalgamate.sh` → regenerates `puchi.h`)
2. Runs the **full suite** under **MSVC** and **Clang** — **GCC** and **Clang** on Linux (all three numeric configs; binaries are **executed**, not only linked)
3. Re-runs the **same suite** under **Clang ASan + UBSan** with `-fno-sanitize-recover=all` (any sanitizer hit fails the script).
4. **Linux only:** re-runs it once more under **Clang ThreadSanitizer** (`halt_on_error=1`), which checks the parallel contexts for data races. TSan uses 16 contexts instead of 64 (`PUCHI_HARNESS_THREADS=n`, 1–64; unset means 64): 64 contexts of `lib-tests-embed` under TSan exceed 16 GB and get OOM-killed. TSan has no Windows runtime, so `build_puchi_tests.bat` has no such pass, and it cannot be combined with ASan, hence a separate pass. GCC also supports `-fsanitize=thread`; clang is used to match the ASan pass.
5. **Linux only:** re-runs it under **Clang MemorySanitizer** (uninitialized reads; origin tracking on, 16 contexts like TSan). Clang-only and Linux-only; cannot be combined with ASan or TSan.

The ASan pass also enables `-fsanitize=local-bounds`. The other non-UB UBSan checks (`implicit-conversion`, `unsigned-integer-overflow`, `unsigned-shift-base`, `float-divide-by-zero`) were audited once and are **deliberately not enabled**: they flag only intentional C (the `~PUCHI_FIXNUM_TAG` mask in `puchi_unbox_fixnum` alone is ~88% of the reports; the rest is hash/bignum wraparound, UTF-8 bytes stored in `char`, and `(/ 1. 0.)` → `+inf.0`) and found no real bug. Gating on them would need hundreds of suppressions, so do not re-add them without a new finding.

Both scripts need the generated FFI stubs under `lib/` (gitignored). Build
Chibi normally once (`make`), or point `generate_harness_stubs.sh` at any
`chibi-scheme` binary. A binary built inside the repo (not installed) must be
able to find its shared library and modules, e.g.
`LD_LIBRARY_PATH=. CHIBI_MODULE_PATH=lib bash puchi/tools/generate_harness_stubs.sh ./chibi-scheme`.

Puchi keeps those checks honest on x86: `SEXP_USE_ALIGNED_BYTECODE` is forced on, and patch `005-sexp-c-safe-fixnum-read.diff` avoids signed overflow UB in `sexp_read_number`.

Linking without running is not enough. `check_amalgamate.sh` only checks drift — it does **not** replace the gate script.

### Order of operations (mandatory)

The gate regenerates `puchi.h` in place, and the file is half-written while
amalgamation runs. Never stage or commit while the gate is running. Always:

1. **Amalgamate:** `bash puchi/tools/amalgamate.sh` (wait for `[puchi] done.`).
2. **Commit and push** the change together with the regenerated `puchi.h`.
3. **Run the gate:** `puchi\tools\build_puchi_tests.bat` (Windows) or
   `bash puchi/tools/build_puchi_tests.sh` (Linux); it must exit 0.
4. **Verify:** after it succeeds, `git status --short puchi/puchi.h` must
   print nothing — the gate's own amalgamation reproduced the committed header
   byte for byte. If it shows `M`, the committed `puchi.h` is stale or partial:
   go back to step 1.

| Suite | Integer (`PUCHI_INTEGER_ONLY`) | Default (flonums) | Tower (`PUCHI_ENABLE_NUMERICAL_TOWER`) |
|-------|--------------------------------|-------------------|----------------------------------------|
| C preflight | yes | yes | yes (+ two-host) |
| `tests/r5rs-tests.scm` | yes (skinny gate) | yes (`BIGNUMS=0` gate) | yes |
| `tests/basic/*.scm` | yes (`--expect` vs `.res`) | yes | yes |
| `tests/r7rs-tests.scm` | no — needs tower/complex | no — same | yes |
| `tests/syntax-tests.scm` | no — `Complex` / digitless `+i` | no — same | yes |
| `tests/division-tests.scm` | no — same | no — same | yes |
| `tests/unicode-tests.scm` | no — same | no — same | yes |
| `puchi/test/lib-tests-embed.scm` | no — Complex / digitless `+i` on import | no — same | yes (curated SRFI/chibi minus OS + missing FFI) |

Every harness script: single-threaded first, then 64 parallel contexts.

**Permanently out of scope** (all configs): `tests/ffi/`, `tests/snow/`, `tests/net-tests.scm`, `tests/memory/`, install/CLI (`tests/install/`, `tests/run/`), `tests/build/build-tests.sh`, and `(chibi process)` / `(chibi system)` / `(chibi tar)` / filesystem lib tests (no dlopen, process spawn, sockets, or disk VFS in the amalgamation).

On Windows the sanitizer pass needs the Clang ASan runtime DLL on PATH (the bat adds `$(clang -print-resource-dir)/lib/windows` automatically). On Linux it needs Clang's sanitizer runtime (Debian/Ubuntu: `libclang-rt-<ver>-dev`). `build_puchi_tests.sh asan` (or `gcc`, `clang`, `tsan`, `msan`) re-runs just that pass; no arguments runs the full gate. TSan needs the same clang runtime package. Linux ASan also checks leaks (LSan); `test/lsan.supp` lists the upstream stub leaks it skips (never `puchi.h` code).

## Layout

| Path | Role |
|------|------|
| `product/` | Puchi-owned fragments (banner, feature forces, host API/accessors, test API, `#e` mul) — concatenated as-is |
| `product/puchi_host_symbols.txt` | HOST allowlist: which Chibi symbols become always-visible `puchi_*` / `PUCHI_*` (vs `PUCHI_TEST` / impl-only) |
| `patches/` | Thin unified diffs: host ports, diskless boot, safe fixnum read, explicit integer conversions, bignum / uniform-vector range fixes |
| `tools/amalgamate.sh` | Orchestrator: copy → patch → mechanical rewrite → trim/embed → concat → strip |
| `tools/puchi_*.py` | Mechanical helpers (HOST ABI gen from manifest, features scrub, strip, …) |
| `tools/build_puchi_tests.bat` | **Mandatory verify** (Windows): amalgamate + MSVC + Clang + Clang ASan/UBSan (tag `asan`) |
| `tools/build_puchi_tests.sh` | **Mandatory verify** (Linux): amalgamate + GCC + Clang + Clang ASan/UBSan (tag `asan`) |
| `test/puchi_impl.c`, `test/puchi_impl_host.c` | The two body TUs. `puchi_impl.c` defines `PUCHI_TEST` (harness and its clibs link it). `puchi_impl_host.c` is built the way an embedder builds it (no `PUCHI_TEST`); the smoke tests link it. **Never mix them**: `PUCHI_TEST` changes `puchi.h`'s type numbering and struct layouts, so a TU and a body built with different settings disagree about type checks. |

## Numeric modes

| Mode | Macro | Chibi flags |
|------|-------|-------------|
| Integers + floats (default) | *(none)* | F=1, B=R=C=0 (ABI `f`) |
| Integer only | `PUCHI_INTEGER_ONLY` | F=B=R=C=0 |
| Full tower | `PUCHI_ENABLE_NUMERICAL_TOWER` | F=B=R=C=1 |

Middle mode (F∧¬B): ABI-f splice gates call sites (`sexp_to_double` / `exact-sqrt` / `#e` mul / `MIN_FIXNUM/-1`); `#e` mul body lives in `product/puchi_fx_or_fl_mul.inc` (not a parallel arith ABI).

## Pipeline

1. Copy upstream Chibi sources into `tools/.amalgamate-tmp/`.
2. Apply `patches/*.diff` in sorted order (hard fail on reject).
3. Mechanical rewrites: features scrub, GC host policy, ABI-f splice, branding, libc → `PUCHI_*`, allocators → `SEXP_MALLOC`.
4. Generate host ABI / decls / wrappers from `product/puchi_host_symbols.txt` (`puchi_gen_host_api.py`).
5. Trim init-7 / meta-7 (file/load stubs, if-style and/or, include-shared stubs), embed as C strings.
6. Concatenate `product/` + transformed sources → `puchi.h`.
7. `strip-dead-backends` + assert always-visible `PUCHI_API` decls match the HOST manifest.

## Refreshing after upstream Chibi changes

```bash
bash puchi/tools/amalgamate.sh
# If a patch rejects:
# Edit workdir file to the desired puchi shape, then:
#   diff -u /path/to/upstream/sexp.h sexp.h > ../../patches/001-....diff
# Paths inside the diff must be workdir-relative (e.g. sexp.h), for patch -p0.

bash puchi/tools/check_amalgamate.sh   # must exit 0; commit puchi.h + refreshed patches
puchi\tools\build_puchi_tests.bat      # mandatory: suite + sanitizers must exit 0
bash puchi/tools/build_puchi_tests.sh   # same gate on Linux
```

## Drift check

```bash
bash puchi/tools/check_amalgamate.sh
```

Fails if any patch does not apply, or if regenerated `puchi.h` differs from git. Still run `build_puchi_tests.bat` / `build_puchi_tests.sh` before calling the change done.
