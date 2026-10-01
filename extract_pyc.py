# -*- coding: utf-8 -*-
# Extract main script + PYZ from CArchive
import struct, zlib, json

FN = r'C:\Users\TianYifan\Downloads\001 F-Car Export jira-tickpets luochangchuan.exe'
data = open(FN, 'rb').read()
PKG_START = 0x53A00
OUT = r'C:\Users\TianYifan\.doubao\lark-chats\2026-10-01\new-chat\re_work\extracted'
import os
os.makedirs(OUT, exist_ok=True)

entries = json.load(open(r'C:\Users\TianYifan\.doubao\lark-chats\2026-10-01\new-chat\re_work\toc_full.json', encoding='utf-8'))

def get_entry(name):
    for e in entries:
        if e['name'] == name:
            return e
    return None

def extract_entry(name, outname):
    e = get_entry(name)
    if not e:
        print('NOT FOUND', name)
        return
    raw = data[PKG_START + e['off'] : PKG_START + e['off'] + e['size']]
    if e['comp'] == 1:
        dec = zlib.decompress(raw)
    else:
        dec = raw
    path = os.path.join(OUT, outname)
    with open(path, 'wb') as f:
        f.write(dec)
    print(f'{name}: {len(raw)} -> {len(dec)} bytes -> {outname}')

# main script
extract_entry('jira_feishu_sync', 'jira_feishu_sync.pyc')
# PYZ
extract_entry('PYZ.pyz', 'PYZ.pyz')
# bootloaders (maybe useful)
extract_entry('pyiboot01_bootstrap', 'pyiboot01_bootstrap.pyc')
