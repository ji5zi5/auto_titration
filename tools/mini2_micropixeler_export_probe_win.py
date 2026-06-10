#!/usr/bin/env python3
from __future__ import annotations
import argparse, ctypes, json, os
from pathlib import Path
DLL_DIR_DEFAULT=Path(r'C:\Program Files\HIKMICRO Analyzer\HIKMICRO Analyzer')
KEEP=[]
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
        # MSVC std::string small-string layout stores bytes directly in the
        # 16-byte inline buffer.  Assigning st.buf[i] is unreliable through
        # ctypes on Windows/Python because c_char arrays are exposed as bytes,
        # so copy the whole NUL-terminated payload at once.
        ctypes.memmove(ctypes.addressof(st),b+b'\0',len(b)+1); st.size=len(b); st.capacity=15
    else:
        keep=ctypes.create_string_buffer(b+b'\0'); p=ctypes.c_void_p(ctypes.addressof(keep)); ctypes.memmove(ctypes.addressof(st),ctypes.byref(p),8); st.size=len(b); st.capacity=len(b); KEEP.append(keep)
    return st
def fake_ctrl(initial=1000000):
    ctrl=ctypes.create_string_buffer(0x40); vt=(ctypes.c_void_p*4)(); ctypes.c_void_p.from_buffer(ctrl,0).value=ctypes.addressof(vt); ctypes.c_uint32.from_buffer(ctrl,8).value=initial; ctypes.c_uint32.from_buffer(ctrl,12).value=initial; KEEP.extend([ctrl,vt]); return ctypes.addressof(ctrl)
def hx(x): return hex(int(x)) if x else None
def parse_mat(pix,jpeg,flag=False):
    st=sstr(str(jpeg)); vec=StdVector(None,None,None); ot=ctypes.c_uint32(); ob=ctypes.c_bool()
    f=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint32),ctypes.POINTER(ctypes.c_bool),ctypes.POINTER(StdString),ctypes.POINTER(StdVector),ctypes.c_bool)(proc(pix,b'?parseRadiometricsJPEG@MaterialParseFactory@MICROPIXELER@@SAPEAVTakedMaterial@2@AEAIAEA_NAEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@AEBV?$vector@UCustomFusionMatchParam@iVMS4800@@V?$allocator@UCustomFusionMatchParam@iVMS4800@@@std@@@5@_N@Z'))
    return f(ctypes.byref(ot),ctypes.byref(ob),ctypes.byref(st),ctypes.byref(vec),flag), {'out_type':ot.value,'out_bool':bool(ob.value),'flag':flag}
def analyze(pix,mat):
    cdef=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_void_p)(proc(pix,b'?createDefault@AnalyzerBuilderManager@MICROPIXELER@@SA?AV?$shared_ptr@VAnalyzerBuilderManager@MICROPIXELER@@@std@@XZ'))
    ctor=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_void_p,ctypes.POINTER(SharedPtr))(proc(pix,b'??0TakedMaterialAnalyzControl@MICROPIXELER@@QEAA@V?$shared_ptr@VAnalyzerBuilderManager@MICROPIXELER@@@std@@@Z'))
    temp=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.POINTER(SharedPtr))(proc(pix,b'?tempAnalyze@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NV?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@@Z'))
    sp=SharedPtr(ctypes.c_void_p(mat),ctypes.c_void_p(fake_ctrl()))
    b=SharedPtr(); cdef(ctypes.byref(b)); obj=ctypes.create_string_buffer(0x5000); KEEP.append(obj); ctor(ctypes.byref(obj),ctypes.byref(b))
    return bool(temp(ctypes.byref(obj),ctypes.byref(sp)))
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--dll-dir',type=Path,default=DLL_DIR_DEFAULT); ap.add_argument('--jpeg',type=Path,required=True); ap.add_argument('--out',type=Path,default=Path('data/mini2_micropixeler_export_probe'))
    a=ap.parse_args(); orig=Path.cwd(); jpeg=a.jpeg.resolve(); outdir=a.out if a.out.is_absolute() else orig/a.out; outdir.mkdir(parents=True,exist_ok=True)
    add_dir(a.dll_dir); pix=ctypes.WinDLL(str(a.dll_dir/'MicroPixeler_Release_x64.dll')); os.chdir(str(orig))
    rep={'jpeg':str(jpeg),'cases':[]}
    exports=[
      ('exportAnalyzableThermalPic', b'?exportAnalyzableThermalPic@MaterialParseFactory@MICROPIXELER@@SA_NV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@V?$shared_ptr@VTakedMaterial@MICROPIXELER@@@4@@Z','bool'),
      ('exportAnalyzableAcousticPic', b'?exportAnalyzableAcousticPic@MaterialParseFactory@MICROPIXELER@@SA_NV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@V?$shared_ptr@VTakedMaterial@MICROPIXELER@@@4@@Z','bool'),
      ('saveAsThermalPicModify', b'?saveAsThermalPicModify@MaterialParseFactory@MICROPIXELER@@SA_NV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@V?$shared_ptr@VTakedMaterial@MICROPIXELER@@@4@@Z','bool'),
    ]
    for flag in [False,True]:
      mat,meta=parse_mat(pix,jpeg,flag); sp=SharedPtr(ctypes.c_void_p(mat),ctypes.c_void_p(fake_ctrl()))
      for do_an in [False,True]:
        if do_an and mat: an=analyze(pix,mat)
        else: an=None
        for label,exp,kind in exports:
          rec={'flag':flag,'mat':hx(mat),'parse':meta,'analyzed':an,'export':label}
          try:
            # Export function takes std::string by value; keep the argument SSO-short so its destructor won't free Python memory.
            short_name=f'e{len(rep["cases"])}.jpg'
            path=orig/short_name
            ss=sstr(short_name)
            if kind=='bool':
              fn=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.POINTER(StdString),ctypes.POINTER(SharedPtr))(proc(pix,exp))
              ok=bool(fn(ctypes.byref(ss),ctypes.byref(sp)))
              rec['ok']=ok
            rec['path']=str(path); rec['exists']=path.exists(); rec['size']=path.stat().st_size if path.exists() else None
          except Exception as e: rec['exception']=repr(e)
          rep['cases'].append(rec)
    op=outdir/(jpeg.stem+'_export_probe.json'); op.write_text(json.dumps(rep,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(rep,ensure_ascii=False,indent=2)[:20000]); print('saved:',op)
if __name__=='__main__': main()
