;; puchi replacement for upstream lib/scheme/time.sld (which uses the OS
;; library (chibi time)): the clock is the host's current_second callback.
(define-library (scheme time)
  (import (only (puchi host) current-second current-jiffy jiffies-per-second))
  (export current-second current-jiffy jiffies-per-second))
