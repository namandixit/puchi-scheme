/* puchi_threads.h — tiny thread helpers for the harness.
 *
 * Win32 first. A later #else can call pthread with the same API.
 */
#ifndef PUCHI_THREADS_H
#define PUCHI_THREADS_H

#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <stdlib.h>

typedef HANDLE puchi_thread;
typedef int (*puchi_thread_fn)(void *);

typedef struct {
  puchi_thread_fn fn;
  void *arg;
} puchi_thread_start;

static DWORD WINAPI puchi_thread_trampoline(LPVOID p) {
  puchi_thread_start *s = (puchi_thread_start *)p;
  puchi_thread_fn fn = s->fn;
  void *arg = s->arg;
  free(s);
  return (DWORD)fn(arg);
}

static int puchi_thread_create(puchi_thread *t, puchi_thread_fn fn, void *arg) {
  puchi_thread_start *s;
  if (!t || !fn) return -1;
  s = (puchi_thread_start *)malloc(sizeof(*s));
  if (!s) return -1;
  s->fn = fn;
  s->arg = arg;
  *t = CreateThread(NULL, 0, puchi_thread_trampoline, s, 0, NULL);
  if (!*t) {
    free(s);
    return -1;
  }
  return 0;
}

/* Join one thread. WaitForMultipleObjects caps at 64 handles. */
static int puchi_thread_join(puchi_thread t, int *status) {
  DWORD code = 1;
  if (!t) return -1;
  if (WaitForSingleObject(t, INFINITE) != WAIT_OBJECT_0) {
    CloseHandle(t);
    return -1;
  }
  GetExitCodeThread(t, &code);
  CloseHandle(t);
  if (status) *status = (int)code;
  return 0;
}

static void puchi_thread_exit(int status) {
  ExitThread((DWORD)status);
}

#else
#error puchi_threads.h: Win32 only for now; add pthread when porting
#endif

#endif /* PUCHI_THREADS_H */
