# puchi guide: verified reference files

These files accompany `puchi/GUIDE.md` (the step-by-step guide). Every file
here was compiled and tested against upstream chibi-scheme `c4e7367`; the
guide says which gate exercised which file. Layout mirrors the `puchi/`
directory the guide tells you to build:

- `patches/` - the five upstream patches (2 features, 3 upstream bug fixes)
- `src/` - puchi's own sources (`puchi.h.in`, profile, redirect layer, glue, API)
- `lib/` - puchi's replacement `.sld` files
- `tools/` - `amalgamate.py` (generator), `check_collisions.py`, `inventory.py`
- `tests/` - the test host (`runner.c`), the abandon test, small Scheme tests
