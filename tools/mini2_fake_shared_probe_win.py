#!/usr/bin/env python3
from __future__ import annotations
import argparse, ctypes, json, os
from pathlib import Path
DLL_DIR_DEFAULT=Path(r'C:\Program Files\HIKMICRO Analyzer\HIKMICRO Analyzer')
class StdString(ctypes.Structure): _fields_=[('buf',ctypes.c_char*16),('size',ctypes.c_size_t),('capacity',ctypes.c_size_t)]
class StdVector(ctypes.Structure): _fields_=[('begin',ctypes.c_void_p),('end',ctypes.c_void_p),('cap',ctypes.c_void_p)]
class SharedPtr(ctypes.Structure): _fields_=[('ptr',ctypes.c_void_p),('ctrl',ctypes.c_void_p)]
KEEP=[]
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
        keep=ctypes.create_string_buffer(b+b'\0'); p=ctypes.c_void_p(ctypes.addressof(keep)); ctypes.memmove(ctypes.addressof(st),ctypes.byref(p),8); st.size=len(b); st.capacity=len(b)
    return st,keep
def hx(x): return hex(int(x)) if x else None
def words(addr,n=12):
    if not addr: return []
    return [hex(int(ctypes.c_uint64.from_address(int(addr)+8*i).value)) for i in range(n)]
def fake_ctrl(initial=1000000):
    # MSVC _Ref_count_base-like: vptr, uses counts at +8/+0xc. Keep counts high so destructors never hit callbacks.
    ctrl=ctypes.create_string_buffer(0x40)
    # dummy vtable of 4 nulls; if hit, crash, but counts should not hit zero.
    vt=(ctypes.c_void_p*4)()
    ctypes.c_void_p.from_buffer(ctrl,0).value=ctypes.addressof(vt)
    ctypes.c_uint32.from_buffer(ctrl,8).value=initial
    ctypes.c_uint32.from_buffer(ctrl,12).value=initial
    KEEP.extend([ctrl,vt])
    return ctypes.addressof(ctrl)
def parse_pix(pix,jp):
    st,keep=sstr(str(jp)); KEEP.append(keep); vec=StdVector(None,None,None); ot=ctypes.c_uint32(); ob=ctypes.c_bool()
    parse=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint32),ctypes.POINTER(ctypes.c_bool),ctypes.POINTER(StdString),ctypes.POINTER(StdVector),ctypes.c_bool)(proc(pix,b'?parseRadiometricsJPEG@MaterialParseFactory@MICROPIXELER@@SAPEAVTakedMaterial@2@AEAIAEA_NAEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@AEBV?$vector@UCustomFusionMatchParam@iVMS4800@@V?$allocator@UCustomFusionMatchParam@iVMS4800@@@std@@@5@_N@Z'))
    return parse(ctypes.byref(ot),ctypes.byref(ob),ctypes.byref(st),ctypes.byref(vec),False), {'out_type':ot.value,'out_bool':bool(ob.value)}
def make_ctrl(pix):
    cdef=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_void_p)(proc(pix,b'?createDefault@AnalyzerBuilderManager@MICROPIXELER@@SA?AV?$shared_ptr@VAnalyzerBuilderManager@MICROPIXELER@@@std@@XZ'))
    builder=SharedPtr(); cdef(ctypes.byref(builder))
    ctor=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_void_p,ctypes.POINTER(SharedPtr))(proc(pix,b'??0TakedMaterialAnalyzControl@MICROPIXELER@@QEAA@V?$shared_ptr@VAnalyzerBuilderManager@MICROPIXELER@@@std@@@Z'))
    obj=ctypes.create_string_buffer(0x3000); ctor(ctypes.byref(obj),ctypes.byref(builder)); KEEP.append(obj)
    return obj, builder
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--dll-dir',type=Path,default=DLL_DIR_DEFAULT); ap.add_argument('--jpeg',type=Path,default=Path('data/fixtures/mini2/IR_00001.jpeg')); ap.add_argument('--grays',default='5038,5100,5200,5338,5364'); ap.add_argument('--out',type=Path,default=Path('data/mini2_fake_shared_probe'))
    a=ap.parse_args(); orig=Path.cwd(); jp=a.jpeg.resolve(); outdir=a.out if a.out.is_absolute() else orig/a.out
    add_dir(a.dll_dir); pix=ctypes.WinDLL(str(a.dll_dir/'MicroPixeler_Release_x64.dll')); ana=ctypes.WinDLL(str(a.dll_dir/'MicroAnalytics_Release_x64.dll'))
    grays=[int(x) for x in a.grays.split(',') if x]
    mat,meta=parse_pix(pix,jp); ctrladdr=fake_ctrl(); sp=SharedPtr(ctypes.c_void_p(mat), ctypes.c_void_p(ctrladdr))
    rep={'jpeg':str(jp),'mat':hx(mat),'parse_meta':meta,'fake_ctrl':hx(ctrladdr),'fake_ctrl_words_start':words(ctrladdr,4)}
    # Direct MicroPixeler control
    cobj,builder=make_ctrl(pix); rep['builder']={'ptr':hx(builder.ptr),'ctrl':hx(builder.ctrl)}; rep['ctrl_words_before']=words(ctypes.addressof(cobj),10)
    for label, exp, ftype in [
        ('tempAnalyze_shared', b'?tempAnalyze@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NV?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@@Z', 'sp'),
        ('tempAnalyze_raw', b'?tempAnalyze@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NPEAVTakedMaterial@2@@Z', 'raw'),
    ]:
        try:
            if ftype=='sp': fn=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.POINTER(SharedPtr))(proc(pix,exp)); rep[label]=bool(fn(ctypes.byref(cobj),ctypes.byref(sp)))
            else: fn=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)(proc(pix,exp)); rep[label]=bool(fn(ctypes.byref(cobj),ctypes.c_void_p(mat)))
        except Exception as e: rep[label+'_exception']=repr(e)
    rep['ctrl_words_after_analyze']=words(ctypes.addressof(cobj),10)
    try:
        gta=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.POINTER(ctypes.c_int32),ctypes.POINTER(SharedPtr),ctypes.c_int32)(proc(pix,b'?grayToTemp@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NAEAHV?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@H@Z'))
        rows=[]
        for g in grays:
            o=ctypes.c_int32(-2147483648); ok=bool(gta(ctypes.byref(cobj),ctypes.byref(o),ctypes.byref(sp),g)); rows.append({'gray':g,'ok':ok,'out_int':int(o.value),'div10':None if o.value<-1000000 else o.value/10,'div100':None if o.value<-1000000 else o.value/100})
        rep['pix_grayToTemp']=rows
    except Exception as e: rep['pix_grayToTemp_exception']=repr(e)
    # TempMeasuredResultModel with same valid fake shared ptr.
    try:
        model=ctypes.create_string_buffer(0x3000); KEEP.append(model)
        ctor=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_void_p)(proc(ana,b'??0TempMeasuredResultModel@MicroAnalytics@@QEAA@XZ'))
        ctor(ctypes.byref(model))
        rep['model_head_after_default_ctor']=words(ctypes.addressof(model),10)
        setm=ctypes.CFUNCTYPE(None,ctypes.c_void_p,ctypes.POINTER(SharedPtr))(proc(ana,b'?setTakedMaterial@TempMeasuredResultModel@MicroAnalytics@@QEAAXV?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@@Z'))
        setm(ctypes.byref(model),ctypes.byref(sp))
        rep['model_head_after_set']=words(ctypes.addressof(model),10)
        gettbl=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.POINTER(SharedPtr))(proc(ana,b'?getGrayToTempTable@TempMeasuredResultModel@MicroAnalytics@@QEBA_NV?$shared_ptr@UGrayToTempTable@MICROPIXELER@@@std@@@Z'))
        tbl=SharedPtr(); rep['tempmodel_getGrayToTempTable_ok']=bool(gettbl(ctypes.byref(model),ctypes.byref(tbl))); rep['tempmodel_table']={'ptr':hx(tbl.ptr),'ctrl':hx(tbl.ctrl)}; rep['tempmodel_table_words']=words(tbl.ptr,20)
        gta2=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.POINTER(ctypes.c_int32),ctypes.c_uint16)(proc(ana,b'?grayToTemp@TempMeasuredResultModel@MicroAnalytics@@QEAA_NAEAHG@Z'))
        rows=[]
        for g in grays:
            o=ctypes.c_int32(-2147483648); ok=bool(gta2(ctypes.byref(model),ctypes.byref(o),ctypes.c_uint16(g))); rows.append({'gray':g,'ok':ok,'out_int':int(o.value),'div10':None if o.value<-1000000 else o.value/10,'div100':None if o.value<-1000000 else o.value/100})
        rep['tempmodel_grayToTemp']=rows
    except Exception as e: rep['tempmodel_exception']=repr(e)
    rep['fake_ctrl_words_end']=words(ctrladdr,4)
    outdir.mkdir(parents=True,exist_ok=True); op=outdir/(jp.stem+'_fake_shared_probe.json'); op.write_text(json.dumps(rep,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(rep,ensure_ascii=False,indent=2)[:30000]); print('saved:',op)
if __name__=='__main__': main()
