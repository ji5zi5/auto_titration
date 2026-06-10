#!/usr/bin/env python3
"""Probe Mini2 raw->temperature through MicroJPEG member getters + MicroJITA.

This is not CSV fitting. It uses the HIKMICRO DLLs and the full JPEG only:
1. MicroJPEG createImage parses the radiometric JPEG.
2. Correct MSVC member ABI copies RawDataInfo / TempDeviceConfigParams /
   TempMeasurementParameters from the MicroRImageV1 object.
3. MicroJITA createEmptyJPEG + setters + grayToTemperature converts raw grays.
CSV is used only for validation.
"""
from __future__ import annotations
import argparse, ctypes, csv, json, math, os, struct, sys
from pathlib import Path

DLL_DIR_DEFAULT = Path(r"C:\Program Files\HIKMICRO Analyzer\HIKMICRO Analyzer")
WIDTH = 256
HEIGHT = 192

class BareBlock(ctypes.Structure):
    _fields_ = [('data', ctypes.c_void_p), ('size', ctypes.c_uint32), ('pad', ctypes.c_uint32)]

def add_dll_dir(p: Path):
    if hasattr(os, 'add_dll_directory'):
        os.add_dll_directory(str(p))
    ctypes.windll.kernel32.SetDllDirectoryW(str(p))

def get_proc(dll, name: bytes) -> int:
    k = ctypes.windll.kernel32
    k.GetProcAddress.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    k.GetProcAddress.restype = ctypes.c_void_p
    a = k.GetProcAddress(dll._handle, name)
    if not a:
        raise RuntimeError(f'missing export {name!r}')
    return int(a)

def make_block(data: bytes):
    buf = ctypes.create_string_buffer(data, len(data))
    return buf, BareBlock(ctypes.cast(buf, ctypes.c_void_p), len(data), 0)

def raw_path_for(jpeg: Path) -> Path:
    for c in [
        Path('data/mini2_multi_image_formula/raw') / f'{jpeg.stem}_lpld_raw_u16_256x192.bin',
        Path('/mnt/c/Users/Jio/Downloads/auto_titration_20260513-170048/data/mini2_multi_image_formula/raw') / f'{jpeg.stem}_lpld_raw_u16_256x192.bin',
    ]:
        if c.exists():
            return c
    raise RuntimeError(f'raw missing for {jpeg}')

def csv_flat(path: Path) -> list[float]:
    last = None
    for enc in ['utf-8-sig','cp949','euc-kr','latin1']:
        try:
            text = path.read_text(encoding=enc)
            break
        except UnicodeDecodeError as e:
            last = e
    else:
        raise last or RuntimeError('decode failed')
    out=[]
    for row in csv.reader(text.splitlines()):
        vals=[]
        for cell in row:
            try: vals.append(float(cell.strip()))
            except Exception: pass
        if len(vals) >= WIDTH:
            vals = vals[-WIDTH:]
            if vals and max(vals) > 150: continue
            out.extend(vals)
    return out

def validate(outs: list[float], ref: list[float]) -> dict[str, object]:
    n=min(len(outs),len(ref))
    idxs=[i for i in range(n) if math.isfinite(outs[i])]
    diffs=[outs[i]-ref[i] for i in idxs]
    rd=[round(outs[i],1)-ref[i] for i in idxs]
    worst=sorted(idxs, key=lambda i: abs(outs[i]-ref[i]), reverse=True)[:24]
    return {
        'count': len(diffs),
        'mae': sum(abs(d) for d in diffs)/len(diffs) if diffs else None,
        'max_abs': max((abs(d) for d in diffs), default=None),
        'bias': sum(diffs)/len(diffs) if diffs else None,
        'rounded_0p1_mae': sum(abs(d) for d in rd)/len(rd) if rd else None,
        'rounded_0p1_max_abs': max((abs(d) for d in rd), default=None),
        'rounded_0p1_match_rate': sum(1 for d in rd if abs(d) < 1e-9)/len(rd) if rd else None,
        'count_abs_gt_0p05': sum(1 for d in diffs if abs(d)>0.05),
        'count_abs_gt_0p10': sum(1 for d in diffs if abs(d)>0.10),
        'worst_pairs': [[i, i//WIDTH, i%WIDTH, outs[i], ref[i], outs[i]-ref[i], round(outs[i],1)-ref[i]] for i in worst],
    }

def u32_list(buf: ctypes.Array, n=0x120):
    b=bytes(buf.raw[:n])
    return [struct.unpack_from('<I',b,i)[0] for i in range(0, len(b)//4*4, 4)]

def i32_list(buf: ctypes.Array, n=0x120):
    b=bytes(buf.raw[:n])
    return [struct.unpack_from('<i',b,i)[0] for i in range(0, len(b)//4*4, 4)]

def f32_list(buf: ctypes.Array, n=0x120):
    b=bytes(buf.raw[:n])
    return [struct.unpack_from('<f',b,i)[0] for i in range(0, len(b)//4*4, 4)]

def ptr_list(addr: int, n=0x120):
    out=[]
    for off in range(0,n,8):
        try: v=ctypes.c_void_p.from_address(addr+off).value or 0
        except Exception: break
        if v: out.append([hex(off),hex(v)])
    return out

def copy_member(addr: int, this_ptr: int, size: int, label: str) -> tuple[ctypes.Array, dict[str, object]]:
    # Correct MSVC x64 ABI observed in disassembly for these MicroJPEG members:
    # RCX=this, RDX=destination return buffer; function returns destination pointer.
    fn = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(addr)
    buf = ctypes.create_string_buffer(size)
    ret = fn(ctypes.c_void_p(this_ptr), ctypes.byref(buf))
    raw = bytes(buf.raw)
    return buf, {
        'label': label,
        'ret': hex(ret) if ret else None,
        'size': size,
        'hex_first128': raw[:128].hex(' '),
        'u32_first72': u32_list(buf, 0x120)[:72],
        'i32_first72': i32_list(buf, 0x120)[:72],
        'f32_first36': f32_list(buf, 0x90)[:36],
    }

def compact_ctx(ctx: int) -> dict[str, object]:
    if not ctx: return {}
    rep={'ctx':hex(ctx),'ptrs':ptr_list(ctx,0x120)}
    try:
        first = ctypes.c_void_p.from_address(ctx).value or 0
        rep['ctx_0_ptr']=hex(first) if first else None
        if first:
            rep['inner_u32_first16']=[ctypes.c_uint32.from_address(first+i).value for i in range(0,64,4)]
            rep['inner_ptrs']=ptr_list(first,0x80)
    except Exception as e:
        rep['ctx_error']=repr(e)
    return rep

def run_one(jpeg: Path, dll_dir: Path, limit: int, out_dir: Path) -> dict[str, object]:
    add_dll_dir(dll_dir)
    mj = ctypes.WinDLL(str(dll_dir/'MicroJPEG_Release_x64.dll'))
    jita = ctypes.WinDLL(str(dll_dir/'MicroJITA_Release_x64.dll'))

    # MicroJPEG exports
    file_type = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(BareBlock))(get_proc(mj,b'?fileType@MicroSDK@@YA?AW4FileType@1@AEBUBareBlock@1@@Z'))
    create_img = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.POINTER(BareBlock))(get_proc(mj,b'?createImage@MicroSDK@@YAPEAVBaseImage@1@AEBUBareBlock@1@@Z'))
    type_fn = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p)(get_proc(mj,b'?type@BaseImage@MicroSDK@@QEBA?AW4FileType@2@XZ'))
    raw_v1_addr = get_proc(mj,b'?rawDataInfo@MicroRImageV1@MicroSDK@@UEBA?AURawDataInfo@2@XZ')
    dev_v1_addr = get_proc(mj,b'?tempDeviceConfigParams@MicroRImageV1@MicroSDK@@UEBA?AUTempDeviceConfigParams@2@XZ')
    meas_v1_addr = get_proc(mj,b'?tempMeasurementParams@MicroRImageV1@MicroSDK@@UEBA?AUTempMeasurementParameters@2@XZ')
    dev_ref_v1 = ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p)(get_proc(mj,b'?tempDeviceConfigParams@MicroRImageV1@MicroSDK@@QEAAAEBUTempDeviceConfigParams@2@XZ'))

    # MicroJITA exports
    create_empty = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_void_p))(get_proc(jita,b'?createEmptyJPEG@MicroSDK@@YA_NAEAPEAX@Z'))
    destroy = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p)(get_proc(jita,b'?destroy@MicroSDK@@YA_NPEAX@Z'))
    set_raw = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(get_proc(jita,b'?setRawDataInfo@MicroSDK@@YA_NAEBURawDataInfo@1@PEAX@Z'))
    set_dev = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(get_proc(jita,b'?setTempDeviceConfigParams@MicroSDK@@YA_NAEBUTempDeviceConfigParams@1@PEAX@Z'))
    set_meas = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(get_proc(jita,b'?setTempMeasurementParams@MicroSDK@@YA_NAEBUTempMeasurementParameters@1@PEAX@Z'))
    gray_to_temp = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_int32), ctypes.c_uint16, ctypes.c_void_p)(get_proc(jita,b'?grayToTemperature@MicroSDK@@YA_NAEAHGQEAX@Z'))
    get_dev = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(get_proc(jita,b'?getTempDeviceConfigParams@MicroSDK@@YA_NAEAUTempDeviceConfigParams@1@QEAX@Z'))
    get_meas = ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(get_proc(jita,b'?getTempMeasurementParams@MicroSDK@@YA_NAEAUTempMeasurementParameters@1@QEAX@Z'))
    last_error = ctypes.CFUNCTYPE(ctypes.c_uint32)(get_proc(jita,b'?lastError@MicroSDK@@YAIXZ'))

    jpg_buf, bb = make_block(jpeg.read_bytes())
    ft = int(file_type(ctypes.byref(bb)))
    img = int(create_img(ctypes.byref(bb)) or 0)
    report: dict[str, object] = {'jpeg':str(jpeg),'file_type':ft,'microjpeg_ptr':hex(img) if img else None}
    if not img:
        report['error']='MicroJPEG createImage returned null'
        return report
    report['microjpeg_type']=int(type_fn(ctypes.c_void_p(img)))
    report['microjpeg_object_ptrs']=ptr_list(img,0x700)
    try:
        ref = int(dev_ref_v1(ctypes.c_void_p(img)) or 0)
        report['dev_ref_v1_ptr']=hex(ref) if ref else None
    except Exception as e:
        report['dev_ref_v1_exception']=repr(e)

    raw_info, raw_rep = copy_member(raw_v1_addr, img, 0x80, 'MicroRImageV1.rawDataInfo')
    dev_info, dev_rep = copy_member(dev_v1_addr, img, 0x200, 'MicroRImageV1.tempDeviceConfigParams')
    meas_info, meas_rep = copy_member(meas_v1_addr, img, 0x300, 'MicroRImageV1.tempMeasurementParams')
    report['member_getters']=[raw_rep,dev_rep,meas_rep]

    raw_path=raw_path_for(jpeg)
    raw_bytes=raw_path.read_bytes()
    raw_vals=list(struct.unpack('<'+'H'*(WIDTH*HEIGHT), raw_bytes[:WIDTH*HEIGHT*2]))
    report['raw_path']=str(raw_path)
    report['raw_stats']={'min':min(raw_vals),'max':max(raw_vals),'mean':sum(raw_vals)/len(raw_vals)}

    attempts=[]
    # Try plausible setter orders. For correct structs, meas may itself include dev.
    for order in [
        ['raw','dev','meas'], ['raw','meas','dev'], ['dev','meas','raw'], ['meas','dev','raw'],
        ['raw','dev'], ['raw','meas'], ['dev','raw'], ['meas','raw'],
    ]:
        ctx=ctypes.c_void_p()
        rec={'order':order, 'create_empty_ok':bool(create_empty(ctypes.byref(ctx))), 'ctx_initial':hex(ctx.value) if ctx.value else None, 'steps':[]}
        if ctx.value:
            rec['ctx_after_create']=compact_ctx(int(ctx.value))
            try:
                for step in order:
                    try:
                        if step == 'raw': ok=bool(set_raw(ctypes.byref(raw_info), ctx))
                        elif step == 'dev': ok=bool(set_dev(ctypes.byref(dev_info), ctx))
                        elif step == 'meas': ok=bool(set_meas(ctypes.byref(meas_info), ctx))
                        else: raise AssertionError(step)
                        rec['steps'].append([step, ok, int(last_error()), compact_ctx(int(ctx.value))])
                    except Exception as e:
                        rec['steps'].append([step, 'exception', repr(e), int(last_error()), compact_ctx(int(ctx.value))])
                for label,fn,sz in [('dev',get_dev,0x300),('meas',get_meas,0x400)]:
                    b=ctypes.create_string_buffer(sz)
                    try:
                        ok=bool(fn(ctypes.byref(b), ctx))
                        rec[f'get_{label}_ok']=ok; rec[f'get_{label}_last']=int(last_error())
                        rec[f'get_{label}_u32_first48']=u32_list(b,0xc0)[:48]
                    except Exception as e:
                        rec[f'get_{label}_exception']=repr(e); rec[f'get_{label}_last']=int(last_error())
                total=min(len(raw_vals), limit) if limit else len(raw_vals)
                outs=[]; ints=[]; okn=0; errs=[]
                for g in raw_vals[:total]:
                    o=ctypes.c_int32(-2147483648)
                    ok=bool(gray_to_temp(ctypes.byref(o), ctypes.c_uint16(g), ctx))
                    okn += int(ok); ints.append(int(o.value))
                    if not ok and len(errs)<16: errs.append(int(last_error()))
                    # MicroTA/JITA APIs normally output d3/deci-style signed int; infer scale later.
                    outs.append(float(o.value)/10.0 if ok else float('nan'))
                rec['gray_ok_count']=okn; rec['gray_errors_first16']=errs; rec['out_int_first16']=ints[:16]
                if okn:
                    finite=[x for x in outs if math.isfinite(x)]
                    rec['out_deci_c_stats']={'min':min(finite),'max':max(finite),'mean':sum(finite)/len(finite),'first16':outs[:16]}
                    csvp=jpeg.with_name(jpeg.stem+'_이미지.csv')
                    if csvp.exists():
                        refcsv=csv_flat(csvp)
                        rec['validation_vs_csv_deci']=validate(outs, refcsv)
                        # Also test common d3 scale only as unit inference, not fitting.
                        outs8192=[(v*10.0)/8192.0 if math.isfinite(v) else v for v in outs]
                        # Wait: outs was int/10, so convert original int /8192 below.
                        outs8192=[(ints[i]/8192.0 if i < len(ints) and math.isfinite(outs[i]) else float('nan')) for i in range(len(outs))]
                        rec['validation_vs_csv_d3']=validate(outs8192, refcsv)
            finally:
                try: destroy(ctx)
                except Exception: pass
        attempts.append(rec)
        print(json.dumps({
            'jpeg':jpeg.name,'order':order,'steps':[[s[0],s[1],s[2]] for s in rec.get('steps',[])],
            'gray_ok_count':rec.get('gray_ok_count'),
            'errs':rec.get('gray_errors_first16'),
            'deci_val':rec.get('validation_vs_csv_deci'),
            'd3_val':rec.get('validation_vs_csv_d3'),
        }, ensure_ascii=False))
    report['attempts']=attempts
    out_dir.mkdir(parents=True, exist_ok=True)
    out=out_dir/f'{jpeg.stem}_microjpeg_jita_correct_abi_probe.json'
    out.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    report['out']=str(out)
    print('saved:',out)
    return report

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument('--dll-dir', type=Path, default=DLL_DIR_DEFAULT)
    ap.add_argument('--jpeg', type=Path, action='append', required=True)
    ap.add_argument('--limit', type=int, default=4096, help='0 = all pixels')
    ap.add_argument('--out', type=Path, default=Path('data/mini2_microjpeg_jita_correct_abi_probe'))
    args=ap.parse_args()
    reports=[]
    for j in args.jpeg:
        reports.append(run_one(j,args.dll_dir,args.limit,args.out))
    summary=[]
    for r in reports:
        best=[]
        for a in r.get('attempts',[]):
            val=a.get('validation_vs_csv_deci') or a.get('validation_vs_csv_d3')
            if val: best.append((val.get('mae'), a.get('order'), val))
        best=sorted([b for b in best if b[0] is not None], key=lambda x:x[0])[:3]
        summary.append({'jpeg':r.get('jpeg'),'file_type':r.get('file_type'),'microjpeg_type':r.get('microjpeg_type'),'best':best})
    (args.out/'summary.json').write_text(json.dumps(summary,indent=2,ensure_ascii=False),encoding='utf-8')
    print('SUMMARY',json.dumps(summary,ensure_ascii=False,indent=2))
    return 0
if __name__=='__main__':
    raise SystemExit(main())
