#!/usr/bin/env python3
from __future__ import annotations
import argparse, ctypes, json, os
from pathlib import Path
DLL_DIR_DEFAULT = Path(r"C:\Program Files\HIKMICRO Analyzer\HIKMICRO Analyzer")
class StdString(ctypes.Structure):
    _fields_=[('buf',ctypes.c_char*16),('size',ctypes.c_size_t),('capacity',ctypes.c_size_t)]
class StdVector(ctypes.Structure):
    _fields_=[('begin',ctypes.c_void_p),('end',ctypes.c_void_p),('cap',ctypes.c_void_p)]
class SharedPtr(ctypes.Structure):
    _fields_=[('ptr',ctypes.c_void_p),('ctrl',ctypes.c_void_p)]
class BareBlock(ctypes.Structure):
    _fields_=[('data',ctypes.c_void_p),('size',ctypes.c_uint32),('pad',ctypes.c_uint32)]
def make_std_string(s:str):
    b=s.encode('utf-8'); st=StdString(); keep=None
    if len(b)<16:
        ctypes.memmove(ctypes.addressof(st), b, len(b)); st.buf[len(b)]=0; st.size=len(b); st.capacity=15
    else:
        keep=ctypes.create_string_buffer(b+b'\0')
        ctypes.memmove(ctypes.addressof(st), ctypes.byref(ctypes.c_void_p(ctypes.addressof(keep))), ctypes.sizeof(ctypes.c_void_p)); st.size=len(b); st.capacity=len(b)
    return st,keep
def add_dll_dir(dll_dir:Path):
    if hasattr(os,'add_dll_directory'): os.add_dll_directory(str(dll_dir))
    ctypes.windll.kernel32.SetDllDirectoryW(str(dll_dir)); os.chdir(str(dll_dir))
def get_proc(dll,name:bytes):
    k=ctypes.windll.kernel32; k.GetProcAddress.argtypes=[ctypes.c_void_p,ctypes.c_char_p]; k.GetProcAddress.restype=ctypes.c_void_p
    a=k.GetProcAddress(dll._handle,name)
    if not a: raise RuntimeError(f'missing {name!r}')
    return int(a)
def hx(v): return hex(int(v)) if v else None
def u64(addr): return int(ctypes.c_uint64.from_address(int(addr)).value)
def ptr_rva(p,base): return hex(int(p)-base) if p and base <= int(p) < base+0x4000000 else None
def decode(buf,n=128):
    raw=bytes(buf.raw[:n])
    return {'u32':[int.from_bytes(raw[i:i+4],'little') for i in range(0,n,4)], 'hex':raw.hex(' ')}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--dll-dir',type=Path,default=DLL_DIR_DEFAULT); ap.add_argument('--jpeg',type=Path,required=True); ap.add_argument('--gray',type=int,default=5338); ap.add_argument('--out',type=Path,default=Path('data/mini2_micropixeler_parser_matrix'))
    a=ap.parse_args(); orig=Path.cwd(); jpeg_abs=a.jpeg.resolve(); out_dir=a.out if a.out.is_absolute() else orig/a.out
    add_dll_dir(a.dll_dir)
    pix=ctypes.WinDLL(str(a.dll_dir/'MicroPixeler_Release_x64.dll'))
    jita=ctypes.WinDLL(str(a.dll_dir/'MicroJITA_Release_x64.dll'))
    base=int(pix._handle)
    rep={'jpeg':str(jpeg_abs),'module_base':hx(base),'gray':a.gray,'results':[]}
    s,keep=make_std_string(str(jpeg_abs)); vec=StdVector(None,None,None)
    parsers=[]
    # parser name, callable, args_builder
    try:
        addr=get_proc(pix,b'?parseRadiometricsJPEG@MaterialParseFactory@MICROPIXELER@@SAPEAVTakedMaterial@2@AEAIAEA_NAEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@AEBV?$vector@UCustomFusionMatchParam@iVMS4800@@V?$allocator@UCustomFusionMatchParam@iVMS4800@@@std@@@5@_N@Z')
        fn=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint32),ctypes.POINTER(ctypes.c_bool),ctypes.POINTER(StdString),ctypes.POINTER(StdVector),ctypes.c_bool)(addr)
        parsers.append(('parseRadiometrics_false', lambda fn=fn: (fn(ctypes.byref(ctypes.c_uint32(0)),ctypes.byref(ctypes.c_bool(False)),ctypes.byref(s),ctypes.byref(vec),False),{})))
        parsers.append(('parseRadiometrics_true', lambda fn=fn: (fn(ctypes.byref(ctypes.c_uint32(0)),ctypes.byref(ctypes.c_bool(False)),ctypes.byref(s),ctypes.byref(vec),True),{})))
    except Exception as e: rep['results'].append({'parser':'parseRadiometrics_setup','exception':repr(e)})
    for nm,exp in [('parseElecThermalJPEG',b'?parseElecThermalJPEG@MaterialParseFactory@MICROPIXELER@@SAPEAVTakedMaterial@2@AEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@@Z'),('parseNormalJPEG',b'?parseNormalJPEG@MaterialParseFactory@MICROPIXELER@@SAPEAVTakedMaterial@2@AEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@@Z')]:
        try:
            fn=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.POINTER(StdString))(get_proc(pix,exp))
            parsers.append((nm, lambda fn=fn: (fn(ctypes.byref(s)),{})))
        except Exception as e: rep['results'].append({'parser':nm+'_setup','exception':repr(e)})
    try:
        fn=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.POINTER(StdString),ctypes.POINTER(StdVector))(get_proc(pix,b'?createMaterialQ@MaterialParseFactory@MICROPIXELER@@SAPEAVTakedMaterial@2@AEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@AEBV?$vector@UCustomFusionMatchParam@iVMS4800@@V?$allocator@UCustomFusionMatchParam@iVMS4800@@@std@@@5@@Z'))
        parsers.append(('createMaterialQ_auto', lambda: (fn(ctypes.byref(s),ctypes.byref(vec)),{})))
    except Exception as e: rep['results'].append({'parser':'createMaterialQ_auto_setup','exception':repr(e)})
    try:
        fn=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_int32,ctypes.POINTER(StdString),ctypes.POINTER(StdVector),ctypes.c_bool)(get_proc(pix,b'?createMaterialQ@MaterialParseFactory@MICROPIXELER@@SAPEAVTakedMaterial@2@W4MaterialType@iVMS4800@@AEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@AEBV?$vector@UCustomFusionMatchParam@iVMS4800@@V?$allocator@UCustomFusionMatchParam@iVMS4800@@@std@@@7@_N@Z'))
        for mt in range(0,16):
            parsers.append((f'createMaterialQ_type{mt}_false', lambda mt=mt,fn=fn: (fn(mt,ctypes.byref(s),ctypes.byref(vec),False),{'material_type':mt,'flag':False})))
            parsers.append((f'createMaterialQ_type{mt}_true', lambda mt=mt,fn=fn: (fn(mt,ctypes.byref(s),ctypes.byref(vec),True),{'material_type':mt,'flag':True})))
    except Exception as e: rep['results'].append({'parser':'createMaterialQ_typed_setup','exception':repr(e)})

    # exports for testing
    get_jpeg=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_void_p)(get_proc(pix,b'?getJPEG@TakedMaterial@MICROPIXELER@@QEBAPEAXXZ'))
    get_tpi=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p)(get_proc(pix,b'?getThermalPicInterface@TakedMaterial@MICROPIXELER@@QEAA?AV?$shared_ptr@VThermalPicInterface@MICROPIXELER@@@std@@XZ'))
    tpi_raw_ptr=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_void_p)(get_proc(pix,b'?thermalPicInterface@TakedMaterial@MICROPIXELER@@QEBAPEBVThermalPicInterface@2@XZ'))
    j_get_raw=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)(get_proc(jita,b'?getRawDataInfo@MicroSDK@@YA_NAEAURawDataInfo@1@QEAX@Z'))
    j_gray=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_uint16,ctypes.c_void_p)(get_proc(jita,b'?grayToTemperature@MicroSDK@@YA_NAEAHGQEAX@Z'))
    j_format=ctypes.CFUNCTYPE(ctypes.c_int32,ctypes.c_void_p)(get_proc(jita,b'?format@MicroSDK@@YA?AW4JPEGFormat@1@QEAX@Z'))
    j_last=ctypes.CFUNCTYPE(ctypes.c_uint32)(get_proc(jita,b'?lastError@MicroSDK@@YAIXZ'))

    for name,call in parsers:
        rec={'parser':name}
        try:
            mat,extra=call(); rec.update(extra); rec['mat']=hx(mat)
            if mat:
                mv=u64(mat); rec['mat_vptr']=hx(mv); rec['mat_vptr_rva']=ptr_rva(mv,base)
                try:
                    jpeg_ctx=get_jpeg(ctypes.c_void_p(mat)); rec['getJPEG_ctx']=hx(jpeg_ctx)
                    if jpeg_ctx:
                        rec['jita_format_ctx']=int(j_format(jpeg_ctx))
                        rb=ctypes.create_string_buffer(0x200); rec['jita_getRaw_ok']=bool(j_get_raw(ctypes.byref(rb),jpeg_ctx)); rec['jita_getRaw_last']=int(j_last()); rec['jita_raw_u32']=decode(rb,128)['u32']
                        out=ctypes.c_int32(-999999); rec['jita_gray_ok']=bool(j_gray(ctypes.byref(out),ctypes.c_uint16(a.gray),jpeg_ctx)); rec['jita_gray_out']=int(out.value); rec['jita_gray_last']=int(j_last())
                except Exception as e: rec['getJPEG_exception']=repr(e)
                try:
                    rawt=tpi_raw_ptr(ctypes.c_void_p(mat)); rec['thermalPicInterface_raw']=hx(rawt)
                except Exception as e: rec['thermalPicInterface_raw_exception']=repr(e)
                try:
                    sp=SharedPtr(); get_tpi(ctypes.c_void_p(mat),ctypes.byref(sp)); rec['tpi_sp']={'ptr':hx(sp.ptr),'ctrl':hx(sp.ctrl)}
                    if sp.ptr:
                        tv=u64(sp.ptr); rec['tpi_vptr_rva']=ptr_rva(tv,base); rec['tpi_minus30']=hx(u64(sp.ptr-0x30));
                        # tryData and rawdata via vtable
                        tryfn=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p)(u64(tv+0*8)); rec['tpi_tryData']=bool(tryfn(ctypes.c_void_p(sp.ptr)))
                        rb=ctypes.create_string_buffer(0x200); rawfn=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)(u64(tv+12*8)); rec['tpi_v_raw_ok']=bool(rawfn(ctypes.c_void_p(sp.ptr),ctypes.byref(rb))); rec['tpi_v_raw_u32']=decode(rb,128)['u32']
                except Exception as e: rec['tpi_exception']=repr(e)
        except Exception as e:
            rec['exception']=repr(e)
        rep['results'].append(rec)
    out_dir.mkdir(parents=True,exist_ok=True); op=out_dir/(jpeg_abs.stem+'_parser_matrix.json'); op.write_text(json.dumps(rep,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(rep,ensure_ascii=False,indent=2)[:30000]); print('saved:',op)
if __name__=='__main__': main()
