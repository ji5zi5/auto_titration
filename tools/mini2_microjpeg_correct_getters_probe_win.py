#!/usr/bin/env python3
from __future__ import annotations
import argparse, ctypes, json, os, struct
from pathlib import Path
DLL_DIR_DEFAULT=Path(r"C:\Program Files\HIKMICRO Analyzer\HIKMICRO Analyzer")
class BareBlock(ctypes.Structure): _fields_=[('data',ctypes.c_void_p),('size',ctypes.c_uint32),('pad',ctypes.c_uint32)]
def add(p):
    if hasattr(os,'add_dll_directory'): os.add_dll_directory(str(p))
    ctypes.windll.kernel32.SetDllDirectoryW(str(p))
def proc(dll,name):
    k=ctypes.windll.kernel32; k.GetProcAddress.argtypes=[ctypes.c_void_p,ctypes.c_char_p]; k.GetProcAddress.restype=ctypes.c_void_p
    a=k.GetProcAddress(dll._handle,name)
    if not a: raise RuntimeError(name)
    return int(a)
def bb(data):
    b=ctypes.create_string_buffer(data,len(data)); return b,BareBlock(ctypes.cast(b,ctypes.c_void_p),len(data),0)
def ptrs(addr,n=0x800):
    out=[]
    for off in range(0,n,8):
        try: v=ctypes.c_void_p.from_address(addr+off).value or 0
        except Exception: break
        if v: out.append([hex(off),hex(v)])
    return out
def hexmem(addr,n=0x80):
    try: raw=ctypes.string_at(addr,n)
    except Exception as e: return {'error':repr(e)}
    return {'hex':raw.hex(' '),'u32':[struct.unpack_from('<I',raw,i)[0] for i in range(0,n//4*4,4)],'ascii':''.join(chr(x) if 32<=x<127 else '.' for x in raw)}
def call_val(addr,this,size,label):
    # try both possible ABIs in isolated catch
    reps=[]
    for abi in ['this_ret','ret_this']:
        buf=ctypes.create_string_buffer(size)
        fn=ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.c_void_p,ctypes.c_void_p)(addr)
        try:
            if abi=='this_ret': ret=fn(ctypes.c_void_p(this), ctypes.c_void_p(ctypes.addressof(buf)))
            else: ret=fn(ctypes.c_void_p(ctypes.addressof(buf)), ctypes.c_void_p(this))
            raw=bytes(buf.raw)
            reps.append({'label':label,'abi':abi,'ok':True,'ret':hex(ret) if ret else None,'hex128':raw[:128].hex(' '),'u32_64':[struct.unpack_from('<I',raw,i)[0] for i in range(0,256,4)],'ascii128':''.join(chr(x) if 32<=x<127 else '.' for x in raw[:128])})
        except Exception as e:
            reps.append({'label':label,'abi':abi,'ok':False,'exception':repr(e)})
    return reps
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--dll-dir',type=Path,default=DLL_DIR_DEFAULT); ap.add_argument('--jpeg',type=Path,default=Path('data/fixtures/mini2/IR_00001.jpeg')); ap.add_argument('--out',type=Path,default=Path('data/mini2_microjpeg_correct_getters_probe')); args=ap.parse_args()
    add(args.dll_dir); mj=ctypes.WinDLL(str(args.dll_dir/'MicroJPEG_Release_x64.dll'))
    data=args.jpeg.read_bytes(); keep,block=bb(data)
    names={
      'fileType':b'?fileType@MicroSDK@@YA?AW4FileType@1@AEBUBareBlock@1@@Z',
      'createImage':b'?createImage@MicroSDK@@YAPEAVBaseImage@1@AEBUBareBlock@1@@Z',
      'createImage_ft':b'?createImage@MicroSDK@@YAPEAVBaseImage@1@AEBUBareBlock@1@W4FileType@1@@Z',
      'createMicroRImageV1':b'?createMicroRImageV1@ImageFactory@MicroSDK@@SAPEAVMicroRImageV1@2@AEBUBareBlock@2@@Z',
      'createMicroRImageV2':b'?createMicroRImageV2@ImageFactory@MicroSDK@@SAPEAVMicroRImageV2@2@AEBUBareBlock@2@@Z',
      'createStandardRImage':b'?createStandardRImage@ImageFactory@MicroSDK@@SAPEAVStandardRImage@2@AEBUBareBlock@2@@Z',
      'type':b'?type@BaseImage@MicroSDK@@QEBA?AW4FileType@2@XZ',
      'raw_v1':b'?rawDataInfo@MicroRImageV1@MicroSDK@@UEBA?AURawDataInfo@2@XZ',
      'raw_v2':b'?rawDataInfo@MicroRImageV2@MicroSDK@@UEBA?AURawDataInfo@2@XZ',
      'raw_thermal':b'?rawDataInfo@ThermalImage@MicroSDK@@UEBA?AURawDataInfo@2@XZ',
      'dev_v1':b'?tempDeviceConfigParams@MicroRImageV1@MicroSDK@@UEBA?AUTempDeviceConfigParams@2@XZ',
      'dev_v2':b'?tempDeviceConfigParams@MicroRImageV2@MicroSDK@@UEBA?AUTempDeviceConfigParams@2@XZ',
      'dev_std':b'?tempDeviceConfigParams@StandardRImage@MicroSDK@@UEBA?AUTempDeviceConfigParams@2@XZ',
      'dev_thermal':b'?tempDeviceConfigParams@ThermalImage@MicroSDK@@UEBA?AUTempDeviceConfigParams@2@XZ',
      'meas_v1':b'?tempMeasurementParams@MicroRImageV1@MicroSDK@@UEBA?AUTempMeasurementParameters@2@XZ',
      'meas_v2':b'?tempMeasurementParams@MicroRImageV2@MicroSDK@@UEBA?AUTempMeasurementParameters@2@XZ',
      'meas_std':b'?tempMeasurementParams@StandardRImage@MicroSDK@@UEBA?AUTempMeasurementParameters@2@XZ',
      'meas_thermal':b'?tempMeasurementParams@ThermalImage@MicroSDK@@UEBA?AUTempMeasurementParameters@2@XZ',
    }
    addrs={k:proc(mj,v) for k,v in names.items()}
    ftype=ctypes.CFUNCTYPE(ctypes.c_int32,ctypes.POINTER(BareBlock))(addrs['fileType'])(ctypes.byref(block))
    rep={'jpeg':str(args.jpeg),'fileType':int(ftype),'objects':[]}
    creators=[]
    creators.append(('createImage', ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.POINTER(BareBlock))(addrs['createImage']), (ctypes.byref(block),)))
    for ft in range(0,6):
        creators.append((f'createImage_ft{ft}', ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.POINTER(BareBlock),ctypes.c_int32)(addrs['createImage_ft']), (ctypes.byref(block),ft)))
    for k in ['createMicroRImageV1','createMicroRImageV2','createStandardRImage']:
        creators.append((k, ctypes.CFUNCTYPE(ctypes.c_void_p,ctypes.POINTER(BareBlock))(addrs[k]), (ctypes.byref(block),)))
    typefn=ctypes.CFUNCTYPE(ctypes.c_int32,ctypes.c_void_p)(addrs['type'])
    for label,fn,pargs in creators:
        o={'creator':label}
        try: ptr=fn(*pargs) or 0
        except Exception as e: o['exception']=repr(e); ptr=0
        o['ptr']=hex(ptr) if ptr else None
        if ptr:
            try: o['type']=int(typefn(ctypes.c_void_p(ptr)))
            except Exception as e: o['type_exception']=repr(e)
            o['ptrs']=ptrs(ptr,0x900)
            for off in [0,0x18,0x28,0x4c0,0x4d8,0x4f8,0x500,0x518,0x528,0x540,0x590,0x5f8,0x608,0x650]:
                o[f'mem_{off:#x}']=hexmem(ptr+off,0x80)
            vals=[]
            for key in ['raw_v1','raw_v2','raw_thermal','dev_v1','dev_v2','dev_std','dev_thermal','meas_v1','meas_v2','meas_std','meas_thermal']:
                vals.extend(call_val(addrs[key],ptr,0x400,key))
            o['getter_calls']=vals
        rep['objects'].append(o)
        print(json.dumps({'creator':label,'ptr':o.get('ptr'),'type':o.get('type'),'ex':o.get('exception')},ensure_ascii=False))
    args.out.mkdir(parents=True,exist_ok=True); out=args.out/(args.jpeg.stem+'_correct_getters.json'); out.write_text(json.dumps(rep,ensure_ascii=False,indent=2),encoding='utf-8'); print('saved',out)
if __name__=='__main__': main()
