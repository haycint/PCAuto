# -*- coding: utf-8 -*-
# Disassemble specific functions from main script (fixed name matching)
import marshal, dis, types

data = open(r'C:\Users\TianYifan\.doubao\lark-chats\2026-10-01\new-chat\re_work\extracted\jira_feishu_sync.pyc','rb').read()
code = marshal.loads(data[0:])

codes = {}
def walk(c, prefix=None):
    name = (prefix + '.' if prefix else '') + c.co_name
    codes[name] = c
    for const in c.co_consts:
        if isinstance(const, types.CodeType):
            walk(const, name)
walk(code)

targets = ['JiraHtmlClient.login', 'JiraHtmlClient.fetch_filter_html',
           'SyncManager.parse_feishu_url', 'SyncManager.parse_jira_filter_url',
           'SyncManager.sync_incremental', 'JiraFeishuSyncApp._do_sync']
out = []
for t in targets:
    # find code whose co_name matches and ancestor chain contains class
    c = None
    for k, v in codes.items():
        if k.endswith('.' + t) or k == t:
            c = v
            break
    out.append('#'*70)
    out.append('### DISASSEMBLY: ' + t)
    out.append('#'*70)
    if c is None:
        out.append('  (not found)')
        continue
    try:
        import io
        buf = io.StringIO()
        dis.dis(c, file=buf)
        out.append(buf.getvalue())
    except Exception as e:
        out.append('  DIS ERROR: %r' % e)
open(r'C:\Users\TianYifan\.doubao\lark-chats\2026-10-01\new-chat\re_work\dis_key.txt','w',encoding='utf-8').write('\n'.join(out))
print('done')
