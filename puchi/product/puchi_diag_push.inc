/* Silence /W4 and -Weverything noise from amalgamated upstream Chibi.
 * amalgamate.sh gates this on PUCHI_IMPLEMENTATION || PUCHI_TEST so bare
 * API includes are not wrapped. */
#if defined(__clang__)
#pragma clang diagnostic push
#pragma clang diagnostic ignored "-Wcast-align"
#pragma clang diagnostic ignored "-Wcast-function-type-strict"
#pragma clang diagnostic ignored "-Wcast-function-type-mismatch"
#pragma clang diagnostic ignored "-Wbad-function-cast"
#pragma clang diagnostic ignored "-Wsign-conversion"
#pragma clang diagnostic ignored "-Wsign-compare"
#pragma clang diagnostic ignored "-Wshorten-64-to-32"
#pragma clang diagnostic ignored "-Wimplicit-int-conversion"
#pragma clang diagnostic ignored "-Wimplicit-int-conversion-on-negation"
#pragma clang diagnostic ignored "-Wimplicit-int-float-conversion"
#pragma clang diagnostic ignored "-Wimplicit-const-int-float-conversion"
#pragma clang diagnostic ignored "-Wimplicit-float-conversion"
#pragma clang diagnostic ignored "-Wfloat-conversion"
#pragma clang diagnostic ignored "-Wdouble-promotion"
#pragma clang diagnostic ignored "-Wfloat-equal"
#pragma clang diagnostic ignored "-Wunused-parameter"
#pragma clang diagnostic ignored "-Wunused-variable"
#pragma clang diagnostic ignored "-Wunused-but-set-variable"
#pragma clang diagnostic ignored "-Wunused-function"
#pragma clang diagnostic ignored "-Wunused-macros"
#pragma clang diagnostic ignored "-Wmissing-prototypes"
#pragma clang diagnostic ignored "-Wmissing-variable-declarations"
#pragma clang diagnostic ignored "-Wdeclaration-after-statement"
#pragma clang diagnostic ignored "-Wimplicit-fallthrough"
#pragma clang diagnostic ignored "-Wcomma"
#pragma clang diagnostic ignored "-Wpadded"
#pragma clang diagnostic ignored "-Wpadded-bitfield"
#pragma clang diagnostic ignored "-Wswitch-default"
#pragma clang diagnostic ignored "-Wgnu-folding-constant"
#pragma clang diagnostic ignored "-Wimplicit-void-ptr-cast"
#pragma clang diagnostic ignored "-Wtentative-definition-compat"
#pragma clang diagnostic ignored "-Wsometimes-uninitialized"
#pragma clang diagnostic ignored "-Wunsafe-buffer-usage"
#elif defined(_MSC_VER)
#pragma warning(push)
#pragma warning(disable : 4100) /* unreferenced formal parameter */
#pragma warning(disable : 4101) /* unreferenced local variable */
#pragma warning(disable : 4189) /* local variable initialized but not referenced */
#pragma warning(disable : 4018) /* signed/unsigned mismatch */
#pragma warning(disable : 4389) /* signed/unsigned mismatch */
#pragma warning(disable : 4244) /* conversion possible loss of data */
#pragma warning(disable : 4245) /* signed/unsigned conversion */
#pragma warning(disable : 4267) /* size_t conversion */
#pragma warning(disable : 4146) /* unary minus on unsigned */
#pragma warning(disable : 4334) /* 32-bit shift result converted to 64 bits */
#endif
