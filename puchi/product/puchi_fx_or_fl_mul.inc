#if !defined(PUCHI_INTEGER_ONLY) && !defined(PUCHI_ENABLE_NUMERICAL_TOWER)
/* Exact #e mantissa * 10^e without sexp_mul (no bignum.c). */
static sexp puchi_fx_or_fl_mul(sexp ctx, sexp a, sexp b) {
  if (sexp_fixnump(a) && sexp_fixnump(b)) {
    sexp_sint_t x = sexp_unbox_fixnum(a), y = sexp_unbox_fixnum(b);
    if (x != 0 && y != 0) {
      if (x > 0) {
        if (y > 0) {
          if (x > SEXP_MAX_FIXNUM / y) goto flo;
        } else {
          if (y < SEXP_MIN_FIXNUM / x) goto flo;
        }
      } else {
        if (y > 0) {
          if (x < SEXP_MIN_FIXNUM / y) goto flo;
        } else {
          if (x == SEXP_MIN_FIXNUM || y == SEXP_MIN_FIXNUM) goto flo;
          if (-x > SEXP_MAX_FIXNUM / -y) goto flo;
        }
      }
    }
    return sexp_fx_mul(a, b);
  flo:
    return sexp_make_flonum(ctx, (double)x * (double)y);
  }
  if (sexp_flonump(a) && sexp_flonump(b))
    return sexp_fp_mul(ctx, a, b);
  if (sexp_flonump(a) && sexp_fixnump(b))
    return sexp_make_flonum(ctx, sexp_flonum_value(a) * (double)sexp_unbox_fixnum(b));
  if (sexp_fixnump(a) && sexp_flonump(b))
    return sexp_make_flonum(ctx, (double)sexp_unbox_fixnum(a) * sexp_flonum_value(b));
  return sexp_type_exception(ctx, NULL, SEXP_NUMBER, sexp_list2(ctx, a, b));
}
#endif
