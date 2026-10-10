/* torn.c - verification only.  Does a stock Chibi context survive being
 * abandoned mid-evaluation (host exit callback that never returns), and can
 * the green-thread scheduler slot serve as an interrupt hook?
 *
 *   torn exit      abandon from a nested C->Scheme call, free the stack, destroy
 *   torn control   same, but run a GC before destroy (must be reported by ASan)
 *   torn hard      scheduler hook abandons an infinite loop, free stack, destroy
 *   torn soft      scheduler hook sets interruptp: catchable? context reusable?
 */
#define _XOPEN_SOURCE 700
#include <ucontext.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "chibi/eval.h"

#define STACK_SIZE (1 << 20)
static ucontext_t main_uc, vm_uc;
static sexp ctx, result;
static const char *program;
static int mode, sched_calls, sched_limit, exited;

static sexp host_exit(sexp ctx, sexp self, sexp_sint_t n, sexp code) {
  (void)ctx; (void)self; (void)n; (void)code;
  exited = 1;
  swapcontext(&vm_uc, &main_uc);      /* never resumed */
  return SEXP_VOID;
}

/* A C primitive that preserves a GC variable and calls back into Scheme,
 * so the abandoned stack holds linked sexp_gc_var_t frames. */
static sexp call_thunk(sexp ctx, sexp self, sexp_sint_t n, sexp thunk) {
  sexp_gc_var1(tmp);
  (void)self; (void)n;
  sexp_gc_preserve1(ctx, tmp);
  tmp = sexp_make_vector(ctx, SEXP_TEN, SEXP_FALSE);
  tmp = sexp_apply(ctx, thunk, SEXP_NULL);
  sexp_gc_release1(ctx);
  return tmp;
}

static sexp scheduler(sexp ctx, sexp self, sexp_sint_t n, sexp root) {
  (void)self; (void)n; (void)root;
  if (++sched_calls >= sched_limit) {
    sched_calls = 0;
    if (mode == 1) { exited = 1; swapcontext(&vm_uc, &main_uc); }   /* hard */
    else sexp_context_interruptp(ctx) = 1;                         /* soft */
  }
  return ctx;
}

static void vm_main(void) {
  result = sexp_eval_string(ctx, program, -1, NULL);
  swapcontext(&vm_uc, &main_uc);
}

static void open_ctx(void) {
  ctx = sexp_make_eval_context(NULL, NULL, NULL, 0, 0);
  sexp_load_standard_env(ctx, NULL, SEXP_SEVEN);
  sexp_load_standard_ports(ctx, NULL, stdin, stdout, stderr, 1);
  sexp_define_foreign(ctx, sexp_context_env(ctx), "host-exit", 1, host_exit);
  sexp_define_foreign(ctx, sexp_context_env(ctx), "call-thunk", 1, call_thunk);
  sexp_global(ctx, SEXP_G_THREADS_SCHEDULER) =
    sexp_make_foreign(ctx, "puchi-scheduler", 1, 0, NULL, (sexp_proc1)scheduler, NULL);
}

/* Run program on its own stack; return 1 if it was abandoned. */
static int run_on_coroutine(const char *prog) {
  char *stack = malloc(STACK_SIZE);
  program = prog;
  exited = 0;
  result = SEXP_VOID;
  getcontext(&vm_uc);
  vm_uc.uc_stack.ss_sp = stack;
  vm_uc.uc_stack.ss_size = STACK_SIZE;
  vm_uc.uc_link = NULL;
  makecontext(&vm_uc, vm_main, 0);
  swapcontext(&main_uc, &vm_uc);
  { struct sexp_gc_var_t *g; int k = 0;
    for (g = sexp_context_saves(ctx); g && k < 50; g = g->next, k++)
      printf("  saves[%d]=%p in_vm_stack=%d\n", k, (void*)g, (char*)g >= stack && (char*)g < stack + STACK_SIZE);
    printf("  saves chain length %d (stack %p..%p)\n", k, (void*)stack, (void*)(stack+STACK_SIZE)); }
  memset(stack, 0xA5, STACK_SIZE);   /* trash, then free, the VM's stack */
  free(stack);
  return exited;
}

static void show(const char *label, sexp x) {
  sexp out = sexp_open_output_string(ctx);
  if (sexp_exceptionp(x)) sexp_print_exception(ctx, x, out);
  else sexp_write(ctx, x, out);
  printf("%s: %s\n", label, sexp_string_data(sexp_get_output_string(ctx, out)));
}

int main(int argc, char **argv) {
  const char *what = argc > 1 ? argv[1] : "exit";
  sexp_scheme_init();
  open_ctx();
  if (!strcmp(what, "exit") || !strcmp(what, "control")) {
    mode = 0; sched_limit = 1 << 30;
    printf("abandoned: %d\n", run_on_coroutine(
      "(dynamic-wind (lambda () #f)"
      "  (lambda () (call-thunk (lambda ()"
      "    (let loop ((i 0)) (if (< i 2000) (begin (make-vector 50 i) (loop (+ i 1)))"
      "                          (call-thunk (lambda () (host-exit 3))))))))"
      "  (lambda () (display \"after\\n\")))"));
    if (!strcmp(what, "control")) { puts("control: GC on torn context"); sexp_gc(ctx, NULL); }
  } else if (!strcmp(what, "hard")) {
    mode = 1; sched_limit = 200;
    printf("abandoned: %d\n", run_on_coroutine(
      "(let loop ((i 0)) (call-thunk (lambda () (make-vector 10 i))) (loop (+ i 1)))"));
  } else if (!strcmp(what, "soft")) {
    mode = 2; sched_limit = 200;
    run_on_coroutine("(let loop () (loop))");
    show("uncaught loop returns", result);
    run_on_coroutine("(guard (e (#t 'caught-by-guard)) (let loop () (loop)))");
    show("guard returns", result);
    run_on_coroutine("(call-with-current-continuation (lambda (k) (with-exception-handler (lambda (e) (k (list 'caught-by-handler e))) (lambda () (let loop () (loop))))))");
    show("with-exception-handler returns", result);
    run_on_coroutine("(call-with-current-continuation (lambda (k) (with-exception-handler (lambda (e) (k 'caught-car-error)) (lambda () (car 1)))))");
    show("handler on (car 1) returns", result);
    sched_limit = 1 << 30;
    run_on_coroutine("(+ 1 2)");
    show("context still usable", result);
  }
  printf("destroy: %s\n", sexp_destroy_context(ctx) == SEXP_TRUE ? "ok" : "failed");
  return 0;
}
