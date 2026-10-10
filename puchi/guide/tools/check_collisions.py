#!/usr/bin/env python3
"""check_collisions.py - fail if upstream code declares an identifier that a
puchi redirect macro would rewrite.

A function-like redirect macro NAME(...) rewrites every "NAME (" token
sequence.  That breaks a function-pointer member, variable or parameter
named NAME (p->free(x)), and a function defined with that name (Windows
ast.c defines setenv).  Members, variables and parameters of any other
type are never followed by "(" and are harmless.

Usage: check_collisions.py REDIRECT_HEADER CLANG_ARGS... -- FILE...
Exit status 1 if any collision is found, 2 if a file does not parse."""
import os
import re
import sys
import clang.cindex as ci

ci.Config.set_library_file(os.environ.get('LIBCLANG', '/usr/lib/llvm-18/lib/libclang-18.so.1'))
K = ci.CursorKind


def redirected_names(header):
    names = set()
    for line in open(header, encoding='utf-8'):
        m = re.match(r'\s*#\s*define\s+([A-Za-z_]\w*)\(', line)
        if m and not m.group(1).startswith(('PUCHI_', 'puchi_')):
            names.add(m.group(1))
    return names


def main():
    header = sys.argv[1]
    sep = sys.argv.index('--')
    args, files = sys.argv[2:sep], sys.argv[sep + 1:]
    names = redirected_names(header)
    found = []
    for f in files:
        tu = ci.Index.create().parse(f, args=args)
        errors = [d for d in tu.diagnostics if d.severity >= ci.Diagnostic.Error]
        if errors:                      # a file that does not parse hides collisions
            for d in errors[:5]:
                print('parse error:', d)
            return 2
        root = os.path.dirname(os.path.abspath(f))
        for c in tu.cursor.walk_preorder():
            try:
                kind = c.kind
            except ValueError:
                continue
            if c.spelling not in names or c.location.file is None:
                continue
            loc = os.path.abspath(c.location.file.name)
            if loc.startswith('/usr/'):
                continue                         # system headers
            t = c.type.get_canonical()
            callable = (t.kind == ci.TypeKind.POINTER and t.get_pointee().kind
                        in (ci.TypeKind.FUNCTIONPROTO, ci.TypeKind.FUNCTIONNOPROTO))
            bad = ((kind == K.FUNCTION_DECL and c.is_definition())
                   or (kind in (K.FIELD_DECL, K.VAR_DECL, K.PARM_DECL) and callable))
            if bad:
                found.append('%s:%d: %s %s' % (loc, c.location.line, kind.name, c.spelling))
    for line in sorted(set(found)):
        print('collision:', line)
    print('check_collisions: %d collision(s), %d redirected names' % (len(set(found)), len(names)))
    return 1 if found else 0


if __name__ == '__main__':
    sys.exit(main())
