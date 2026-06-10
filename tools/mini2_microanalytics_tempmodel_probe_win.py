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
class Coordinate(ctypes.Structure):
    # Best-effort; MicroAnalytics symbol says Coordinate@iVMS4800, likely two int fields.
    _fields_=[('x',ctypes.c_int32),('y',ctypes.c_int32)]

def add_dir(d: Path):
    if hasattr(os,'add_dll_directory'): os.add_dll_directory(str(d))
    ctypes.windll.kernel32.SetDllDirectoryW(str(d)); os.chdir(str(d))

def proc(dll, n: bytes) -> int:
    k=ctypes.windll.kernel32; k.GetProcAddress.argtypes=[ctypes.c_void_p,ctypes.c_char_p]; k.GetProcAddress.restype=ctypes.c_void_p
    a=k.GetProcAddress(dll._handle,n)
    if not a: raise RuntimeError(f'missing {n!r}')
    return int(a)

def sstr(s: str):
    b=s.encode('utf-8'); st=StdString(); keep=None
    if len(b)<16:
        ctypes.memmove(ctypes.addressof(st),b,len(b)); st.buf[len(b)]=0; st.size=len(b); st.capacity=15
    else:
        keep=ctypes.create_string_buffer(b+b'\0'); p=ctypes.c_void_p(ctypes.addressof(keep)); ctypes.memmove(ctypes.addressof(st),ctypes.byref(p),8); st.size=len(b); st.capacity=len(b)
    return st,keep

def hx(x): return hex(int(x)) if x else None

def u64(addr): return int(ctypes.c_uint64.from_address(int(addr)).value) if addr else 0

def mem_words(addr, n=16):
    if not addr: return []
    return [hex(u64(int(addr)+8*i)) for i in range(n)]

def parse_materials(ana, pix, jpeg_abs: Path):
    st, keep = sstr(str(jpeg_abs)); vec=StdVector(None,None,None)
    out=[]
    # MicroPixeler direct radiometric parser.
    try:
        parse=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint32),ctypes.POINTER(ctypes.c_bool),ctypes.POINTER(StdString),ctypes.POINTER(StdVector),ctypes.c_bool)(
            proc(pix,b'?parseRadiometricsJPEG@MaterialParseFactory@MICROPIXELER@@SAPEAVTakedMaterial@2@AEAIAEA_NAEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@AEBV?$vector@UCustomFusionMatchParam@iVMS4800@@V?$allocator@UCustomFusionMatchParam@iVMS4800@@@std@@@5@_N@Z'))
        for flag in (False, True):
            ot=ctypes.c_uint32(0); ob=ctypes.c_bool(False)
            mat=parse(ctypes.byref(ot),ctypes.byref(ob),ctypes.byref(st),ctypes.byref(vec),flag)
            out.append({'name':f'MicroPixeler.parseRadiometricsJPEG({flag})','mat':mat,'meta':{'out_type':int(ot.value),'out_bool':bool(ob.value)}})
    except Exception as e:
        out.append({'name':'MicroPixeler.parseRadiometricsJPEG.setup','mat':0,'meta':{'exception':repr(e)}})
    # MicroAnalytics FileParseFactory typed parser. From previous probe type3 is radiometric thermal-like.
    try:
        fn=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_int32,ctypes.POINTER(StdString),ctypes.POINTER(StdVector),ctypes.c_bool)(
            proc(ana,b'?createMaterialQ@FileParseFactory@MicroAnalytics@@SAPEAVTakedMaterial@MICROPIXELER@@W4MaterialType@iVMS4800@@AEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@AEBV?$vector@UCustomFusionMatchParam@iVMS4800@@V?$allocator@UCustomFusionMatchParam@iVMS4800@@@std@@@8@_N@Z'))
        for mt in range(0,12):
            for flag in (False, True):
                try:
                    mat=fn(mt,ctypes.byref(st),ctypes.byref(vec),flag)
                    if mat:
                        out.append({'name':f'MicroAnalytics.FileParseFactory.type{mt}({flag})','mat':mat,'meta':{'type':mt,'flag':flag}})
                except Exception as e:
                    out.append({'name':f'MicroAnalytics.FileParseFactory.type{mt}({flag})','mat':0,'meta':{'exception':repr(e)}})
    except Exception as e:
        out.append({'name':'MicroAnalytics.FileParseFactory.setup','mat':0,'meta':{'exception':repr(e)}})
    return out

def try_analyze(pix, mat, rec):
    # Use raw pointer overloads first; they worked previously and avoid shared_ptr ABI ambiguity.
    try:
        cdef=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_void_p)(proc(pix,b'?createDefault@AnalyzerBuilderManager@MICROPIXELER@@SA?AV?$shared_ptr@VAnalyzerBuilderManager@MICROPIXELER@@@std@@XZ'))
        builder=SharedPtr(); cdef(ctypes.byref(builder)); rec['builder']={'ptr':hx(builder.ptr),'ctrl':hx(builder.ctrl)}
        ctor=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_void_p,ctypes.POINTER(SharedPtr))(proc(pix,b'??0TakedMaterialAnalyzControl@MICROPIXELER@@QEAA@V?$shared_ptr@VAnalyzerBuilderManager@MICROPIXELER@@@std@@@Z'))
        ctrl=ctypes.create_string_buffer(0x2000); ctor(ctypes.byref(ctrl),ctypes.byref(builder)); rec['analyz_ctrl_head']=mem_words(ctypes.addressof(ctrl),8)
        for label, exp, sig in [
            ('imgAnalyzeSyn_raw', b'?imgAnalyzeSyn@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NPEAVTakedMaterial@2@@Z', 'raw'),
            ('tempAnalyze_raw', b'?tempAnalyze@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NPEAVTakedMaterial@2@@Z', 'raw'),
        ]:
            try:
                fn=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.c_void_p)(proc(pix,exp))
                rec[label]=bool(fn(ctypes.byref(ctrl),ctypes.c_void_p(mat)))
            except Exception as e: rec[label+'_exception']=repr(e)
    except Exception as e:
        rec['try_analyze_exception']=repr(e)

def probe_temp_model(ana, pix, mat, grays, coords):
    rec={'mat':hx(mat),'mat_vptr':hx(u64(mat)) if mat else None}
    if not mat: return rec
    # Get existing ThermalPicInterface state too.
    try:
        tpi_raw=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_void_p)(proc(pix,b'?thermalPicInterface@TakedMaterial@MICROPIXELER@@QEBAPEBVThermalPicInterface@2@XZ'))
        rec['thermalPicInterface_raw']=hx(tpi_raw(ctypes.c_void_p(mat)))
    except Exception as e: rec['thermalPicInterface_raw_exception']=repr(e)
    try_analyze(pix, mat, rec)
    fake=SharedPtr(ctypes.c_void_p(mat), None)
    # Construct TempMeasuredResultModel(shared_ptr<TakedMaterial>)
    for obj_size in (0x800,0x1000,0x3000,0x8000):
        obj=ctypes.create_string_buffer(obj_size)
        one={'obj_size':obj_size}
        try:
            ctor=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_void_p,ctypes.POINTER(SharedPtr))(
                proc(ana,b'??0TempMeasuredResultModel@MicroAnalytics@@QEAA@V?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@@Z'))
            rv=ctor(ctypes.byref(obj),ctypes.byref(fake))
            one['ctor_rv']=hx(rv); one['obj_head']=mem_words(ctypes.addressof(obj),16)
        except Exception as e:
            one['ctor_exception']=repr(e); rec.setdefault('models',[]).append(one); continue
        # Optional setTakedMaterial to force init.
        try:
            stmat=ctypes.CFUNCTYPE(None,ctypes.c_void_p,ctypes.POINTER(SharedPtr))(
                proc(ana,b'?setTakedMaterial@TempMeasuredResultModel@MicroAnalytics@@QEAAXV?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@@Z'))
            stmat(ctypes.byref(obj),ctypes.byref(fake)); one['setTakedMaterial_ok']=True
        except Exception as e: one['setTakedMaterial_exception']=repr(e)
        # Direct grayToTemp.
        rows=[]
        try:
            gta=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.POINTER(ctypes.c_int32),ctypes.c_uint16)(
                proc(ana,b'?grayToTemp@TempMeasuredResultModel@MicroAnalytics@@QEAA_NAEAHG@Z'))
            for g in grays:
                o=ctypes.c_int32(-2147483648)
                try:
                    ok=bool(gta(ctypes.byref(obj),ctypes.byref(o),ctypes.c_uint16(g)))
                    rows.append({'gray':int(g),'ok':ok,'temp_int':int(o.value),'temp_c_div10':None if int(o.value)<-1000000 else int(o.value)/10.0,'temp_c_div100':None if int(o.value)<-1000000 else int(o.value)/100.0})
                except Exception as e: rows.append({'gray':int(g),'exception':repr(e)})
            one['grayToTemp_rows']=rows
        except Exception as e: one['grayToTemp_setup_exception']=repr(e)
        # tempToGray too.
        try:
            ttg=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint16),ctypes.c_int32)(
                proc(ana,b'?tempToGray@TempMeasuredResultModel@MicroAnalytics@@QEAA_NAEAGH@Z'))
            trows=[]
            for t in [190,200,222,300,339,356,1000,2000]:
                og=ctypes.c_uint16(65535)
                try: trows.append({'temp_int':t,'ok':bool(ttg(ctypes.byref(obj),ctypes.byref(og),ctypes.c_int32(t))),'gray':int(og.value)})
                except Exception as e: trows.append({'temp_int':t,'exception':repr(e)})
            one['tempToGray_rows']=trows
        except Exception as e: one['tempToGray_setup_exception']=repr(e)
        # getTempByPos if coordinate layout is correct. Export returns double& + reliability enum& + coordinate.
        try:
            gtp=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.POINTER(ctypes.c_double),ctypes.POINTER(ctypes.c_int32),ctypes.POINTER(Coordinate))(
                proc(ana,b'?getTempByPos@TempMeasuredResultModel@MicroAnalytics@@QEBA_NAEANAEAW4TempratureReliability@iVMS4800@@AEBUCoordinate@4@@Z'))
            crows=[]
            for x,y in coords:
                od=ctypes.c_double(-9999.0); rel=ctypes.c_int32(-1); co=Coordinate(int(x),int(y))
                try: crows.append({'x':x,'y':y,'ok':bool(gtp(ctypes.byref(obj),ctypes.byref(od),ctypes.byref(rel),ctypes.byref(co))),'temp_double':float(od.value),'reliability':int(rel.value)})
                except Exception as e: crows.append({'x':x,'y':y,'exception':repr(e)})
            one['getTempByPos_rows']=crows
        except Exception as e: one['getTempByPos_setup_exception']=repr(e)
        rec.setdefault('models',[]).append(one)
        # If first object works, no need to try huge sizes.
        if any(r.get('ok') and r.get('temp_int',-999999) not in (-2147483648,0) for r in rows):
            break
    return rec

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--dll-dir',type=Path,default=DLL_DIR_DEFAULT)
    ap.add_argument('--jpeg',type=Path,default=Path('data/fixtures/mini2/IR_00001.jpeg'))
    ap.add_argument('--grays',default='5000,5038,5100,5200,5338,5364')
    ap.add_argument('--coords',default='0:0,10:10,128:96,255:191')
    ap.add_argument('--out',type=Path,default=Path('data/mini2_microanalytics_tempmodel_probe'))
    args=ap.parse_args()
    orig=Path.cwd(); jpeg_abs=args.jpeg.resolve(); out_dir=args.out if args.out.is_absolute() else orig/args.out
    add_dir(args.dll_dir)
    ana=ctypes.WinDLL(str(args.dll_dir/'MicroAnalytics_Release_x64.dll'))
    pix=ctypes.WinDLL(str(args.dll_dir/'MicroPixeler_Release_x64.dll'))
    grays=[int(x) for x in args.grays.split(',') if x.strip()]
    coords=[]
    for item in args.coords.split(','):
        if ':' in item:
            x,y=item.split(':',1); coords.append((int(x),int(y)))
    rep={'jpeg':str(jpeg_abs),'grays':grays,'coords':coords,'materials':[]}
    mats=parse_materials(ana,pix,jpeg_abs)
    seen=set()
    for m in mats:
        mat=int(m.get('mat') or 0)
        key=(m['name'],mat)
        if key in seen: continue
        seen.add(key)
        rec={'parser':m['name'],'parse_meta':m.get('meta',{}), **probe_temp_model(ana,pix,mat,grays,coords)}
        rep['materials'].append(rec)
    out_dir.mkdir(parents=True,exist_ok=True)
    op=out_dir/(jpeg_abs.stem+'_microanalytics_tempmodel_probe.json')
    op.write_text(json.dumps(rep,ensure_ascii=False,indent=2),encoding='utf-8')
    compact=[]
    for r in rep['materials']:
        first_model=(r.get('models') or [{}])[0]
        compact.append({'parser':r.get('parser'),'mat':r.get('mat'),'parse_meta':r.get('parse_meta'),'analyze':{k:r.get(k) for k in ('imgAnalyzeSyn_raw','tempAnalyze_raw')},'first_gray_rows':first_model.get('grayToTemp_rows'),'first_pos_rows':first_model.get('getTempByPos_rows')})
    print(json.dumps({'jpeg':str(jpeg_abs),'materials':compact,'out':str(op)},ensure_ascii=False,indent=2)[:30000])
    return 0
if __name__=='__main__': raise SystemExit(main())
