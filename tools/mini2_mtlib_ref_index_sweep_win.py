#!/usr/bin/env python3
from __future__ import annotations
import argparse, ctypes, csv, json, math, os, statistics, struct, sys
from pathlib import Path
THIS=Path(__file__).resolve(); sys.path.insert(0,str(THIS.parent))
from mini2_mtlib_api_probe_win import add_dll_dir, extract_blocks, raw_path_for, csv_matrix, WIDTH, HEIGHT, POINT_SIZE, make_desc, buf_from_bytes
DLL_DIR_DEFAULT=Path(r"C:\Program Files\HIKMICRO Analyzer\HIKMICRO Analyzer")

def setup_handle(dll, jpeg):
    blocks=extract_blocks(jpeg); raw=raw_path_for(jpeg).read_bytes(); raw_frame=raw+blocks['tag1']
    params=ctypes.create_string_buffer(0x20); struct.pack_into('<IIII',params,0,WIDTH,HEIGHT,1,1)
    backing, desc, _=make_desc(); handle=ctypes.c_void_p()
    dll.MT_Create(ctypes.byref(params),ctypes.byref(desc),ctypes.byref(handle))
    h=handle
    for typ,data in [(6,blocks['tag519']),(1,struct.pack('<II',15,struct.unpack_from('<I',blocks['tag519'],8)[0])),(7,raw_frame)]:
        buf=buf_from_bytes(data); dll.MT_SetConfig(h,typ,ctypes.cast(buf,ctypes.c_void_p),len(data))
    return backing, h, blocks, list(struct.unpack('<'+('H'*(WIDTH*HEIGHT)),raw))

def mt_temps_for_unique(dll,h,grays,ref,emi=0.97,dist=1.0):
    out={}; items=sorted(set(grays)); batch=4
    for s in range(0,len(items),batch):
        sub=items[s:s+batch]; pts=ctypes.create_string_buffer(len(sub)*POINT_SIZE)
        for j,g in enumerate(sub):
            off=j*POINT_SIZE; struct.pack_into('<i',pts,off+4,int(g)); struct.pack_into('<f',pts,off+0x14,float(emi)); struct.pack_into('<f',pts,off+0x18,float(ref)); struct.pack_into('<f',pts,off+0x1c,float(dist))
        ret=dll.MT_Process(h,0,ctypes.cast(pts,ctypes.c_void_p),len(sub))
        if ret!=0:
            # retry one-by-one
            for g in sub:
                p=ctypes.create_string_buffer(POINT_SIZE); struct.pack_into('<i',p,4,int(g)); struct.pack_into('<f',p,0x14,float(emi)); struct.pack_into('<f',p,0x18,float(ref)); struct.pack_into('<f',p,0x1c,float(dist)); dll.MT_Process(h,0,ctypes.cast(p,ctypes.c_void_p),1); out[g]=struct.unpack_from('<f',p.raw,0x10)[0]
        else:
            for j,g in enumerate(sub): out[g]=struct.unpack_from('<f',pts.raw,j*POINT_SIZE+0x10)[0]
    return out

def metrics(raw,ref_csv,lookup):
    diffs=[]; rdiff=[]
    for i,g in enumerate(raw):
        t=lookup[g]; c=ref_csv[i]; diffs.append(t-c); rdiff.append(round(t,1)-c)
    return {'mae':sum(abs(x) for x in diffs)/len(diffs),'max_abs':max(abs(x) for x in diffs),'bias':sum(diffs)/len(diffs),'match':sum(1 for x in rdiff if abs(x)<1e-6)/len(rdiff),'rmae':sum(abs(x) for x in rdiff)/len(rdiff)}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--dll-dir',type=Path,default=DLL_DIR_DEFAULT); ap.add_argument('--out',type=Path,default=Path('data/mini2_ref_index_sweep')); ap.add_argument('--images',nargs='*',default=[f'IR_0000{i}.jpeg' for i in range(1,6)]); args=ap.parse_args()
    add_dll_dir(args.dll_dir); dll=ctypes.WinDLL(str(args.dll_dir/'MTlib_OL.dll'))
    for name in ['MT_Create','MT_SetConfig','MT_Process']:
        getattr(dll,name).restype=ctypes.c_int
    dll.MT_Create.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.POINTER(ctypes.c_void_p)]; dll.MT_SetConfig.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_int]; dll.MT_Process.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_int]
    args.out.mkdir(parents=True,exist_ok=True)
    per_image={}; aggregate=[]
    for img in args.images:
        jpeg=Path(img); backing,h,blocks,raw=setup_handle(dll,jpeg); csvflat=[v for row in csv_matrix(jpeg.with_name(jpeg.stem+'_이미지.csv')) for v in row]
        tag1=struct.unpack('<512H',blocks['tag1']); cand=[]
        for row,scale in [('row0_div50',50.0),('row1_div1000',1000.0),('row1_div100',100.0),('row1_div50',50.0)]:
            base=0 if row.startswith('row0') else 256
            for idx in range(256):
                val=tag1[base+idx]/scale
                if -50<=val<=150:
                    lu=mt_temps_for_unique(dll,h,raw,val,0.97,1.0)
                    m=metrics(raw,csvflat,lu); cand.append({'source':row,'idx':idx,'value':val,**m})
        cand.sort(key=lambda x:(-x['match'],x['mae'],x['max_abs']))
        per_image[jpeg.stem]=cand[:30]
        print('IMAGE',jpeg.stem,'best',cand[:5])
        for c in cand: aggregate.append((jpeg.stem,c))
    # aggregate by source+idx across images when present
    by={}
    for stem,c in aggregate:
        k=(c['source'],c['idx'])
        by.setdefault(k,[]).append(c)
    agg=[]
    for k,arr in by.items():
        if len(arr)==len(args.images):
            agg.append({'source':k[0],'idx':k[1],'mean_match':statistics.mean(a['match'] for a in arr),'mean_mae':statistics.mean(a['mae'] for a in arr),'max_abs_max':max(a['max_abs'] for a in arr),'values':[a['value'] for a in arr]})
    agg.sort(key=lambda x:(-x['mean_match'],x['mean_mae'],x['max_abs_max']))
    report={'per_image_top':per_image,'aggregate_top':agg[:100]}
    out=args.out/'ref_index_sweep.json'; out.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    print('AGG TOP')
    for x in agg[:20]: print(x)
    print('saved',out)
if __name__=='__main__': main()
