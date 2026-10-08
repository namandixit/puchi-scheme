# puchi — sandboxed single-header Chibi Scheme

`puchi.h` is generated. Do not edit it by hand.

```
bash puchi/tools/amalgamate.sh
```

Requires bash (Git Bash on Windows), `patch` or `git apply`, and Python 3.

## ALWAYS RUN TESTS

After any amalgamation or puchi change, **run the full suite — do not stop at link**.

```bat
puchi\tools\build_puchi_tests.bat
```

That script amalgamates, then for **both** MSVC (`cl`) and Clang:

| Config | Macro | What runs |
|--------|-------|-----------|
| Integer only | `PUCHI_INTEGER_ONLY` | `puchi_integer_smoke.c` (execute) |
| Int + float (default) | *(none)* | `puchi_slim_smoke.c` (execute) |
| Full tower | `PUCHI_ENABLE_NUMERICAL_TOWER` | `puchi_smoke.c` + Scheme harness (`r7rs` / `syntax` / `division` / `unicode`) |

Linking without running is not enough. A change is not done until this bat exits 0.

## Layout

| Path | Role |
|------|------|
| `product/` | Puchi-owned C (banner, feature forces, API, `#e` mul helper) — concatenated as-is |
| `patches/` | Thin unified diffs: host stream_ops ports + diskless boot |
| `tools/amalgamate.sh` | Orchestrator: copy → patch → mechanical rewrite → trim/embed → concat → strip |
| `tools/puchi_*.py` | Mechanical helpers (features scrub, alloc rewrite, ABI-f splice, libc, strip) |

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
```

## Drift check

```bash
bash puchi/tools/check_amalgamate.sh
```

Fails if any patch does not apply, or if regenerated `puchi.h` differs from git.
