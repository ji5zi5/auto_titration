#!/usr/bin/env python3
"""Call MTlib_OL internal environment helper (RVA 0x5490) after official setup.

This is diagnostic evidence for the MT_Process path: MT_Process builds a stack
struct at offsets 0x50.. and calls this helper when distance compensation is
needed, then passes out[0x14] as the fourth float argument to MT_Gray2Temp.
"""
from __future__ import annotations
import argparse, ctypes, json, os, struct, sys
from pathlib import Path

THIS=Path(__file__).resolve(); TOOLS=THIS.parent
if str(TOOLS) not in sys.path: sys.path.insert(0,str(TOOLS))
from mini2_mtlib_api_probe_win import (DLL_DIR_DEFAULT, WIDTH, HEIGHT, add_dll_dir, extract_blocks, raw_path_for, make_desc, buf_from_bytes, inspect_handle, read_f32, read_u8)

RVA_HELPER=0x5490

def main(argv=None):
    ap=argparse.ArgumentParser()
    ap.add_argument('--dll-dir',type=Path,default=DLL_DIR_DEFAULT)
    ap.add_argument('--jpeg',type=Path,default=Path('data/fixtures/mini2/IR_00001.jpeg'))
    ap.add_argument('--distance-m',type=float,default=1.0)
    ap.add_argument('--out',type=Path,default=Path('data/mini2_mtlib_helper_probe'))
    args=ap.parse_args(argv)
    add_dll_dir(args.dll_dir)
    dll=ctypes.WinDLL(str(args.dll_dir/'MTlib_OL.dll'))
    k32=ctypes.windll.kernel32
    k32.GetModuleHandleW.restype=ctypes.c_void_p
    base=k32.GetModuleHandleW('MTlib_OL.dll') or k32.GetModuleHandleW(str(args.dll_dir/'MTlib_OL.dll'))
    if not base: raise RuntimeError('MTlib_OL base not found')
    base=int(base)
    helper=ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)(base+RVA_HELPER)
    MT_GetMemSize=dll.MT_GetMemSize; MT_GetMemSize.argtypes=[ctypes.c_void_p,ctypes.c_void_p]; MT_GetMemSize.restype=ctypes.c_int
    MT_Create=dll.MT_Create; MT_Create.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.POINTER(ctypes.c_void_p)]; MT_Create.restype=ctypes.c_int
    MT_SetConfig=dll.MT_SetConfig; MT_SetConfig.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_int]; MT_SetConfig.restype=ctypes.c_int
    blocks=extract_blocks(args.jpeg)
    raw=raw_path_for(args.jpeg).read_bytes(); raw_frame=raw+blocks['tag1']
    params=ctypes.create_string_buffer(0x20); struct.pack_into('<IIII',params,0,WIDTH,HEIGHT,1,1)
    backing,desc,desc_info=make_desc(); _=MT_GetMemSize(ctypes.byref(params),ctypes.byref(desc))
    backing,desc,desc_info=make_desc(); handle=ctypes.c_void_p(); create_ret=MT_Create(ctypes.byref(params),ctypes.byref(desc),ctypes.byref(handle))
    h=int(handle.value or 0)
    report={'jpeg':str(args.jpeg),'base':hex(base),'helper_addr':hex(base+RVA_HELPER),'create_ret':create_ret,'setconfig':[]}
    calib_param_type=struct.unpack_from('<I',blocks['tag519'],0x08)[0]
    cfg_calib_type=struct.pack('<II',15,calib_param_type)
    for typ,data,name in [(6,blocks['tag519'],'tag519'),(1,cfg_calib_type,'key15'),(7,raw_frame,'raw+tag1')]:
        buf=buf_from_bytes(data)
        ret=MT_SetConfig(handle,typ,ctypes.cast(buf,ctypes.c_void_p),len(data))
        report['setconfig'].append({'type':typ,'name':name,'ret':ret})
    report['handle']=inspect_handle(h)
    # Mirror MT_Process stack struct: +0=d0, +4=d4, +8=distance*0.001, +0xc=dc, +0x10=e0.
    env=ctypes.create_string_buffer(0x40)
    for off,hoff in [(0x00,0xd0),(0x04,0xd4),(0x0c,0xdc),(0x10,0xe0)]:
        struct.pack_into('<f',env,off,read_f32(h,hoff))
    struct.pack_into('<f',env,0x08,float(args.distance_m)*0.001)
    before=env.raw.hex(' ')
    ret=helper(handle,ctypes.cast(env,ctypes.c_void_p))
    floats={hex(o):struct.unpack_from('<f',env.raw,o)[0] for o in range(0,0x28,4)}
    ints={hex(o):struct.unpack_from('<I',env.raw,o)[0] for o in range(0,0x28,4)}
    report['helper']={'ret':ret,'distance_m':args.distance_m,'before_hex':before,'after_hex':env.raw.hex(' '),'floats':floats,'u32':ints}
    args.out.mkdir(parents=True,exist_ok=True)
    out=args.out/f'{args.jpeg.stem}_helper_probe.json'
    out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'jpeg':str(args.jpeg),'helper_ret':ret,'floats':floats,'out':str(out)},ensure_ascii=False,indent=2))
    return 0
if __name__=='__main__': raise SystemExit(main())
