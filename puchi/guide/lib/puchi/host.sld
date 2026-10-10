;; Host services.  The C side is puchi_init_host_library in puchi_glue.c,
;; registered by the generated clibs.c as the static library "lib/puchi/host".
(define-library (puchi host)
  (export %puchi-exit current-second current-jiffy jiffies-per-second
          get-environment-variable file-exists? delete-file)
  (include-shared "host"))
