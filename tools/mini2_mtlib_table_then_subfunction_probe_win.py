#!/usr/bin/env python3
"""Call MT_SubFunction(1) to build the MTlib gray->temp table, then MT_SubFunction(2) for full-frame matrix.

No CSV fitting: CSV is validation only. This probes the Analyzer DLL call path.
"""
from __future__ import annotations

import argparse, ctypes, json, math, struct, sys
from pathlib import Path

THIS=Path(__file__).resolve(); TOOLS=THIS.parent
if str(TOOLS) not in sys.path: sys.path.insert(0,str(TOOLS))
from mini2_mtlib_subfunction_probe_win import setup_handle, metrics, csv_matrix
from mini2_mtlib_api_probe_win import DLL_DIR_DEFAULT, WIDTH, HEIGHT, add_dll_dir, buf_from_bytes, bytes_at, inspect_handle, read_ptr, parse_key_value, type1_payload

PIXELS=WIDTH*HEIGHT

def f32_stats(buf, count):
    vals=[struct.unpack_from('<f', buf.raw, i*4)[0] for i in range(count)]
    finite=[v for v in vals if math.isfinite(v)]
    return vals, {"min":min(finite),"max":max(finite),"mean":sum(finite)/len(finite),"first16":vals[:16],"nonzero":sum(1 for v in vals if v!=0)}

def u16_stats(buf, count):
    vals=[struct.unpack_from('<H', buf.raw, i*2)[0] for i in range(count)]
    return vals, {"min":min(vals),"max":max(vals),"mean":sum(vals)/len(vals),"first16":vals[:16],"nonzero":sum(1 for v in vals if v!=0)}

def main(argv=None):
    ap=argparse.ArgumentParser()
    ap.add_argument('--dll-dir',type=Path,default=DLL_DIR_DEFAULT)
    ap.add_argument('--jpeg',type=Path,default=Path('data/fixtures/mini2/IR_00001.jpeg'))
    ap.add_argument('--out',type=Path,default=Path('data/mini2_mtlib_table_then_subfunction_probe'))
    ap.add_argument('--case1-input', choices=['raw_frame','raw_only','tag1','zero100','empty'], default='raw_frame')
    ap.add_argument('--set-key', action='append', default=[], metavar='KEY=VALUE', help='extra MT_SetConfig(type=1) key/value before table build')
    args=ap.parse_args(argv)
    add_dll_dir(args.dll_dir)
    dll=ctypes.WinDLL(str(args.dll_dir/'MTlib_OL.dll'))
    MT_SubFunction=dll.MT_SubFunction
    MT_SubFunction.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_int,ctypes.c_int]
    MT_SubFunction.restype=ctypes.c_int

    handle,h,keep,blocks,raw,setconfig,desc_info=setup_handle(dll,args.jpeg)
    MT_SetConfig=dll.MT_SetConfig
    MT_SetConfig.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_int]
    MT_SetConfig.restype=ctypes.c_int
    for key, encoded, original in [parse_key_value(x, raw=False) for x in args.set_key]:
        b=buf_from_bytes(type1_payload(key, encoded)); keep.append(b)
        ret=MT_SetConfig(handle,1,ctypes.cast(b,ctypes.c_void_p),8)
        setconfig.append({'type':1,'name':f'extra key{key} value={original} encoded={encoded}','ret':ret})
    raw_frame=raw+blocks['tag1']
    if args.case1_input=='raw_frame': indata=raw_frame
    elif args.case1_input=='raw_only': indata=raw
    elif args.case1_input=='tag1': indata=blocks['tag1']
    elif args.case1_input=='zero100': indata=bytes(0x100)
    else: indata=b'\x00'
    inbuf=buf_from_bytes(indata); keep.append(inbuf)

    tablebuf=ctypes.create_string_buffer(0x10000)
    case1_out=ctypes.create_string_buffer(0x18)
    struct.pack_into('<QQQ', case1_out, 0, 0, ctypes.addressof(tablebuf), 0)
    keep += [tablebuf, case1_out]
    ret1=MT_SubFunction(handle,1,ctypes.cast(inbuf,ctypes.c_void_p),len(indata),ctypes.byref(case1_out),0x18,0)
    out_words=struct.unpack_from('<QQQ',case1_out.raw,0)
    fvals,fstat=f32_stats(tablebuf,0x4000)
    uvals,ustat=u16_stats(tablebuf,0x4000)

    # Case 2: raw pointer + optional aux pointer + gray->temp table pointer.
    raw_buf=ctypes.create_string_buffer(raw,len(raw)); keep.append(raw_buf)
    auxbuf=ctypes.create_string_buffer(PIXELS*4); keep.append(auxbuf)
    in2=ctypes.create_string_buffer(0x18)
    struct.pack_into('<QQQ', in2, 0, ctypes.addressof(raw_buf), ctypes.addressof(auxbuf), ctypes.addressof(tablebuf))
    out2=ctypes.create_string_buffer(PIXELS*4); keep += [in2,out2]
    ret2=MT_SubFunction(handle,2,ctypes.byref(in2),0x18,ctypes.byref(out2),PIXELS*4,0)
    temps=[struct.unpack_from('<f', out2.raw, i*4)[0] for i in range(PIXELS)]
    finite=[v for v in temps if math.isfinite(v)]
    rep={
      'jpeg':str(args.jpeg),'case1_input':args.case1_input,'setconfig':setconfig,'desc_info':desc_info,
      'handle_after_setup':inspect_handle(h),'ret1':ret1,'case1_out_u64':[hex(x) for x in out_words],
      'table_f32_stats':fstat,'table_u16_stats':ustat,
      'ret2':ret2,'temps_stats':{'min':min(finite),'max':max(finite),'mean':sum(finite)/len(finite),'first16':temps[:16],'nonzero':sum(1 for v in temps if v!=0)},
    }
    ref_path=args.jpeg.with_name(f'{args.jpeg.stem}_이미지.csv')
    if ref_path.exists():
        rep['validation_vs_csv']=metrics(temps,csv_matrix(ref_path))
    args.out.mkdir(parents=True,exist_ok=True)
    out=args.out/f'{args.jpeg.stem}_{args.case1_input}_table_then_subfunction.json'
    out.write_text(json.dumps(rep,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:rep[k] for k in ['jpeg','case1_input','ret1','case1_out_u64','table_f32_stats','table_u16_stats','ret2','temps_stats','validation_vs_csv'] if k in rep},ensure_ascii=False,indent=2)[:20000])
    print('out',out)
    return 0
if __name__=='__main__': raise SystemExit(main())
