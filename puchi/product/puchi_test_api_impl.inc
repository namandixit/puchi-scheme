/* PUCHI_TEST API bodies — emitted under IMPLEMENTATION && !PUCHI_TEST_CLIB. */

PUCHI_API void puchi_TEST_add_static_libraries(puchi ctx, struct puchi_library_entry_t *libraries) {
  sexp_add_static_libraries(ctx, libraries);
}

PUCHI_API puchi puchi_TEST_load_op(puchi ctx, puchi self, puchi_sint_t n, puchi source, puchi env) {
  return sexp_load_op(ctx, self, n, source, env);
}

PUCHI_API puchi puchi_TEST_current_module_path_op(puchi ctx, puchi self, puchi_sint_t n, puchi x) {
  return sexp_current_module_path_op(ctx, self, n, x);
}

PUCHI_API puchi puchi_TEST_load_module_file_op(puchi ctx, puchi self, puchi_sint_t n, puchi file, puchi env) {
  return sexp_load_module_file_op(ctx, self, n, file, env);
}

PUCHI_API puchi puchi_TEST_add_module_directory_op(puchi ctx, puchi self, puchi_sint_t n, puchi dir, puchi appendp) {
  return sexp_add_module_directory_op(ctx, self, n, dir, appendp);
}
