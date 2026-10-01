# -*- coding: utf-8 -*-
# Patch: add pagination support to jira_feishu_sync.py
import io

path = r'C:\Users\TianYifan\.doubao\lark-chats\2026-10-01\new-chat\re_work\jira_feishu_sync.py'
src = open(path, encoding='utf-8').read()

# --- 2) add _fetch + fetch_filter_all_pages after fetch_filter_html ---
old = '''    def fetch_filter_html(self, filter_url: str) -> str:
        """下载筛选器 HTML 页面（需先登录）。"""
        if self.session is None:
            raise RuntimeError("尚未登录 Jira，无法抓取页面")
        req = urllib.request.Request(filter_url, method="GET")
        try:
            resp = self.session.open(req, timeout=JIRA_TIMEOUT_FETCH)
            return resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            raise RuntimeError("下载筛选器页面失败: %s" % e)
'''
new = '''    def fetch_filter_html(self, filter_url: str) -> str:
        """下载筛选器 HTML 页面（需先登录）。"""
        return self._fetch(filter_url)

    def _fetch(self, url: str) -> str:
        """带会话 GET 指定 URL，返回解码后的 HTML 文本。"""
        if self.session is None:
            raise RuntimeError("尚未登录 Jira，无法抓取页面")
        req = urllib.request.Request(url, method="GET")
        try:
            resp = self.session.open(req, timeout=JIRA_TIMEOUT_FETCH)
            return resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            raise RuntimeError("下载筛选器页面失败: %s" % e)

    def fetch_filter_all_pages(self, filter_url: str,
                               log_callback=None) -> tuple:
        """抓取筛选器全部页数据：自动翻页并合并。

        Jira 网页列表使用 pager/start 参数翻页（每页默认 50 条）。
        策略：第一页取表头；后续页只合并数据行；某页行数不足一页
        或解析不到数据即停止；JIRA_MAX_PAGES 兜底防死循环。

        返回 (headers, rows_all)。此方法在调用 fetch_filter_html 的
        场景下可直接替换，单页 URL 亦能正确处理（一页即结束）。
        """
        if self.session is None:
            raise RuntimeError("尚未登录 Jira，无法抓取页面")

        base_url = filter_url
        # 决定拼接分隔符：URL 已有查询参数用 &，否则用 ?
        sep = "&" if "?" in base_url else "?"
        headers = []
        rows_all = []
        start = 0
        pages_fetched = 0

        for _ in range(JIRA_MAX_PAGES):
            page_url = base_url if start == 0 else \\
                base_url + sep + "pager/start=" + str(start)
            page_html = self._fetch(page_url)
            pages_fetched += 1

            # 第一页取表头；每页都尝试解析行数据
            h, r = self.parse_html(page_html)
            if not h:
                h, r = self.parse_html_alternative(page_html)
            if not headers and h:
                headers = h

            # 本页无数据 → 全部抓完，结束
            if not r:
                break
            rows_all.extend(r)
            if log_callback:
                log_callback("  已抓取筛选器第 %d 页，累计 %d 行"
                             % (pages_fetched, len(rows_all)))

            # 行数不足一页 → 最后一页，结束
            if len(r) < JIRA_PAGE_SIZE:
                break
            start += len(r)

        if log_callback:
            log_callback("  筛选器抓取完成：共 %d 页，%d 行数据"
                         % (pages_fetched, len(rows_all)))
        return headers, rows_all
'''
assert old in src, 'fetch anchor missing'
src = src.replace(old, new, 1)

# --- 3) update _do_sync to use all-pages fetcher ---
old2 = '''            log("正在下载筛选器页面...")
            try:
                page_html = jira_client.fetch_filter_html(config["jira_filter_url"])
            except Exception as e:
                log("下载筛选器页面失败: %s" % e)
                set_status("同步失败", "red")
                return
            log("HTML页面大小: %d 字节" % len(page_html))

            # 6) 解析 HTML
            log("正在解析HTML...")
            headers, rows = jira_client.parse_html(page_html)
            if not headers:
                log("尝试备用解析方法...")
                headers, rows = jira_client.parse_html_alternative(page_html)
            if not headers:
                log("错误: 无法从HTML中解析出表头")
                set_status("同步失败", "red")
                return
            log("解析到 %d 列: %s" % (len(headers), ", ".join(headers)))
            log("解析到 %d 行数据" % len(rows))
'''
new2 = '''            log("正在下载筛选器页面（自动翻页）...")
            try:
                headers, rows = jira_client.fetch_filter_all_pages(
                    config["jira_filter_url"], log_callback=log)
            except Exception as e:
                log("下载筛选器页面失败: %s" % e)
                set_status("同步失败", "red")
                return
            if not headers:
                log("错误: 无法从HTML中解析出表头")
                set_status("同步失败", "red")
                return
            log("解析到 %d 列: %s" % (len(headers), ", ".join(headers)))
            log("解析到 %d 行数据" % len(rows))
'''
assert old2 in src, 'do_sync anchor missing'
src = src.replace(old2, new2, 1)

open(path, 'w', encoding='utf-8').write(src)
print('patch applied OK')
