#!/usr/bin/env python3
from __future__ import annotations
import argparse, ctypes, json, os, struct
from pathlib import Path
DLL_DIR_DEFAULT = Path(r"C:\Program Files\HIKMICRO Analyzer\HIKMICRO Analyzer")
class SharedBlock(ctypes.Structure):
    _fields_=[('data',ctypes.c_void_p),('owner',ctypes.c_void_p),('size',ctypes.c_size_t)]
def add_dll_dir(p):
    if hasattr(os,'add_dll_directory'): os.add_dll_directory(str(p))
    ctypes.windll.kernel32.SetDllDirectoryW(str(p))
def get_proc(dll,name):
    k=ctypes.windll.kernel32; k.GetProcAddress.argtypes=[ctypes.c_void_p,ctypes.c_char_p]; k.GetProcAddress.restype=ctypes.c_void_p
    a=k.GetProcAddress(dll._handle,name)
    if not a: raise RuntimeError(name)
    return int(a)
def words(b, off, count=64):
    return list(struct.unpack_from('<'+'H'*count,b,off))
def u32s(b,n=128):
    return [int.from_bytes(b[i:i+4],'little') for i in range(0,min(n,len(b)),4)]
def i32s(b,n=128):
    return [int.from_bytes(b[i:i+4],'little',signed=True) for i in range(0,min(n,len(b)),4)]
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--dll-dir',type=Path,default=DLL_DIR_DEFAULT); ap.add_argument('--raw',type=Path,required=True); ap.add_argument('--width',type=int,default=256); ap.add_argument('--height',type=int,default=344); ap.add_argument('--start-row',type=int,default=192); ap.add_argument('--rows',type=int,default=4); ap.add_argument('--out',type=Path,default=Path('data/mini2_raw_addline_probe'))
    a=ap.parse_args(); add_dll_dir(a.dll_dir); dll=ctypes.WinDLL(str(a.dll_dir/'MicroJPEG_Release_x64.dll'))
    fn=ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.POINTER(SharedBlock), ctypes.c_uint32)(get_proc(dll,b'?createRawAddLine@ImageFactory@MicroSDK@@SA_NAEAURawAddLineData@2@AEBUSharedBlock@2@I@Z'))
    allb=a.raw.read_bytes(); frame_bytes=a.width*a.height*2
    data=allb[:frame_bytes]
    add=data[a.start_row*a.width*2:(a.start_row+a.rows)*a.width*2]
    buf=ctypes.create_string_buffer(add)
    sb=SharedBlock(ctypes.cast(buf,ctypes.c_void_p), None, len(add))
    out=ctypes.create_string_buffer(0x400)
    ok=bool(fn(ctypes.byref(out), ctypes.byref(sb), a.width))
    rep={'raw':str(a.raw),'ok':ok,'addline_len':len(add),'addline_hex_prefix':add[:256].hex(' '),'row_words':{},'out_hex_prefix':out.raw[:256].hex(' '),'out_u32':u32s(out.raw,256),'out_i32':i32s(out.raw,256),'out_u16':[int.from_bytes(out.raw[i:i+2],'little') for i in range(0,256,2)]}
    for r in range(a.rows): rep['row_words'][f'row{a.start_row+r}']=words(data,(a.start_row+r)*a.width*2,64)
    a.out.mkdir(parents=True,exist_ok=True); op=a.out/(a.raw.stem+'_raw_addline_probe.json'); op.write_text(json.dumps(rep,indent=2),encoding='utf-8')
    print(json.dumps(rep,indent=2)[:12000]); print('saved:',op)
if __name__=='__main__': main()
