# -*- coding: utf-8 -*-
"""定位 PyInstaller CArchive cookie，解析 TOC，打印条目清单"""
import struct, zlib, os, sys

path = r"C:\Users\TianYifan\Downloads\001 F-Car Export jira-tickpets luochangchuan.exe"
data = open(path, "rb").read()

# PyInstaller cookie magic: MEI\014\013\012\013\016
magic = b"MEI\014\013\012\013\016"
idx = data.rfind(magic)
print(f"Cookie magic found at offset 0x{idx:X} (file size 0x{len(data):X})")
if idx < 0:
    sys.exit("not a pyinstaller archive")

# cookie structure (from PyInstaller archive.py)
# magic(8) | lengthofpackage(4) | toc(4) | toc_len(4) | pyvers(4) | pylibname(64? actually 80)
cookie = data[idx:idx+8+4+4+4+4+80]
lengthofpackage, toc, toc_len, pyvers = struct.unpack_from("!IIII", cookie, 8)
pylibname = cookie[24:24+64].split(b"\0")[0].decode("latin1", "replace")
print(f"lengthofpackage={lengthofpackage} (0x{lengthofpackage:X})")
print(f"toc offset(from archive start)={toc} (0x{toc:X})")
print(f"toc_len={toc_len}")
print(f"pyvers={pyvers} (0x{pyvers:X})")
print(f"pylibname={pylibname}")

archive_start = idx - lengthofpackage
print(f"Archive start offset = 0x{archive_start:X}")
print(f"Archive start bytes: {data[archive_start:archive_start+16].hex()}")

# parse TOC
toc_off = archive_start + toc
toc_data = data[toc_off:toc_off+toc_len]
print(f"\nTOC at 0x{toc_off:X}, parsing {toc_len} bytes...")

TYPE_NAMES = {
    ord("m"): "MODULE", ord("M"): "PKG", ord("z"): "PYMODULE(PYZ)",
    ord("s"): "SCRIPT", ord("b"): "BINARY", ord("x"): "DATA",
    ord("a"): "RUNTIME_OPTION", ord("c"): "SCRIPT2", ord("i"): "SPLASH",
}
entries = []
pos = 0
while pos < toc_len:
    if pos + 14 > toc_len:
        print(f"  [toc truncated at {pos}]")
        break
    entry_off, entry_size, uncomp_size, comp_flag = struct.unpack_from("!IIII", toc_data, pos)
    type_code = toc_data[pos+16]
    name_len = toc_data[pos+17]
    name = toc_data[pos+18:pos+18+name_len].decode("utf-8", "replace")
    entries.append((entry_off, entry_size, uncomp_size, comp_flag, type_code, name))
    pos += 18 + name_len

print(f"Total TOC entries: {len(entries)}")
for e in entries:
    off, size, usz, comp, tc, name = e
    tn = TYPE_NAMES.get(tc, f"?{chr(tc)}")
    print(f"  [{tn:14s}] off=0x{off:08X} size={size:10d} uncomp={usz:10d} comp={comp} name={name}")

# Save entries for later use
import json
with open(r"C:\Users\TianYifan\.doubao\lark-chats\2026-10-01\new-chat\re_work\toc.json", "w", encoding="utf-8") as f:
    json.dump({"archive_start": archive_start, "idx": idx, "entries": entries}, f, ensure_ascii=False)
print("\nSaved to toc.json")
