# puchi harness clibs patches

UBSan fixes for FFI stubs linked into `puchi_harness_clibs.c`.

**Do not edit upstream `lib/`.** Patches live here; `prep_harness_clibs.sh`
copies stock stubs into `puchi/test/build/clibs/` and applies them. A reject
means upstream changed — refresh the `.ubsan.diff` and re-run the bat.

| Patch | Upstream source |
|-------|-----------------|
| `srfi_151_bit.ubsan.diff` | `lib/srfi/151/bit.c` (`log2i` shift-by-width) |
| `scheme_bytevector.ubsan.diff` | `lib/scheme/bytevector.c` (signed endian swaps) |

```bash
bash puchi/tools/prep_harness_clibs.sh   # also invoked by build_puchi_tests.bat
```

After `generate_harness_stubs.sh` regenerates `lib/scheme/bytevector.c`, run
`prep_harness_clibs.sh`; if it fails, update `scheme_bytevector.ubsan.diff`.