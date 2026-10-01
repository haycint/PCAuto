# -*- coding: utf-8 -*-
"""
Jira ↔ 飞书多维表格同步工具（可维护版）
=======================================
功能：
  1. Jira 网页表单登录，下载筛选器 HTML 页面
  2. 正则解析 HTML 提取表格数据（与网页显示的列完全一致）
  3. 按 Jira 网页列名重建飞书多维表格字段
  4. 将数据写入飞书（全量覆盖；含未接线的增量对比逻辑）
  5. 支持定时自动同步（模块常量 SYNC_INTERVAL_MINUTES，默认 5 分钟）
  6. 配置自动保存，下次启动自动填充

本文件由原打包产物（001 F-Car Export jira-tickpets luochangchuan.exe）
静态逆向还原重写：函数签名、接口地址、错误文案均与原程序一致，
仅补充了中文注释、类型标注与少量防御性处理，便于后续维护。

运行：  python jira_feishu_sync.py
打包：  pyinstaller --onefile --windowed jira_feishu_sync.py
"""

import os
import sys
import json
import re
import time
import threading
import traceback
import urllib.request
import urllib.parse
import urllib.error
import html as html_module
from datetime import datetime
from urllib.parse import urlparse, parse_qs

import tkinter as tk
from tkinter import ttk, messagebox

# ---------------------------------------------------------------------------
# 全局常量（与原程序保持一致；需要变更时只改这里）
# ---------------------------------------------------------------------------
CONFIG_FILE = "jira_feishu_sync_config.json"          # 配置文件（exe/脚本同目录）
FEISHU_TOKEN_URL = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
FEISHU_BITABLE_BASE = "https://open.feishu.cn/open-apis/bitable/v1"
SYNC_INTERVAL_MINUTES = 5                             # 定时同步间隔（分钟）
JIRA_DEFAULT_BASE_URL = "http://jira.z-onesoftware.com:8080"  # 原程序硬编码地址
JIRA_TABLE_NAME = "jira-tickets"                      # 飞书侧数据表名（硬编码）
JIRA_TABLE_DESC = "Jira Tickets同步"                  # 建表时描述
PRIMARY_FIELD_NAME = "Issue Key"                      # 主键字段名
BATCH_SIZE = 500                                      # 飞书批量操作每批条数
HTTP_TIMEOUT = 30                                     # 飞书请求超时
JIRA_TIMEOUT_LOGIN = 30                               # Jira 登录超时
JIRA_TIMEOUT_FETCH = 60                               # Jira 页面抓取超时
JIRA_PAGE_SIZE = 50                                   # Jira 列表每页条数（用于翻页判断）
JIRA_MAX_PAGES = 200                                  # 翻页保护上限（防止异常死循环）


def _get_base_dir() -> str:
    """获取程序运行目录（兼容脚本与 PyInstaller exe 模式）。"""
    if getattr(sys, "frozen", False):                 # exe 打包后
        return os.path.dirname(os.path.abspath(sys.executable))
    return os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# 配置管理：读取 / 保存用户配置
# ---------------------------------------------------------------------------
class ConfigManager:
    """配置管理：保存/读取用户配置（JSON 明文，与旧版格式兼容）。"""

    @staticmethod
    def load() -> dict:
        """读取配置文件；不存在或损坏时返回空配置。"""
        path = os.path.join(_get_base_dir(), CONFIG_FILE)
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    @staticmethod
    def save(config: dict) -> None:
        """保存配置到磁盘（ensure_ascii=False 保留中文，indent=2 便于阅读）。"""
        path = os.path.join(_get_base_dir(), CONFIG_FILE)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# 飞书多维表格（Bitable）API 客户端
# ---------------------------------------------------------------------------
class FeishuBitableClient:
    """飞书多维表格（Bitable）API 客户端。"""

    def __init__(self, app_id: str, app_secret: str):
        self.app_id = app_id
        self.app_secret = app_secret
        self.token = None                               # tenant_access_token

    # -- 底层请求 ----------------------------------------------------------
    def _request(self, method: str, url: str, data: dict = None,
                 headers: dict = None) -> dict:
        """发送 HTTP 请求，返回飞书 JSON 响应体（code==0 表示成功）。

        统一处理：Bearer 鉴权头、JSON 编码、超时、HTTPError 与异常兜底。
        """
        req_headers = {
            "Authorization": "Bearer " + (self.token or ""),
            "Content-Type": "application/json; charset=utf-8",
        }
        if headers:
            req_headers.update(headers)

        body = json.dumps(data).encode("utf-8") if data is not None else None
        req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
        try:
            resp = urllib.request.urlopen(req, timeout=HTTP_TIMEOUT)
            result = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            # 飞书业务错误也返回 JSON（code != 0），尽量解析出来供上层展示
            try:
                error_body = e.read().decode("utf-8")
                error_data = json.loads(error_body)
                result = error_data
            except Exception:
                result = {"code": -1, "msg": "HTTP %s" % e.code}
        except Exception as e:
            result = {"code": -1, "msg": str(e)}
        return result

    # -- 认证 --------------------------------------------------------------
    def get_access_token(self):
        """获取 tenant_access_token。返回 (success, msg_or_None)。"""
        result = self._request("POST", FEISHU_TOKEN_URL,
                               data={"app_id": self.app_id,
                                     "app_secret": self.app_secret})
        if result.get("code") == 0:
            self.token = result.get("tenant_access_token")
            return True, None
        return False, result.get("msg", "获取token失败")

    # -- 数据表 ------------------------------------------------------------
    def list_tables(self, app_token: str):
        """列出多维表格中的所有数据表。返回 (success, items_or_msg)。"""
        url = FEISHU_BITABLE_BASE + "/apps/" + app_token + "/tables"
        result = self._request("GET", url)
        if result.get("code") == 0:
            return True, result.get("data", {}).get("items", [])
        return False, result.get("msg", "列出表格失败")

    def create_table(self, app_token: str, table_name: str, description: str):
        """创建新的数据表（只创建表格，不预定义字段）。"""
        url = FEISHU_BITABLE_BASE + "/apps/" + app_token + "/tables"
        result = self._request("POST", url,
                               data={"name": table_name,
                                     "description": description})
        if result.get("code") == 0:
            return True, result.get("data", {}).get("table")
        return False, result.get("msg", "创建表格失败")

    # -- 字段 --------------------------------------------------------------
    def list_fields(self, app_token: str, table_id: str):
        """列出数据表中的所有字段。返回 (success, items_or_msg)。"""
        url = FEISHU_BITABLE_BASE + "/apps/" + app_token + "/tables/" + table_id + "/fields"
        result = self._request("GET", url)
        if result.get("code") == 0:
            return True, result.get("data", {}).get("items", [])
        return False, result.get("msg", "列出字段失败")

    def add_field(self, app_token: str, table_id: str, field_name: str,
                  field_type: int):
        """添加字段到数据表。field_type: 1=文本。"""
        url = FEISHU_BITABLE_BASE + "/apps/" + app_token + "/tables/" + table_id + "/fields"
        result = self._request("POST", url,
                               data={"field_name": field_name,
                                     "type": field_type})
        if result.get("code") == 0:
            return True, result.get("data")
        return False, result.get("msg", "添加字段失败")

    def delete_field(self, app_token: str, table_id: str, field_id: str):
        """删除字段。"""
        url = FEISHU_BITABLE_BASE + "/apps/" + app_token + "/tables/" + table_id \
              + "/fields/" + field_id
        result = self._request("DELETE", url)
        if result.get("code") == 0:
            return True, result.get("data")
        return False, result.get("msg", "删除字段失败")

    def rename_field(self, app_token: str, table_id: str, field_id: str,
                     new_name: str):
        """重命名字段（保留字段类型 type=1）。"""
        url = FEISHU_BITABLE_BASE + "/apps/" + app_token + "/tables/" + table_id \
              + "/fields/" + field_id
        result = self._request("PUT", url,
                               data={"field_name": new_name, "type": 1})
        if result.get("code") == 0:
            return True, result.get("data")
        return False, result.get("msg", "重命名字段失败")

    # -- 记录 --------------------------------------------------------------
    def list_records(self, app_token: str, table_id: str, page_size: int = 100,
                     page_token: str = ""):
        """列出数据表中的记录（一页）。"""
        url = FEISHU_BITABLE_BASE + "/apps/" + app_token + "/tables/" + table_id \
              + "/records?page_size=" + str(page_size) + "&page_token=" + page_token
        result = self._request("GET", url)
        if result.get("code") == 0:
            data = result.get("data", {})
            return True, data.get("items", []), data.get("page_token", "")
        return False, result.get("msg", "获取记录失败"), ""

    def get_all_records(self, app_token: str, table_id: str):
        """获取所有记录（自动分页，每页 500）。返回 (success, items_or_msg)。"""
        all_records = []
        page_token = ""
        while True:
            url = FEISHU_BITABLE_BASE + "/apps/" + app_token + "/tables/" + table_id \
                  + "/records?page_size=500&page_token=" + page_token
            result = self._request("GET", url)
            if result.get("code") != 0:
                return False, result.get("msg", "获取记录失败")
            data = result.get("data", {})
            all_records.extend(data.get("items", []))
            if not data.get("has_more"):
                break
            page_token = data.get("page_token", "")
        return True, all_records

    def create_record(self, app_token: str, table_id: str, fields: dict):
        """单条创建记录。"""
        url = FEISHU_BITABLE_BASE + "/apps/" + app_token + "/tables/" + table_id + "/records"
        result = self._request("POST", url, data={"fields": fields})
        if result.get("code") == 0:
            return True, result.get("data")
        return False, result.get("msg", "创建记录失败")

    def batch_create_records(self, app_token: str, table_id: str, records: list):
        """批量创建记录（records: [{fields: {...}}, ...]）。"""
        url = FEISHU_BITABLE_BASE + "/apps/" + app_token + "/tables/" + table_id \
              + "/records/batch_create"
        result = self._request("POST", url, data={"records": records})
        if result.get("code") == 0:
            return True, result.get("data")
        return False, result.get("msg", "批量创建记录失败")

    def batch_delete_records(self, app_token: str, table_id: str, record_ids: list):
        """批量删除记录（按 record_id 列表）。"""
        url = FEISHU_BITABLE_BASE + "/apps/" + app_token + "/tables/" + table_id \
              + "/records/batch_delete"
        result = self._request("POST", url,
                               data={"records": [{"record_id": rid} for rid in record_ids]})
        if result.get("code") == 0:
            return True, result.get("data")
        return False, result.get("msg", "删除记录失败")

    def update_record(self, app_token: str, table_id: str, record_id: str,
                      fields: dict):
        """更新单条记录。"""
        url = FEISHU_BITABLE_BASE + "/apps/" + app_token + "/tables/" + table_id \
              + "/records/" + record_id
        result = self._request("PUT", url, data={"fields": fields})
        if result.get("code") == 0:
            return True, result.get("data")
        return False, result.get("msg", "更新记录失败")

    def batch_update_records(self, app_token: str, table_id: str, records: list):
        """批量更新记录（records: [{record_id, fields}, ...]）。"""
        url = FEISHU_BITABLE_BASE + "/apps/" + app_token + "/tables/" + table_id \
              + "/records/batch_update"
        result = self._request("PATCH", url, data={"records": records})
        if result.get("code") == 0:
            return True, result.get("data")
        return False, result.get("msg", "批量更新记录失败")


# ---------------------------------------------------------------------------
# Jira 网页客户端（HTML 抓取，非 REST API）
# ---------------------------------------------------------------------------
class JiraHtmlClient:
    """Jira 网页客户端（通过 HTML 抓取获取数据）。"""

    def __init__(self, base_url: str, username: str, password: str):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.session = None          # 登录后的 opener（含 CookieJar）

    def login(self) -> bool:
        """登录 Jira，获取 session（经典表单登录 login.jsp）。

        登录成功判定：响应 HTML 中出现 "Log Out"/"log out"，
        或最终 URL 包含 "dashboard"。
        """
        import http.cookiejar

        cookie_jar = http.cookiejar.CookieJar()
        opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(cookie_jar))

        login_url = self.base_url + "/login.jsp"
        login_data = {
            "os_username": self.username,
            "os_password": self.password,
            "os_destination": "",
            "user_role": "",
            "atl_token": "",
            "login": "Log In",
        }
        data_encoded = urllib.parse.urlencode(login_data).encode("utf-8")
        req = urllib.request.Request(login_url, data=data_encoded, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            resp = opener.open(req, timeout=JIRA_TIMEOUT_LOGIN)
            resp_html = resp.read().decode("utf-8", errors="replace")
        except Exception as e:
            raise RuntimeError("Jira 登录请求失败: %s" % e)

        html_lower = resp_html.lower()
        final_url = resp.geturl().lower()
        if "Log Out" in resp_html or "log out" in html_lower or "dashboard" in final_url:
            self.session = opener
            return True
        inffffo="Jira 登录失败：响应中未检测到登录成功标志"+resp_html
        raise RuntimeError(inffffo)

    def fetch_filter_html(self, filter_url: str) -> str:
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
            page_url = base_url if start == 0 else \
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

    # -- HTML 解析 ---------------------------------------------------------
    @staticmethod
    def _clean_tag(text: str) -> str:
        """去除 HTML 标签并剥离空白。"""
        return re.sub(r"<[^>]+>", "", text).strip()

    def parse_html(self, html_content: str):
        """解析 Jira HTML：提取表头和数据行。返回 (headers, rows)。

        表头来自 <thead> 内 <th>；行来自 <tr class="issuerow"> 的 <td>；
        无 thead 时退化为首行 td；无 issuerow 时退化匹配全部 <tr>。
        """
        headers = []
        thead_pattern = re.compile(r"<thead[^>]*>(.*?)</thead>",
                                   re.DOTALL | re.IGNORECASE)
        thead_match = thead_pattern.search(html_content)
        thead_html = thead_match.group(1) if thead_match else ""

        th_pattern = re.compile(r"<th[^>]*>(.*?)</th>", re.DOTALL | re.IGNORECASE)
        ths = th_pattern.findall(thead_html)
        headers = [self._clean_tag(th) for th in ths]

        rows = []
        # 优先匹配 Jira 标准工单行 class="issuerow"
        row_pattern = re.compile(
            r'<tr[^>]*class="[^"]*issuerow[^"]*"[^>]*>(.*?)</tr>',
            re.DOTALL | re.IGNORECASE)
        row_matches = row_pattern.findall(html_content)
        if not row_matches:
            row_pattern = re.compile(r"<tr[^>]*>(.*?)</tr>",
                                     re.DOTALL | re.IGNORECASE)
            row_matches = row_pattern.findall(html_content)

        td_pattern = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL | re.IGNORECASE)
        for row_html in row_matches:
            tds = td_pattern.findall(row_html)
            if not tds:
                continue
            row_data = [self._clean_tag(td) for td in tds]
            if row_data:
                rows.append(row_data)

        # 表头兜底：无 <th> 时用首行 <td> 文本当表头
        if not headers and rows:
            headers = list(rows[0])
            rows = rows[1:]

        # HTML 实体反转义
        headers = [html_module.unescape(h) for h in headers]
        rows = [[html_module.unescape(c) for c in r] for r in rows]
        return headers, rows

    def parse_html_alternative(self, html_content: str):
        """备用解析方法：从 issuetable / class*="issue" 的表格中提取。"""
        headers = []
        rows = []

        # 定位表格：优先 id="issuetable"，其次 class 含 issue
        table_pattern = re.compile(r'<table[^>]*id="issuetable"[^>]*>(.*?)</table>',
                                   re.DOTALL | re.IGNORECASE)
        table_match = table_pattern.search(html_content)
        if not table_match:
            table_pattern = re.compile(
                r'<table[^>]*class="[^"]*issue[^"]*"[^>]*>(.*?)</table>',
                re.DOTALL | re.IGNORECASE)
            table_match = table_pattern.search(html_content)
        table_html = table_match.group(1) if table_match else ""

        thead_pattern = re.compile(r"<thead[^>]*>(.*?)</thead>",
                                   re.DOTALL | re.IGNORECASE)
        thead_match = thead_pattern.search(table_html)
        if thead_match:
            ths = re.compile(r"<th[^>]*>(.*?)</th>", re.DOTALL | re.IGNORECASE) \
                .findall(thead_match.group(1))
            headers = [self._clean_tag(th) for th in ths]

        row_pattern = re.compile(
            r'<tr[^>]*class="[^"]*issuerow[^"]*"[^>]*>(.*?)</tr>',
            re.DOTALL | re.IGNORECASE)
        row_matches = row_pattern.findall(table_html)
        td_pattern = re.compile(r"<td[^>]*>(.*?)</td>", re.DOTALL | re.IGNORECASE)
        for row_html in row_matches:
            tds = td_pattern.findall(row_html)
            row_data = [self._clean_tag(td) for td in tds]
            if row_data:
                rows.append(row_data)

        if not headers and rows:
            headers = list(rows[0])
            rows = rows[1:]
        headers = [html_module.unescape(h) for h in headers]
        rows = [[html_module.unescape(c) for c in r] for r in rows]
        return headers, rows


# ---------------------------------------------------------------------------
# 同步管理器
# ---------------------------------------------------------------------------
class SyncManager:
    """同步管理器：URL 解析、字段重建、清空、写入、增量对比。"""

    # -- URL 解析 ----------------------------------------------------------
    @staticmethod
    def parse_feishu_url(url: str):
        """解析飞书多维表格 URL，提取 app_token 和可选的 table_id。

        支持 /base/{token} 与 /wiki/{token} 两种形态；
        table_id 通过查询参数 ?table=xxx 传入。
        返回 (app_token, table_id)，无法解析时返回 (None, None)。
        """
        url = url.strip()
        pattern = re.compile(r"(?:/base/([^/?&#\s]+)|/wiki/([^/?&#\s]+))")
        match = pattern.search(url)
        if not match:
            return None, None
        app_token = match.group(1) or match.group(2)

        parsed = urlparse(url)
        query_params = parse_qs(parsed.query)
        table_id = query_params.get("table", [None])[0]
        return app_token, table_id

    @staticmethod
    def parse_jira_filter_url(url: str):
        """解析 Jira 筛选器 URL，提取 filter/requestId 数字 ID。"""
        match = re.search(r"[?&](?:filter|requestId)=(\d+)", url)
        return match.group(1) if match else None

    # -- 字段与记录 --------------------------------------------------------
    @staticmethod
    def rebuild_table_fields(feishu_client, app_token, table_id,
                             column_names, log_callback) -> bool:
        """重建表格字段，与 Jira 网页列名保持一致（全量重建，保证顺序）。

        策略：字段列表无变化 → 跳过；有变化 →
        主键字段改名 "Issue Key" → 删除其余全部字段 → 按 Jira 顺序重建（文本类型）。
        """
        log_callback("正在检查飞书表格字段...")
        success, result = feishu_client.list_fields(app_token, table_id)
        if not success:
            log_callback("获取现有字段失败: %s" % result)
            return False
        existing_fields = result

        # 现有字段名列表 + 主键字段
        existing_names = [f.get("field_name", "") for f in existing_fields]
        primary_field = next((f for f in existing_fields if f.get("is_primary")), None)
        target_names = list(column_names)

        # 字段无变化则跳过（顺序敏感）
        if existing_names == target_names:
            log_callback("字段无变化，跳过重建")
            return True

        log_callback("字段有变化，执行全量重建...")

        # 1) 主键字段改名为 "Issue Key"（主键不可删除，只能改名）
        if primary_field and target_names and target_names[0] == PRIMARY_FIELD_NAME \
                and primary_field.get("field_name") != PRIMARY_FIELD_NAME:
            ok, msg = feishu_client.rename_field(app_token, table_id,
                                                 primary_field.get("field_id"),
                                                 PRIMARY_FIELD_NAME)
            if not ok:
                log_callback("  重命名主键字段失败: %s" % msg)

        # 2) 删除其余全部字段
        delete_targets = [f for f in existing_fields if not f.get("is_primary")]
        log_callback("删除 %d 个现有字段..." % len(delete_targets))
        for field in delete_targets:
            field_id = field.get("field_id")
            ok, _ = feishu_client.delete_field(app_token, table_id, field_id)
            if not ok:
                log_callback("  删除字段失败: %s" % field_id)
            time.sleep(0.3)

        # 3) 按 Jira 顺序创建字段（主键已存在则跳过）
        need_create = [name for name in target_names
                       if not (name == PRIMARY_FIELD_NAME and primary_field)]
        log_callback("按Jira顺序创建 %d 个字段..." % len(need_create))
        for col_name in need_create:
            ok, msg = feishu_client.add_field(app_token, table_id, col_name, 1)
            if not ok:
                log_callback("  创建字段 '%s' 失败: %s" % (col_name, msg))
            time.sleep(0.3)

        log_callback("字段重建完成")
        return True

    @staticmethod
    def clear_all_records(feishu_client, app_token, table_id,
                          log_callback) -> bool:
        """清空表格中的所有记录（分批批量删除）。"""
        log_callback("正在清空现有记录...")
        success, result = feishu_client.get_all_records(app_token, table_id)
        if not success:
            log_callback("获取记录失败: %s" % result)
            return False
        records = result
        if not records:
            log_callback("表格为空，无需清理")
            return True

        record_ids = [r.get("record_id") for r in records if r.get("record_id")]
        for i in range(0, len(record_ids), BATCH_SIZE):
            batch = record_ids[i:i + BATCH_SIZE]
            ok, msg = feishu_client.batch_delete_records(app_token, table_id, batch)
            if not ok:
                log_callback("  批量删除失败: %s" % msg)
            time.sleep(0.5)
        log_callback("已删除 %d 条记录" % len(record_ids))
        return True

    @staticmethod
    def sync_incremental(feishu_client, app_token, table_id,
                         headers, rows, log_callback):
        """增量同步：以第一列（通常为 Issue Key）为主键对比差异。

        返回 (success, stats)。注意：当前 GUI 主流程未调用此方法，
        默认使用全量清空重写（clear_all_records + write_records）。
        """
        log_callback("开始增量同步...")
        success, result = feishu_client.get_all_records(app_token, table_id)
        if not success:
            log_callback("获取飞书记录失败: %s" % result)
            return False, None
        feishu_records = result

        key_col = headers[0] if headers else ""
        # 飞书侧：key -> record_id
        feishu_map = {}
        for record in feishu_records:
            fields = record.get("fields", {})
            key_value = str(fields.get(key_col, "")).strip()
            if key_value:
                feishu_map[key_value] = record.get("record_id")
        # Jira 侧：key -> 行数据
        jira_map = {}
        for row in rows:
            if not row:
                continue
            jira_map[str(row[0]).strip()] = row

        stats = {"to_create": [], "to_update": [], "to_delete": []}
        for key, row in jira_map.items():
            if key not in feishu_map:
                stats["to_create"].append(row)
            else:
                stats["to_update"].append((feishu_map[key], row))
        for key, record_id in feishu_map.items():
            if key not in jira_map:
                stats["to_delete"].append(record_id)

        log_callback("差异分析完成: 需新增 %d 条, 需更新 %d 条, 需删除 %d 条"
                     % (len(stats["to_create"]), len(stats["to_update"]),
                        len(stats["to_delete"])))

        # 新增
        if stats["to_create"]:
            log_callback("正在新增 %d 条记录..." % len(stats["to_create"]))
            for i in range(0, len(stats["to_create"]), BATCH_SIZE):
                batch = stats["to_create"][i:i + BATCH_SIZE]
                records = [{"fields": {headers[j]: row[j] for j in range(len(headers)) if j < len(row)}}
                           for row in batch]
                ok, msg = feishu_client.batch_create_records(app_token, table_id, records)
                if not ok:
                    log_callback("  批量创建失败: %s" % msg)
                time.sleep(0.5)

        # 更新
        if stats["to_update"]:
            log_callback("正在更新 %d 条记录..." % len(stats["to_update"]))
            for i in range(0, len(stats["to_update"]), BATCH_SIZE):
                batch = stats["to_update"][i:i + BATCH_SIZE]
                records = []
                for record_id, row in batch:
                    records.append({
                        "record_id": record_id,
                        "fields": {headers[j]: row[j] for j in range(len(headers)) if j < len(row)},
                    })
                ok, msg = feishu_client.batch_update_records(app_token, table_id, records)
                if not ok:
                    log_callback("  批量更新失败: %s" % msg)
                time.sleep(0.5)

        # 删除
        if stats["to_delete"]:
            log_callback("正在删除 %d 条记录..." % len(stats["to_delete"]))
            for i in range(0, len(stats["to_delete"]), BATCH_SIZE):
                batch = stats["to_delete"][i:i + BATCH_SIZE]
                ok, msg = feishu_client.batch_delete_records(app_token, table_id, batch)
                if not ok:
                    log_callback("  批量删除失败: %s" % msg)
                time.sleep(0.5)

        log_callback("增量同步完成！")
        return True, stats

    @staticmethod
    def write_records(feishu_client, app_token, table_id,
                      headers, rows, log_callback):
        """将数据写入飞书表格（全量，每批 500，批量失败逐条重试）。"""
        if not rows:
            log_callback("没有数据需要写入")
            return True

        log_callback("正在写入 %d 条记录..." % len(rows))
        total_success = 0
        for i in range(0, len(rows), BATCH_SIZE):
            batch = rows[i:i + BATCH_SIZE]
            records = []
            for row in batch:
                fields = {}
                for j, header in enumerate(headers):
                    if j < len(row):
                        fields[header] = row[j]
                records.append({"fields": fields})

            ok, msg = feishu_client.batch_create_records(app_token, table_id, records)
            if ok:
                total_success += len(records)
                continue
            log_callback("  批量创建失败(%d/%d)，尝试逐条创建... %s"
                         % (i + len(batch), len(rows), msg))
            for idx, record in enumerate(records):
                ok, msg = feishu_client.create_record(app_token, table_id, record["fields"])
                if ok:
                    total_success += 1
                else:
                    log_callback("  逐条创建失败(%d/%d): %s" % (i + idx + 1, len(rows), msg))

        log_callback("写入完成！成功: %d 条" % total_success)
        return True


# ---------------------------------------------------------------------------
# Tkinter 主应用
# ---------------------------------------------------------------------------
class JiraFeishuSyncApp:
    """主应用：GUI 配置 + 同步执行 + 定时任务。"""

    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Jira ↔ 飞书多维表格同步工具")
        self.root.geometry("700x650")
        self.root.resizable(True, False)

        # 配置（启动时加载，缺失则为空）
        self.config = ConfigManager.load()

        self.sync_thread = None       # 同步线程
        self.sync_running = False     # 定时同步开关
        self.next_sync_time = None    # 下次定时同步时间戳
        self.timer_thread = None      # 定时检查线程

        self._build_ui()
        self.root.after(1000, self._auto_start_sync)   # 启动 1s 后检查自动开始

    # -- UI ----------------------------------------------------------------
    def _build_ui(self):
        main_frame = ttk.Frame(self.root, padding=20)
        main_frame.pack(fill="both", expand=True)

        # 飞书配置
        feishu_frame = ttk.LabelFrame(main_frame, text="飞书多维表格配置", padding=10)
        feishu_frame.pack(fill="x", pady=5)

        ttk.Label(feishu_frame, text="多维表格地址:").grid(row=0, column=0,
                                                           sticky="w", pady=5)
        self.entry_feishu_url = ttk.Entry(feishu_frame, width=60)
        self.entry_feishu_url.grid(row=0, column=1, padx=5, pady=5)
        self.entry_feishu_url.insert(0, self.config.get("feishu_url", ""))

        ttk.Label(feishu_frame, text="App ID:").grid(row=1, column=0,
                                                     sticky="w", pady=5)
        self.entry_app_id = ttk.Entry(feishu_frame, width=60)
        self.entry_app_id.grid(row=1, column=1, padx=5, pady=5)
        self.entry_app_id.insert(0, self.config.get("app_id", ""))

        ttk.Label(feishu_frame, text="App Secret:").grid(row=2, column=0,
                                                         sticky="w", pady=5)
        self.entry_app_secret = ttk.Entry(feishu_frame, width=60, show="*")
        self.entry_app_secret.grid(row=2, column=1, padx=5, pady=5)
        self.entry_app_secret.insert(0, self.config.get("app_secret", ""))

        # Jira 配置
        jira_frame = ttk.LabelFrame(main_frame, text="Jira 配置", padding=10)
        jira_frame.pack(fill="x", pady=5)

        ttk.Label(jira_frame, text="筛选器地址:").grid(row=0, column=0,
                                                       sticky="w", pady=5)
        self.entry_jira_filter = ttk.Entry(jira_frame, width=60)
        self.entry_jira_filter.grid(row=0, column=1, padx=5, pady=5)
        self.entry_jira_filter.insert(0, self.config.get("jira_filter_url", ""))

        ttk.Label(jira_frame, text="用户名:").grid(row=1, column=0,
                                                   sticky="w", pady=5)
        self.entry_jira_user = ttk.Entry(jira_frame, width=60)
        self.entry_jira_user.grid(row=1, column=1, padx=5, pady=5)
        self.entry_jira_user.insert(0, self.config.get("jira_username", ""))

        ttk.Label(jira_frame, text="密码:").grid(row=2, column=0,
                                                 sticky="w", pady=5)
        self.entry_jira_pass = ttk.Entry(jira_frame, width=60, show="*")
        self.entry_jira_pass.grid(row=2, column=1, padx=5, pady=5)
        self.entry_jira_pass.insert(0, self.config.get("jira_password", ""))

        # 按钮区
        btn_frame = ttk.Frame(main_frame)
        btn_frame.pack(fill="x", pady=10)
        self.btn_sync_once = ttk.Button(btn_frame, text="立即同步",
                                        command=self._sync_once)
        self.btn_sync_once.pack(side="left", padx=5)
        self.btn_auto_sync = ttk.Button(btn_frame, text="开始定时同步",
                                        command=self._toggle_auto_sync)
        self.btn_auto_sync.pack(side="left", padx=5)
        ttk.Button(btn_frame, text="保存配置", command=self._save_config) \
            .pack(side="left", padx=5)

        # 状态栏
        status_frame = ttk.Frame(main_frame)
        status_frame.pack(fill="x", pady=5)
        self.lbl_status = ttk.Label(status_frame, text="就绪", foreground="gray")
        self.lbl_status.pack(side="left")
        self.lbl_next_sync = ttk.Label(status_frame, text="")
        self.lbl_next_sync.pack(side="right")

        # 日志区
        log_frame = ttk.LabelFrame(main_frame, text="同步日志", padding=5)
        log_frame.pack(fill="both", expand=True)
        self.txt_log = tk.Text(log_frame, height=12, wrap="word", state="disabled")
        self.txt_log.pack(side="left", fill="both", expand=True)
        scrollbar = ttk.Scrollbar(log_frame, orient="vertical",
                                  command=self.txt_log.yview)
        scrollbar.pack(side="right", fill="y")
        self.txt_log.config(yscrollcommand=scrollbar.set)

    # -- 日志 / 配置 -------------------------------------------------------
    def _log(self, message: str):
        """向日志区追加一行（线程安全：通过 after 回到主线程写入）。"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_message = "[%s] %s\n" % (timestamp, message)

        def _append(m):
            self.txt_log.config(state="normal")
            self.txt_log.insert("end", m)
            self.txt_log.see("end")
            self.txt_log.config(state="disabled")

        # 若已在主线程直接写，否则排入主线程
        try:
            if self.root.winfo_exists():
                self.root.after(0, _append, log_message)
        except Exception:
            pass

    def _get_config_values(self) -> dict:
        """读取界面输入框当前值。"""
        return {
            "feishu_url": self.entry_feishu_url.get().strip(),
            "app_id": self.entry_app_id.get().strip(),
            "app_secret": self.entry_app_secret.get().strip(),
            "jira_filter_url": self.entry_jira_filter.get().strip(),
            "jira_username": self.entry_jira_user.get().strip(),
            "jira_password": self.entry_jira_pass.get().strip(),
        }

    def _save_config(self):
        """保存配置到磁盘。"""
        self.config = self._get_config_values()
        ConfigManager.save(self.config)
        messagebox.showinfo("配置已保存", "配置已成功保存！")

    # -- 同步 --------------------------------------------------------------
    def _sync_once(self):
        """执行一次同步（校验必填后在线程中运行）。"""
        config = self._get_config_values()
        required = ["feishu_url", "app_id", "app_secret",
                    "jira_filter_url", "jira_username", "jira_password"]
        if not all(config.get(k) for k in required):
            messagebox.showerror("错误", "请填写所有必填项！")
            return
        self.config = config
        self.sync_thread = threading.Thread(target=self._do_sync,
                                            args=(config,), daemon=True)
        self.sync_thread.start()

    def _do_sync(self, config: dict):
        """执行同步的核心逻辑（在工作线程中运行，UI 操作经 after 回主线程）。"""

        def set_status(text, color):
            def _apply():
                self.lbl_status.config(text=text, foreground=color)
            self.root.after(0, _apply)

        def log(msg):
            self._log(msg)

        try:
            # 0) 界面状态：禁用按钮 + 同步中
            self.root.after(0, lambda: self.btn_sync_once.config(state="disabled"))
            log("==================================================")
            log("开始同步...")
            set_status("同步中...", "orange")

            # 1) 解析飞书地址
            log("输入的飞书地址: " + config.get("feishu_url", ""))
            app_token, table_id = SyncManager.parse_feishu_url(config["feishu_url"])
            if not app_token:
                log("错误: 无法解析飞书多维表格地址")
                set_status("同步失败", "red")
                return
            log("飞书 App Token: " + app_token)

            # 2) 解析 Jira 筛选器
            filter_id = SyncManager.parse_jira_filter_url(config["jira_filter_url"])
            if not filter_id:
                log("错误: 无法解析Jira筛选器地址")
                set_status("同步失败", "red")
                return
            log("Jira Filter ID: " + filter_id)

            # 3) 飞书认证
            feishu_client = FeishuBitableClient(config["app_id"], config["app_secret"])
            ok, err = feishu_client.get_access_token()
            if not ok:
                log("飞书认证失败: %s" % (err or ""))
                set_status("同步失败", "red")
                return
            log("飞书认证成功")

            # 4) 定位 / 创建数据表 "jira-tickets"
            ok, tables = feishu_client.list_tables(app_token)
            if not ok:
                log("获取表格列表失败: %s" % (tables or ""))
                set_status("同步失败", "red")
                return
            jira_table = next((t for t in tables
                               if t.get("name") == JIRA_TABLE_NAME), None)
            if not jira_table:
                log('数据表 "jira-tickets" 不存在，正在创建...')
                ok, table = feishu_client.create_table(
                    app_token, JIRA_TABLE_NAME, JIRA_TABLE_DESC)
                if not ok:
                    log("创建表格失败: %s" % (table or ""))
                    set_status("同步失败", "red")
                    return
                jira_table = table
                log('已创建数据表 "jira-tickets" (ID: %s)' % jira_table.get("table_id"))
            else:
                log('找到数据表 "jira-tickets" (ID: %s)' % jira_table.get("table_id"))
            table_id = jira_table.get("table_id")

            # 5) Jira 登录 + 抓取
            log("正在连接Jira...")
            # 如需更换 Jira 地址，请在模块常量 JIRA_DEFAULT_BASE_URL 修改，
            # 或在 config 中增加 "jira_base_url" 键（下句已支持）：
            base_url = config.get("jira_base_url", JIRA_DEFAULT_BASE_URL)
            jira_client = JiraHtmlClient(base_url,
                                         config["jira_username"],
                                         config["jira_password"])
            log("正在登录Jira...")
            try:
                jira_client.login()
            except Exception as e:
                log("Jira登录失败: %s" % e)
                set_status("同步失败", "red")
                return
            log("Jira登录成功")

            log("正在下载筛选器页面（自动翻页）...")
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

            # 7) 重建字段 + 清空 + 写入
            log("正在检查并重建飞书表格字段...")
            if not SyncManager.rebuild_table_fields(
                    feishu_client, app_token, table_id, headers, log):
                log("重建表格字段失败")
                set_status("同步失败", "red")
                return
            if not SyncManager.clear_all_records(
                    feishu_client, app_token, table_id, log):
                log("清空记录失败")
                set_status("同步失败", "red")
                return
            if not SyncManager.write_records(
                    feishu_client, app_token, table_id, headers, rows, log):
                log("写入记录失败")
                set_status("同步失败", "red")
                return

            log("总计: %d 行数据, %d 列" % (len(rows), len(headers)))
            log("同步完成")
            set_status("同步完成", "green")

        except Exception as e:
            log("同步异常: %s\n%s" % (e, traceback.format_exc()))
            set_status("同步异常", "red")
        finally:
            self.root.after(0, lambda: self.btn_sync_once.config(state="normal"))

    # -- 定时同步 ----------------------------------------------------------
    def _auto_start_sync(self):
        """启动时若配置完整，自动开始定时同步。"""
        required = ["feishu_url", "app_id", "app_secret",
                    "jira_filter_url", "jira_username", "jira_password"]
        if all(self.config.get(k) for k in required):
            self._log("配置已加载，自动启动定时同步...")
            self._toggle_auto_sync()
        else:
            self._log("配置不完整，请填写所有配置项后手动启动定时同步")

    def _toggle_auto_sync(self):
        """切换定时同步状态。"""
        if self.sync_running:
            self.sync_running = False
            self.btn_auto_sync.config(text="开始定时同步")
            self.lbl_status.config(text="已停止", foreground="gray")
            self._log("定时同步已停止")
        else:
            self.sync_running = True
            self.next_sync_time = time.time() + SYNC_INTERVAL_MINUTES * 60
            self.btn_auto_sync.config(text="停止定时同步")
            self.lbl_status.config(text="定时同步中", foreground="blue")
            self._log("定时同步已启动，每 %d 分钟同步一次" % SYNC_INTERVAL_MINUTES)
            self._start_timer()

    def _start_timer(self):
        """启动定时检查线程：每 60s 检查是否到达下次同步时间。"""
        def timer_loop():
            i = 0
            while self.sync_running:
                time.sleep(60)
                if not self.sync_running:
                    break
                i += 1
                if i >= SYNC_INTERVAL_MINUTES:
                    i = 0
                    config = self._get_config_values()
                    required = ["feishu_url", "app_id", "app_secret",
                                "jira_filter_url", "jira_username", "jira_password"]
                    if all(config.get(k) for k in required):
                        self._sync_once()

        self.timer_thread = threading.Thread(target=timer_loop, daemon=True)
        self.timer_thread.start()

    # -- 启动 --------------------------------------------------------------
    def run(self):
        self.root.mainloop()


if __name__ == "__main__":
    app = JiraFeishuSyncApp()
    app.run()
