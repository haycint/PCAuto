# -*- coding: utf-8 -*-
"""提取字符串：ASCII + UTF-16LE，并按关键字分类"""
import struct, re, sys

path = r"C:\Users\TianYifan\Downloads\001 F-Car Export jira-tickpets luochangchuan.exe"
data = open(path, "rb").read()

pe_off = struct.unpack_from("<I", data, 0x3C)[0]
opt = pe_off + 24
opt_size = struct.unpack_from("<H", data, pe_off+20)[0]
num_sec = struct.unpack_from("<H", data, pe_off+6)[0]
secs = []
for i in range(num_sec):
    off = opt + opt_size + i*40
    name = data[off:off+8].rstrip(b"\0").decode("latin1")
    vsize, va, rsize, raw = struct.unpack_from("<IIII", data, off+8)
    secs.append((name, va, vsize, raw, rsize))

# Only scan .rdata and .data (strings live there); also .text for safety
target = [s for s in secs if s[0] in (".rdata", ".data")]
print("Scanning sections:", [s[0] for s in target])

# ---- ASCII strings (min len 5) ----
ascii_re = re.compile(rb"[\x20-\x7E]{5,}")
ascii_strings = []
for name, va, vsize, raw, rsize in target:
    blob = data[raw:raw+min(vsize, rsize)]
    for m in ascii_re.finditer(blob):
        ascii_strings.append((name, raw + m.start(), m.group().decode("latin1")))

print(f"\nTotal ASCII strings: {len(ascii_strings)}")

# ---- UTF-16LE strings (min len 4 chars = 8 bytes) ----
u16_re = re.compile(rb"(?:[\x20-\x7E]\x00){4,}")
u16_strings = []
for name, va, vsize, raw, rsize in target:
    blob = data[raw:raw+min(vsize, rsize)]
    for m in u16_re.finditer(blob):
        s = m.group().decode("utf-16le", errors="replace")
        u16_strings.append((name, raw + m.start(), s))

print(f"Total UTF-16 strings: {len(u16_strings)}")

# ---- keyword classification ----
keywords = {
    "jira/atlassian": re.compile(r"jira|atlassian|confluence", re.I),
    "http/url": re.compile(r"https?://|rest/api|/api/", re.I),
    "auth": re.compile(r"token|auth|login|password|passwd|basic|bearer|api[_-]?key|credential", re.I),
    "export": re.compile(r"export|csv|excel|xlsx|json|xml|attachment", re.I),
    "query/jql": re.compile(r"jql|project|issuetype|issue|field", re.I),
    "ui": re.compile(r"dialog|button|label|window|title|message", re.I),
    "error": re.compile(r"error|fail|invalid|exception|panic", re.I),
    "encoding": re.compile(r"utf-8|utf8|base64|sha|md5|hex|gbk|gb2312", re.I),
}

for cat, rx in keywords.items():
    hits = [(s[1], s[2]) for s in ascii_strings if rx.search(s[2])]
    print(f"\n===== {cat}: {len(hits)} hits =====")
    for off, s in hits[:80]:
        print(f"  0x{off:08X}: {s[:160]}")

print("\n===== UTF-16 hits (jira/http/auth/export) =====")
for off, s in u16_strings:
    if any(k in s.lower() for k in ("jira", "http", "token", "export", "login", "password", "rest", "api", "csv", "xlsx", ".exe", ".json")):
        print(f"  U16 0x{off:08X}: {s[:160]}")
