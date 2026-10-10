;; puchi harness (non-Windows only): stand-in for upstream (chibi process),
;; which the harness does not ship (no process spawn / signals / fork).
;; Exports just what (scheme process-context) imports from it, built from
;; upstream's (chibi win32 process-win32) sources: plain CRT exit(), already
;; linked into the harness as a static library.
;; puchi_harness.c puts puchi/test/harness-lib first on the module path.
(define-library (chibi process)
  (import (scheme base))
  (export exit emergency-exit)
  (include-shared "win32/process-win32")
  (include "win32/process-win32.scm"))
