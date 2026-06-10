#!/usr/bin/env python3
from __future__ import annotations
import argparse, csv, ctypes, json, math, os, random, struct
from pathlib import Path

DLL_DIR_DEFAULT = Path(r"C:\Program Files\HIKMICRO Analyzer\HIKMICRO Analyzer")
KEEP=[]
class StdString(ctypes.Structure):
    _fields_=[('buf',ctypes.c_char*16),('size',ctypes.c_size_t),('capacity',ctypes.c_size_t)]
class StdVector(ctypes.Structure):
    _fields_=[('begin',ctypes.c_void_p),('end',ctypes.c_void_p),('cap',ctypes.c_void_p)]
class SharedPtr(ctypes.Structure):
    _fields_=[('ptr',ctypes.c_void_p),('ctrl',ctypes.c_void_p)]
class Coord(ctypes.Structure):
    _fields_=[('x',ctypes.c_int32),('y',ctypes.c_int32)]

def add_dir(d:Path):
    if hasattr(os,'add_dll_directory'): os.add_dll_directory(str(d))
    ctypes.windll.kernel32.SetDllDirectoryW(str(d)); os.chdir(str(d))
def proc(dll,name:bytes)->int:
    k=ctypes.windll.kernel32; k.GetProcAddress.argtypes=[ctypes.c_void_p,ctypes.c_char_p]; k.GetProcAddress.restype=ctypes.c_void_p
    p=k.GetProcAddress(dll._handle,name)
    if not p: raise RuntimeError(f'missing {name!r}')
    return int(p)
def sstr(text:str):
    b=text.encode('utf-8'); st=StdString(); keep=None
    if len(b)<16:
        ctypes.memmove(ctypes.addressof(st),b,len(b)); st.buf[len(b)]=0; st.size=len(b); st.capacity=15
    else:
        keep=ctypes.create_string_buffer(b+b'\0'); ptr=ctypes.c_void_p(ctypes.addressof(keep)); ctypes.memmove(ctypes.addressof(st),ctypes.byref(ptr),8); st.size=len(b); st.capacity=len(b); KEEP.append(keep)
    return st
def fake_ctrl(initial=1000000):
    ctrl=ctypes.create_string_buffer(0x40); vt=(ctypes.c_void_p*4)()
    ctypes.c_void_p.from_buffer(ctrl,0).value=ctypes.addressof(vt)
    ctypes.c_uint32.from_buffer(ctrl,8).value=initial
    ctypes.c_uint32.from_buffer(ctrl,12).value=initial
    KEEP.extend([ctrl,vt]); return ctypes.addressof(ctrl)
def hx(x): return hex(int(x)) if x else None
def words(addr,n=12):
    out=[]
    if not addr: return out
    for i in range(n):
        try: out.append(hex(ctypes.c_uint64.from_address(int(addr)+8*i).value))
        except Exception as e: out.append('ERR:'+repr(e)); break
    return out

def parse_material(ana,pix,jpeg:Path, parser:str, mtype:int, flag:bool):
    st=sstr(str(jpeg)); vec=StdVector(None,None,None)
    if parser=='analytics':
        f=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_int32,ctypes.POINTER(StdString),ctypes.POINTER(StdVector),ctypes.c_bool)(proc(ana,b'?createMaterialQ@FileParseFactory@MicroAnalytics@@SAPEAVTakedMaterial@MICROPIXELER@@W4MaterialType@iVMS4800@@AEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@AEBV?$vector@UCustomFusionMatchParam@iVMS4800@@V?$allocator@UCustomFusionMatchParam@iVMS4800@@@std@@@8@_N@Z'))
        return f(mtype,ctypes.byref(st),ctypes.byref(vec),flag), {'parser':parser,'mtype':mtype,'flag':flag}
    f=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint32),ctypes.POINTER(ctypes.c_bool),ctypes.POINTER(StdString),ctypes.POINTER(StdVector),ctypes.c_bool)(proc(pix,b'?parseRadiometricsJPEG@MaterialParseFactory@MICROPIXELER@@SAPEAVTakedMaterial@2@AEAIAEA_NAEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@AEBV?$vector@UCustomFusionMatchParam@iVMS4800@@V?$allocator@UCustomFusionMatchParam@iVMS4800@@@std@@@5@_N@Z'))
    ot=ctypes.c_uint32(); ob=ctypes.c_bool()
    mat=f(ctypes.byref(ot),ctypes.byref(ob),ctypes.byref(st),ctypes.byref(vec),flag)
    return mat, {'parser':parser,'flag':flag,'out_type':ot.value,'out_bool':bool(ob.value)}

def load_csv_matrix(path:Path):
    if not path or not path.exists(): return None
    txt=path.read_text(encoding='utf-8-sig',errors='ignore')
    rows=[]
    for line in txt.splitlines():
        parts=[p.strip() for p in line.replace('\t',',').split(',')]
        vals=[]
        for p in parts:
            if not p: continue
            try: vals.append(float(p))
            except: pass
        if vals: rows.append(vals)
    # keep rows with common width
    if not rows: return None
    # Analyzer csv can include headers; choose largest rectangular tail/group
    best=[]; width=0
    for r in rows:
        if len(r)>width: width=len(r)
    mat=[r for r in rows if len(r)==width]
    return mat if mat else rows

def csv_val(mat,x,y):
    if mat is None: return None
    if 0<=y<len(mat) and 0<=x<len(mat[y]): return mat[y][x]
    return None

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--dll-dir',type=Path,default=DLL_DIR_DEFAULT)
    ap.add_argument('--jpeg',type=Path,required=True)
    ap.add_argument('--csv',type=Path)
    ap.add_argument('--out',type=Path,default=Path('data/mini2_tempmodel_gettemp_probe'))
    ap.add_argument('--points',default='0,0;10,10;64,48;128,96;255,191')
    args=ap.parse_args()
    orig=Path.cwd(); jpeg=args.jpeg.resolve(); outdir=args.out if args.out.is_absolute() else orig/args.out
    add_dir(args.dll_dir)
    pix=ctypes.WinDLL(str(args.dll_dir/'MicroPixeler_Release_x64.dll'))
    ana=ctypes.WinDLL(str(args.dll_dir/'MicroAnalytics_Release_x64.dll'))
    csvmat=load_csv_matrix(args.csv.resolve()) if args.csv else None
    points=[]
    for p in args.points.split(';'):
        if not p.strip(): continue
        x,y=[int(v) for v in p.split(',')[:2]]; points.append((x,y))
    if csvmat:
        h=len(csvmat); w=max(len(r) for r in csvmat)
        points += [(w//4,h//4),(w//2,h//2),(3*w//4,3*h//4),(w-1,h-1)]
    # unique points
    seen=set(); points=[p for p in points if not (p in seen or seen.add(p))]

    ctor=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_void_p)(proc(ana,b'??0TempMeasuredResultModel@MicroAnalytics@@QEAA@XZ'))
    setm=ctypes.CFUNCTYPE(None,ctypes.c_void_p,ctypes.POINTER(SharedPtr))(proc(ana,b'?setTakedMaterial@TempMeasuredResultModel@MicroAnalytics@@QEAAXV?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@@Z'))
    getpos=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.POINTER(ctypes.c_double),ctypes.POINTER(ctypes.c_int32),ctypes.POINTER(Coord))(proc(ana,b'?getTempByPos@TempMeasuredResultModel@MicroAnalytics@@QEBA_NAEANAEAW4TempratureReliability@iVMS4800@@AEBUCoordinate@4@@Z'))
    # optional TakedMaterialAnalyzControl tempAnalyze first
    cdef=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_void_p)(proc(pix,b'?createDefault@AnalyzerBuilderManager@MICROPIXELER@@SA?AV?$shared_ptr@VAnalyzerBuilderManager@MICROPIXELER@@@std@@XZ'))
    ctrl_ctor=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_void_p,ctypes.POINTER(SharedPtr))(proc(pix,b'??0TakedMaterialAnalyzControl@MICROPIXELER@@QEAA@V?$shared_ptr@VAnalyzerBuilderManager@MICROPIXELER@@@std@@@Z'))
    temp_an_sp=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.POINTER(SharedPtr))(proc(pix,b'?tempAnalyze@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NV?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@@Z'))
    img_an_sp=ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.POINTER(SharedPtr))(proc(pix,b'?imgAnalyzeSyn@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NV?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@@Z'))

    report={'jpeg':str(jpeg),'csv':str(args.csv) if args.csv else None,'csv_shape':None if not csvmat else [len(csvmat),max(len(r) for r in csvmat)],'results':[]}
    parse_variants=[('analytics',3,False),('analytics',3,True),('pix',3,False),('pix',3,True)]
    sequences=[[],['tempAnalyze'],['imgAnalyzeSyn'],['imgAnalyzeSyn','tempAnalyze']]
    for parser,mtype,flag in parse_variants:
        try:
            mat,meta=parse_material(ana,pix,jpeg,parser,mtype,flag)
        except Exception as e:
            report['results'].append({'parse':{'parser':parser,'mtype':mtype,'flag':flag},'exception':repr(e)}); continue
        for seq in sequences:
            rec={'parse_meta':meta,'mat':hx(mat),'sequence':seq}
            if not mat:
                report['results'].append(rec); continue
            sp=SharedPtr(ctypes.c_void_p(mat),ctypes.c_void_p(fake_ctrl()))
            # optionally analyze before model
            call_results=[]
            if seq:
                builder=SharedPtr(); cdef(ctypes.byref(builder)); ctrl=ctypes.create_string_buffer(0x4000); KEEP.append(ctrl); ctrl_ctor(ctypes.byref(ctrl),ctypes.byref(builder))
                for step in seq:
                    try:
                        ok=bool((img_an_sp if step=='imgAnalyzeSyn' else temp_an_sp)(ctypes.byref(ctrl),ctypes.byref(sp)))
                        call_results.append({'call':step,'ok':ok})
                    except Exception as e: call_results.append({'call':step,'exception':repr(e)})
            model=ctypes.create_string_buffer(0x5000); KEEP.append(model); ctor(ctypes.byref(model)); setm(ctypes.byref(model),ctypes.byref(sp))
            rec['analyze_calls']=call_results
            rec['model_head']=words(ctypes.addressof(model),12)
            rows=[]
            for x,y in points:
                temp=ctypes.c_double(-999999.0); rel=ctypes.c_int32(-999); c=Coord(x,y)
                try:
                    ok=bool(getpos(ctypes.byref(model),ctypes.byref(temp),ctypes.byref(rel),ctypes.byref(c)))
                    cv=csv_val(csvmat,x,y)
                    rows.append({'x':x,'y':y,'ok':ok,'temp':temp.value,'reliability':rel.value,'csv':cv,'diff':None if cv is None or not ok else temp.value-cv})
                except Exception as e:
                    rows.append({'x':x,'y':y,'exception':repr(e),'csv':csv_val(csvmat,x,y)})
            diffs=[abs(r['diff']) for r in rows if r.get('diff') is not None]
            rec['points']=rows
            rec['mae']=sum(diffs)/len(diffs) if diffs else None
            rec['max_abs']=max(diffs) if diffs else None
            report['results'].append(rec)
    outdir.mkdir(parents=True,exist_ok=True); op=outdir/(jpeg.stem+'_tempmodel_gettemp_probe.json'); op.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    compact=[]
    for r in report['results']:
        pts=r.get('points') or []
        useful=sum(1 for p in pts if p.get('ok'))
        compact.append({'parse':r.get('parse_meta'),'seq':r.get('sequence'),'mat':r.get('mat'),'calls':r.get('analyze_calls'),'ok_points':useful,'mae':r.get('mae'),'max_abs':r.get('max_abs'),'sample':pts[:5]})
    print(json.dumps({'csv_shape':report['csv_shape'],'compact':compact,'out':str(op)},ensure_ascii=False,indent=2)[:30000])
    return 0
if __name__=='__main__': raise SystemExit(main())
