#!/usr/bin/env python3
"""Probe MT_SubFunction case2 using an official MT_Process-derived f32 table.

This is diagnostic evidence only: it proves whether MT_SubFunction case2's
full-frame loop can reproduce Analyzer CSV when its gray->Celsius table is
filled by the official MT_Process point API. It is not the accepted final path
for the MT_SubFunction goal because table values are not produced by case1.
"""
from __future__ import annotations
import argparse, ctypes, csv, json, math, struct, sys
from pathlib import Path
THIS=Path(__file__).resolve(); TOOLS=THIS.parent
if str(TOOLS) not in sys.path: sys.path.insert(0,str(TOOLS))
from mini2_mtlib_api_probe_win import (DLL_DIR_DEFAULT, WIDTH, HEIGHT, POINT_SIZE, add_dll_dir, buf_from_bytes, extract_blocks, make_desc, raw_path_for, radiometric_params_from_jpeg, tag1_internal_reflected_c)
PIXELS=WIDTH*HEIGHT

def csv_flat(path: Path):
    text=None
    for enc in ('utf-8-sig','cp949','euc-kr','latin1'):
        try: text=path.read_text(encoding=enc); break
        except UnicodeDecodeError: pass
    out=[]
    for row in csv.reader((text or '').splitlines()):
        nums=[]
        for c in row:
            try: nums.append(float(c.strip()))
            except Exception: pass
        if len(nums)>=WIDTH:
            xs=nums[-WIDTH:]
            if max(xs)<=150: out.extend(xs)
    return out

def metric(pred, truth):
    n=min(len(pred),len(truth)); diffs=[pred[i]-truth[i] for i in range(n) if math.isfinite(pred[i])]
    rd=[round(pred[i],1)-truth[i] for i in range(n) if math.isfinite(pred[i])]
    return {'count':len(diffs),'mae':sum(abs(d) for d in diffs)/len(diffs),'max_abs':max(abs(d) for d in diffs),'bias':sum(diffs)/len(diffs),'rounded_0p1_mae':sum(abs(d) for d in rd)/len(rd),'rounded_0p1_match_rate':sum(1 for d in rd if abs(d)<1e-9)/len(rd)}

def type1_payload(key,value): return struct.pack('<II', int(key), int(value)&0xffffffff)

def make_points(raw_values, emissivity, reflected_c, distance_m):
    pts=ctypes.create_string_buffer(len(raw_values)*POINT_SIZE)
    for i,g in enumerate(raw_values):
        off=i*POINT_SIZE
        struct.pack_into('<i', pts, off+0x04, int(g))
        struct.pack_into('<f', pts, off+0x14, float(emissivity))
        struct.pack_into('<f', pts, off+0x18, float(reflected_c))
        struct.pack_into('<f', pts, off+0x1c, float(distance_m))
    return pts

def run_one(dll, jpeg: Path, batch: int):
    blocks=extract_blocks(jpeg); raw_bytes=raw_path_for(jpeg).read_bytes(); raw=list(struct.unpack('<'+'H'*PIXELS,raw_bytes)); raw_frame=raw_bytes+blocks['tag1']
    p=ctypes.create_string_buffer(0x20); struct.pack_into('<IIII',p,0,WIDTH,HEIGHT,1,1)
    backing,desc,_=make_desc(); dll.MT_GetMemSize(ctypes.byref(p),ctypes.byref(desc)); backing,desc,desc_info=make_desc()
    handle=ctypes.c_void_p(); cret=dll.MT_Create(ctypes.byref(p),ctypes.byref(desc),ctypes.byref(handle))
    if cret!=0 or not handle.value: raise RuntimeError(f'MT_Create failed {cret}')
    keep=[p,backing,desc]
    set_rets=[]
    for typ,payload,name in [(6,blocks['tag519'],'tag519'),(1,type1_payload(15,struct.unpack_from('<I',blocks['tag519'],8)[0]),'key15'),(7,raw_frame,'raw+tag1')]:
        b=buf_from_bytes(payload); keep.append(b); set_rets.append((name,dll.MT_SetConfig(handle,typ,ctypes.cast(b,ctypes.c_void_p),len(payload))))
    # case1 just to establish case2 state/offsets, then we overwrite the table.
    raw_buf=ctypes.create_string_buffer(raw_bytes,len(raw_bytes)); tag1_buf=ctypes.create_string_buffer(blocks['tag1'],len(blocks['tag1']))
    table=ctypes.create_string_buffer(0x20000); out_struct=ctypes.create_string_buffer(0x20)
    struct.pack_into('<QQ',out_struct,0,0,ctypes.addressof(table)); keep += [raw_buf,tag1_buf,table,out_struct]
    ret1=dll.MT_SubFunction(handle,1,ctypes.cast(raw_buf,ctypes.c_void_p),len(raw_bytes),ctypes.cast(out_struct,ctypes.c_void_p),0,None)
    params=radiometric_params_from_jpeg(jpeg); reflected=tag1_internal_reflected_c(blocks['tag1'])
    unique=sorted(set(raw))
    for start in range(0,len(unique),batch):
        sub=unique[start:start+batch]
        pts=make_points(sub, params['emissivity'], reflected, params['distance_m']); keep.append(pts)
        ret=dll.MT_Process(handle,0,ctypes.cast(pts,ctypes.c_void_p),len(sub))
        if ret!=0: raise RuntimeError(f'MT_Process failed {ret}')
        for i,g in enumerate(sub):
            temp=struct.unpack_from('<f',pts.raw,i*POINT_SIZE+0x10)[0]
            struct.pack_into('<f', table, g*4, temp)
    in2=ctypes.create_string_buffer(0xD0); struct.pack_into('<Q',in2,0,ctypes.addressof(raw_buf)); struct.pack_into('<Q',in2,8,ctypes.addressof(tag1_buf)); struct.pack_into('<Q',in2,0x10,ctypes.addressof(table))
    out2=ctypes.create_string_buffer(PIXELS*4); keep += [in2,out2]
    ret2=dll.MT_SubFunction(handle,2,ctypes.cast(in2,ctypes.c_void_p),len(in2),ctypes.cast(out2,ctypes.c_void_p),PIXELS*4,None)
    vals=list(struct.unpack('<'+'f'*PIXELS,out2.raw))
    truth=csv_flat(jpeg.with_name(jpeg.stem+'_이미지.csv'))
    return {'image':jpeg.stem,'ret1':ret1,'ret2':ret2,'set_rets':set_rets,'unique_raw':len(unique),'reflected_c':reflected,'metric':metric(vals,truth)}

def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument('--dll-dir',type=Path,default=DLL_DIR_DEFAULT); ap.add_argument('--jpeg',type=Path,action='append',required=True); ap.add_argument('--out',type=Path,default=Path('data/mini2_case2_process_table_probe')); ap.add_argument('--batch',type=int,default=4)
    a=ap.parse_args(argv); add_dll_dir(a.dll_dir); dll=ctypes.WinDLL(str(a.dll_dir/'MTlib_OL.dll'))
    dll.MT_GetMemSize.argtypes=[ctypes.c_void_p,ctypes.c_void_p]; dll.MT_GetMemSize.restype=ctypes.c_int
    dll.MT_Create.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.POINTER(ctypes.c_void_p)]; dll.MT_Create.restype=ctypes.c_int
    dll.MT_SetConfig.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_int]; dll.MT_SetConfig.restype=ctypes.c_int
    dll.MT_SubFunction.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p]; dll.MT_SubFunction.restype=ctypes.c_int
    dll.MT_Process.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_int]; dll.MT_Process.restype=ctypes.c_int
    rows=[run_one(dll,j.resolve(),a.batch) for j in a.jpeg]
    rep={'rows':rows,'worst_mae':max(r['metric']['mae'] for r in rows),'worst_max_abs':max(r['metric']['max_abs'] for r in rows)}
    a.out.mkdir(parents=True,exist_ok=True); op=a.out/'case2_process_table_probe.json'; op.write_text(json.dumps(rep,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'saved':str(op),**rep},ensure_ascii=False,indent=2)[:20000])
    return 0
if __name__=='__main__': raise SystemExit(main())
