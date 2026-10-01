# -*- coding: utf-8 -*-
# 翻页功能专项测试（模拟 Jira 多页筛选器，不触网）
import importlib.util

spec = importlib.util.spec_from_file_location(
    "jfs_mod", r"C:\Users\TianYifan\.doubao\lark-chats\2026-10-01\new-chat\re_work\jira_feishu_sync.py")
mod = importlib.util.module_from_spec(spec)
# 直接加载整个模块会 import tkinter（无显示环境可能失败），改为 exec 纯逻辑部分
src = open(r"C:\Users\TianYifan\.doubao\lark-chats\2026-10-01\new-chat\re_work\jira_feishu_sync.py", encoding="utf-8").read()
cut = src.index("class JiraFeishuSyncApp")
logic_src = src[:cut].replace("import tkinter as tk", "").replace("from tkinter import ttk, messagebox", "")
ns = {}
ns["__file__"] = r"C:\Users\TianYifan\.doubao\lark-chats\2026-10-01\new-chat\re_work\jira_feishu_sync.py"
exec(compile(logic_src, "logic", "exec"), ns)

JiraHtmlClient = ns["JiraHtmlClient"]
PAGE_SIZE = ns["JIRA_PAGE_SIZE"]
MAX_PAGES = ns["JIRA_MAX_PAGES"]


def make_page(rows, page_label):
    """构造一页 Jira HTML（含 thead 与 issuerow 行）。"""
    thead = "<thead><tr><th>Issue Key</th><th>Summary</th></tr></thead>"
    body = "".join(
        '<tr class="issuerow"><td><a>%s</a></td><td>%s</td></tr>' % (k, s)
        for k, s in rows)
    return "<html><body><table>%s%s</table></body></html>" % (thead, body)


# ---- Mock session：按 URL 返回对应页 ----
class FakeSession:
    def __init__(self, pages):
        self.pages = pages          # {url: html}
        self.calls = []
    def open(self, req, timeout=None):
        self.calls.append(req.full_url)
        html = self.pages.get(req.full_url)
        if html is None:
            html = make_page([], 0)      # 未知页返回空
        import urllib.request
        return FakeResp(html)

class FakeResp:
    def __init__(self, html):
        self._b = html.encode("utf-8")
    def read(self):
        return self._b
    def geturl(self):
        return "http://jira.test:8080/dashboard"

# ---- 场景 1: 3 页数据（50+50+20 = 120 条）----
base = "http://jira.test:8080/issues/?filter=12345"
page1 = make_page([("A%03d" % i, "s%d" % i) for i in range(1, PAGE_SIZE + 1)], 1)
page2 = make_page([("A%03d" % i, "s%d" % i) for i in range(PAGE_SIZE + 1, PAGE_SIZE * 2 + 1)], 2)
page3 = make_page([("A%03d" % i, "s%d" % i) for i in range(PAGE_SIZE * 2 + 1, PAGE_SIZE * 2 + 21)], 3)

sess = FakeSession({
    base: page1,
    base + "&pager/start=50": page2,
    base + "&pager/start=100": page3,
})
client = JiraHtmlClient("http://jira.test:8080", "u", "p")
client.session = sess
logs = []
headers, rows = client.fetch_filter_all_pages(base, log_callback=logs.append)

assert headers == ["Issue Key", "Summary"], headers
assert len(rows) == 120, len(rows)
assert rows[0] == ["A001", "s1"] and rows[-1] == ["A120", "s120"], (rows[0], rows[-1])
# 翻页请求顺序
assert sess.calls[0] == base
assert sess.calls[1] == base + "&pager/start=50"
assert sess.calls[2] == base + "&pager/start=100"
assert len(sess.calls) == 3, sess.calls
print("PASS 3-page merge (120 rows), pager/start=0/50/100")

# ---- 场景 2: 单页数据（不足一页，只请求一次）----
sess2 = FakeSession({base: make_page([("A001", "s1"), ("A002", "s2")], 1)})
client2 = JiraHtmlClient("http://jira.test:8080", "u", "p")
client2.session = sess2
h2, r2 = client2.fetch_filter_all_pages(base)
assert len(r2) == 2 and len(sess2.calls) == 1, (len(r2), sess2.calls)
print("PASS single page (2 rows, 1 request)")

# ---- 场景 3: 恰好整页数（50 条），应再多抓一页空页后停止 ----
sess3 = FakeSession({
    base: make_page([("A%03d" % i, "s") for i in range(1, PAGE_SIZE + 1)], 1),
    base + "&pager/start=50": make_page([], 2),   # 第二页空
})
client3 = JiraHtmlClient("http://jira.test:8080", "u", "p")
client3.session = sess3
h3, r3 = client3.fetch_filter_all_pages(base)
assert len(r3) == PAGE_SIZE and len(sess3.calls) == 2, (len(r3), sess3.calls)
print("PASS exact-page-size (50 rows, stops after empty page)")

# ---- 场景 4: URL 无查询参数（? 分隔符正确）----
base4 = "http://jira.test:8080/issues"
sess4 = FakeSession({base4: make_page([("A001", "s")], 1)})
client4 = JiraHtmlClient("http://jira.test:8080", "u", "p")
client4.session = sess4
h4, r4 = client4.fetch_filter_all_pages(base4)
assert len(r4) == 1, r4
print("PASS URL without query params (? separator)")

# ---- 场景 5: 未登录抛错 ----
client5 = JiraHtmlClient("http://jira.test:8080", "u", "p")
try:
    client5.fetch_filter_all_pages(base)
    raise SystemExit("should have raised")
except RuntimeError as e:
    assert "尚未登录" in str(e)
print("PASS not-logged-in raises RuntimeError")

print("\nALL PAGINATION TESTS PASSED")
