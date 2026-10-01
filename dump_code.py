# -*- coding: utf-8 -*-
# Dump all string constants + code structure from main script code object
import marshal, dis, types

data = open(r'C:\Users\TianYifan\.doubao\lark-chats\2026-10-01\new-chat\re_work\extracted\jira_feishu_sync.pyc','rb').read()
code = marshal.loads(data[0:])
print('TOP:', code.co_name, code.co_filename, code.co_firstlineno)

seen = set()
all_strings = []
funcs = []

def walk(c, depth=0):
    if id(c) in seen:
        return
    seen.add(id(c))
    try:
        funcs.append((c.co_name, c.co_firstlineno, depth, c))
    except Exception:
        pass
    for const in c.co_consts:
        if isinstance(const, types.CodeType):
            walk(const, depth+1)
        elif isinstance(const, str):
            all_strings.append((c.co_name, const))

walk(code)
print('TOTAL CODES:', len(funcs))
print()
print('===== FUNCTIONS / CLASSES =====')
for name, lineno, depth, c in funcs:
    args = c.co_varnames[:c.co_argcount]
    print(f'{"  "*depth}{name}() @line {lineno}  args={args}  varnames={c.co_varnames}')
print()
print('===== ALL STRING CONSTANTS (%d) =====' % len(all_strings))
for owner, s in all_strings:
    print(f'[{owner}] {s!r}')
