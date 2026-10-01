# -*- coding: utf-8 -*-
"""纯 Python PE 解析：节区、导入表、导出表、资源、证书/时间戳"""
import struct, sys

path = r"C:\Users\TianYifan\Downloads\001 F-Car Export jira-tickpets luochangchuan.exe"
data = open(path, "rb").read()

pe_off = struct.unpack_from("<I", data, 0x3C)[0]
assert data[pe_off:pe_off+4] == b"PE\0\0"
machine = struct.unpack_from("<H", data, pe_off+4)[0]
num_sec = struct.unpack_from("<H", data, pe_off+6)[0]
ts = struct.unpack_from("<I", data, pe_off+8)[0]  # TimeDateStamp
opt_size = struct.unpack_from("<H", data, pe_off+20)[0]
opt = pe_off + 24
magic = struct.unpack_from("<H", data, opt)[0]
import datetime
print(f"PE32+={magic==0x20B}, machine=0x{machine:04X}, sections={num_sec}, TimeDateStamp={ts} ({datetime.datetime.utcfromtimestamp(ts)})")
print(f"OptHeaderSize={opt_size}, Characteristics=0x{struct.unpack_from('<H', data, pe_off+22)[0]:04X}")

# subsystem / dll characteristics
subsys = struct.unpack_from("<H", data, opt+68)[0]
dllchar = struct.unpack_from("<H", data, opt+70)[0]
print(f"Subsystem={subsys} (2=GUI,3=CUI), DllCharacteristics=0x{dllchar:04X}")

secs = []
for i in range(num_sec):
    off = opt + opt_size + i*40
    name = data[off:off+8].rstrip(b"\0").decode("latin1")
    vsize, va, rsize, raw = struct.unpack_from("<IIII", data, off+8)
    secs.append((name, va, vsize, raw, rsize))
    print(f"  sec {name:10s} VA=0x{va:08X} VS=0x{vsize:08X} raw=0x{raw:08X} RS=0x{rsize:08X}")

def rva_to_off(rva):
    for name, va, vsize, raw, rsize in secs:
        if va <= rva < va + min(vsize, rsize):
            return raw + (rva - va)
    return None

dd = opt + 112
def dd_get(i):
    rva, size = struct.unpack_from("<II", data, dd + i*8)
    return rva, size

print("\n=== Data directories ===")
names = ["Export","Import","Resource","Exception","Security","BaseReloc","Debug","Arch","GlobalPtr","TLS","LoadConfig","BoundImport","IAT","DelayImport","CLR","Reserved"]
for i in range(16):
    rva, size = dd_get(i)
    if rva or size:
        print(f"  {names[i]:14s} RVA=0x{rva:08X} size={size}")

# --- imports ---
imp_rva, imp_size = dd_get(1)
print("\n=== Imports ===")
if imp_rva:
    off = rva_to_off(imp_rva)
    i = 0
    funcs = {}
    while True:
        e = off + i*20
        oft, ts2, fwd, name_rva, iat = struct.unpack_from("<IIIII", data, e)
        if oft == 0: break
        noff = rva_to_off(name_rva)
        end = data.index(b"\0", noff)
        dll = data[noff:end].decode("latin1")
        cnt = 0
        poff = rva_to_off(oft)
        fnames = []
        while True:
            v = struct.unpack_from("<Q", data, poff + cnt*8)[0]
            if v == 0: break
            if v & 0x8000000000000000:  # ordinal import
                fnames.append(f"ord{ v & 0xFFFF }")
            else:
                hn = rva_to_off(v & 0xFFFFFFFF)
                if hn:
                    endn = data.index(b"\0", hn)
                    fnames.append(data[hn:endn].decode("latin1", errors="replace"))
            cnt += 1
        funcs[dll] = fnames
        print(f"  {dll}: {len(fnames)} funcs")
        for fn in fnames:
            print(f"      {fn}")
        i += 1
        if i > 40: break

# --- exports ---
exp_rva, exp_size = dd_get(0)
print("\n=== Exports ===")
if exp_rva:
    off = rva_to_off(exp_rva)
    nfuncs = struct.unpack_from("<I", data, off+20)[0]
    print(f"  {nfuncs} exported functions")
else:
    print("  (none)")

# --- resources ---
res_rva, res_size = dd_get(2)
print(f"\n=== Resources ===")
if res_rva:
    off = rva_to_off(res_rva)
    if off:
        # parse top-level directory
        nid = struct.unpack_from("<H", data, off+12)[0]
        nname = struct.unpack_from("<H", data, off+14)[0]
        print(f"  top-level: {nid} named entries, {nname} id entries")
else:
    print("  (none)")

# --- TLS / LoadConfig (for packer detection) ---
tls_rva, tls_size = dd_get(9)
print(f"\nTLS dir: RVA=0x{tls_rva:08X} size={tls_size}")
lc_rva, lc_size = dd_get(10)
print(f"LoadConfig dir: RVA=0x{lc_rva:08X} size={lc_size}")

# --- Debug dir ---
dbg_rva, dbg_size = dd_get(6)
print(f"\nDebug dir: RVA=0x{dbg_rva:08X} size={dbg_size}")
if dbg_rva:
    off = rva_to_off(dbg_rva)
    # first entry
    typ = struct.unpack_from("<I", data, off+12)[0]
    sz = struct.unpack_from("<I", data, off+16)[0]
    print(f"  Debug type={typ} (2=CODEVIEW, 3=PDB, 10=Repro)")
