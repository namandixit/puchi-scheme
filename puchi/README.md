# puchi — sandboxed single-header Chibi Scheme

`puchi.h` is generated. Do not edit it by hand.

```
bash puchi/tools/amalgamate.sh
```

Requires bash (Git Bash on Windows), `patch` or `git apply`, and Python 3.

## Sandbox contract

The amalgamated header is platform-independent for embeds:

- **Host owns memory and I/O.** Pass a `puchi_host` with `alloc` / `free` at context create. Ports use `puchi_stream_ops`. A null or incomplete host does not fall back to CRT `malloc`.
- **No OS `#if` or syscalls in the header.** No `_WIN32` / `__APPLE__` / … layout forks, no `close` / `fopen` / `dlopen`. Post-amalgamate assert fails if those tokens return.
- **No OS names in `*features*`.** `"chibi"` and `"puchi"` stay; `"windows"` does not. A `PUCHI_TEST` harness may use the CRT and may cons `windows` onto `*features*` at runtime so upstream Chibi libs (e.g. `(scheme process-context)`) load.

## Definition of done (mandatory)

After **any** puchi change (patches, `product/`, tools, tests, feature forces, amalgamation inputs), a change is **not done** until:

```bat
puchi\tools\build_puchi_tests.bat
```

exits **0**. That script is the gate. It always:

1. **Amalgamates** (`amalgamate.sh` → regenerates `puchi.h`)
2. Runs the **full suite** under **MSVC** and **Clang** (all three numeric configs; binaries are **executed**, not only linked)
3. Re-runs the **same suite** under **Clang ASan + UBSan** with `-fno-sanitize-recover=all` (any sanitizer hit fails the bat).

Puchi keeps those checks honest on x86: `SEXP_USE_ALIGNED_BYTECODE` is forced on, and patch `005-sexp-c-safe-fixnum-read.diff` avoids signed overflow UB in `sexp_read_number`.

Linking without running is not enough. `check_amalgamate.sh` only checks drift — it does **not** replace this bat.

| Config | Macro | What runs |
|--------|-------|-----------|
| Integer only | `PUCHI_INTEGER_ONLY` | `puchi_integer_smoke.c` (execute) |
| Int + float (default) | *(none)* | `puchi_slim_smoke.c` (execute) |
| Full tower | `PUCHI_ENABLE_NUMERICAL_TOWER` | `puchi_smoke.c` + Scheme harness (`r7rs` / `syntax` / `division` / `unicode`) |

Sanitizer pass needs the Clang ASan runtime DLL on PATH (the bat adds `$(clang -print-resource-dir)/lib/windows` automatically).

## Layout

| Path | Role |
|------|------|
| `product/` | Puchi-owned C (banner, feature forces, API, `#e` mul helper) — concatenated as-is |
| `patches/` | Thin unified diffs: host ports, diskless boot, safe fixnum read |
| `tools/amalgamate.sh` | Orchestrator: copy → patch → mechanical rewrite → trim/embed → concat → strip |
| `tools/puchi_*.py` | Mechanical helpers (features scrub, alloc rewrite, ABI-f splice, libc, strip) |
| `tools/build_puchi_tests.bat` | **Mandatory verify**: amalgamate + MSVC + Clang + Clang ASan/UBSan (tag `asan`) |

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
4. Trim init-7 / meta-7 (file/load stubs, if-style and/or, include-shared stubs), embed as C strings.
5. Concatenate `product/` + transformed sources → `puchi.h`.
6. `strip-dead-backends` + single-header assert.

## Refreshing after upstream Chibi changes

```bash
bash puchi/tools/amalgamate.sh
# If a patch rejects:
# Edit workdir file to the desired puchi shape, then:
#   diff -u /path/to/upstream/sexp.h sexp.h > ../../patches/001-....diff
# Paths inside the diff must be workdir-relative (e.g. sexp.h), for patch -p0.

bash puchi/tools/check_amalgamate.sh   # must exit 0; commit puchi.h + refreshed patches
puchi\tools\build_puchi_tests.bat      # mandatory: suite + sanitizers must exit 0
```

## Drift check

```bash
bash puchi/tools/check_amalgamate.sh
```

Fails if any patch does not apply, or if regenerated `puchi.h` differs from git. Still run `build_puchi_tests.bat` before calling the change done.
