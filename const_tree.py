# -*- coding: utf-8 -*-
# Dump full constants tree per function (strings, numbers, tuples) - reliable for logic reconstruction
import marshal, types

data = open(r'C:\Users\TianYifan\.doubao\lark-chats\2026-10-01\new-chat\re_work\extracted\jira_feishu_sync.pyc','rb').read()
code = marshal.loads(data[0:])

def fmt(v):
    if isinstance(v, str):
        return repr(v)
    if isinstance(v, tuple):
        return '(' + ', '.join(fmt(x) for x in v) + ')'
    if isinstance(v, types.CodeType):
        return '<code %s>' % v.co_name
    if isinstance(v, bytes):
        return 'b%r' % v
    return repr(v)

def walk(c, prefix, out, depth=0):
    name = (prefix + '.' if prefix else '') + c.co_name
    out.append('='*66)
    out.append('### %s  (line %d, args=%s)' % (name, c.co_firstlineno, c.co_varnames[:c.co_argcount]))
    out.append('  co_names: %s' % (c.co_names,))
    out.append('  co_consts:')
    for const in c.co_consts:
        out.append('    %s' % fmt(const))
    for const in c.co_consts:
        if isinstance(const, types.CodeType):
            walk(const, name, out, depth+1)

out = []
walk(code, '', out)
open(r'C:\Users\TianYifan\.doubao\lark-chats\2026-10-01\new-chat\re_work\const_tree.txt','w',encoding='utf-8').write('\n'.join(out))
print('wrote', len(out), 'lines')
