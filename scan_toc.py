# -*- coding: utf-8 -*-
"""暴力扫描定位真实 TOC 起点，并解析条目"""
import struct

path = r"C:\Users\TianYifan\Downloads\001 F-Car Export jira-tickpets luochangchuan.exe"
data = open(path, "rb").read()
idx = data.rfind(b"MEI\x0c\x0b\x0a\x0b\x0e")
lengthofpackage = 10631875
pkg_start = idx - lengthofpackage
toc_len = 53152
print(f"pkg_start=0x{pkg_start:X}, cookie=0x{idx:X}, toc_len={toc_len}")

# Scan candidate start offsets in [pkg_start, idx-toc_len]
valid_types = set(b"mMsxbzcafg")

def try_parse(off, max_entries=2000):
    pos = off
    n = 0
    bad = 0
    entries = []
    limit = idx  # cookie start = end of toc
    while pos + 18 <= limit and n < max_entries:
        if pos + 18 > idx:
            break
        off_v, size, uncomp, comp, typ, nlen = struct.unpack_from("!IIIIBB", data, pos)
        if typ not in valid_types:
            bad += 1
            if bad > 3:
                return n, entries
            pos += 1
            continue
        if nlen > 500 or off_v > lengthofpackage:
            bad += 1
            if bad > 3:
                return n, entries
            pos += 1
            continue
        name = data[pos+18:pos+18+nlen].decode("latin1", "replace")
        entries.append((off_v, size, uncomp, comp, chr(typ), name))
        pos += 18 + nlen
        n += 1
    return n, entries

best = []
for cand in range(pkg_start, idx - toc_len - 200):
    n, entries = try_parse(cand)
    if n > len(best):
        best = entries
        best_off = cand
        if n > 50:
            break

print(f"\nBest TOC start: 0x{best_off:X} with {len(best)} entries")
print("\nFirst 40 entries:")
for e in best[:40]:
    print(f"  off=0x{e[0]:08X} size={e[1]} uncomp={e[2]} comp={e[3]} type={e[4]} name={e[5][:60]}")
print("\nLast 10 entries:")
for e in best[-10:]:
    print(f"  off=0x{e[0]:08X} size={e[1]} uncomp={e[2]} comp={e[3]} type={e[4]} name={e[5][:60]}")
