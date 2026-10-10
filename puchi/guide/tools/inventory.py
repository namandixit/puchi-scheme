#!/usr/bin/env python3
"""inventory.py - list every reference from upstream code to a function or
variable declared in a system header: where, in which function, call or
value use, and whether an identifier `ctx` of type sexp is in scope.

Use it when gate G6 reports a new symbol, to decide STUB / DENY / ROUTE:
a ROUTE needs `ctx` in scope at every call site.

Usage: inventory.py CLANG_ARGS... -- FILE...
  e.g. inventory.py -include puchi/src/puchi_config.h -Ipuchi/build/gen \
         -Ipuchi/build/src/include -Ipuchi/build/src \
         -resource-dir $(clang -print-resource-dir) -- puchi/build/src/sexp.c
Prints tab-separated: name, file:line, function, call|value, param|local|none
Set LIBCLANG to the libclang shared library if the default is wrong."""
import os
import sys
import clang.cindex as ci

ci.Config.set_library_file(os.environ.get('LIBCLANG', '/usr/lib/llvm-18/lib/libclang-18.so.1'))
K = ci.CursorKind


def kind_of(c):
    try:
        return c.kind
    except ValueError:               # cursor kind unknown to these bindings
        return None


def is_system(loc):
    return loc.file is None or os.path.abspath(loc.file.name).startswith('/usr/')


def ctx_in_scope(func, offset):
    best = ''
    for c in func.walk_preorder():
        if kind_of(c) in (K.PARM_DECL, K.VAR_DECL) and c.spelling == 'ctx' \
                and c.extent.start.offset <= offset and 'sexp' in c.type.spelling:
            if kind_of(c) == K.PARM_DECL:
                return 'param'
            best = 'local'
    return best or 'none'


def main():
    sep = sys.argv.index('--')
    args, files = sys.argv[1:sep], sys.argv[sep + 1:]
    rows = set()
    for f in files:
        tu = ci.Index.create().parse(f, args=args)
        errors = [d for d in tu.diagnostics if d.severity >= ci.Diagnostic.Error]
        if errors:
            for d in errors[:5]:
                print('parse error:', d, file=sys.stderr)
            return 2

        def walk(c, func, parent):
            k = kind_of(c)
            if k is None:
                return
            if k == K.FUNCTION_DECL and c.is_definition():
                func = c
            if k == K.DECL_REF_EXPR and c.referenced is not None \
                    and kind_of(c.referenced) in (K.FUNCTION_DECL, K.VAR_DECL) \
                    and is_system(c.referenced.location) and not is_system(c.location):
                use = 'value'
                if parent is not None and kind_of(parent) == K.CALL_EXPR:
                    first = next(parent.get_children(), None)
                    while first is not None and kind_of(first) == K.UNEXPOSED_EXPR:
                        first = next(first.get_children(), None)
                    if first is not None and first == c:
                        use = 'call'
                where = '%s:%d' % (os.path.relpath(c.location.file.name), c.location.line)
                rows.add((c.referenced.spelling, where,
                          func.spelling if func is not None else '<file scope>', use,
                          ctx_in_scope(func, c.location.offset) if func is not None else 'none'))
            for ch in c.get_children():
                p = c if k == K.CALL_EXPR else (parent if k == K.UNEXPOSED_EXPR else c)
                walk(ch, func, p)
        walk(tu.cursor, None, None)
    for r in sorted(rows):
        print('\t'.join(r))
    return 0


if __name__ == '__main__':
    sys.exit(main())
