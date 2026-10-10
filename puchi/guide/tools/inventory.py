#!/usr/bin/env python3
"""For every reference from upstream code to a function or variable declared
in a system header: where, in which function, call or value use, and whether
an identifier `ctx` of type sexp is in scope.  Also reports upstream
declarations/members whose names equal a system-header name (collision risk
for redirect macros).  Usage: callsites.py OUT.tsv COLLISIONS.tsv FILE..."""
import os
import sys
import clang.cindex as ci

ci.Config.set_library_file('/usr/lib/llvm-18/lib/libclang-18.so.1')
V = os.path.dirname(os.path.abspath(__file__))
UP = os.path.join(V, 'up') + os.sep
ARGS = os.environ.get('EXTRA_ARGS', '').split() + ['-O2', '-include', os.environ.get('PROFILE', os.path.join(V, 'profile.h')),
        '-I', os.path.join(V, 'up', 'include'), '-I', os.path.join(V, 'up')]
K = ci.CursorKind


def in_upstream(loc):
    return loc.file is not None and os.path.abspath(loc.file.name).startswith(UP)


def rel(loc):
    return '%s:%d' % (os.path.relpath(loc.file.name, os.path.join(V, 'up')), loc.line)


def ctx_in_scope(func, ref_offset):
    """'param', 'local', or '' — an sexp named ctx declared before ref in func."""
    best = ''
    stack = [func]
    while stack:
        c = stack.pop()
        for ch in c.get_children():
            if ch.kind in (K.PARM_DECL, K.VAR_DECL) and ch.spelling == 'ctx':
                if ch.extent.start.offset <= ref_offset <= func.extent.end.offset \
                        and 'sexp' in ch.type.spelling:
                    if ch.kind == K.PARM_DECL:
                        return 'param'
                    best = 'local'
            stack.append(ch)
    return best


def main():
    out_path, coll_path, files = sys.argv[1], sys.argv[2], sys.argv[3:]
    idx = ci.Index.create()
    rows, colls = set(), set()
    sys_names = set()
    for f in files:
        tu = idx.parse(os.path.join(V, 'up', f), args=ARGS)
        errs = [d for d in tu.diagnostics if d.severity >= ci.Diagnostic.Error]
        if errs:
            print('parse errors in', f, errs[:3], file=sys.stderr)

        def walk(c, func, parent):
            try:
                c.kind
            except ValueError:          # cursor kind unknown to these bindings
                return
            if c.kind == K.FUNCTION_DECL and c.is_definition():
                func = c
            if c.kind == K.DECL_REF_EXPR and c.referenced is not None \
                    and c.referenced.kind in (K.FUNCTION_DECL, K.VAR_DECL) \
                    and not in_upstream(c.referenced.location) \
                    and c.referenced.location.file is not None \
                    and in_upstream(c.location):
                name = c.referenced.spelling
                sys_names.add(name)
                # callee if the nearest non-cast ancestor is a CALL_EXPR whose
                # first child (through implicit casts) is this reference
                use = 'value'
                if parent is not None and parent.kind == K.CALL_EXPR:
                    first = next(parent.get_children(), None)
                    while first is not None and first.kind == K.UNEXPOSED_EXPR:
                        first = next(first.get_children(), None)
                    if first is not None and first == c:
                        use = 'call'
                fname = func.spelling if func is not None else '<file scope>'
                scope = ctx_in_scope(func, c.location.offset) if func is not None else ''
                rows.add((name, rel(c.location), fname, use, scope or 'none'))
            if c.kind in (K.MEMBER_REF_EXPR, K.FIELD_DECL, K.FUNCTION_DECL, K.VAR_DECL,
                          K.PARM_DECL, K.TYPEDEF_DECL) and in_upstream(c.location):
                colls.add((c.spelling, c.kind.name, rel(c.location)))
            # pass the call expr as parent through implicit casts
            for ch in c.get_children():
                try:
                    ch.kind
                except ValueError:
                    continue
                p = c if c.kind == K.CALL_EXPR else (parent if c.kind == K.UNEXPOSED_EXPR else c)
                walk(ch, func, p)
        walk(tu.cursor, None, None)
    with open(out_path, 'w') as o:
        for r in sorted(rows):
            o.write('\t'.join(r) + '\n')
    with open(coll_path, 'w') as o:
        for name, kind, where in sorted(colls):
            if name in sys_names:
                o.write('\t'.join((name, kind, where)) + '\n')


if __name__ == '__main__':
    main()
