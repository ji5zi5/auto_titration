#!/usr/bin/env python3
from __future__ import annotations
import argparse, ctypes, json, os, struct, math
from pathlib import Path
DLL_DIR_DEFAULT=Path(r'C:\Program Files\HIKMICRO Analyzer\HIKMICRO Analyzer')
KEEP=[]
class StdString(ctypes.Structure):
    _fields_=[('buf',ctypes.c_char*16),('size',ctypes.c_size_t),('capacity',ctypes.c_size_t)]
class StdVector(ctypes.Structure):
    _fields_=[('begin',ctypes.c_void_p),('end',ctypes.c_void_p),('cap',ctypes.c_void_p)]
class SharedPtr(ctypes.Structure):
    _fields_=[('ptr',ctypes.c_void_p),('ctrl',ctypes.c_void_p)]

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
        keep=ctypes.create_string_buffer(b+b'\0'); p=ctypes.c_void_p(ctypes.addressof(keep)); ctypes.memmove(ctypes.addressof(st),ctypes.byref(p),8); st.size=len(b); st.capacity=len(b); KEEP.append(keep)
    return st
def hx(v): return hex(int(v)) if v else None
def safe(addr,n):
    try: return ctypes.string_at(int(addr),n) if addr else b''
    except Exception: return b''
def dump_addr(addr,n=0x200):
    raw=safe(addr,n); rec={'ptr':hx(addr),'size':len(raw)}
    if not raw: return rec
    rec['hex0']=raw[:128].hex(' ')
    rec['u16']=[struct.unpack_from('<H',raw,i)[0] for i in range(0,min(len(raw),128)-1,2)]
    rec['u32']=[struct.unpack_from('<I',raw,i)[0] for i in range(0,min(len(raw),128)-3,4)]
    rec['i32']=[struct.unpack_from('<i',raw,i)[0] for i in range(0,min(len(raw),128)-3,4)]
    rec['f32']=[struct.unpack_from('<f',raw,i)[0] for i in range(0,min(len(raw),128)-3,4)]
    rec['qword']=[hex(struct.unpack_from('<Q',raw,i)[0]) for i in range(0,min(len(raw),128)-7,8)]
    ptrs=[]
    for off in range(0,min(len(raw),128)-7,8):
        p=struct.unpack_from('<Q',raw,off)[0]
        if 0x10000 < p < 0x0000800000000000:
            rr=safe(p,0x2000)
            ent={'off':hex(off),'ptr':hex(p),'read':len(rr)}
            if rr:
                # classify as vector header if object has begin/end/cap
                for base in [0,8,16,24,32,40,48,56,64,72,80,88,96]:
                    if base+24 <= len(raw):
                        b,e,c=struct.unpack_from('<QQQ',raw,base)
                        if 0x10000 < b <= e <= c < 0x0000800000000000 and c-b < 100000000:
                            ent.setdefault('vector_headers_in_obj',[]).append({'off':hex(base),'begin':hex(b),'end':hex(e),'cap':hex(c),'bytes':e-b})
                # stats for pointed data
                vals16=[struct.unpack_from('<H',rr,i)[0] for i in range(0,min(len(rr),512)-1,2)]
                vals32=[struct.unpack_from('<i',rr,i)[0] for i in range(0,min(len(rr),512)-3,4)]
                valsf=[struct.unpack_from('<f',rr,i)[0] for i in range(0,min(len(rr),512)-3,4)]
                ent['u16_stats']={'n':len(vals16),'min':min(vals16),'max':max(vals16),'first20':vals16[:20]} if vals16 else None
                ent['i32_stats']={'n':len(vals32),'min':min(vals32),'max':max(vals32),'first20':vals32[:20]} if vals32 else None
                finite=[v for v in valsf if math.isfinite(v)]
                ent['f32_stats']={'n':len(finite),'min':min(finite),'max':max(finite),'first20':valsf[:20]} if finite else None
                ent['hex0']=rr[:64].hex(' ')
            ptrs.append(ent)
    rec['pointers']=ptrs
    return rec

def fake_shared_ptr(raw_ptr):
    # Dangerous but enough for APIs that only dereference .ptr and do not retain ownership.
    return SharedPtr(ctypes.c_void_p(raw_ptr), None)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--dll-dir',type=Path,default=DLL_DIR_DEFAULT); ap.add_argument('--jpeg',type=Path,required=True); ap.add_argument('--gray',type=int,default=5200); ap.add_argument('--out',type=Path,default=Path('data/mini2_micropixeler_correct_sret_probe'))
    a=ap.parse_args(); orig=Path.cwd(); jpeg=a.jpeg.resolve(); outdir=a.out if a.out.is_absolute() else orig/a.out
    add_dir(a.dll_dir)
    pix=ctypes.WinDLL(str(a.dll_dir/'MicroPixeler_Release_x64.dll'))
    ana=ctypes.WinDLL(str(a.dll_dir/'MicroAnalytics_Release_x64.dll'))
    rep={'jpeg':str(jpeg),'gray':a.gray,'cases':[]}
    # parse by MicroPixeler direct
    st=sstr(str(jpeg)); vec=StdVector(None,None,None); out_type=ctypes.c_uint32(0xdeadbeef); out_bool=ctypes.c_bool(False)
    parse=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint32),ctypes.POINTER(ctypes.c_bool),ctypes.POINTER(StdString),ctypes.POINTER(StdVector),ctypes.c_bool)(proc(pix,b'?parseRadiometricsJPEG@MaterialParseFactory@MICROPIXELER@@SAPEAVTakedMaterial@2@AEAIAEA_NAEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@AEBV?$vector@UCustomFusionMatchParam@iVMS4800@@V?$allocator@UCustomFusionMatchParam@iVMS4800@@@std@@@5@_N@Z'))
    mat=parse(ctypes.byref(out_type),ctypes.byref(out_bool),ctypes.byref(st),ctypes.byref(vec),False)
    rep['parse_pix']={'mat':hx(mat),'type':out_type.value,'bool':bool(out_bool.value)}
    # also analytics createMaterialQ type 3
    st2=sstr(str(jpeg)); vec2=StdVector(None,None,None)
    try:
        cmq=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_int32,ctypes.POINTER(StdString),ctypes.POINTER(StdVector),ctypes.c_bool)(proc(ana,b'?createMaterialQ@FileParseFactory@MicroAnalytics@@SAPEAVTakedMaterial@MICROPIXELER@@W4MaterialType@iVMS4800@@AEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@AEBV?$vector@UCustomFusionMatchParam@iVMS4800@@V?$allocator@UCustomFusionMatchParam@iVMS4800@@@std@@@8@_N@Z'))
        mat2=cmq(3,ctypes.byref(st2),ctypes.byref(vec2),False)
        rep['parse_analytics']={'mat':hx(mat2)}
    except Exception as e:
        mat2=0; rep['parse_analytics']={'exception':repr(e)}
    mats=[('pix',mat),('analytics',mat2)]
    # functions
    raw_tpi_fn=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_void_p)(proc(pix,b'?thermalPicInterface@TakedMaterial@MICROPIXELER@@QEBAPEBVThermalPicInterface@2@XZ'))
    # correct sret: return buffer first, this second
    get_tpi_sret=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p)(proc(pix,b'?getThermalPicInterface@TakedMaterial@MICROPIXELER@@QEAA?AV?$shared_ptr@VThermalPicInterface@MICROPIXELER@@@std@@XZ'))
    get_tbl_sret=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p)(proc(pix,b'?getGrayToTempTable@ThermalPicInterface@MICROPIXELER@@UEBA?AV?$shared_ptr@UGrayToTempTable@MICROPIXELER@@@std@@XZ'))
    # analyzer control setup
    create_def=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_void_p)(proc(pix,b'?createDefault@AnalyzerBuilderManager@MICROPIXELER@@SA?AV?$shared_ptr@VAnalyzerBuilderManager@MICROPIXELER@@@std@@XZ'))
    ctrl_ctor=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_void_p,ctypes.POINTER(SharedPtr))(proc(pix,b'??0TakedMaterialAnalyzControl@MICROPIXELER@@QEAA@V?$shared_ptr@VAnalyzerBuilderManager@MICROPIXELER@@@std@@@Z'))
    builder=SharedPtr(); create_def(ctypes.byref(builder)); ctrl=ctypes.create_string_buffer(0x8000); KEEP.append(ctrl); ctrl_ctor(ctypes.byref(ctrl),ctypes.byref(builder))
    funcs=[]
    for name, sym, mode in [
        ('none',None,None),
        ('imgAnalyzeSyn_raw',b'?imgAnalyzeSyn@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NPEAVTakedMaterial@2@@Z','raw'),
        ('tempAnalyze_raw',b'?tempAnalyze@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NPEAVTakedMaterial@2@@Z','raw'),
        ('ruleAreaMeasure_raw',b'?ruleAreaMeasure@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NPEAVTakedMaterial@2@@Z','raw'),
        ('imgAnalyzeSyn_shared',b'?imgAnalyzeSyn@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NV?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@@Z','shared'),
        ('tempAnalyze_shared',b'?tempAnalyze@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NV?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@@Z','shared'),
        ('ruleAreaMeasure_shared',b'?ruleAreaMeasure@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NV?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@@Z','shared'),
    ]:
        if sym:
            funcs.append((name,ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)(proc(pix,sym)),mode))
        else: funcs.append((name,None,None))
    gray_to_temp=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.POINTER(ctypes.c_int32),ctypes.c_void_p,ctypes.c_int32)(proc(pix,b'?grayToTemp@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NAEAHV?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@H@Z'))
    for mlabel,m in mats:
        if not m: continue
        cumulative=[]
        for fname,fn,mode in funcs:
            case={'mat_source':mlabel,'mat':hx(m),'after_call':fname}
            if fn:
                try:
                    if mode=='raw': ok=bool(fn(ctypes.byref(ctrl),ctypes.c_void_p(m)))
                    else:
                        spm=fake_shared_ptr(m); ok=bool(fn(ctypes.byref(ctrl),ctypes.byref(spm)))
                    cumulative.append({'call':fname,'ok':ok}); case['call_ok']=ok
                except Exception as e: cumulative.append({'call':fname,'exception':repr(e)}); case['call_exception']=repr(e)
            case['cumulative']=list(cumulative)
            try:
                t_raw=raw_tpi_fn(ctypes.c_void_p(m)); case['tpi_raw']=hx(t_raw); case['tpi_raw_dump']=dump_addr(t_raw,0x300)
            except Exception as e: case['tpi_raw_exception']=repr(e); t_raw=0
            try:
                sp=SharedPtr(); rv=get_tpi_sret(ctypes.byref(sp),ctypes.c_void_p(m)); case['get_tpi_sret']={'rv':hx(rv),'sp':{'ptr':hx(sp.ptr),'ctrl':hx(sp.ctrl)},'dump':dump_addr(sp.ptr,0x300)}
            except Exception as e: case['get_tpi_sret_exception']=repr(e); sp=SharedPtr()
            for tlabel,tptr in [('raw',t_raw),('sret_sp',sp.ptr)]:
                if tptr:
                    try:
                        tbl=SharedPtr(); rv=get_tbl_sret(ctypes.byref(tbl),ctypes.c_void_p(tptr)); case[f'table_{tlabel}']={'rv':hx(rv),'sp':{'ptr':hx(tbl.ptr),'ctrl':hx(tbl.ctrl)},'obj_dump':dump_addr(tbl.ptr,0x500)}
                    except Exception as e: case[f'table_{tlabel}_exception']=repr(e)
            try:
                out=ctypes.c_int32(-999999); spm=fake_shared_ptr(m); ok=bool(gray_to_temp(ctypes.byref(ctrl),ctypes.byref(out),ctypes.byref(spm),int(a.gray)))
                case['control_grayToTemp']={'ok':ok,'out_i32':out.value}
            except Exception as e: case['control_grayToTemp_exception']=repr(e)
            rep['cases'].append(case)
    outdir.mkdir(parents=True,exist_ok=True); op=outdir/(jpeg.stem+'_correct_sret_probe.json'); op.write_text(json.dumps(rep,ensure_ascii=False,indent=2),encoding='utf-8')
    compact=[]
    for c in rep['cases']:
        compact.append({
            'mat_source':c['mat_source'],'after':c['after_call'],'call_ok':c.get('call_ok'),'call_exc':c.get('call_exception'),'tpi_raw':c.get('tpi_raw'),
            'get_tpi_sp':(c.get('get_tpi_sret') or {}).get('sp'),
            'table_raw_sp':(c.get('table_raw') or {}).get('sp'),
            'table_sret_sp':(c.get('table_sret_sp') or {}).get('sp'),
            'grayToTemp':c.get('control_grayToTemp'),
            'table_raw_obj_u32':((c.get('table_raw') or {}).get('obj_dump') or {}).get('u32',[])[:16],
            'table_raw_ptrs':[((p.get('off'),p.get('ptr'),p.get('u16_stats'),p.get('i32_stats'),p.get('f32_stats'))) for p in (((c.get('table_raw') or {}).get('obj_dump') or {}).get('pointers') or [])[:8]],
        })
    print(json.dumps({'out':str(op),'parse_pix':rep.get('parse_pix'),'parse_analytics':rep.get('parse_analytics'),'compact':compact},ensure_ascii=False,indent=2)[:50000])
if __name__=='__main__': main()
