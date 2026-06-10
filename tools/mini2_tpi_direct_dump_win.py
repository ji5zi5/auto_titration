#!/usr/bin/env python3
from __future__ import annotations
import argparse, ctypes, json, os, struct, math
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
        ctypes.memmove(ctypes.addressof(st),b,len(b)); st.buf[len(b)]=0; st.size=len(b); st.capacity=15
    else:
        keep=ctypes.create_string_buffer(b+b'\0'); p=ctypes.c_void_p(ctypes.addressof(keep)); ctypes.memmove(ctypes.addressof(st),ctypes.byref(p),8); st.size=len(b); st.capacity=len(b); KEEP.append(keep)
    return st
def fake_ctrl(initial=1000000):
    ctrl=ctypes.create_string_buffer(0x40); vt=(ctypes.c_void_p*4)(); ctypes.c_void_p.from_buffer(ctrl,0).value=ctypes.addressof(vt); ctypes.c_uint32.from_buffer(ctrl,8).value=initial; ctypes.c_uint32.from_buffer(ctrl,12).value=initial; KEEP.extend([ctrl,vt]); return ctypes.addressof(ctrl)
def hx(v): return hex(int(v)) if v else None
def u64(addr): return struct.unpack('<Q',ctypes.string_at(int(addr),8))[0]
def dump_buf(buf,n=256):
    raw=bytes(buf.raw[:n])
    return {'hex':raw.hex(' '),'u32':[struct.unpack_from('<I',raw,i)[0] for i in range(0,len(raw)-3,4)],'i32':[struct.unpack_from('<i',raw,i)[0] for i in range(0,len(raw)-3,4)],'f32':[struct.unpack_from('<f',raw,i)[0] for i in range(0,len(raw)-3,4)],'qword':[hex(struct.unpack_from('<Q',raw,i)[0]) for i in range(0,len(raw)-7,8)]}
def safe_read(addr,n):
    try: return ctypes.string_at(int(addr),n)
    except Exception: return b''
def ptr_probe(addr,label=''):
    rec={'label':label,'ptr':hx(addr)}
    if not addr: return rec
    raw=safe_read(addr,256)
    if raw:
        rec.update({'u32':[struct.unpack_from('<I',raw,i)[0] for i in range(0,min(len(raw),128)-3,4)],'i32':[struct.unpack_from('<i',raw,i)[0] for i in range(0,min(len(raw),128)-3,4)],'f32':[struct.unpack_from('<f',raw,i)[0] for i in range(0,min(len(raw),128)-3,4)],'qword':[hex(struct.unpack_from('<Q',raw,i)[0]) for i in range(0,min(len(raw),128)-7,8)]})
        # candidate numeric array stats
        for typ,fmt,sz in [('u16','<H',2),('i32','<i',4),('f32','<f',4)]:
            vals=[]
            maxn=min(len(raw),1024)
            for i in range(0,maxn-sz+1,sz):
                try: vals.append(struct.unpack_from(fmt,raw,i)[0])
                except: break
            if vals:
                nums=[float(v) for v in vals if isinstance(v,(int,float)) and math.isfinite(float(v))]
                if nums: rec[typ+'_stats']={'n':len(nums),'min':min(nums),'max':max(nums),'mean':sum(nums)/len(nums),'first16':vals[:16]}
    return rec

def parse_mat(ana,pix,jpeg,parser='analytics',flag=False):
    st=sstr(str(jpeg)); vec=StdVector(None,None,None)
    if parser=='analytics':
        f=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_int32,ctypes.POINTER(StdString),ctypes.POINTER(StdVector),ctypes.c_bool)(proc(ana,b'?createMaterialQ@FileParseFactory@MicroAnalytics@@SAPEAVTakedMaterial@MICROPIXELER@@W4MaterialType@iVMS4800@@AEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@AEBV?$vector@UCustomFusionMatchParam@iVMS4800@@V?$allocator@UCustomFusionMatchParam@iVMS4800@@@std@@@8@_N@Z'))
        return f(3,ctypes.byref(st),ctypes.byref(vec),flag), {'parser':parser,'type':3,'flag':flag}
    f=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.POINTER(ctypes.c_uint32),ctypes.POINTER(ctypes.c_bool),ctypes.POINTER(StdString),ctypes.POINTER(StdVector),ctypes.c_bool)(proc(pix,b'?parseRadiometricsJPEG@MaterialParseFactory@MICROPIXELER@@SAPEAVTakedMaterial@2@AEAIAEA_NAEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@AEBV?$vector@UCustomFusionMatchParam@iVMS4800@@V?$allocator@UCustomFusionMatchParam@iVMS4800@@@std@@@5@_N@Z'))
    ot=ctypes.c_uint32(); ob=ctypes.c_bool(); mat=f(ctypes.byref(ot),ctypes.byref(ob),ctypes.byref(st),ctypes.byref(vec),flag)
    return mat, {'parser':parser,'flag':flag,'out_type':ot.value,'out_bool':bool(ob.value)}

def analyze_seq(pix,mat,seq):
    sp=SharedPtr(ctypes.c_void_p(mat),ctypes.c_void_p(fake_ctrl()))
    cdef=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_void_p)(proc(pix,b'?createDefault@AnalyzerBuilderManager@MICROPIXELER@@SA?AV?$shared_ptr@VAnalyzerBuilderManager@MICROPIXELER@@@std@@XZ'))
    ctor=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_void_p,ctypes.POINTER(SharedPtr))(proc(pix,b'??0TakedMaterialAnalyzControl@MICROPIXELER@@QEAA@V?$shared_ptr@VAnalyzerBuilderManager@MICROPIXELER@@@std@@@Z'))
    builder=SharedPtr(); cdef(ctypes.byref(builder)); ctrl=ctypes.create_string_buffer(0x5000); KEEP.append(ctrl); ctor(ctypes.byref(ctrl),ctypes.byref(builder))
    funcs={
        'tempAnalyze':ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.POINTER(SharedPtr))(proc(pix,b'?tempAnalyze@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NV?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@@Z')),
        'imgAnalyzeSyn':ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.POINTER(SharedPtr))(proc(pix,b'?imgAnalyzeSyn@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NV?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@@Z')),
        'ruleAreaMeasure':ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.c_void_p,ctypes.POINTER(SharedPtr))(proc(pix,b'?ruleAreaMeasure@TakedMaterialAnalyzControl@MICROPIXELER@@QEAA_NV?$shared_ptr@VTakedMaterial@MICROPIXELER@@@std@@@Z')),
    }
    out=[]
    for s in seq:
        try: out.append({'call':s,'ok':bool(funcs[s](ctypes.byref(ctrl),ctypes.byref(sp)))})
        except Exception as e: out.append({'call':s,'exception':repr(e)})
    return out

def get_tpi(pix,mat):
    raw=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_void_p)(proc(pix,b'?thermalPicInterface@TakedMaterial@MICROPIXELER@@QEBAPEBVThermalPicInterface@2@XZ'))
    spfn=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p)(proc(pix,b'?getThermalPicInterface@TakedMaterial@MICROPIXELER@@QEAA?AV?$shared_ptr@VThermalPicInterface@MICROPIXELER@@@std@@XZ'))
    t_raw=raw(ctypes.c_void_p(mat))
    sp=SharedPtr(); rv=spfn(ctypes.c_void_p(mat),ctypes.byref(sp))
    return t_raw,sp,rv

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--dll-dir',type=Path,default=DLL_DIR_DEFAULT); ap.add_argument('--jpeg',type=Path,required=True); ap.add_argument('--out',type=Path,default=Path('data/mini2_tpi_direct_dump'))
    a=ap.parse_args(); orig=Path.cwd(); jpeg=a.jpeg.resolve(); outdir=a.out if a.out.is_absolute() else orig/a.out
    add_dir(a.dll_dir); pix=ctypes.WinDLL(str(a.dll_dir/'MicroPixeler_Release_x64.dll')); ana=ctypes.WinDLL(str(a.dll_dir/'MicroAnalytics_Release_x64.dll'))
    f_get_resolution=ctypes.CFUNCTYPE(None,ctypes.c_void_p,ctypes.c_void_p)(proc(pix,b'?getResolutionInfo@ThermalPicInterface@MICROPIXELER@@QEBAXAEAUResolutionInfo@iVMS4800@@@Z'))
    f_get_thermal=ctypes.CFUNCTYPE(None,ctypes.c_void_p,ctypes.c_void_p)(proc(pix,b'?getThermalPic@ThermalPicInterface@MICROPIXELER@@QEBAXAEAUImage@MicroSDK@@@Z'))
    f_get_globe=ctypes.CFUNCTYPE(None,ctypes.c_void_p,ctypes.c_void_p)(proc(pix,b'?getGlobeTempParam@ThermalPicInterface@MICROPIXELER@@QEBAXAEAUGlobeTempParam@iVMS4800@@@Z'))
    f_get_rule=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_void_p,ctypes.c_uint32)(proc(pix,b'?getRule@ThermalPicInterface@MICROPIXELER@@QEAAPEAVRule@2@I@Z'))
    f_get_rule_res=ctypes.CFUNCTYPE(None,ctypes.c_void_p,ctypes.c_void_p)(proc(pix,b'?getThermResult@Rule@MICROPIXELER@@QEBAXAEAURuleThermResult@iVMS4800@@@Z'))
    rep={'jpeg':str(jpeg),'cases':[]}
    for parser in ['analytics','pix']:
        for flag in [False,True]:
            mat,meta=parse_mat(ana,pix,jpeg,parser,flag)
            for seq in [[],['tempAnalyze'],['ruleAreaMeasure'],['tempAnalyze','ruleAreaMeasure']]:
                case={'parse':meta,'mat':hx(mat),'seq':seq}
                if not mat: rep['cases'].append(case); continue
                case['analyze']=analyze_seq(pix,mat,seq) if seq else []
                t_raw,sp,rv=get_tpi(pix,mat); case['tpi_raw']=hx(t_raw); case['tpi_sp']={'ptr':hx(sp.ptr),'ctrl':hx(sp.ctrl),'rv':hx(rv)}
                t=int(sp.ptr or t_raw or 0)
                if t:
                    for name,fn,size in [('resolution',f_get_resolution,0x100),('thermalPic',f_get_thermal,0x400),('globeTempParam',f_get_globe,0x500)]:
                        buf=ctypes.create_string_buffer(size)
                        try:
                            fn(ctypes.c_void_p(t),ctypes.byref(buf)); rec=dump_buf(buf,min(size,0x300))
                            # follow qword-looking pointers from first 0x100 bytes
                            ptrs=[]
                            for off in range(0,min(size,0x100)-7,8):
                                p=struct.unpack_from('<Q',buf.raw,off)[0]
                                if 0x10000 < p < 0x7fffffffffff:
                                    ptrs.append({'off':hex(off),**ptr_probe(p,name+':'+hex(off))})
                            rec['ptrs']=ptrs[:20]
                            case[name]=rec
                        except Exception as e: case[name+'_exception']=repr(e)
                    for rid in [0,1,2,100,0xffffffff]:
                        try:
                            rule=f_get_rule(ctypes.c_void_p(t),ctypes.c_uint32(rid)); rr={'rid':rid,'rule':hx(rule)}
                            if rule:
                                buf=ctypes.create_string_buffer(0x500); f_get_rule_res(ctypes.c_void_p(rule),ctypes.byref(buf)); rr['thermResult']=dump_buf(buf,0x300)
                                ptrs=[]
                                for off in range(0,0x100-7,8):
                                    p=struct.unpack_from('<Q',buf.raw,off)[0]
                                    if 0x10000 < p < 0x7fffffffffff: ptrs.append({'off':hex(off),**ptr_probe(p,'rule:'+hex(off))})
                                rr['ptrs']=ptrs[:20]
                            case.setdefault('rules',[]).append(rr)
                        except Exception as e: case.setdefault('rules',[]).append({'rid':rid,'exception':repr(e)})
                rep['cases'].append(case)
    outdir.mkdir(parents=True,exist_ok=True); op=outdir/(jpeg.stem+'_tpi_direct_dump.json'); op.write_text(json.dumps(rep,ensure_ascii=False,indent=2),encoding='utf-8')
    compact=[]
    for c in rep['cases']:
        compact.append({
            'parse':c.get('parse'),'seq':c.get('seq'),'mat':c.get('mat'),'analyze':c.get('analyze'),'tpi_raw':c.get('tpi_raw'),'tpi_sp':c.get('tpi_sp'),
            'resolution_u32':(c.get('resolution') or {}).get('u32',[])[:16],
            'thermal_u32':(c.get('thermalPic') or {}).get('u32',[])[:32],
            'thermal_ptrs':[(p.get('off'),p.get('u16_stats'),p.get('i32_stats'),p.get('f32_stats')) for p in (c.get('thermalPic') or {}).get('ptrs',[])[:6]],
            'globe_u32':(c.get('globeTempParam') or {}).get('u32',[])[:40],
            'globe_ptrs':[(p.get('off'),p.get('u16_stats'),p.get('i32_stats'),p.get('f32_stats')) for p in (c.get('globeTempParam') or {}).get('ptrs',[])[:8]],
            'rules':[{k:r.get(k) for k in ['rid','rule']} for r in c.get('rules',[])],
        })
    print(json.dumps({'compact':compact,'out':str(op)},ensure_ascii=False,indent=2)[:40000])
if __name__=='__main__': main()
