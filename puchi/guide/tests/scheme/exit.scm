(import (scheme base) (scheme process-context) (scheme write))
(dynamic-wind (lambda () #f) (lambda () (exit 7)) (lambda () (display "after\n")))
