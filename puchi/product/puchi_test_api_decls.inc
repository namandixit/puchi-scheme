/* PUCHI_TEST function decls — include under #if PUCHI_TEST after host ABI. */
PUCHI_API void puchi_TEST_add_static_libraries(puchi ctx, struct puchi_library_entry_t *libraries);
PUCHI_API puchi puchi_TEST_load_op(puchi ctx, puchi self, puchi_sint_t n, puchi source, puchi env);
PUCHI_API puchi puchi_TEST_current_module_path_op(puchi ctx, puchi self, puchi_sint_t n, puchi x);
PUCHI_API puchi puchi_TEST_load_module_file_op(puchi ctx, puchi self, puchi_sint_t n, puchi file, puchi env);
PUCHI_API puchi puchi_TEST_add_module_directory_op(puchi ctx, puchi self, puchi_sint_t n, puchi dir, puchi appendp);
