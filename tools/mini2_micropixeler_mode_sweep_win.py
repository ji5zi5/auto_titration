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
    if keep is not None: KEEP.append(keep)
    return st,keep
def fake_ctrl(initial=1000000):
    ctrl=ctypes.create_string_buffer(0x40); vt=(ctypes.c_void_p*4)()
    ctypes.c_void_p.from_buffer(ctrl,0).value=ctypes.addressof(vt)
    ctypes.c_uint32.from_buffer(ctrl,8).value=initial; ctypes.c_uint32.from_buffer(ctrl,12).value=initial
    KEEP.extend([ctrl,vt]); return ctypes.addressof(ctrl)
def hx(x): return hex(int(x)) if x else None
def u64(addr): return int(ctypes.c_uint64.from_address(int(addr)).value) if addr else 0
def words(addr,n=16):
    if not addr: return []
    out=[]
    for i in range(n):
        try: out.append(hex(u64(int(addr)+8*i)))
        except Exception: out.append('ERR'); break
    return out
def parse_all(ana,pix,jp):
    st,keep=sstr(str(jp)); vec=StdVector(None,None,None); mats=[]
    try:
        f=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint32),ctypes.POINTER(ctypes.c_bool),ctypes.POINTER(StdString),ctypes.POINTER(StdVector),ctypes.c_bool)(proc(pix,b'?parseRadiometricsJPEG@MaterialParseFactory@MICROPIXELER@@SAPEAVTakedMaterial@2@AEAIAEA_NAEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@AEBV?$vector@UCustomFusionMatchParam@iVMS4800@@V?$allocator@UCustomFusionMatchParam@iVMS4800@@@std@@@5@_N@Z'))
        for flag in (False,True):
            ot=ctypes.c_uint32(0); ob=ctypes.c_bool(False); mat=f(ctypes.byref(ot),ctypes.byref(ob),ctypes.byref(st),ctypes.byref(vec),flag)
            if mat: mats.append((f'pix_parseRadiometrics flag={flag}',mat,{'out_type':ot.value,'out_bool':bool(ob.value)}))
    except Exception as e: mats.append(('pix_parse_exception',0,{'exception':repr(e)}))
    try:
        f=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_int32,ctypes.POINTER(StdString),ctypes.POINTER(StdVector),ctypes.c_bool)(proc(ana,b'?createMaterialQ@FileParseFactory@MicroAnalytics@@SAPEAVTakedMaterial@MICROPIXELER@@W4MaterialType@iVMS4800@@AEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@AEBV?$vector@UCustomFusionMatchParam@iVMS4800@@V?$allocator@UCustomFusionMatchParam@iVMS4800@@@std@@@8@_N@Z'))
        for mt in range(0,12):
            for flag in (False,True):
                try:
                    mat=f(mt,ctypes.byref(st),ctypes.byref(vec),flag)
                    if mat: mats.append((f'ana_createMaterialQ type={mt} flag={flag}',mat,{}))
                except Exception as e: mats.append((f'ana_createMaterialQ type={mt} flag={flag}',0,{'exception':repr(e)}))
    except Exception as e: mats.append(('ana_create_setup_exception',0,{'exception':repr(e)}))
    return mats
def make_control(pix, mode=None):
    # Try explicit AnalyzerBuilderManager object instead of null createDefault too.
    builder_obj=ctypes.create_string_buffer(0x1000); KEEP.append(builder_obj)
    try:
        ctor_b=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_void_p)(proc(pix,b'??0AnalyzerBuilderManager@MICROPIXELER@@QEAA@XZ'))
        ctor_b(ctypes.byref(builder_obj))
    except Exception:
        pass
    bctrl=fake_ctrl(); builder_sp=SharedPtr(ctypes.c_void_p(ctypes.addressof(builder_obj)),ctypes.c_void_p(bctrl))
    ctrl=ctypes.create_string_buffer(0x4000); KEEP.append(ctrl)
    ctor=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_void_p,ctypes.POINTER(SharedPtr))(proc(pix,b'??0TakedMaterialAnalyzControl@MICROPIXELER@@QEAA@V?$shared_ptr@VAnalyzerBuilderManager@MICROPIXELER@@@std@@@Z'))
    ctor(ctypes.byref(ctrl),ctypes.byref(builder_sp))
    if mode is not None:
        try:
            setmode=ctypes.CFUNCTYPE(None,ctypes.c_void_p,ctypes.c_int32)(proc(pix,b'?setAnalyzeMode@TakedMaterialAnalyzControl@MICROPIXELER@@QEAAXW4AnalyzeMode@2@@Z'))
            setmode(ctypes.byref(ctrl),int(mode))
        except Exception as e:
            pass
    return ctrl

def get_tpi_table(pix, mat):
    rec={}
    try:
        tpi_raw=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_void_p)(proc(pix,b'?thermalPicInterface@TakedMaterial@MICROPIXELER@@QEBAPEBVThermalPicInterface@2@XZ'))
        tpi=tpi_raw(ctypes.c_void_p(mat)); rec['tpi_raw']=hx(tpi); rec['tpi_words']=words(tpi,24)
        if tpi:
            gettbl=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_void_p,ctypes.POINTER(SharedPtr))(proc(pix,b'?getGrayToTempTable@ThermalPicInterface@MICROPIXELER@@UEBA?AV?$shared_ptr@UGrayToTempTable@MICROPIXELER@@@std@@XZ'))
            sp=SharedPtr(); gettbl(ctypes.c_void_p(tpi),ctypes.byref(sp)); rec['table_sp']={'ptr':hx(sp.ptr),'ctrl':hx(sp.ctrl)}; rec['table_words']=words(sp.ptr,24)
    except Exception as e: rec['tpi_table_exception']=repr(e)
    return rec

def run_sequence(pix, ana, mat, grays, mode, seq):
    rec={'mode':mode,'seq':seq}
    sp=SharedPtr(ctypes.c_void_p(mat),ctypes.c_void_p(fake_ctrl()))
    ctrl=make_control(pix,mode)
    rec['ctrl_before']=words(ctypes.addressof(ctrl),14)
    calls={
        'imgAnalyzeSyn_shared': (b'?imgAnalyzeSyn@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NV?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@@Z','sp'),
        'imgAnalyzeSyn_raw': (b'?imgAnalyzeSyn@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NPEAVTakedMaterial@2@@Z','raw'),
        'imgAnalyze_shared_false': (b'?imgAnalyze@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NV?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@_N@Z','sp_bool_false'),
        'imgAnalyze_shared_true': (b'?imgAnalyze@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NV?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@_N@Z','sp_bool_true'),
        'imgAnalyze_raw_false': (b'?imgAnalyze@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NPEAVTakedMaterial@2@_N@Z','raw_bool_false'),
        'imgAnalyze_raw_true': (b'?imgAnalyze@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NPEAVTakedMaterial@2@_N@Z','raw_bool_true'),
        'tempAnalyze_shared': (b'?tempAnalyze@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NV?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@@Z','sp'),
        'tempAnalyze_raw': (b'?tempAnalyze@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NPEAVTakedMaterial@2@@Z','raw'),
        'ruleAreaMeasure_shared': (b'?ruleAreaMeasure@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NV?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@@Z','sp'),
        'ruleAreaMeasure_raw': (b'?ruleAreaMeasure@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NPEAVTakedMaterial@2@@Z','raw'),
        'pcmFilterProcess_shared': (b'?pcmFilterProcess@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NV?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@@Z','sp'),
        'pcmFilterProcess_raw': (b'?pcmFilterProcess@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NPEAVTakedMaterial@2@@Z','raw'),
    }
    call_results=[]
    for name in seq:
        exp,typ=calls[name]
        try:
            if typ=='sp': fn=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.POINTER(SharedPtr))(proc(pix,exp)); ok=bool(fn(ctypes.byref(ctrl),ctypes.byref(sp)))
            elif typ=='raw': fn=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)(proc(pix,exp)); ok=bool(fn(ctypes.byref(ctrl),ctypes.c_void_p(mat)))
            elif typ.startswith('sp_bool'): fn=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.POINTER(SharedPtr),ctypes.c_bool)(proc(pix,exp)); ok=bool(fn(ctypes.byref(ctrl),ctypes.byref(sp),typ.endswith('true')))
            elif typ.startswith('raw_bool'): fn=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p,ctypes.c_bool)(proc(pix,exp)); ok=bool(fn(ctypes.byref(ctrl),ctypes.c_void_p(mat),typ.endswith('true')))
            call_results.append({'call':name,'ok':ok})
        except Exception as e: call_results.append({'call':name,'exception':repr(e)})
    rec['call_results']=call_results; rec['ctrl_after']=words(ctypes.addressof(ctrl),20); rec.update(get_tpi_table(pix,mat))
    try:
        gta=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.POINTER(ctypes.c_int32),ctypes.POINTER(SharedPtr),ctypes.c_int32)(proc(pix,b'?grayToTemp@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NAEAHV?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@H@Z'))
        rows=[]
        for g in grays:
            o=ctypes.c_int32(-2147483648); ok=bool(gta(ctypes.byref(ctrl),ctypes.byref(o),ctypes.byref(sp),g)); rows.append({'gray':g,'ok':ok,'out':int(o.value),'div10':None if o.value<-1000000 else o.value/10,'div100':None if o.value<-1000000 else o.value/100})
        rec['grayToTemp']=rows
    except Exception as e: rec['grayToTemp_exception']=repr(e)
    return rec

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--dll-dir',type=Path,default=DLL_DIR_DEFAULT); ap.add_argument('--jpeg',type=Path,default=Path('data/fixtures/mini2/IR_00001.jpeg')); ap.add_argument('--grays',default='5038,5100,5200,5338,5364'); ap.add_argument('--modes',default='0,1,2,3,4,5,6,7,8,9,10'); ap.add_argument('--out',type=Path,default=Path('data/mini2_micropixeler_mode_sweep'))
    a=ap.parse_args(); orig=Path.cwd(); jp=a.jpeg.resolve(); outdir=a.out if a.out.is_absolute() else orig/a.out
    add_dir(a.dll_dir); pix=ctypes.WinDLL(str(a.dll_dir/'MicroPixeler_Release_x64.dll')); ana=ctypes.WinDLL(str(a.dll_dir/'MicroAnalytics_Release_x64.dll'))
    grays=[int(x) for x in a.grays.split(',') if x]; modes=[int(x) for x in a.modes.split(',') if x]
    mats=parse_all(ana,pix,jp)
    seqs=[
        ['tempAnalyze_shared'], ['imgAnalyzeSyn_shared'], ['imgAnalyze_shared_false'], ['imgAnalyze_shared_true'],
        ['imgAnalyzeSyn_shared','tempAnalyze_shared'], ['imgAnalyze_shared_false','tempAnalyze_shared'], ['imgAnalyze_shared_true','tempAnalyze_shared'],
        ['tempAnalyze_raw'], ['imgAnalyzeSyn_raw'], ['imgAnalyze_raw_false'], ['imgAnalyze_raw_true'],
        ['imgAnalyzeSyn_raw','tempAnalyze_raw'], ['imgAnalyze_raw_false','tempAnalyze_raw'], ['imgAnalyze_raw_true','tempAnalyze_raw'],
        ['pcmFilterProcess_shared','tempAnalyze_shared'], ['ruleAreaMeasure_shared','tempAnalyze_shared'],
    ]
    rep={'jpeg':str(jp),'grays':grays,'results':[]}
    for mname,mat,meta in mats:
        if not mat: continue
        # Focus on promising parser types to avoid giant output.
        if not any(s in mname for s in ['pix_parseRadiometrics','type=3']): continue
        mrec={'parser':mname,'mat':hx(mat),'meta':meta,'initial_tpi':get_tpi_table(pix,mat),'sweeps':[]}
        for mode in modes:
            for seq in seqs:
                r=run_sequence(pix,ana,mat,grays,mode,seq)
                # keep all nonzero/non-null table, and all first few records for audit
                useful=bool((r.get('table_sp') or {}).get('ptr')) or any(row.get('out') not in (0,-2147483648) for row in r.get('grayToTemp',[])) or any(c.get('ok') for c in r.get('call_results',[]) if 'imgAnalyze' in c.get('call',''))
                if useful or mode in (0,1,2,3) and seq in seqs[:7]:
                    mrec['sweeps'].append(r)
        rep['results'].append(mrec)
    outdir.mkdir(parents=True,exist_ok=True); op=outdir/(jp.stem+'_mode_sweep.json'); op.write_text(json.dumps(rep,ensure_ascii=False,indent=2),encoding='utf-8')
    summary=[]
    for mr in rep['results']:
        found=[]
        for sw in mr['sweeps']:
            if bool((sw.get('table_sp') or {}).get('ptr')) or any(row.get('out') not in (0,-2147483648) for row in sw.get('grayToTemp',[])):
                found.append({'mode':sw['mode'],'seq':sw['seq'],'calls':sw.get('call_results'),'table':sw.get('table_sp'),'gray':sw.get('grayToTemp')})
        summary.append({'parser':mr['parser'],'mat':mr['mat'],'found':found[:20],'kept_sweeps':len(mr['sweeps'])})
    print(json.dumps({'summary':summary,'out':str(op)},ensure_ascii=False,indent=2)[:30000])
if __name__=='__main__': main()
