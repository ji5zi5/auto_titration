#!/usr/bin/env python3
"""Probe MTlib_OL with MicroJPEG-extracted TempDeviceConfigParams.

Purpose: test whether HIKMICRO Analyzer's exact Mini2 raw->temperature path
requires the 0xD8-byte TempDeviceConfigParams block parsed by MicroJPEG, in
addition to APP2 tag519 calibration and APP3 raw+tag1. This is not CSV fitting;
CSV is used only for validation.
"""
from __future__ import annotations
import argparse, ctypes, csv, json, math, os, struct, sys
from pathlib import Path

THIS = Path(__file__).resolve(); TOOLS = THIS.parent
if str(TOOLS) not in sys.path: sys.path.insert(0, str(TOOLS))
from mini2_mtlib_api_probe_win import (  # noqa:E402
    WIDTH, HEIGHT, POINT_SIZE, DLL_DIR_DEFAULT, add_dll_dir, extract_blocks,
    raw_path_for, csv_matrix, radiometric_params_from_jpeg,
    tag1_internal_reflected_c, make_desc, buf_from_bytes, type1_payload,
    encode_type1_value, radiometric_type1_pairs, inspect_handle,
)

class BareBlock(ctypes.Structure):
    _fields_=[('data',ctypes.c_void_p),('size',ctypes.c_uint32),('pad',ctypes.c_uint32)]

def get_proc(dll, name: bytes) -> int:
    k32=ctypes.windll.kernel32
    k32.GetProcAddress.argtypes=[ctypes.c_void_p,ctypes.c_char_p]
    k32.GetProcAddress.restype=ctypes.c_void_p
    addr=k32.GetProcAddress(dll._handle,name)
    if not addr: raise RuntimeError(f'missing export {name!r}')
    return int(addr)

def make_block(data: bytes):
    buf=ctypes.create_string_buffer(data)
    return buf, BareBlock(ctypes.cast(buf,ctypes.c_void_p),len(data),0)

def extract_microjpeg_dev_block(jpeg: Path, dll_dir: Path, n: int=0xD8) -> dict[str, object]:
    mj=ctypes.WinDLL(str(dll_dir/'MicroJPEG_Release_x64.dll'))
    create=ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.POINTER(BareBlock), ctypes.c_int32)(
        get_proc(mj,b'?createImage@ImageFactory@MicroSDK@@SAPEAVBaseImage@2@AEBUBareBlock@2@W4FileType@2@@Z'))
    typefn=ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p)(
        get_proc(mj,b'?type@BaseImage@MicroSDK@@QEBA?AW4FileType@2@XZ'))
    # Ref getter is dangerous only if object is wrong. For these Mini2 JPEGs previous
    # probe showed it returns obj+0x528; also validate sane offset.
    ref_dev=ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p)(
        get_proc(mj,b'?tempDeviceConfigParams@MicroRImageV1@MicroSDK@@QEAAAEBUTempDeviceConfigParams@2@XZ'))
    data=jpeg.read_bytes(); data_buf, bb=make_block(data)
    ptr=create(ctypes.byref(bb),1) or 0
    if not ptr: raise RuntimeError('MicroJPEG ImageFactory::createImage returned null')
    ftype=typefn(ctypes.c_void_p(ptr))
    dev=ref_dev(ctypes.c_void_p(ptr)) or 0
    if not dev: raise RuntimeError('MicroJPEG tempDeviceConfigParams ref returned null')
    raw=ctypes.string_at(dev,n)
    return {'ptr':hex(ptr),'file_type':int(ftype),'dev_ptr':hex(dev),'dev_off':hex(dev-ptr),'block':raw,
            'u32_first64':list(struct.unpack('<'+'I'*(min(len(raw),256)//4),raw[:min(len(raw),256)])),
            'hex_first128':raw[:128].hex(' ')}

def flat_csv(path: Path) -> list[float]:
    return [v for row in csv_matrix(path) for v in row]

def validate(temps: list[float], ref: list[float]) -> dict[str, object]:
    diffs=[temps[i]-ref[i] for i in range(min(len(temps),len(ref))) if math.isfinite(temps[i])]
    rdiff=[round(temps[i],1)-ref[i] for i in range(min(len(temps),len(ref))) if math.isfinite(temps[i])]
    worst=sorted(range(len(diffs)), key=lambda i: abs(diffs[i]), reverse=True)[:20]
    return {
        'count':len(diffs),
        'mae':sum(abs(d) for d in diffs)/len(diffs),
        'rmse':math.sqrt(sum(d*d for d in diffs)/len(diffs)),
        'max_abs':max(abs(d) for d in diffs),
        'bias':sum(diffs)/len(diffs),
        'rounded_0p1_mae':sum(abs(d) for d in rdiff)/len(rdiff),
        'rounded_0p1_max_abs':max(abs(d) for d in rdiff),
        'rounded_0p1_match_rate':sum(1 for d in rdiff if abs(d)<1e-9)/len(rdiff),
        'count_abs_gt_0p05':sum(1 for d in diffs if abs(d)>0.05),
        'count_abs_gt_0p10':sum(1 for d in diffs if abs(d)>0.10),
        'worst_pairs':[[i,i//WIDTH,i%WIDTH,temps[i],ref[i],diffs[i]] for i in worst],
    }

def mt_run_one(jpeg: Path, dll_dir: Path, use_type8: bool, reflected_source: str, radiometric_profile: str, out_matrix: Path|None=None) -> dict[str, object]:
    add_dll_dir(dll_dir)
    mt=ctypes.WinDLL(str(dll_dir/'MTlib_OL.dll'))
    for name in ['MT_GetMemSize','MT_Create','MT_SetConfig','MT_Process']:
        getattr(mt,name).restype=ctypes.c_int
    mt.MT_Create.argtypes=[ctypes.c_void_p,ctypes.c_void_p,ctypes.POINTER(ctypes.c_void_p)]
    mt.MT_SetConfig.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_int]
    mt.MT_Process.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_void_p,ctypes.c_int]
    blocks=extract_blocks(jpeg)
    raw_bytes=raw_path_for(jpeg).read_bytes()
    raw_u16=list(struct.unpack('<'+'H'*(WIDTH*HEIGHT),raw_bytes))
    raw_frame=raw_bytes+blocks['tag1']
    params=ctypes.create_string_buffer(0x20); struct.pack_into('<IIII',params,0,WIDTH,HEIGHT,1,1)
    backing,desc,desc_info=make_desc(); handle=ctypes.c_void_p()
    create_ret=mt.MT_Create(ctypes.byref(params),ctypes.byref(desc),ctypes.byref(handle)); h=handle.value or 0
    rep={'jpeg':str(jpeg),'use_type8_microjpeg_dev':use_type8,'reflected_source':reflected_source,'radiometric_profile':radiometric_profile,'create_ret':create_ret,'handle':hex(h) if h else None,'desc_info':desc_info,'setconfig':[]}
    if not h: return rep
    radiometric=None
    try: radiometric=radiometric_params_from_jpeg(jpeg)
    except Exception as e: rep['radiometric_error']=repr(e)
    rep['radiometric_params']=radiometric
    tag1_ref=tag1_internal_reflected_c(blocks['tag1'])
    reflected_c={'tag1_internal_avg':tag1_ref,'radiometric_reflected':(radiometric or {}).get('reflected_c',25.0),'radiometric_atmospheric':(radiometric or {}).get('atmospheric_c',25.0)}[reflected_source]
    emissivity=(radiometric or {}).get('emissivity',7946/8192)
    distance=(radiometric or {}).get('distance_m',1.0)
    rep['point_params']={'emissivity':emissivity,'reflected_c':reflected_c,'distance_m':distance,'tag1_internal_reflected_c':tag1_ref}
    cfg=[]
    calib_type=struct.unpack_from('<I',blocks['tag519'],8)[0]
    cfg.append((6,blocks['tag519'],'APP2 tag519 calibration'))
    cfg.append((1,type1_payload(15,calib_type),f'key15 calibration param type={calib_type}'))
    if radiometric:
        for key,value,label in radiometric_type1_pairs(radiometric,radiometric_profile):
            cfg.append((1,type1_payload(key,encode_type1_value(key,value)),f'{label}; value={value}'))
    if use_type8:
        dev=extract_microjpeg_dev_block(jpeg,dll_dir,0xD8)
        rep['microjpeg_dev_block']={k:v for k,v in dev.items() if k!='block'}
        cfg.append((8,dev['block'],'MicroJPEG TempDeviceConfigParams first 0xD8 bytes'))
    cfg.append((7,raw_frame,'APP3 raw_u16 + tag1 addline'))
    for typ,data,label in cfg:
        b=buf_from_bytes(data); ret=mt.MT_SetConfig(handle,typ,ctypes.cast(b,ctypes.c_void_p),len(data))
        rep['setconfig'].append({'type':typ,'len':len(data),'label':label,'ret':ret,'handle_summary':inspect_handle(h)})
    temps=[]; codes=[]; rets=[]; batch=4
    for start in range(0,len(raw_u16),batch):
        n=min(batch,len(raw_u16)-start); pts=ctypes.create_string_buffer(n*POINT_SIZE)
        for j in range(n):
            off=j*POINT_SIZE; g=raw_u16[start+j]
            struct.pack_into('<i',pts,off+4,g)
            struct.pack_into('<f',pts,off+0x14,float(emissivity))
            struct.pack_into('<f',pts,off+0x18,float(reflected_c))
            struct.pack_into('<f',pts,off+0x1c,float(distance))
        ret=mt.MT_Process(handle,0,ctypes.cast(pts,ctypes.c_void_p),n); rets.append(ret)
        for j in range(n):
            codes.append(struct.unpack_from('<i',pts.raw,j*POINT_SIZE)[0])
            temps.append(struct.unpack_from('<f',pts.raw,j*POINT_SIZE+0x10)[0])
    rep['process']={'count':len(temps),'batch_rets_unique':sorted(set(rets)),'codes_unique':sorted(set(codes))[:20],
                    'temp_min':min(temps),'temp_max':max(temps),'temp_mean':sum(temps)/len(temps),'first16':temps[:16]}
    csv_path=jpeg.with_name(jpeg.stem+'_이미지.csv')
    if csv_path.exists(): rep['validation_vs_csv']=validate(temps,flat_csv(csv_path))
    if out_matrix:
        out_matrix.parent.mkdir(parents=True,exist_ok=True)
        with out_matrix.open('w',newline='',encoding='utf-8') as f:
            w=csv.writer(f)
            for y in range(HEIGHT): w.writerow([f'{v:.6f}' for v in temps[y*WIDTH:(y+1)*WIDTH]])
        rep['saved_matrix']=str(out_matrix)
    return rep

def main() -> int:
    ap=argparse.ArgumentParser(); ap.add_argument('--dll-dir',type=Path,default=DLL_DIR_DEFAULT)
    ap.add_argument('--images',nargs='*',default=[f'IR_0000{i}.jpeg' for i in range(1,6)])
    ap.add_argument('--use-type8',action='store_true')
    ap.add_argument('--reflected-source',choices=['tag1_internal_avg','radiometric_reflected','radiometric_atmospheric'],default='tag1_internal_avg')
    ap.add_argument('--radiometric-profile',choices=['none','basic','with_window','with_expert','all_known'],default='none')
    ap.add_argument('--out',type=Path,default=Path('data/mini2_mtlib_microjpeg_dev_probe'))
    args=ap.parse_args(); args.out.mkdir(parents=True,exist_ok=True)
    rows=[]; per=[]
    for img in args.images:
        jpeg=Path(img)
        rep=mt_run_one(jpeg,args.dll_dir,args.use_type8,args.reflected_source,args.radiometric_profile,args.out/f'{jpeg.stem}_temps.csv')
        per.append(rep)
        out=args.out/f'{jpeg.stem}_mtlib_microjpeg_dev_probe.json'; out.write_text(json.dumps(rep,indent=2,ensure_ascii=False),encoding='utf-8')
        v=rep.get('validation_vs_csv') or {}
        rows.append({'stem':jpeg.stem,'use_type8':args.use_type8,'reflected_source':args.reflected_source,'radiometric_profile':args.radiometric_profile,
                     'mae':v.get('mae'),'max_abs':v.get('max_abs'),'match':v.get('rounded_0p1_match_rate'),'bias':v.get('bias'),
                     'gt005':v.get('count_abs_gt_0p05'),'gt010':v.get('count_abs_gt_0p10')})
        print(json.dumps(rows[-1],ensure_ascii=False))
    summary={'args':vars(args)|{'out':str(args.out),'dll_dir':str(args.dll_dir)},'rows':rows}
    (args.out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    with (args.out/'summary.csv').open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    return 0
if __name__=='__main__': raise SystemExit(main())
