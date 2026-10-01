# -*- coding: utf-8 -*-
# 对还原源码的纯逻辑部分做单元验证（不触网、不开 GUI）
import sys, importlib.util, os

spec = importlib.util.spec_from_file_location(
    "jfs", r"C:\Users\TianYifan\.doubao\lark-chats\2026-10-01\new-chat\re_work\jira_feishu_sync.py")
# 直接加载模块定义（不执行 __main__，因为 tkinter 实例化只在 __main__ 下）
# 用 importlib 加载整个模块会执行 import tkinter —— 无显示环境下可能失败，这里改为 exec 源码中的类定义部分。
src = open(r"C:\Users\TianYifan\.doubao\lark-chats\2026-10-01\new-chat\re_work\jira_feishu_sync.py", encoding="utf-8").read()

# 分离出纯逻辑部分（常量 + 除 GUI 类外的所有类）验证
import re
# 提取从开头到 JiraFeishuSyncApp 之前的代码
cut = src.index("class JiraFeishuSyncApp")
logic_src = src[:cut]
# 去掉 tkinter 导入避免无显示问题（解析函数用不到 GUI）
logic_src = logic_src.replace("import tkinter as tk", "")
logic_src = logic_src.replace("from tkinter import ttk, messagebox", "")
ns = {}
ns["__file__"] = r"C:\Users\TianYifan\.doubao\lark-chats\2026-10-01\new-chat\re_work\jira_feishu_sync.py"
exec(compile(logic_src, "logic", "exec"), ns)

# ---- 测试 1: parse_feishu_url ----
sm = ns["SyncManager"]
cases = [
    ("https://xxx.feishu.cn/base/basabc123?table=tblXYZ", "basabc123", "tblXYZ"),
    ("https://xxx.feishu.cn/wiki/wikABC", "wikABC", None),
    ("https://example.com/other", None, None),
    ("  https://xxx.feishu.cn/base/basXYZ  ", "basXYZ", None),
]
for url, exp_token, exp_table in cases:
    t, t_id = sm.parse_feishu_url(url)
    assert t == exp_token, (url, t, exp_token)
    assert t_id == exp_table, (url, t_id, exp_table)
print("PASS parse_feishu_url")

# ---- 测试 2: parse_jira_filter_url ----
cases = [
    ("http://jira.x:8080/issues/?filter=12345", "12345"),
    ("http://jira.x:8080/secure/IssueNavigator.jspa?requestId=678", "678"),
    ("http://jira.x:8080/browse/PROJ-1", None),
]
for url, exp in cases:
    r = sm.parse_jira_filter_url(url)
    assert r == exp, (url, r, exp)
print("PASS parse_jira_filter_url")

# ---- 测试 3: JiraHtmlClient.parse_html ----
jc = ns["JiraHtmlClient"]
client = jc("http://jira.test:8080", "u", "p")  # 仅测解析，不登录
html_sample = """<html><body>
<table id="issuetable">
<thead><tr><th>Issue Key</th><th>Summary</th><th>Status</th></tr></thead>
<tbody>
<tr class="issuerow"><td><a>PROJ-1</a></td><td>Fix &amp; bug</td><td>Open</td></tr>
<tr class="issuerow"><td>PROJ-2</td><td>Test</td><td>Closed</td></tr>
</tbody>
</table></body></html>"""
headers, rows = client.parse_html(html_sample)
assert headers == ["Issue Key", "Summary", "Status"], headers
assert rows == [["PROJ-1", "Fix & bug", "Open"], ["PROJ-2", "Test", "Closed"]], rows
print("PASS parse_html (issuerow + thead + unescape)")

# ---- 测试 4: parse_html_alternative ----
headers2, rows2 = client.parse_html_alternative(html_sample)
assert headers2 == ["Issue Key", "Summary", "Status"], headers2
assert rows2 == [["PROJ-1", "Fix & bug", "Open"], ["PROJ-2", "Test", "Closed"]], rows2
print("PASS parse_html_alternative")

# ---- 测试 5: parse_html 无 thead 时用首行兜底 ----
html2 = """<table><tr><td>ColA</td><td>ColB</td></tr>
<tr><td>1</td><td>2</td></tr></table>"""
h3, r3 = client.parse_html(html2)
assert h3 == ["ColA", "ColB"], h3
assert r3 == [["1", "2"]], r3
print("PASS parse_html fallback (td-as-header)")

# ---- 测试 6: _get_base_dir ----
bd = ns["_get_base_dir"]
p = bd()
assert os.path.isdir(p), p
print("PASS _get_base_dir ->", p)

# ---- 测试 7: 常量核对 ----
assert ns["JIRA_DEFAULT_BASE_URL"] == "http://jira.z-onesoftware.com:8080"
assert ns["JIRA_TABLE_NAME"] == "jira-tickets"
assert ns["SYNC_INTERVAL_MINUTES"] == 5
assert ns["FEISHU_TOKEN_URL"] == "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
assert ns["FEISHU_BITABLE_BASE"] == "https://open.feishu.cn/open-apis/bitable/v1"
print("PASS constants")

print("\nALL LOGIC TESTS PASSED")
