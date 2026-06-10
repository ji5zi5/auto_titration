#!/usr/bin/env python3
"""Try MicroJITA grayToTemperature after injecting MicroJPEG-parsed params.

This uses only the JPEG + HIKMICRO DLLs. It creates a MicroRImageV1 via
MicroJPEG, points MicroJITA at the raw matrix, and injects the parameter block
from the MicroRImageV1 object (object+0x528 per disassembly).
"""
from __future__ import annotations
import argparse, ctypes, csv, json, math, os, struct
from pathlib import Path

DLL_DIR_DEFAULT=Path(r"C:\Program Files\HIKMICRO Analyzer\HIKMICRO Analyzer")
WIDTH=256; HEIGHT=192
class BareBlock(ctypes.Structure):
    _fields_=[('data',ctypes.c_void_p),('size',ctypes.c_uint32),('pad',ctypes.c_uint32)]

def add_dll_dir(p):
    if hasattr(os,'add_dll_directory'): os.add_dll_directory(str(p))
    ctypes.windll.kernel32.SetDllDirectoryW(str(p))
def get_proc(dll,name):
    k=ctypes.windll.kernel32; k.GetProcAddress.argtypes=[ctypes.c_void_p,ctypes.c_char_p]; k.GetProcAddress.restype=ctypes.c_void_p
    a=k.GetProcAddress(dll._handle,name)
    if not a: raise RuntimeError(f'missing {name!r}')
    return int(a)
def make_block(data):
    b=ctypes.create_string_buffer(data,len(data)); return b,BareBlock(ctypes.cast(b,ctypes.c_void_p),len(data),0)
def raw_path_for(jpeg):
    for c in [Path('data/mini2_multi_image_formula/raw')/f'{jpeg.stem}_lpld_raw_u16_256x192.bin', Path('/mnt/c/Users/Jio/Downloads/auto_titration_20260513-170048/data/mini2_multi_image_formula/raw')/f'{jpeg.stem}_lpld_raw_u16_256x192.bin']:
        if c.exists(): return c
    raise RuntimeError('raw missing')
def csv_flat(path):
    for enc in ['utf-8-sig','cp949','euc-kr','latin1']:
        try: text=path.read_text(encoding=enc); break
        except UnicodeDecodeError: pass
    rows=[]
    for row in csv.reader(text.splitlines()):
        vals=[]
        for cell in row:
            try: vals.append(float(cell.strip()))
            except: pass
        if len(vals)>=WIDTH:
            vals=vals[-WIDTH:]
            if max(vals)>150: continue
            rows.extend(vals)
    return rows
def validate(outs, ref):
    n=min(len(outs),len(ref)); diffs=[outs[i]-ref[i] for i in range(n) if math.isfinite(outs[i])]
    rd=[round(outs[i],1)-ref[i] for i in range(n) if math.isfinite(outs[i])]
    worst=sorted(range(n), key=lambda i: abs(outs[i]-ref[i]) if math.isfinite(outs[i]) else -1, reverse=True)[:16]
    return {'count':len(diffs),'mae':sum(abs(d) for d in diffs)/len(diffs) if diffs else None,'max_abs':max((abs(d) for d in diffs),default=None),'bias':sum(diffs)/len(diffs) if diffs else None,'rounded_0p1_mae':sum(abs(d) for d in rd)/len(rd) if rd else None,'rounded_0p1_match_rate':sum(1 for d in rd if abs(d)<1e-9)/len(rd) if rd else None,'worst_pairs':[[i,i//WIDTH,i%WIDTH,outs[i],ref[i],outs[i]-ref[i]] for i in worst]}

def u32s(addr,n=0x120):
    raw=ctypes.string_at(addr,n); return [struct.unpack_from('<I',raw,i)[0] for i in range(0,n,4)]

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--dll-dir',type=Path,default=DLL_DIR_DEFAULT); ap.add_argument('--jpeg',type=Path,required=True); ap.add_argument('--limit',type=int,default=4096); ap.add_argument('--out',type=Path,default=Path('data/mini2_jita_microjpeg_params_probe')); args=ap.parse_args()
    add_dll_dir(args.dll_dir)
    mj=ctypes.WinDLL(str(args.dll_dir/'MicroJPEG_Release_x64.dll')); jita=ctypes.WinDLL(str(args.dll_dir/'MicroJITA_Release_x64.dll'))
    create_img=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.POINTER(BareBlock))(get_proc(mj,b'?createImage@MicroSDK@@YAPEAVBaseImage@1@AEBUBareBlock@1@@Z'))
    type_fn=ctypes.CFUNCTYPE(ctypes.c_int32,ctypes.c_void_p)(get_proc(mj,b'?type@BaseImage@MicroSDK@@QEBA?AW4FileType@2@XZ'))
    create_empty=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.POINTER(ctypes.c_void_p))(get_proc(jita,b'?createEmptyJPEG@MicroSDK@@YA_NAEAPEAX@Z'))
    destroy=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p)(get_proc(jita,b'?destroy@MicroSDK@@YA_NPEAX@Z'))
    set_raw=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)(get_proc(jita,b'?setRawDataInfo@MicroSDK@@YA_NAEBURawDataInfo@1@PEAX@Z'))
    set_dev=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)(get_proc(jita,b'?setTempDeviceConfigParams@MicroSDK@@YA_NAEBUTempDeviceConfigParams@1@PEAX@Z'))
    set_meas=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)(get_proc(jita,b'?setTempMeasurementParams@MicroSDK@@YA_NAEBUTempMeasurementParameters@1@PEAX@Z'))
    gray_to_temp=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.POINTER(ctypes.c_int32),ctypes.c_uint16,ctypes.c_void_p)(get_proc(jita,b'?grayToTemperature@MicroSDK@@YA_NAEAHGQEAX@Z'))
    get_dev=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)(get_proc(jita,b'?getTempDeviceConfigParams@MicroSDK@@YA_NAEAUTempDeviceConfigParams@1@QEAX@Z'))
    get_meas=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)(get_proc(jita,b'?getTempMeasurementParams@MicroSDK@@YA_NAEAUTempMeasurementParameters@1@QEAX@Z'))
    last=ctypes.CFUNCTYPE(ctypes.c_uint32)(get_proc(jita,b'?lastError@MicroSDK@@YAIXZ'))
    jpgbuf,bb=make_block(args.jpeg.read_bytes()); img=create_img(ctypes.byref(bb)) or 0
    raw=raw_path_for(args.jpeg).read_bytes(); raw_vals=list(struct.unpack('<'+'H'*(WIDTH*HEIGHT), raw[:WIDTH*HEIGHT*2]))
    raw_buf=ctypes.create_string_buffer(raw[:WIDTH*HEIGHT*2])
    raw_info=ctypes.create_string_buffer(0x100)
    # RawDataInfo layout from get_raw output: width,height,format; pointer at +0x10; byte count at +0x20.
    struct.pack_into('<III', raw_info, 0, WIDTH, HEIGHT, 14)
    struct.pack_into('<Q', raw_info, 0x10, ctypes.addressof(raw_buf))
    struct.pack_into('<I', raw_info, 0x20, WIDTH*HEIGHT*2)
    param_ptr=img+0x528 if img else 0
    report={'jpeg':str(args.jpeg),'microjpeg_ptr':hex(img) if img else None,'microjpeg_type':int(type_fn(img)) if img else None,'param_ptr':hex(param_ptr) if param_ptr else None,'param_u32_first72':u32s(param_ptr,0x120) if param_ptr else None,'attempts':[]}
    orders=[
      ['raw','dev','meas'], ['raw','meas','dev'], ['dev','meas','raw'], ['meas','dev','raw'], ['raw','dev'], ['raw','meas']
    ]
    for order in orders:
        ctx=ctypes.c_void_p(); okc=bool(create_empty(ctypes.byref(ctx)))
        rec={'order':order,'create_ok':okc,'ctx':hex(ctx.value) if ctx.value else None,'steps':[]}
        if okc and ctx.value:
            try:
                for step in order:
                    try:
                        if step=='raw': ok=bool(set_raw(ctypes.byref(raw_info), ctx))
                        elif step=='dev': ok=bool(set_dev(ctypes.c_void_p(param_ptr), ctx))
                        elif step=='meas': ok=bool(set_meas(ctypes.c_void_p(param_ptr), ctx))
                        rec['steps'].append([step,ok,int(last())])
                    except Exception as e:
                        rec['steps'].append([step,'exception',repr(e),int(last())])
                for label,fn,sz in [('get_dev',get_dev,0x400),('get_meas',get_meas,0x600)]:
                    buf=ctypes.create_string_buffer(sz)
                    try:
                        ok=bool(fn(ctypes.byref(buf), ctx)); rec[label+'_ok']=ok; rec[label+'_last']=int(last()); rec[label+'_u32_first72']=[struct.unpack_from('<I',buf.raw,i)[0] for i in range(0,0x120,4)]
                    except Exception as e: rec[label+'_exception']=repr(e); rec[label+'_last']=int(last())
                total=min(args.limit,len(raw_vals)); outs=[]; okn=0; errs=[]; ints=[]
                for g in raw_vals[:total]:
                    o=ctypes.c_int32(-2147483648); ok=bool(gray_to_temp(ctypes.byref(o), ctypes.c_uint16(g), ctx)); okn+=int(ok); ints.append(int(o.value))
                    if not ok and len(errs)<10: errs.append(int(last()))
                    # try deci C first; also report raw int stats below
                    outs.append(o.value/10.0 if ok else float('nan'))
                rec['gray_ok_count']=okn; rec['gray_errors_first10']=errs; rec['out_int_first16']=ints[:16]
                if okn:
                    vals=[x for x in outs if math.isfinite(x)]; rec['out_c_stats']={'min':min(vals),'max':max(vals),'mean':sum(vals)/len(vals),'first16':outs[:16]}
                    csvp=args.jpeg.with_name(args.jpeg.stem+'_이미지.csv')
                    if csvp.exists(): rec['validation_vs_csv_deci']=validate(outs,csv_flat(csvp))
            finally:
                try: destroy(ctx)
                except Exception: pass
        report['attempts'].append(rec)
    args.out.mkdir(parents=True,exist_ok=True); out=args.out/f'{args.jpeg.stem}_jita_microjpeg_params_probe.json'; out.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    compact={'jpeg':report['jpeg'],'microjpeg_type':report['microjpeg_type'],'param_u32_first32':(report['param_u32_first72'] or [])[:32],'attempts':[{k:a.get(k) for k in ['order','steps','gray_ok_count','gray_errors_first10','out_int_first16','out_c_stats','validation_vs_csv_deci']} for a in report['attempts']], 'out':str(out)}
    print(json.dumps(compact,ensure_ascii=False,indent=2))
    return 0
if __name__=='__main__': raise SystemExit(main())
