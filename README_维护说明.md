# jira_feishu_sync 维护说明（可维护版源码）

## 文件清单

| 文件 | 说明 |
|---|---|
| `jira_feishu_sync.py` | **可维护版源码**（还原自原 exe，可直接运行/重新打包） |
| `test_logic.py` | 纯逻辑单元验证（URL 解析、HTML 解析、常量） |
| `test_integration.py` | 集成模拟验证（字段重建、写入、增量、清空，用 mock 客户端，不触网） |
| `test_pagination.py` | 翻页专项验证（多页合并、单页、整页边界、URL 分隔符、未登录异常） |
| `jira_detail_export_demo.py` | **详情+改动记录导出 Demo**（本地 Excel，不落飞书） |
| `test_demo.py` | Demo 专项验证（改动记录解析、首个 KEY 先全部后改动记录、Excel 写入） |
| `dist\JiraDetailExport.exe` | Demo 打包产物（PyInstaller onefile windowed） |

## 运行方式

```bash
# 直接运行（需 Python 3.8+，仅标准库，无需 pip install）
python jira_feishu_sync.py

# 重新打包成与原版一致的 exe
pyinstaller --onefile --windowed jira_feishu_sync.py
```

## 还原与原版的一致性（已逐项核对）

- Jira 地址硬编码默认 `http://jira.z-onesoftware.com:8080`（模块常量 `JIRA_DEFAULT_BASE_URL`，支持通过 config 的 `jira_base_url` 覆盖）
- Jira 认证：`POST {base}/login.jsp` 表单 `os_username/os_password/os_destination/user_role/atl_token/login`，CookieJar 会话，`Log Out`/`dashboard` 判定
- 飞书认证：`tenant_access_token`（app_id+app_secret）；API base `https://open.feishu.cn/open-apis/bitable/v1`
- 数据表：硬编码 `jira-tickets`（描述 `Jira Tickets同步`），缺失自动创建
- 字段：全量重建（有变化才删光重建，文本类型 type=1，Issue Key 主键）
- 记录：全量清空重写，每批 500，批量失败逐条重试
- 定时：`SYNC_INTERVAL_MINUTES=5` 分钟
- 配置：`jira_feishu_sync_config.json`（exe/脚本同目录，明文）

## 已做的维护性改进（不改变原行为）

1. 全部魔法值收敛为模块顶部常量，改一处即可全局生效
2. 飞书 API 统一返回 `(success, result_or_msg)` 元组，错误可追溯
3. 补充中文注释、docstring、类型标注
4. Jira 登录/抓取异常转为带上下文的 RuntimeError，日志可读
5. `jira_base_url` 支持从配置读取（默认值仍是原硬编码地址）

## 测试验证结果

- `test_logic.py`：7 项全过（parse_feishu_url / parse_jira_filter_url / parse_html / parse_html_alternative / td 兜底 / _get_base_dir / 常量核对）
- `test_integration.py`：5 项全过（字段重建-有变化 / 无变化跳过 / 写入分批 / 增量差异 / 清空分批 500/500/200）
- `test_pagination.py`：5 项全过（3 页合并 120 行 / 单页 1 请求 / 整页边界停止 / URL 无参分隔符 / 未登录抛错）
- 网络侧（Jira 登录、飞书 API）未实测：需真实环境凭据，按原版接口行为还原

## 翻页抓取说明（v2 新增）

- `JiraHtmlClient.fetch_filter_all_pages()`：自动按 `pager/start` 翻页抓取筛选器全部页数据，表头取第一页，数据行逐页合并
- 停止条件：某页行数不足一页（默认 50）或解析不到数据；`JIRA_MAX_PAGES=200` 兜底防死循环
- 与单页逻辑完全兼容：数据不足一页时只请求一次，行为与旧版一致
- `_do_sync` 已切换到翻页抓取；如需改回单页，把调用改回 `fetch_filter_html + parse_html` 即可
- 翻页参数按 Jira 老版网页列表标准 `pager/start` 实现；若贵司 Jira 版本使用不同参数（如 `start` / `pager/limit`），只需修改 `fetch_filter_all_pages` 内拼接逻辑

## 详情+改动记录导出 Demo（v3 新增，独立于主程序）

**用途**：GUI 输入保持 filter 页面 URL 不变；对 filter 下所有 KEY 抓取内部信息（原列表列 + 改动记录），在**用户指定文件夹**保存 Excel（每行一个 KEY，改动记录整体放一个单元格），不落飞书。每次运行执行一次；首个 KEY 先请求「全部」再请求「改动记录」（Jira 用 Cookie 持久化 tab 选择）；输出目录同时保存错误日志。

**运行/打包**：
```bash
python jira_detail_export_demo.py
pyinstaller --onefile --windowed --name JiraDetailExport jira_detail_export_demo.py
```

**结构**：`DemoJiraClient(JiraHtmlClient)` 子类扩展（不动原文件）——`fetch_activity_tab()` 复刻 HAR 中 `GET /browse/{KEY}?page={tab}&_={ts}` 请求；`parse_changehistory()`/`parse_all_activity()` 解析 issue-data-block（时间/操作人/域·原值·新值）。

**已知边界**：
- 改动记录「域/原值/新值」按 wiki 表格行解析；HAR 实测字段名（域/Field/字段）均兼容
- 「全部」流中的注释/工作日志目前只统计数量不展开（改动记录完整展开）
- 详情页字段未单独抓取，Excel 的"原信息"= filter 列表已有列；如需详情页全部字段可后续加 `fetch_issue_detail()`

## 接手注意事项

- 原 exe 每次同步**先清空飞书表再写入**，数据量大时有空窗；如需改为纯增量，可把 `_do_sync` 中的 `clear_all_records + write_records` 替换为 `sync_incremental`（该方法已实现并通过差异测试）
- Jira 为 HTTP 明文 + 老式表单登录，若 Jira 升级 SSO 需改造登录逻辑
- 配置明文存密钥，注意文件权限与备份
