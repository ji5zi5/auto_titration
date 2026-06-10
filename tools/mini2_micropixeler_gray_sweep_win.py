#!/usr/bin/env python3
from __future__ import annotations
import argparse, ctypes, json, os
from pathlib import Path
DLL_DIR_DEFAULT=Path(r'C:\Program Files\HIKMICRO Analyzer\HIKMICRO Analyzer')
class StdString(ctypes.Structure): _fields_=[('buf',ctypes.c_char*16),('size',ctypes.c_size_t),('capacity',ctypes.c_size_t)]
class StdVector(ctypes.Structure): _fields_=[('begin',ctypes.c_void_p),('end',ctypes.c_void_p),('cap',ctypes.c_void_p)]
class SharedPtr(ctypes.Structure): _fields_=[('ptr',ctypes.c_void_p),('ctrl',ctypes.c_void_p)]
def add_dir(d):
    if hasattr(os,'add_dll_directory'): os.add_dll_directory(str(d))
    ctypes.windll.kernel32.SetDllDirectoryW(str(d)); os.chdir(str(d))
def proc(dll,n):
    k=ctypes.windll.kernel32; k.GetProcAddress.argtypes=[ctypes.c_void_p,ctypes.c_char_p]; k.GetProcAddress.restype=ctypes.c_void_p
    a=k.GetProcAddress(dll._handle,n)
    if not a: raise RuntimeError(n)
    return int(a)
def sstr(s):
    b=s.encode('utf-8'); st=StdString(); keep=None
    if len(b)<16:
        ctypes.memmove(ctypes.addressof(st),b,len(b)); st.buf[len(b)]=0; st.size=len(b); st.capacity=15
    else:
        keep=ctypes.create_string_buffer(b+b'\0'); ctypes.memmove(ctypes.addressof(st),ctypes.byref(ctypes.c_void_p(ctypes.addressof(keep))),8); st.size=len(b); st.capacity=len(b)
    return st,keep
def hx(x): return hex(int(x)) if x else None
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--dll-dir',type=Path,default=DLL_DIR_DEFAULT); ap.add_argument('--jpeg',type=Path,required=True); ap.add_argument('--out',type=Path,default=Path('data/mini2_micropixeler_gray_sweep.json')); ap.add_argument('--grays',default='0,1,100,1000,3000,4500,5000,5200,5338,5500,6000,10000,20000,65535')
    a=ap.parse_args(); orig=Path.cwd(); jp=a.jpeg.resolve(); out=a.out if a.out.is_absolute() else orig/a.out
    add_dir(a.dll_dir); dll=ctypes.WinDLL(str(a.dll_dir/'MicroPixeler_Release_x64.dll'))
    st,keep=sstr(str(jp)); vec=StdVector(None,None,None); ot=ctypes.c_uint32(0); ob=ctypes.c_bool(False)
    parse=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint32),ctypes.POINTER(ctypes.c_bool),ctypes.POINTER(StdString),ctypes.POINTER(StdVector),ctypes.c_bool)(proc(dll,b'?parseRadiometricsJPEG@MaterialParseFactory@MICROPIXELER@@SAPEAVTakedMaterial@2@AEAIAEA_NAEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@AEBV?$vector@UCustomFusionMatchParam@iVMS4800@@V?$allocator@UCustomFusionMatchParam@iVMS4800@@@std@@@5@_N@Z'))
    mat=parse(ctypes.byref(ot),ctypes.byref(ob),ctypes.byref(st),ctypes.byref(vec),False)
    cdef=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_void_p)(proc(dll,b'?createDefault@AnalyzerBuilderManager@MICROPIXELER@@SA?AV?$shared_ptr@VAnalyzerBuilderManager@MICROPIXELER@@@std@@XZ'))
    builder=SharedPtr(); cdef(ctypes.byref(builder))
    ctor=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_void_p,ctypes.POINTER(SharedPtr))(proc(dll,b'??0TakedMaterialAnalyzControl@MICROPIXELER@@QEAA@V?$shared_ptr@VAnalyzerBuilderManager@MICROPIXELER@@@std@@@Z'))
    ctrl=ctypes.create_string_buffer(0x800); ctor(ctypes.byref(ctrl),ctypes.byref(builder))
    fake=SharedPtr(ctypes.c_void_p(mat),None)
    ta=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.POINTER(SharedPtr))(proc(dll,b'?tempAnalyze@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NV?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@@Z'))
    ta_ok=bool(ta(ctypes.byref(ctrl),ctypes.byref(fake)))
    gta=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.POINTER(ctypes.c_int32),ctypes.POINTER(SharedPtr),ctypes.c_int32)(proc(dll,b'?grayToTemp@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NAEAHV?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@H@Z'))
    ttg=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint16),ctypes.POINTER(SharedPtr),ctypes.c_int32)(proc(dll,b'?tempToGray@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NAEAGV?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@H@Z'))
    rows=[]
    for g in [int(x) for x in a.grays.split(',') if x.strip()]:
        o=ctypes.c_int32(-999999); ok=bool(gta(ctypes.byref(ctrl),ctypes.byref(o),ctypes.byref(fake),g))
        og=ctypes.c_uint16(65535); ok2=bool(ttg(ctypes.byref(ctrl),ctypes.byref(og),ctypes.byref(fake),g))
        rows.append({'in':g,'grayToTemp_ok':ok,'grayToTemp_out':int(o.value),'tempToGray_ok':ok2,'tempToGray_out':int(og.value)})
    rep={'jpeg':str(jp),'mat':hx(mat),'out_type':int(ot.value),'out_bool':bool(ob.value),'builder':{'ptr':hx(builder.ptr),'ctrl':hx(builder.ctrl)},'tempAnalyze_ok':ta_ok,'rows':rows}
    out.parent.mkdir(parents=True,exist_ok=True); out.write_text(json.dumps(rep,indent=2),encoding='utf-8'); print(json.dumps(rep,indent=2))
if __name__=='__main__': main()
