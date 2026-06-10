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

def make_std_string(s: str):
    b=s.encode('utf-8')
    st=StdString()
    keep=None
    if len(b) < 16:
        ctypes.memmove(ctypes.addressof(st), b, len(b))
        st.buf[len(b)] = 0
        st.size=len(b); st.capacity=15
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

def hx(v):
    return hex(int(v)) if v else None

def u64_at(addr):
    return int(ctypes.c_uint64.from_address(int(addr)).value)

def dump_ptrs(addr, n, base=0):
    out=[]
    if not addr: return out
    for i in range(n):
        try:
            val=u64_at(int(addr)+i*8)
            item={'slot':i,'ptr':hx(val)}
            if base and val and base <= val < base + 0x4000000:
                item['rva']=hex(val-base)
            out.append(item)
        except Exception as e:
            out.append({'slot':i,'error':repr(e)})
            break
    return out

def decode_buf(buf, n=128):
    raw=bytes(buf.raw[:n])
    return {
        'u32':[int.from_bytes(raw[i:i+4],'little',signed=False) for i in range(0,n,4)],
        'i32':[int.from_bytes(raw[i:i+4],'little',signed=True) for i in range(0,n,4)],
        'u16':[int.from_bytes(raw[i:i+2],'little',signed=False) for i in range(0,min(n,128),2)],
        'hex':raw[:128].hex(' '),
    }

def call_bool_slot(vptr, slot, this_ptr, out_size=0x2000):
    fptr=u64_at(int(vptr)+slot*8)
    out=ctypes.create_string_buffer(out_size)
    fn=ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)(fptr)
    ok=bool(fn(ctypes.c_void_p(this_ptr), ctypes.byref(out)))
    return {'slot':slot,'fptr':hx(fptr),'ok':ok,'buf':decode_buf(out,256)}

def call_void_float_slot(vptr, slot, this_ptr):
    fptr=u64_at(int(vptr)+slot*8)
    out=ctypes.c_float(-9999.0)
    fn=ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.POINTER(ctypes.c_float))(fptr)
    fn(ctypes.c_void_p(this_ptr), ctypes.byref(out))
    return {'slot':slot,'fptr':hx(fptr),'value':float(out.value)}

def call_shared_ret_slot(vptr, slot, this_ptr):
    fptr=u64_at(int(vptr)+slot*8)
    sp=SharedPtr()
    fn=ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(fptr)
    rv=fn(ctypes.c_void_p(this_ptr), ctypes.byref(sp))
    return {'slot':slot,'fptr':hx(fptr),'rv':hx(rv),'shared_ptr':{'ptr':hx(sp.ptr),'ctrl':hx(sp.ctrl)},'mem':dump_ptrs(sp.ptr,32)}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--dll-dir',type=Path,default=DLL_DIR_DEFAULT)
    ap.add_argument('--jpeg',type=Path,required=True)
    ap.add_argument('--out',type=Path,default=Path('data/mini2_micropixeler_vtable_probe'))
    a=ap.parse_args()
    orig=Path.cwd()
    jpeg_abs=a.jpeg.resolve()
    out_dir=a.out if a.out.is_absolute() else orig/a.out
    add_dll_dir(a.dll_dir)
    dll=ctypes.WinDLL(str(a.dll_dir/'MicroPixeler_Release_x64.dll'))
    base=int(dll._handle)
    rep={'jpeg':str(jpeg_abs),'module_base':hx(base),'steps':[]}

    s,keep=make_std_string(str(jpeg_abs))
    vec=StdVector(None,None,None)
    out_type=ctypes.c_uint32(0xdeadbeef); out_bool=ctypes.c_bool(False)
    parse_addr=get_proc(dll,b'?parseRadiometricsJPEG@MaterialParseFactory@MICROPIXELER@@SAPEAVTakedMaterial@2@AEAIAEA_NAEBV?$basic_string@DU?$char_traits@D@std@@V?$allocator@D@2@@std@@AEBV?$vector@UCustomFusionMatchParam@iVMS4800@@V?$allocator@UCustomFusionMatchParam@iVMS4800@@@std@@@5@_N@Z')
    parse=ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_bool), ctypes.POINTER(StdString), ctypes.POINTER(StdVector), ctypes.c_bool)(parse_addr)
    mat=parse(ctypes.byref(out_type),ctypes.byref(out_bool),ctypes.byref(s),ctypes.byref(vec),False)
    rep['steps'].append({'parse_ptr':hx(mat),'out_type':int(out_type.value),'out_bool':bool(out_bool.value)})
    if not mat:
        raise SystemExit(json.dumps(rep,ensure_ascii=False,indent=2))
    mat_vptr=u64_at(mat)
    rep['steps'].append({'mat_vptr':hx(mat_vptr),'mat_vtable':dump_ptrs(mat_vptr,24,base)})

    # Get thermal interface shared_ptr. ABI: RCX=this, RDX=hidden return shared_ptr.
    get_tpi_addr=get_proc(dll,b'?getThermalPicInterface@TakedMaterial@MICROPIXELER@@QEAA?AV?$shared_ptr@VThermalPicInterface@MICROPIXELER@@@std@@XZ')
    get_tpi=ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(get_tpi_addr)
    tpi_sp=SharedPtr(); rv=get_tpi(ctypes.c_void_p(mat), ctypes.byref(tpi_sp))
    rep['steps'].append({'get_tpi_rv':hx(rv),'tpi_sp':{'ptr':hx(tpi_sp.ptr),'ctrl':hx(tpi_sp.ctrl)}})
    if tpi_sp.ptr:
        tpi_vptr=u64_at(tpi_sp.ptr)
        rep['steps'].append({'tpi_vptr':hx(tpi_vptr),'tpi_mem':dump_ptrs(tpi_sp.ptr,96,base),'tpi_vtable':dump_ptrs(tpi_vptr,80,base)})
        # Call real virtual dispatch slots, not base export stubs.
        virtual_calls=[]
        for name,slot in [
            ('tryData',0),
            ('getGrayToTempTable',2),
            ('getCapabilitiesSet',9),
            ('getRawDataInfo',12),
            ('getLevelSpanParams',14),
            ('getPseudoColorParams',20),
            ('getMeasureEnvParams',38),
            ('getTempMeasurementParams',50),
        ]:
            try:
                if name=='tryData':
                    fptr=u64_at(tpi_vptr+slot*8)
                    fn=ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.c_void_p)(fptr)
                    virtual_calls.append({'name':name,'slot':slot,'fptr':hx(fptr),'ok':bool(fn(ctypes.c_void_p(tpi_sp.ptr)))})
                elif name=='getGrayToTempTable':
                    r=call_shared_ret_slot(tpi_vptr,slot,tpi_sp.ptr); r['name']=name; virtual_calls.append(r)
                else:
                    r=call_bool_slot(tpi_vptr,slot,tpi_sp.ptr); r['name']=name; virtual_calls.append(r)
            except Exception as e:
                virtual_calls.append({'name':name,'slot':slot,'exception':repr(e)})
        rep['steps'].append({'virtual_calls':virtual_calls})
    out_dir.mkdir(parents=True,exist_ok=True)
    op=out_dir/(jpeg_abs.stem+'_vtable_probe.json')
    op.write_text(json.dumps(rep,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(rep,ensure_ascii=False,indent=2)[:30000])
    print('saved:',op)

if __name__=='__main__': main()
