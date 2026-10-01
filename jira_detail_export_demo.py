# -*- coding: utf-8 -*-
"""
Jira 详情+改动记录 导出 Demo（本地 EXCEL，不落飞书）
=====================================================
需求：
  1. GUI 输入保持为 filter 页面 URL 不变
  2. 对 filter 下所有 KEY 抓取内部信息（原列表列 + 详情 + 改动记录）
  3. 在用户指定文件夹保存 Excel：每行一个 KEY，改动记录整体放一个单元格
  4. 每次运行执行一次（无定时）；Cookie 持久化 tab 选择，
     开始记录时对第一个 KEY 先请求「全部」再请求「改动记录」
  5. 输出目录同时保存错误日志
  6. 打包为 exe（不修改原重建代码 jira_feishu_sync.py）

运行:  python jira_detail_export_demo.py
打包:  pyinstaller --onefile --windowed --name JiraDetailExport jira_detail_export_demo.py
"""

import os
import re
import sys
import json
import time
import html as html_module
import threading
import traceback
from datetime import datetime

import tkinter as tk
from tkinter import ttk, messagebox, filedialog

# 复用原重建代码的客户端与常量（不修改原文件）
from jira_feishu_sync import JiraHtmlClient, ConfigManager, JIRA_DEFAULT_BASE_URL


# ---------------------------------------------------------------------------
# 扩展客户端：详情 + 活动日志（改动记录 / 全部）
# ---------------------------------------------------------------------------
class DemoJiraClient(JiraHtmlClient):
    """在原 JiraHtmlClient 基础上增加详情与活动日志抓取。"""

    # Jira 活动日志 tab 的页面 key（与 HAR 实测一致）
    TAB_CHANGEHISTORY = "com.atlassian.jira.plugin.system.issuetabpanels:changehistory-tabpanel"
    TAB_ALL = "com.atlassian.jira.plugin.system.issuetabpanels:all-tabpanel"

    def fetch_activity_tab(self, issue_key: str, tab_key: str) -> str:
        """按 HAR 复刻 tab 切换请求：GET /browse/{KEY}?page={tab}&_={ts}。

        issue_key: 例如 BSUVVW-30904
        tab_key:   self.TAB_ALL / self.TAB_CHANGEHISTORY
        返回该 tab 的 HTML 片段。
        """
        url = self.base_url + "/browse/" + issue_key + \
              "?page=" + tab_key + "&_=" + str(int(time.time() * 1000))
        return self._fetch(url)

    # -- 解析 --------------------------------------------------------------
    @staticmethod
    def _extract_author(block_html: str) -> str:
        """提取 changehistory 块中的操作人（user-hover 链接文本）。"""
        m = re.search(r'<a[^>]*class="user-hover[^"]*"[^>]*>(.*?)</a>',
                      block_html, re.DOTALL | re.IGNORECASE)
        if m:
            return re.sub(r"<[^>]+>", "", m.group(1)).strip()
        m2 = re.search(r'class="[^"]*user-avatar[^"]*"[^>]*>(.*?)</a>',
                       block_html, re.DOTALL | re.IGNORECASE)
        return re.sub(r"<[^>]+>", "", m2.group(1)).strip() if m2 else ""

    @staticmethod
    def _extract_time(block_html: str) -> str:
        """提取活动时间：优先 livestamp datetime（单/双引号），其次 title。"""
        m = re.search(r'<time[^>]*datetime=["\']([^"\']+)["\'][^>]*>',
                      block_html, re.IGNORECASE)
        if m:
            return m.group(1)
        m2 = re.search(r"<span[^>]*class='date'[^>]*title='([^']*)'",
                       block_html, re.IGNORECASE)
        if m2:
            return m2.group(1)
        m3 = re.search(r'<span[^>]*class="date"[^>]*title="([^"]*)"',
                       block_html, re.IGNORECASE)
        return m3.group(1) if m3 else ""

    @staticmethod
    def _extract_change_table(block_html: str) -> str:
        """提取变更明细（域/原值/新值）为多行文本。

        在 issue-data-block 内查找 changehistory action-body，
        其内容是 wiki 表格转出的 HTML table；逐行抽取文本。
        返回形如：
            域: 原值 → 新值
        """
        m = re.search(r'<div[^>]*class="changehistory[^"]*action-body[^"]*"[^>]*>(.*?)</div>',
                      block_html, re.DOTALL | re.IGNORECASE)
        if not m:
            # 兜底：捕获整个 block 内最后一个 table
            m = re.search(r"<table[^>]*>(.*?)</table>",
                          block_html, re.DOTALL | re.IGNORECASE)
        table_html = m.group(1) if m else ""

        # 逐行解析 <tr>：第一行表头（域/原值/新值），后续行数据
        tr_pattern = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
        lines = []
        for tr_html in tr_pattern.findall(table_html):
            tds = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr_html,
                             re.DOTALL | re.IGNORECASE)
            cells = [re.sub(r"<[^>]+>", "", c).strip() for c in tds]
            cells = [html_module.unescape(c) for c in cells]
            if len(cells) >= 3 and cells[0] in ("域", "Field", "字段"):
                continue          # 跳过表头行
            if cells:
                lines.append(" | ".join(cells))
        return "\n".join(lines)

    def parse_changehistory(self, html_content: str) -> list:
        """解析「改动记录」tab HTML，返回活动列表。

        每条活动: {"time": str, "author": str, "changes": str}
        """
        # 每个 issue-data-block 一条活动（创建记录 id 为 issuecreated-*，跳过）
        block_pattern = re.compile(
            r'<div[^>]*class="issue-data-block"[^>]*id="(changehistory-\d+)"[^>]*>(.*?)</div>\s*</div>\s*</div>',
            re.DOTALL | re.IGNORECASE)
        activities = []
        for block_id, block_html in block_pattern.findall(html_content):
            author = self._extract_author(block_html)
            act_time = self._extract_time(block_html)
            changes = self._extract_change_table(block_html)
            if not author and not changes:
                continue
            activities.append({
                "id": block_id,
                "time": act_time,
                "author": author,
                "changes": changes,
            })
        return activities

    def parse_all_activity(self, html_content: str) -> list:
        """解析「全部」tab HTML。

        「全部」为 注释 + 改动记录 + 工作日志 混合流。本 demo 只要求
        改动记录入 Excel，因此从混合流中过滤 changehistory 块即可；
        注释/工作日志暂记为一行摘要（保留结构，便于后续扩展）。
        """
        activities = self.parse_changehistory(html_content)
        # 额外识别注释/工作日志块数量（仅用于日志统计，不展开）
        comment_n = len(re.findall(r'id="comment-\d+"', html_content))
        worklog_n = len(re.findall(r'id="worklog-\d+"', html_content))
        return activities, comment_n, worklog_n


# ---------------------------------------------------------------------------
# Excel 导出（openpyxl）
# ---------------------------------------------------------------------------
def write_excel(path: str, headers: list, rows: list) -> None:
    """把 (headers, rows) 写为 Excel；最后一列若为改动记录则自动换行。"""
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Jira数据"

    # 表头
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="4472C4")
    for col_idx, h in enumerate(headers, start=1):
        cell = ws.cell(row=1, column=col_idx, value=h)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(vertical="center")

    # 数据
    for r_idx, row in enumerate(rows, start=2):
        for c_idx, val in enumerate(row, start=1):
            cell = ws.cell(row=r_idx, column=c_idx,
                           value=None if val is None else str(val))
            cell.alignment = Alignment(vertical="top", wrap_text=True)

    # 列宽：改动记录列（最后一列）加宽，其余自适应
    for col_idx in range(1, len(headers) + 1):
        letter = get_column_letter(col_idx)
        if col_idx == len(headers):
            ws.column_dimensions[letter].width = 80
        else:
            ws.column_dimensions[letter].width = 20

    # 冻结表头
    ws.freeze_panes = "A2"
    wb.save(path)


# ---------------------------------------------------------------------------
# 应用 GUI
# ---------------------------------------------------------------------------
class DetailExportApp:
    """Jira 详情+改动记录 导出 Demo 主窗口。"""

    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("Jira 详情 + 改动记录导出（Demo）")
        self.root.geometry("720x560")

        self.config = ConfigManager.load()
        self.sync_running = False

        self._build_ui()
        self._load_config_into_ui()

    # -- UI ----------------------------------------------------------------
    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        frm = ttk.Frame(self.root)
        frm.pack(fill="both", expand=True, padx=12, pady=12)

        # Jira 基本信息
        ttk.Label(frm, text="Jira 筛选器页面 URL（与原来一致）").grid(
            row=0, column=0, sticky="w", **pad)
        self.var_filter_url = tk.StringVar()
        ttk.Entry(frm, textvariable=self.var_filter_url, width=70).grid(
            row=0, column=1, columnspan=3, sticky="we", **pad)

        ttk.Label(frm, text="Jira 地址（默认原硬编码地址）").grid(
            row=1, column=0, sticky="w", **pad)
        self.var_jira_base = tk.StringVar(value=JIRA_DEFAULT_BASE_URL)
        ttk.Entry(frm, textvariable=self.var_jira_base, width=70).grid(
            row=1, column=1, columnspan=3, sticky="we", **pad)

        ttk.Label(frm, text="Jira 用户名").grid(row=2, column=0, sticky="w", **pad)
        self.var_username = tk.StringVar()
        ttk.Entry(frm, textvariable=self.var_username, width=40).grid(
            row=2, column=1, sticky="w", **pad)

        ttk.Label(frm, text="Jira 密码").grid(row=3, column=0, sticky="w", **pad)
        self.var_password = tk.StringVar()
        ttk.Entry(frm, textvariable=self.var_password, width=40,
                  show="*").grid(row=3, column=1, sticky="w", **pad)

        # 输出文件夹
        ttk.Label(frm, text="保存目录（Excel 与错误日志）").grid(
            row=4, column=0, sticky="w", **pad)
        self.var_outdir = tk.StringVar()
        ttk.Entry(frm, textvariable=self.var_outdir, width=52).grid(
            row=4, column=1, sticky="we", **pad)
        ttk.Button(frm, text="选择文件夹…",
                   command=self._choose_dir).grid(row=4, column=2, **pad)

        # 按钮行
        self.btn_start = ttk.Button(frm, text="开始导出", command=self._on_start)
        self.btn_start.grid(row=5, column=1, sticky="w", **pad)

        # 日志区
        ttk.Label(frm, text="运行日志").grid(row=6, column=0, sticky="nw", **pad)
        self.txt_log = tk.Text(frm, height=18, width=82, state="disabled")
        self.txt_log.grid(row=6, column=1, columnspan=3, sticky="we", **pad)
        sb = ttk.Scrollbar(frm, command=self.txt_log.yview)
        sb.grid(row=6, column=4, sticky="ns")
        self.txt_log.configure(yscrollcommand=sb.set)

        frm.columnconfigure(1, weight=1)

    def _choose_dir(self):
        d = filedialog.askdirectory(title="选择保存目录")
        if d:
            self.var_outdir.set(d)

    # -- 配置 ---------------------------------------------------------------
    def _load_config_into_ui(self):
        cfg = self.config
        if cfg.get("jira_filter_url"):
            self.var_filter_url.set(cfg["jira_filter_url"])
        if cfg.get("jira_username"):
            self.var_username.set(cfg["jira_username"])
        if cfg.get("jira_password"):
            self.var_password.set(cfg["jira_password"])
        if cfg.get("jira_base_url"):
            self.var_jira_base.set(cfg["jira_base_url"])

    def _save_config(self, cfg: dict):
        cfg = dict(self.config)
        cfg.update({k: v for k, v in cfg.items() if v})
        try:
            ConfigManager.save(cfg)
        except Exception:
            pass

    # -- 日志 ---------------------------------------------------------------
    def _log(self, msg: str):
        def _append():
            self.txt_log.configure(state="normal")
            self.txt_log.insert("end", msg + "\n")
            self.txt_log.see("end")
            self.txt_log.configure(state="disabled")
        self.root.after(0, _append)

    # -- 主流程 -------------------------------------------------------------
    def _on_start(self):
        if self.sync_running:
            return
        filter_url = self.var_filter_url.get().strip()
        username = self.var_username.get().strip()
        password = self.var_password.get()
        base_url = self.var_jira_base.get().strip() or JIRA_DEFAULT_BASE_URL
        out_dir = self.var_outdir.get().strip()

        if not filter_url or not username or not password:
            messagebox.showwarning("提示", "请填写筛选器 URL、用户名和密码")
            return
        if not out_dir:
            messagebox.showwarning("提示", "请选择保存目录")
            return
        if not os.path.isdir(out_dir):
            try:
                os.makedirs(out_dir)
            except Exception as e:
                messagebox.showerror("错误", "无法创建保存目录: %s" % e)
                return

        # 保存配置
        self.config.update({
            "jira_filter_url": filter_url,
            "jira_username": username,
            "jira_password": password,
            "jira_base_url": base_url,
        })
        ConfigManager.save(self.config)

        self.sync_running = True
        self.btn_start.config(state="disabled")
        threading.Thread(target=self._run_once, args=(base_url, username,
                                                      password, filter_url,
                                                      out_dir), daemon=True).start()

    def _run_once(self, base_url, username, password, filter_url, out_dir):
        """每次运行执行一次：登录 → 抓列表 → 逐 KEY 抓改动记录 → 写 Excel + 错误日志。"""
        error_log_path = os.path.join(
            out_dir, "error_log_%s.txt" % datetime.now().strftime("%Y%m%d_%H%M%S"))
        error_lines = []
        client = DemoJiraClient(base_url, username, password)

        try:
            self._log("1/5 登录 Jira...")
            client.login()
            self._log("  登录成功")
        except Exception as e:
            msg = "登录失败: %s" % e
            self._log(msg)
            error_lines.append("[登录] " + traceback.format_exc())
            self._finish(error_log_path, error_lines, None)
            return

        headers = rows = None
        try:
            self._log("2/5 抓取筛选器列表（自动翻页）...")
            headers, rows = client.fetch_filter_all_pages(
                filter_url, log_callback=self._log)
            if not headers or not rows:
                raise RuntimeError("筛选器页面未解析出数据")
            self._log("  列表 %d 列 / %d 行" % (len(headers), len(rows)))
        except Exception as e:
            msg = "列表抓取失败: %s" % e
            self._log(msg)
            error_lines.append("[列表] " + traceback.format_exc())
            self._finish(error_log_path, error_lines, None)
            return

        # 定位 KEY 列（列表首列一般为 Issue Key / 关键字）
        key_col = 0
        for i, h in enumerate(headers):
            if h in ("Issue Key", "关键字", "Key", "KEY"):
                key_col = i
                break
        keys = [row[key_col] for row in rows if row[key_col].strip()]

        self._log("3/5 共 %d 个 KEY，开始抓取改动记录..." % len(keys))
        new_headers = list(headers) + ["改动记录"]
        new_rows = []

        for idx, key in enumerate(keys):
            try:
                # —— 第一个 KEY：先请求「全部」再请求「改动记录」——
                # （Jira 用 Cookie 持久化 tab 选择；先全部后改动记录确保
                #   本次运行后续请求落在「改动记录」状态）
                if idx == 0:
                    self._log("  首个 KEY %s：先请求「全部」..." % key)
                    all_html = client.fetch_activity_tab(key, DemoJiraClient.TAB_ALL)
                    acts_all, n_c, n_w = client.parse_all_activity(all_html)
                    self._log("    全部流：改动记录 %d 条，注释 %d 条，工作日志 %d 条"
                              % (len(acts_all), n_c, n_w))
                    self._log("  再请求「改动记录」...")
                    ch_html = client.fetch_activity_tab(
                        key, DemoJiraClient.TAB_CHANGEHISTORY)
                    activities = client.parse_changehistory(ch_html)
                else:
                    ch_html = client.fetch_activity_tab(
                        key, DemoJiraClient.TAB_CHANGEHISTORY)
                    activities = client.parse_changehistory(ch_html)

                # 组装改动记录单元格（多行文本）
                if activities:
                    parts = []
                    for act in activities:
                        head = "[%s] %s" % (act["time"], act["author"])
                        if act["changes"]:
                            head += "\n" + act["changes"]
                        parts.append(head)
                    cell_text = "\n\n".join(parts)
                else:
                    cell_text = "（无改动记录）"

                row_out = list(rows[idx]) + [cell_text]
                new_rows.append(row_out)
                self._log("  [%d/%d] %s 改动记录 %d 条"
                          % (idx + 1, len(keys), key, len(activities)))
            except Exception as e:
                self._log("  [%d/%d] %s 抓取失败: %s" % (idx + 1, len(keys), key, e))
                error_lines.append("[%s] %s\n%s"
                                   % (key, e, traceback.format_exc()))
                row_out = list(rows[idx]) + ["（抓取失败）"]
                new_rows.append(row_out)

        # 写 Excel
        xlsx_path = os.path.join(
            out_dir, "jira_detail_export_%s.xlsx"
            % datetime.now().strftime("%Y%m%d_%H%M%S"))
        try:
            self._log("4/5 写入 Excel...")
            write_excel(xlsx_path, new_headers, new_rows)
            self._log("  已保存: %s" % xlsx_path)
        except Exception as e:
            msg = "Excel 写入失败: %s" % e
            self._log(msg)
            error_lines.append("[Excel] " + traceback.format_exc())
            self._finish(error_log_path, error_lines, None)
            return

        self._finish(error_log_path, error_lines, xlsx_path)

    def _finish(self, error_log_path, error_lines, xlsx_path):
        if error_lines:
            try:
                with open(error_log_path, "w", encoding="utf-8") as f:
                    f.write("运行时间: %s\n" % datetime.now().isoformat())
                    f.write("错误 %d 条:\n%s\n"
                            % (len(error_lines), "\n---\n".join(error_lines)))
                self._log("5/5 错误日志已保存: %s（%d 条错误）"
                          % (error_log_path, len(error_lines)))
            except Exception as e:
                self._log("错误日志写入失败: %s" % e)
        else:
            self._log("5/5 无错误，全部完成")

        def _done():
            self.sync_running = False
            self.btn_start.config(state="normal")
            if xlsx_path and os.path.exists(xlsx_path):
                messagebox.showinfo("完成", "导出完成：\n%s" % xlsx_path)
        self.root.after(0, _done)


def main():
    root = tk.Tk()
    DetailExportApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
