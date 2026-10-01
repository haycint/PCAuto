# -*- coding: utf-8 -*-
"""解析 Debug 目录、PDB 信息、资源树"""
import struct, datetime

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

def rva_to_off(rva):
    for name, va, vsize, raw, rsize in secs:
        if va <= rva < va + min(vsize, rsize):
            return raw + (rva - va)
    return None

dd = opt + 112
def dd_get(i):
    rva, size = struct.unpack_from("<II", data, dd + i*8)
    return rva, size

# --- Debug dir ---
dbg_rva, dbg_size = dd_get(6)
print("=== Debug directory ===")
if dbg_rva:
    off = rva_to_off(dbg_rva)
    for e in range(dbg_size // 28):
        eoff = off + e*28
        ctype = struct.unpack_from("<I", data, eoff+12)[0]
        size = struct.unpack_from("<I", data, eoff+16)[0]
        addr = struct.unpack_from("<I", data, eoff+20)[0]
        pdata = struct.unpack_from("<I", data, eoff+24)[0]
        print(f"  entry {e}: type={ctype} size={size} dataRVA=0x{addr:X} ptrRaw=0x{pdata:X}")
        if ctype == 2:  # CODEVIEW
            cv = pdata
            sig = data[cv:cv+4]
            if sig == b"RSDS":
                guid = data[cv+4:cv+20]
                age = struct.unpack_from("<I", data, cv+20)[0]
                end = data.index(b"\0", cv+24)
                pdb = data[cv+24:end].decode("latin1")
                print(f"    PDB: {pdb} age={age} guid={guid.hex().upper()}")
            elif sig == b"NB10":
                print("    NB10 (old MSVC pdb)")
        elif ctype == 13:
            # REPRO or EX_DLLCHARACTERISTICS
            print(f"    raw bytes: {data[pdata:pdata+size].hex()}")

# --- Resources ---
res_rva, res_size = dd_get(2)
print("\n=== Resource tree ===")
if res_rva:
    off = rva_to_off(res_rva)

    def parse_dir(diroff, depth, pathstr):
        # IMAGE_RESOURCE_DIRECTORY
        nid = struct.unpack_from("<H", data, diroff+12)[0]
        nname = struct.unpack_from("<H", data, diroff+14)[0]
        entries = []
        base = diroff + 16
        for i in range(nid + nname):
            eoff = base + i*8
            name_id, data_off = struct.unpack_from("<II", data, eoff)
            if name_id & 0x80000000:
                # named entry
                noff = res_rva + (name_id & 0x7FFFFFFF)  # relative to resource section start!
                # name is UTF-16
                slen = struct.unpack_from("<H", data, noff)[0]
                sname = data[noff+2:noff+2+slen*2].decode("utf-16le", errors="replace")
                label = sname
            else:
                label = str(name_id)
            if data_off & 0x80000000:
                suboff = res_rva + (data_off & 0x7FFFFFFF)
                entries.append((label, suboff, True))
            else:
                daddr = res_rva + data_off
                entries.append((label, daddr, False))
        for label, addr, isdir in entries:
            if isdir:
                parse_dir(addr, depth+1, pathstr + "/" + label)
            else:
                # data entry: 3 x DWORD (RVA, size, codepage)
                rva, size, cp = struct.unpack_from("<III", data, addr)
                print(f"  {'  '*depth}{pathstr}/{label}: RVA=0x{rva:X} size={size} cp={cp}")

    # top level
    parse_dir(off, 0, "")

# --- Version info extraction from .rsrc ---
print("\n=== Version info search ===")
for name, va, vsize, raw, rsize in secs:
    if name == ".rsrc":
        blob = data[raw:raw+rsize]
        idx = blob.find(b"VS_VERSION_INFO")
        if idx >= 0:
            print(f"  VS_VERSION_INFO found at offset 0x{raw+idx:X}")
            # print surrounding ASCII
            chunk = blob[idx-64:idx+1024]
            printable = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
            print(printable)
PY_EOF = None
