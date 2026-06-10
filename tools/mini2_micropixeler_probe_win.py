#!/usr/bin/env python3
from __future__ import annotations
import argparse, ctypes, json, os, sys
from pathlib import Path

DLL_DIR_DEFAULT = Path(r"C:\Program Files\HIKMICRO Analyzer\HIKMICRO Analyzer")

class StdString(ctypes.Structure):
    _fields_=[('buf',ctypes.c_char*16),('size',ctypes.c_size_t),('capacity',ctypes.c_size_t)]
class StdVector(ctypes.Structure):
    _fields_=[('begin',ctypes.c_void_p),('end',ctypes.c_void_p),('cap',ctypes.c_void_p)]
class SharedPtr(ctypes.Structure):
    _fields_=[('ptr',ctypes.c_void_p),('ctrl',ctypes.c_void_p)]
class SharedBlock(ctypes.Structure):
    _fields_=[('data',ctypes.c_void_p),('owner',ctypes.c_void_p),('size',ctypes.c_size_t)]

def make_std_string(s: str):
    b=s.encode('utf-8')
    st=StdString()
    # MSVC std::string layout: small-string buffer if cap < 16; size at +16, capacity at +24.
    if len(b) < 16:
        st.buf[:len(b)] = b
        st.buf[len(b)] = 0
        st.size=len(b); st.capacity=15
        keep=None
    else:
        keep=ctypes.create_string_buffer(b+b'\x00')
        ctypes.memmove(ctypes.addressof(st), ctypes.byref(ctypes.c_void_p(ctypes.addressof(keep))), ctypes.sizeof(ctypes.c_void_p))
        st.size=len(b); st.capacity=len(b)
    return st, keep

def add_dll_dir(dll_dir: Path):
    if hasattr(os,'add_dll_directory'):
        os.add_dll_directory(str(dll_dir))
    ctypes.windll.kernel32.SetDllDirectoryW(str(dll_dir))
    os.chdir(str(dll_dir))

def get_proc(dll, name: bytes):
    k=ctypes.windll.kernel32
    k.GetProcAddress.argtypes=[ctypes.c_void_p,ctypes.c_char_p]
    k.GetProcAddress.restype=ctypes.c_void_p
    a=k.GetProcAddress(dll._handle,name)
    if not a: raise RuntimeError(f'missing {name!r}')
    return int(a)

def ptr_hex(p): return hex(int(p)) if p else None

def mem_u64(addr, count=8):
    if not addr: return []
    arr=(ctypes.c_uint64*count).from_address(int(addr))
    return [hex(int(x)) for x in arr]

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--dll-dir',type=Path,default=DLL_DIR_DEFAULT)
    ap.add_argument('--jpeg',type=Path,required=True)
    ap.add_argument('--mode',choices=['parse','interface','graytotemp'],default='parse')
    ap.add_argument('--gray',type=int,default=5100)
    ap.add_argument('--out',type=Path,default=Path('data/mini2_micropixeler_probe'))
    a=ap.parse_args()
    orig_cwd = Path.cwd()
    jpeg_abs = a.jpeg.resolve()
    out_dir = a.out if a.out.is_absolute() else (orig_cwd / a.out)
    add_dll_dir(a.dll_dir)
    dll=ctypes.WinDLL(str(a.dll_dir/'MicroPixeler_Release_x64.dll'))
    rep={'jpeg':str(a.jpeg),'mode':a.mode,'gray':a.gray,'steps':[]}
    path=str(jpeg_abs)
    s,keep=make_std_string(path)
    vec=StdVector(None,None,None)
    out_type=ctypes.c_uint32(0xdeadbeef)
    out_bool=ctypes.c_bool(False)
    try:
        parse_addr=get_proc(dll,b'?parseRadiometricsJPEG@MaterialParseFactory@MICROPIXELER@@SAPEAVTakedMaterial@2@AEAIAEA_NAEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@AEBV?$vector@UCustomFusionMatchParam@iVMS4800@@V?$allocator@UCustomFusionMatchParam@iVMS4800@@@std@@@5@_N@Z')
        parse=ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_bool), ctypes.POINTER(StdString), ctypes.POINTER(StdVector), ctypes.c_bool)(parse_addr)
        mat=parse(ctypes.byref(out_type),ctypes.byref(out_bool),ctypes.byref(s),ctypes.byref(vec),False)
        rep['steps'].append({'parseRadiometricsJPEG_ptr':ptr_hex(mat),'out_type':int(out_type.value),'out_bool':bool(out_bool.value)})
    except Exception as e:
        rep['steps'].append({'parse_exception':repr(e)})
        mat=None
    if mat:
        try:
            get_tpi_addr=get_proc(dll,b'?getThermalPicInterface@TakedMaterial@MICROPIXELER@@QEAA?AV?$shared_ptr@VThermalPicInterface@MICROPIXELER@@@std@@XZ')
            get_tpi=ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(get_tpi_addr)
            sp=SharedPtr()
            rv=get_tpi(ctypes.c_void_p(mat), ctypes.byref(sp))
            rep['steps'].append({'getThermalPicInterface_rv':ptr_hex(rv),'shared_ptr':{'ptr':ptr_hex(sp.ptr),'ctrl':ptr_hex(sp.ctrl)},'tpi_mem':mem_u64(sp.ptr,8)})
        except Exception as e:
            rep['steps'].append({'getThermalPicInterface_exception':repr(e)})
            sp=SharedPtr()
        if getattr(sp,'ptr',None):
            try:
                get_tbl_addr=get_proc(dll,b'?getGrayToTempTable@ThermalPicInterface@MICROPIXELER@@UEBA?AV?$shared_ptr@UGrayToTempTable@MICROPIXELER@@@std@@XZ')
                get_tbl=ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(get_tbl_addr)
                tblsp=SharedPtr()
                rv=get_tbl(ctypes.c_void_p(sp.ptr), ctypes.byref(tblsp))
                rep['steps'].append({'getGrayToTempTable_rv':ptr_hex(rv),'table_sp':{'ptr':ptr_hex(tblsp.ptr),'ctrl':ptr_hex(tblsp.ctrl)},'table_mem':mem_u64(tblsp.ptr,32)})
            except Exception as e:
                rep['steps'].append({'getGrayToTempTable_exception':repr(e)})
            # Dump key SDK structs parsed by MicroPixeler from the JPEG. These are not CSV-derived.
            for label, exp in [
                ('tpi_rawDataInfo', b'?getRawDataInfo@ThermalPicInterface@MICROPIXELER@@UEBA_NAEAURawDataInfo@MicroSDK@@@Z'),
                ('tpi_measureEnvParams', b'?getMeasureEnvParams@ThermalPicInterface@MICROPIXELER@@UEBA_NAEAUMeasurementEnvParams@MicroSDK@@@Z'),
                ('tpi_tempMeasurementParams', b'?getTempMeasurementParams@ThermalPicInterface@MICROPIXELER@@UEBA_NAEAUTempMeasurementParameters@MicroSDK@@@Z'),
                ('tpi_capabilitiesSet', b'?getCapabilitiesSet@ThermalPicInterface@MICROPIXELER@@UEBA_NAEAUIRCapabilities@MicroSDK@@@Z'),
                ('tpi_levelSpanParams', b'?getLevelSpanParams@ThermalPicInterface@MICROPIXELER@@UEBA_NAEAULevelSpanParams@MicroSDK@@@Z'),
                ('tpi_pseudoColorParams', b'?getPseudoColorParams@ThermalPicInterface@MICROPIXELER@@UEBA_NAEAUPseudoColorParams@MicroSDK@@@Z'),
            ]:
                outb=ctypes.create_string_buffer(0x1000)
                try:
                    fn=ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(get_proc(dll, exp))
                    ok=bool(fn(ctypes.c_void_p(sp.ptr), ctypes.byref(outb)))
                    rep['steps'].append({label+'_ok':ok, label+'_u32':[int.from_bytes(outb.raw[i:i+4],'little',signed=False) for i in range(0,256,4)], label+'_i32':[int.from_bytes(outb.raw[i:i+4],'little',signed=True) for i in range(0,256,4)], label+'_u64':[hex(int.from_bytes(outb.raw[i:i+8],'little')) for i in range(0,128,8)]})
                except Exception as e:
                    rep['steps'].append({label+'_exception':repr(e)})
        if a.mode=='graytotemp':
            try:
                create_def_addr=get_proc(dll,b'?createDefault@AnalyzerBuilderManager@MICROPIXELER@@SA?AV?$shared_ptr@VAnalyzerBuilderManager@MICROPIXELER@@@std@@XZ')
                create_def=ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p)(create_def_addr)
                builder=SharedPtr(); rv=create_def(ctypes.byref(builder))
                rep['steps'].append({'createDefault_rv':ptr_hex(rv),'builder':{'ptr':ptr_hex(builder.ptr),'ctrl':ptr_hex(builder.ctrl)}})
                ctor_addr=get_proc(dll,b'??0TakedMaterialAnalyzControl@MICROPIXELER@@QEAA@V?$shared_ptr@VAnalyzerBuilderManager@MICROPIXELER@@@std@@@Z')
                ctor=ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.POINTER(SharedPtr))(ctor_addr)
                ctrl=ctypes.create_string_buffer(0x800)
                rv=ctor(ctypes.byref(ctrl), ctypes.byref(builder))
                rep['steps'].append({'control_ctor_rv':ptr_hex(rv),'control_u64':[hex(int.from_bytes(ctrl.raw[i:i+8],"little")) for i in range(0,0x80,8)]})
                # Build analysis/cache before grayToTemp. Try raw-pointer and shared_ptr overloads; both are non-destructive diagnostics.
                try:
                    ia_raw_addr=get_proc(dll,b'?imgAnalyzeSyn@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NPEAVTakedMaterial@2@@Z')
                    ia_raw=ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(ia_raw_addr)
                    rep['steps'].append({'imgAnalyzeSyn_raw_ok':bool(ia_raw(ctypes.byref(ctrl), ctypes.c_void_p(mat)))})
                except Exception as e:
                    rep['steps'].append({'imgAnalyzeSyn_raw_exception':repr(e)})
                try:
                    ia_sp_addr=get_proc(dll,b'?imgAnalyzeSyn@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NV?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@@Z')
                    ia_sp=ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.POINTER(SharedPtr))(ia_sp_addr)
                    tmp_sp=SharedPtr(ctypes.c_void_p(mat), None)
                    rep['steps'].append({'imgAnalyzeSyn_shared_ok':bool(ia_sp(ctypes.byref(ctrl), ctypes.byref(tmp_sp)))})
                except Exception as e:
                    rep['steps'].append({'imgAnalyzeSyn_shared_exception':repr(e)})
                try:
                    ta_raw_addr=get_proc(dll,b'?tempAnalyze@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NPEAVTakedMaterial@2@@Z')
                    ta_raw=ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(ta_raw_addr)
                    ok_ta_raw=bool(ta_raw(ctypes.byref(ctrl), ctypes.c_void_p(mat)))
                    rep['steps'].append({'tempAnalyze_raw_ok':ok_ta_raw})
                except Exception as e:
                    rep['steps'].append({'tempAnalyze_raw_exception':repr(e)})
                fake_mat=SharedPtr(ctypes.c_void_p(mat), None)
                try:
                    ta_sp_addr=get_proc(dll,b'?tempAnalyze@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NV?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@@Z')
                    ta_sp=ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.POINTER(SharedPtr))(ta_sp_addr)
                    ok_ta_sp=bool(ta_sp(ctypes.byref(ctrl), ctypes.byref(fake_mat)))
                    rep['steps'].append({'tempAnalyze_shared_ok':ok_ta_sp})
                except Exception as e:
                    rep['steps'].append({'tempAnalyze_shared_exception':repr(e)})
                try:
                    sp2=SharedPtr(); rv2=get_tpi(ctypes.c_void_p(mat), ctypes.byref(sp2))
                    tblsp2=SharedPtr(); rv3=get_tbl(ctypes.c_void_p(sp2.ptr), ctypes.byref(tblsp2)) if sp2.ptr else 0
                    rep['steps'].append({'postAnalyze_getThermalPicInterface':{'ptr':ptr_hex(sp2.ptr),'ctrl':ptr_hex(sp2.ctrl)}, 'postAnalyze_getGrayToTempTable':{'ptr':ptr_hex(tblsp2.ptr),'ctrl':ptr_hex(tblsp2.ctrl)}, 'postAnalyze_table_mem':mem_u64(tblsp2.ptr,64)})
                except Exception as e:
                    rep['steps'].append({'postAnalyze_table_exception':repr(e)})
                gta_addr=get_proc(dll,b'?grayToTemp@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NAEAHV?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@H@Z')
                gta=ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.POINTER(ctypes.c_int32), ctypes.POINTER(SharedPtr), ctypes.c_int32)(gta_addr)
                out=ctypes.c_int32(-999999)
                ok=bool(gta(ctypes.byref(ctrl), ctypes.byref(out), ctypes.byref(fake_mat), int(a.gray)))
                rep['steps'].append({'grayToTemp_ok':ok,'out_int':int(out.value)})
            except Exception as e:
                rep['steps'].append({'grayToTemp_exception':repr(e)})
    out_dir.mkdir(parents=True,exist_ok=True)
    op=out_dir/(a.jpeg.stem+'_'+a.mode+'_micropixeler_probe.json')
    op.write_text(json.dumps(rep,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(rep,ensure_ascii=False,indent=2)[:20000])
    print('saved:',op)
if __name__=='__main__': main()
