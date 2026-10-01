# -*- coding: utf-8 -*-
# Parse PYZ.pyz: list module names (PyInstaller 6.x format)
import struct, zlib

data = open(r'C:\Users\TianYifan\.doubao\lark-chats\2026-10-01\new-chat\re_work\extracted\PYZ.pyz','rb').read()
print('PYZ size:', len(data))
print('head:', data[:16].hex(' '))

# PyInstaller 6.x PYZ layout:
# magic 4 bytes ('PYZ\x00'), pythonversion 4 bytes, toc_offset... Actually:
# older: header = magic + python magic + toc offset
# Let's inspect: find TOC. PyInstaller 6.x PYZ: struct { uint32 magic; uint32 pyvers; uint32 toc_off; }? then toc at toc_off:
# entries: off(4) size(4) name(null)
magic = data[:4]
print('magic:', magic)
pyvers = struct.unpack('<I', data[4:8])[0]
print('pyvers:', pyvers)
toc_off = struct.unpack('<I', data[8:12])[0]
print('toc_off:', hex(toc_off))

entries = []
pos = toc_off
while pos < len(data):
    if pos + 8 > len(data):
        break
    off, size = struct.unpack('!II', data[pos:pos+8])
    nz = data.find(b'\x00', pos+8)
    if nz < 0:
        break
    name = data[pos+8:nz].decode('utf-8', 'replace')
    entries.append((name, off, size))
    pos = nz + 1
print('TOTAL modules:', len(entries))
names = sorted(e[0] for e in entries)
open(r'C:\Users\TianYifan\.doubao\lark-chats\2026-10-01\new-chat\re_work\pyz_modules.txt','w',encoding='utf-8').write('\n'.join(names))
print('sample:', names[:40])
print('last 20:', names[-20:])
# check third-party
third = [n for n in names if not n.startswith(('_',)) and '.' not in n and n not in ('struct','marshal','json','re','os','sys','time','urllib','http','html','tkinter','traceback','datetime','subprocess','pathlib','threading','queue','collections','base64','hashlib','random','math','string','typing','warnings','functools','itertools','copy','logging','socket','ssl','select','array','binascii','codecs','io','abc','contextlib','tempfile','shutil','glob','stat','importlib','inspect','tokenize','token','keyword','linecache','enum','fnmatch','locale','operator','dis','pickle','getopt','argparse','configparser','signal','atexit','errno','gc','weakref','zipfile','gzip','bz2','lzma','csv','xml','decimal','fractions','numbers','dataclasses','textwrap','platform','ctypes','mmap','zlib','unicodedata','stringprep')]
print('possible third-party:', third[:60])
