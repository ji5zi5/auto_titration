#!/usr/bin/env python3
from __future__ import annotations
import argparse, ctypes, json, os, struct
from pathlib import Path
DLL_DIR_DEFAULT=Path(r'C:\Program Files\HIKMICRO Analyzer\HIKMICRO Analyzer')
class BareBlock(ctypes.Structure): _fields_=[('data',ctypes.c_void_p),('size',ctypes.c_uint32),('pad',ctypes.c_uint32)]
def add(d):
    if hasattr(os,'add_dll_directory'): os.add_dll_directory(str(d))
    ctypes.windll.kernel32.SetDllDirectoryW(str(d))
def proc(dll,n):
    k=ctypes.windll.kernel32; k.GetProcAddress.argtypes=[ctypes.c_void_p,ctypes.c_char_p]; k.GetProcAddress.restype=ctypes.c_void_p
    a=k.GetProcAddress(dll._handle,n)
    if not a: raise RuntimeError(n)
    return int(a)
def hx(x): return hex(int(x)) if x else None
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--dll-dir',type=Path,default=DLL_DIR_DEFAULT); ap.add_argument('--jpeg',type=Path,required=True); ap.add_argument('--out',type=Path,default=Path('data/mini2_microjpeg_vtable_map.json')); args=ap.parse_args()
    add(args.dll_dir); dll=ctypes.WinDLL(str(args.dll_dir/'MicroJPEG_Release_x64.dll')); base=int(dll._handle)
    data=args.jpeg.read_bytes(); buf=ctypes.create_string_buffer(data); bb=BareBlock(ctypes.cast(buf,ctypes.c_void_p),len(data),0)
    create=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.POINTER(BareBlock))(proc(dll,b'?createImage@MicroSDK@@YAPEAVBaseImage@1@AEBUBareBlock@1@@Z'))
    ptr=int(create(ctypes.byref(bb)) or 0)
    vptr=ctypes.c_void_p.from_address(ptr).value or 0
    entries=[]
    for i in range(0,160):
        try: f=ctypes.c_void_p.from_address(vptr+i*8).value or 0
        except Exception: break
        entries.append({'slot':i,'addr':hx(f),'rva':hex(f-base) if base<=f<base+0x3000000 else None})
    probes=[]
    rep={'jpeg':str(args.jpeg),'module_base':hx(base),'object':hx(ptr),'vptr':hx(vptr),'entries':entries[:120],'probes':probes}
    out=args.out; out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(rep,indent=2),encoding='utf-8')
    print(json.dumps({'module_base':rep['module_base'],'object':rep['object'],'vptr':rep['vptr'],'entries':entries[:40],'probe_count':len(probes),'out':str(out)},indent=2))
if __name__=='__main__': main()
