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
