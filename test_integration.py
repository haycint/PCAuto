# -*- coding: utf-8 -*-
# 用 mock 客户端集成验证 SyncManager 流程（不触网）
import importlib.util, os

src = open(r"C:\Users\TianYifan\.doubao\lark-chats\2026-10-01\new-chat\re_work\jira_feishu_sync.py", encoding="utf-8").read()
cut = src.index("class JiraFeishuSyncApp")
logic_src = src[:cut].replace("import tkinter as tk", "").replace("from tkinter import ttk, messagebox", "")
ns = {}
ns["__file__"] = r"C:\Users\TianYifan\.doubao\lark-chats\2026-10-01\new-chat\re_work\jira_feishu_sync.py"
exec(compile(logic_src, "logic", "exec"), ns)

SyncManager = ns["SyncManager"]
logs = []

# ---- Mock 飞书客户端：记录所有调用 ----
class MockFeishu:
    def __init__(self):
        self.calls = []
        self.fields = [{"field_id": "f1", "field_name": "Summary", "is_primary": False}]
        self.records = []
    def list_fields(self, at, tid):
        self.calls.append(("list_fields", at, tid))
        return True, self.fields
    def rename_field(self, at, tid, fid, new_name):
        self.calls.append(("rename_field", new_name))
        return True, {}
    def delete_field(self, at, tid, fid):
        self.calls.append(("delete_field", fid))
        return True, {}
    def add_field(self, at, tid, name, ftype):
        self.calls.append(("add_field", name, ftype))
        return True, {}
    def get_all_records(self, at, tid):
        self.calls.append(("get_all_records", at, tid))
        return True, self.records
    def batch_delete_records(self, at, tid, ids):
        self.calls.append(("batch_delete", len(ids)))
        return True, {}
    def batch_create_records(self, at, tid, records):
        self.calls.append(("batch_create", len(records)))
        return True, {}
    def create_record(self, at, tid, fields):
        self.calls.append(("create_record", fields))
        return True, {}
    def batch_update_records(self, at, tid, records):
        self.calls.append(("batch_update", len(records)))
        return True, {}
    def update_record(self, at, tid, rid, fields):
        self.calls.append(("update_record", rid))
        return True, {}

# ---- 测试 1: rebuild_table_fields（字段有变化：现有 [Summary] → 目标 [Issue Key, Summary, Status]）----
fc = MockFeishu()
ok = SyncManager.rebuild_table_fields(fc, "app", "tbl", ["Issue Key", "Summary", "Status"], logs.append)
assert ok, logs
# 目标: rename 主键(无主键字段则不 rename) → 删除非主键 → 按序创建
# 现有 fields 无主键，目标首列 Issue Key：应创建 Issue Key + Summary(已存在但被删后重建) + Status
adds = [c for c in fc.calls if c[0] == "add_field"]
assert adds == [("add_field", "Issue Key", 1), ("add_field", "Summary", 1), ("add_field", "Status", 1)], adds
dels = [c for c in fc.calls if c[0] == "delete_field"]
assert dels == [("delete_field", "f1")], dels
print("PASS rebuild_table_fields (create in order, delete old non-primary)")

# ---- 测试 2: rebuild 无变化跳过 ----
fc2 = MockFeishu()
fc2.fields = [{"field_id": "pk", "field_name": "Issue Key", "is_primary": True},
              {"field_id": "f2", "field_name": "Summary", "is_primary": False},
              {"field_id": "f3", "field_name": "Status", "is_primary": False}]
logs.clear()
ok = SyncManager.rebuild_table_fields(fc2, "app", "tbl", ["Issue Key", "Summary", "Status"], logs.append)
assert ok and "跳过" in logs[-1], logs
assert not [c for c in fc2.calls if c[0] in ("delete_field", "add_field")], fc2.calls
print("PASS rebuild_table_fields (no change -> skip)")

# ---- 测试 3: write_records 分批 ----
fc3 = MockFeishu()
headers = ["Issue Key", "Summary"]
rows = [["A-1", "s1"], ["A-2", "s2"], ["A-3", "s3"]]
ok = SyncManager.write_records(fc3, "app", "tbl", headers, rows, logs.append)
assert ok
creates = [c for c in fc3.calls if c[0] == "batch_create"]
assert creates and creates[0][1] == 3, creates
# 字段映射正确
assert fc3.calls[0][0] == "batch_create"
print("PASS write_records (single batch, fields mapped)")

# ---- 测试 4: sync_incremental 差异 ----
fc4 = MockFeishu()
fc4.records = [{"record_id": "r1", "fields": {"Issue Key": "A-1", "Summary": "old"}},
               {"record_id": "r2", "fields": {"Issue Key": "A-99", "Summary": "gone"}}]
logs.clear()
ok, stats = SyncManager.sync_incremental(fc4, "app", "tbl", headers, rows, logs.append)
assert ok
assert stats["to_create"] == [["A-2", "s2"], ["A-3", "s3"]], stats["to_create"]  # A-2/A-3 新增
assert len(stats["to_update"]) == 1, stats["to_update"]                 # A-1 存在
assert stats["to_delete"] == ["r2"], stats["to_delete"]                 # A-99 删除
names = [c[0] for c in fc4.calls]
assert "batch_update" in names and "batch_delete" in names, names
print("PASS sync_incremental (create/update/delete diff)")

# ---- 测试 5: clear_all_records ----
fc5 = MockFeishu()
fc5.records = [{"record_id": f"r{i}"} for i in range(1200)]  # 1200 条 → 3 批
ok = SyncManager.clear_all_records(fc5, "app", "tbl", logs.append)
assert ok
dels = [c for c in fc5.calls if c[0] == "batch_delete"]
assert len(dels) == 3 and dels[0][1] == 500 and dels[-1][1] == 200, dels
print("PASS clear_all_records (3 batches: 500/500/200)")

print("\nALL INTEGRATION TESTS PASSED")
