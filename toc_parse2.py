# -*- coding: utf-8 -*-
# TOC parser for PyInstaller 6.x CArchive
# Entry: off(4) size(4) uncomp(4) comp(1) type(1) name(null-terminated)
# plus 0x30 padding marker between entries (observed)
import struct, zlib, json, sys

FN = r'C:\Users\TianYifan\Downloads\001 F-Car Export jira-tickpets luochangchuan.exe'
data = open(FN, 'rb').read()
PKG_START = 0x53A00
TOC_START = 0xA6A4CB   # per cookie: pkgStart + toc
TOC_END = 0xA7746B     # cookie start

def parse_entry(pos):
    if pos + 14 > TOC_END:
        return None
    off, size, uncomp, comp, typ = struct.unpack_from('!IIIBB', data, pos)
    nz = data.find(b'\x00', pos + 14)
    if nz < 0 or nz > TOC_END:
        return None
    name = data[pos + 14:nz].decode('latin1', 'replace')
    return {
        'pos': pos,
        'off': off,
        'size': size,
        'uncomp': uncomp,
        'comp': comp,
        'type': chr(typ) if 32 <= typ < 127 else '?',
        'name': name,
        'end': nz + 1,
    }

entries = []
# first entry observed at 0xA6A4CF (4-byte prefix 0x00000020 at 0xA6A4CB)
pos = 0xA6A4CF
while pos < TOC_END:
    e = parse_entry(pos)
    if e is None:
        print('STOP at', hex(pos), 'no valid entry')
        break
    entries.append(e)
    # next: off chain contiguity => find next entry start where off == e.off + e.size
    # scan forward from e.end; allow 0x00 padding and 0x30 markers
    nxt = None
    for p in range(e['end'], min(e['end'] + 64, TOC_END)):
        # candidate: bytes at p must be 4-byte off == expected
        exp = e['off'] + e['size']
        if p + 4 <= TOC_END:
            cand = struct.unpack_from('!I', data, p)[0]
            if cand == exp:
                # validate it really parses as entry
                ne = parse_entry(p)
                if ne is not None and ne['off'] == exp:
                    nxt = p
                    break
    if nxt is None:
        print('CHAIN BREAK after', e['name'], 'at', hex(e['pos']), 'expected off', e['off'] + e['size'])
        # try brute: continue 1 byte
        pos = e['end']
        continue
    pos = nxt

print('TOTAL ENTRIES:', len(entries))
# save json
with open(r'C:\Users\TianYifan\.doubao\lark-chats\2026-10-01\new-chat\re_work\toc_full.json', 'w', encoding='utf-8') as f:
    json.dump(entries, f, ensure_ascii=False, indent=1)

# summary: unique types
from collections import Counter
print('types:', Counter(e['type'] for e in entries))
print('names sample:')
for e in entries[:10]:
    print(' ', e['name'], e['type'], e['off'], e['size'], e['comp'])
