#!/usr/bin/env python3
"""Probe MicroJPEG MicroRImage V1/V2 factory against SDMP/APP3 blocks only.

Avoids StandardRImage/libjpeg paths, which can abort on non-JPEG payloads.
Uses correct MSVC x64 sret ABI for getters if an object is returned.
"""
from __future__ import annotations
import argparse, ctypes, json, os, struct, zipfile, io
from pathlib import Path
from mini2_sdk_exact_probe_win import collect_blocks

DLL_DIR_DEFAULT = Path(r"C:\Program Files\HIKMICRO Analyzer\HIKMICRO Analyzer")
class BareBlock(ctypes.Structure):
    _fields_=[('data',ctypes.c_void_p),('size',ctypes.c_uint32),('pad',ctypes.c_uint32)]

def add_dll_dir(d):
    if hasattr(os,'add_dll_directory'): os.add_dll_directory(str(d))
    ctypes.windll.kernel32.SetDllDirectoryW(str(d))

def get_proc(dll,name):
    k=ctypes.windll.kernel32; k.GetProcAddress.argtypes=[ctypes.c_void_p,ctypes.c_char_p]; k.GetProcAddress.restype=ctypes.c_void_p
    a=k.GetProcAddress(dll._handle,name)
    if not a: raise RuntimeError(f'missing {name!r}')
    return int(a)

def make_block(data):
    buf=ctypes.create_string_buffer(data)
    return buf,BareBlock(ctypes.cast(buf,ctypes.c_void_p),len(data),0)

def u32s(raw,n=256): return [int.from_bytes(raw[i:i+4],'little',signed=False) for i in range(0,min(n,len(raw)),4)]
def i32s(raw,n=256): return [int.from_bytes(raw[i:i+4],'little',signed=True) for i in range(0,min(n,len(raw)),4)]
def nz(raw,n=1024):
    vals=u32s(raw,n)
    return [{'idx':i,'off':hex(i*4),'value':v,'hex':hex(v)} for i,v in enumerate(vals) if v][:80]

def sret(dll,name,ptr,size=0x1000):
    out=ctypes.create_string_buffer(size)
    fn=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p)(get_proc(dll,name))
    rv=fn(ctypes.byref(out),ctypes.c_void_p(ptr))
    raw=bytes(out.raw)
    return {'return':hex(rv) if rv else None,'u32_prefix':u32s(raw,256),'i32_prefix':i32s(raw,256),'nonzero_u32':nz(raw,1024),'hex_prefix':raw[:256].hex(' ')}

def main(argv=None):
    ap=argparse.ArgumentParser(); ap.add_argument('--dll-dir',type=Path,default=DLL_DIR_DEFAULT); ap.add_argument('--jpeg',type=Path,required=True); ap.add_argument('--out',type=Path,default=Path('data/mini2_microjpeg_rimage_block_probe'))
    args=ap.parse_args(argv)
    add_dll_dir(args.dll_dir); dll=ctypes.WinDLL(str(args.dll_dir/'MicroJPEG_Release_x64.dll'))
    funcs={
      'v1_is':ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.POINTER(BareBlock))(get_proc(dll,b'?is@MicroRImageV1@MicroSDK@@SA_NAEBUBareBlock@2@@Z')),
      'v2_is':ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.POINTER(BareBlock))(get_proc(dll,b'?is@MicroRImageV2@MicroSDK@@SA_NAEBUBareBlock@2@@Z')),
      'v1_create_ret':ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.POINTER(BareBlock))(get_proc(dll,b'?createMicroRImageV1@ImageFactory@MicroSDK@@SAPEAVMicroRImageV1@2@AEBUBareBlock@2@@Z')),
      'v2_create_ret':ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.POINTER(BareBlock))(get_proc(dll,b'?createMicroRImageV2@ImageFactory@MicroSDK@@SAPEAVMicroRImageV2@2@AEBUBareBlock@2@@Z')),
      'v1_create_bool':ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.POINTER(ctypes.c_void_p),ctypes.POINTER(BareBlock))(get_proc(dll,b'?createMicroRImageV1@ImageFactory@MicroSDK@@SA_NPEAPEAVMicroRImageV1@2@AEBUBareBlock@2@@Z')),
      'v2_create_bool':ctypes.CFUNCTYPE(ctypes.c_bool,ctypes.POINTER(ctypes.c_void_p),ctypes.POINTER(BareBlock))(get_proc(dll,b'?createMicroRImageV2@ImageFactory@MicroSDK@@SA_NPEAPEAVMicroRImageV2@2@AEBUBareBlock@2@@Z')),
    }
    getters={
      'v1.raw': b'?rawDataInfo@MicroRImageV1@MicroSDK@@UEBA?AURawDataInfo@2@XZ',
      'v2.raw': b'?rawDataInfo@MicroRImageV2@MicroSDK@@UEBA?AURawDataInfo@2@XZ',
      'v1.tempDevice': b'?tempDeviceConfigParams@MicroRImageV1@MicroSDK@@UEBA?AUTempDeviceConfigParams@2@XZ',
      'v2.tempDevice': b'?tempDeviceConfigParams@MicroRImageV2@MicroSDK@@UEBA?AUTempDeviceConfigParams@2@XZ',
      'v1.tempMeasure': b'?tempMeasurementParams@MicroRImageV1@MicroSDK@@UEBA?AUTempMeasurementParameters@2@XZ',
      'v2.tempMeasure': b'?tempMeasurementParams@MicroRImageV2@MicroSDK@@UEBA?AUTempMeasurementParameters@2@XZ',
    }
    allb=collect_blocks(args.jpeg)
    # Include only candidate radiometric binary payloads, not full JPEG/normal APPs.
    items=[]
    for k,v in allb.items():
        if 'APP3' in k or k.endswith('tag0_data') or k.endswith('tag1_data'):
            items.append((k,v))
    # add variants of APP3 with SDMP stripped after header/table to catch parser expectations
    records=[]
    for name,data in items:
        if not data or len(data)>200000: continue
        rec={'block':name,'len':len(data),'magic':data[:32].hex(' '),'is':{},'creates':[]}
        buf,blk=make_block(data)
        for which in ['v1_is','v2_is']:
            try: rec['is'][which]=bool(funcs[which](ctypes.byref(blk)))
            except Exception as e: rec['is'][which]=repr(e)
        for which in ['v1_create_ret','v2_create_ret']:
            cre={'call':which,'ptr':None,'methods':{}}
            try:
                ptr=funcs[which](ctypes.byref(blk)) or 0
                cre['ptr']=hex(ptr) if ptr else None
                if ptr:
                    try: cre['obj_prefix']=ctypes.string_at(ptr,0x80).hex(' ')
                    except Exception as e: cre['obj_exception']=repr(e)
                    for gl,gn in getters.items():
                        if gl.startswith('v1.') and 'v1_' not in which: continue
                        if gl.startswith('v2.') and 'v2_' not in which: continue
                        try: cre['methods'][gl]=sret(dll,gn,ptr)
                        except Exception as e: cre['methods'][gl]={'exception':repr(e)}
            except Exception as e: cre['exception']=repr(e)
            rec['creates'].append(cre)
        for which in ['v1_create_bool','v2_create_bool']:
            cre={'call':which,'ok':None,'ptr':None,'methods':{}}
            try:
                op=ctypes.c_void_p(); ok=funcs[which](ctypes.byref(op),ctypes.byref(blk)); ptr=op.value or 0
                cre['ok']=bool(ok); cre['ptr']=hex(ptr) if ptr else None
                if ptr:
                    for gl,gn in getters.items():
                        if gl.startswith('v1.') and 'v1_' not in which: continue
                        if gl.startswith('v2.') and 'v2_' not in which: continue
                        try: cre['methods'][gl]=sret(dll,gn,ptr)
                        except Exception as e: cre['methods'][gl]={'exception':repr(e)}
            except Exception as e: cre['exception']=repr(e)
            rec['creates'].append(cre)
        if rec['is'].get('v1_is') or rec['is'].get('v2_is') or any(c.get('ptr') or c.get('ok') or c.get('exception') for c in rec['creates']):
            records.append(rec); print(json.dumps(rec,ensure_ascii=False)[:3000])
    report={'jpeg':str(args.jpeg),'records':records}
    args.out.mkdir(parents=True,exist_ok=True); op=args.out/f'{args.jpeg.stem}_rimage_block_probe.json'; op.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print('saved:',op)
    return 0
if __name__=='__main__': raise SystemExit(main())
