;; puchi replacement for upstream lib/scheme/process-context.sld (which
;; imports exit from the OS library (chibi process)).  exit runs the
;; outstanding dynamic-wind "after" thunks by jumping to a continuation
;; captured when this library was loaded (as upstream's lib/chibi/process.scm
;; does), then calls the host's on_exit callback through %puchi-exit.
(define-library (scheme process-context)
  (import (chibi) (puchi host))
  (export get-environment-variable get-environment-variables
          command-line exit emergency-exit)
  (begin
    (define (get-environment-variables) '())
    (define (exit-code o)
      (cond ((null? o) 0)
            ((eq? #t (car o)) 0)
            ((exact-integer? (car o)) (car o))
            (else 1)))
    (define (emergency-exit . o) (%puchi-exit (exit-code o)))
    (define unwind #f)
    ((call-with-current-continuation
      (lambda (k)
        (set! unwind k)
        (lambda () #f))))
    (define (exit . o)
      (unwind (lambda () (apply emergency-exit o))))))
