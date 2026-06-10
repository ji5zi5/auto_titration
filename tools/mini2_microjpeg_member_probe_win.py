#!/usr/bin/env python3
from __future__ import annotations
import argparse, ctypes, json, os, struct
from pathlib import Path

DLL_DIR_DEFAULT=Path(r"C:\Program Files\HIKMICRO Analyzer\HIKMICRO Analyzer")

class BareBlock(ctypes.Structure):
    _fields_=[('data',ctypes.c_void_p),('size',ctypes.c_uint32),('pad',ctypes.c_uint32)]

def add_dll_dir(p:Path):
    if hasattr(os,'add_dll_directory'): os.add_dll_directory(str(p))
    ctypes.windll.kernel32.SetDllDirectoryW(str(p))

def get_proc(dll,name:bytes):
    k32=ctypes.windll.kernel32
    k32.GetProcAddress.argtypes=[ctypes.c_void_p,ctypes.c_char_p]
    k32.GetProcAddress.restype=ctypes.c_void_p
    a=k32.GetProcAddress(dll._handle,name)
    if not a: raise RuntimeError(f'missing {name!r}')
    return int(a)

def make_block(data:bytes):
    buf=ctypes.create_string_buffer(data)
    return buf, BareBlock(ctypes.cast(buf,ctypes.c_void_p), len(data), 0)

def u32s(raw,n=128):
    return [struct.unpack_from('<I',raw,i)[0] for i in range(0,min(n,len(raw)),4)]
def i32s(raw,n=128):
    return [struct.unpack_from('<i',raw,i)[0] for i in range(0,min(n,len(raw)),4)]
def f32s(raw,n=128):
    return [struct.unpack_from('<f',raw,i)[0] for i in range(0,min(n,len(raw)),4)]
def ptrs_at(addr,n=0x100):
    out=[]
    for i in range(0,n,8):
        try: v=ctypes.c_void_p.from_address(addr+i).value or 0
        except Exception: break
        out.append(hex(v) if v else None)
    return out

def dump_mem(addr:int,n:int):
    try: raw=ctypes.string_at(addr,n)
    except Exception as e: return {'error':repr(e)}
    return {'addr':hex(addr),'len':n,'hex_first128':raw[:128].hex(' '),'u32_first64':u32s(raw,256),'i32_first64':i32s(raw,256),'f32_first64':f32s(raw,256)}

def call_sret(name, fn_addr, ptr, size=0x800):
    # MSVC x64 large-struct return: fn(retbuf*, this*)
    ret=ctypes.create_string_buffer(size)
    fn=ctypes.CFUNCTYPE(None, ctypes.c_void_p, ctypes.c_void_p)(fn_addr)
    try:
        rv=fn(ctypes.byref(ret), ctypes.c_void_p(ptr))
        raw=bytes(ret.raw)
        return {'ok':True,'rv':rv,'hex_first128':raw[:128].hex(' '),'u32_first96':u32s(raw,384),'i32_first96':i32s(raw,384),'f32_first64':f32s(raw,256)}
    except Exception as e:
        return {'ok':False,'exception':repr(e)}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument('--dll-dir',type=Path,default=DLL_DIR_DEFAULT)
    ap.add_argument('--jpeg',type=Path,default=Path('data/fixtures/mini2/IR_00001.jpeg'))
    ap.add_argument('--out',type=Path,default=Path('data/mini2_microjpeg_member_probe'))
    args=ap.parse_args()
    add_dll_dir(args.dll_dir)
    dll=ctypes.WinDLL(str(args.dll_dir/'MicroJPEG_Release_x64.dll'))
    exports={
      'fileType': b'?fileType@MicroSDK@@YA?AW4FileType@1@AEBUBareBlock@1@@Z',
      'createImage_static_ptr': b'?createImage@ImageFactory@MicroSDK@@SAPEAVBaseImage@2@AEBUBareBlock@2@W4FileType@2@@Z',
      'createImage_ns_ptr': b'?createImage@MicroSDK@@YAPEAVBaseImage@1@AEBUBareBlock@1@W4FileType@1@@Z',
      'type_BaseImage': b'?type@BaseImage@MicroSDK@@QEBA?AW4FileType@2@XZ',
      'rawDataInfo_BaseImage': b'?rawDataInfo@BaseImage@MicroSDK@@UEBA?AURawDataInfo@2@XZ',
      'rawDataInfo_MicroRImageV1': b'?rawDataInfo@MicroRImageV1@MicroSDK@@UEBA?AURawDataInfo@2@XZ',
      'rawDataInfo_MicroRImageV2': b'?rawDataInfo@MicroRImageV2@MicroSDK@@UEBA?AURawDataInfo@2@XZ',
      'tempDev_BaseImage': b'?tempDeviceConfigParams@BaseImage@MicroSDK@@UEBA?AUTempDeviceConfigParams@2@XZ',
      'tempDev_MicroRImageV1_value': b'?tempDeviceConfigParams@MicroRImageV1@MicroSDK@@UEBA?AUTempDeviceConfigParams@2@XZ',
      'tempDev_MicroRImageV1_ref': b'?tempDeviceConfigParams@MicroRImageV1@MicroSDK@@QEAAAEBUTempDeviceConfigParams@2@XZ',
      'tempDev_MicroRImageV2_value': b'?tempDeviceConfigParams@MicroRImageV2@MicroSDK@@UEBA?AUTempDeviceConfigParams@2@XZ',
      'tempDev_MicroRImageV2_ref': b'?tempDeviceConfigParams@MicroRImageV2@MicroSDK@@QEAAAEBUTempDeviceConfigParams@2@XZ',
      'tempMeas_BaseImage': b'?tempMeasurementParams@BaseImage@MicroSDK@@UEBA?AUTempMeasurementParameters@2@XZ',
      'tempMeas_MicroRImageV1': b'?tempMeasurementParams@MicroRImageV1@MicroSDK@@UEBA?AUTempMeasurementParameters@2@XZ',
      'tempMeas_MicroRImageV2': b'?tempMeasurementParams@MicroRImageV2@MicroSDK@@UEBA?AUTempMeasurementParameters@2@XZ',
      'measureResults_BaseImage': b'?measureResults@BaseImage@MicroSDK@@UEBA?AUMeasureResults@2@XZ',
    }
    addrs={k:get_proc(dll,v) for k,v in exports.items()}
    fileType=ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.POINTER(BareBlock))(addrs['fileType'])
    create_static=ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.POINTER(BareBlock), ctypes.c_int32)(addrs['createImage_static_ptr'])
    create_ns=ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.POINTER(BareBlock), ctypes.c_int32)(addrs['createImage_ns_ptr'])
    type_fn=ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p)(addrs['type_BaseImage'])
    ref_v1=ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p)(addrs['tempDev_MicroRImageV1_ref'])
    ref_v2=ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p)(addrs['tempDev_MicroRImageV2_ref'])
    data=args.jpeg.read_bytes(); buf,bb=make_block(data)
    report={'jpeg':str(args.jpeg),'exports':{k:hex(v) for k,v in addrs.items()},'attempts':[]}
    try: report['fileType']=int(fileType(ctypes.byref(bb)))
    except Exception as e: report['fileType_exception']=repr(e)
    factories=[('static',create_static),('ns',create_ns)]
    for fname, create in factories:
      for ft in range(0,8):
        att={'factory':fname,'ft':ft}
        try:
          ptr=create(ctypes.byref(bb),ft)
          att['ptr']=hex(ptr) if ptr else None
          if ptr:
            try: att['type']=int(type_fn(ctypes.c_void_p(ptr)))
            except Exception as e: att['type_exception']=repr(e)
            att['object_mem_u64']=ptrs_at(ptr,0x200)
            for key in ['rawDataInfo_BaseImage','rawDataInfo_MicroRImageV1','rawDataInfo_MicroRImageV2','tempDev_BaseImage','tempDev_MicroRImageV1_value','tempDev_MicroRImageV2_value','tempMeas_BaseImage','tempMeas_MicroRImageV1','tempMeas_MicroRImageV2','measureResults_BaseImage']:
              att[key]=call_sret(key, addrs[key], ptr)
            for label,fn in [('tempDev_MicroRImageV1_ref',ref_v1),('tempDev_MicroRImageV2_ref',ref_v2)]:
              try:
                rp=fn(ctypes.c_void_p(ptr))
                att[label+'_ptr']=hex(rp) if rp else None
                if rp: att[label+'_dump']=dump_mem(int(rp),0x400)
              except Exception as e: att[label+'_exception']=repr(e)
        except Exception as e:
          att['exception']=repr(e)
        if att.get('ptr') or att.get('exception'):
          report['attempts'].append(att)
          print(json.dumps({'factory':fname,'ft':ft,'ptr':att.get('ptr'),'type':att.get('type'),'raw_ok':att.get('rawDataInfo_BaseImage',{}).get('ok'),'dev_ref':att.get('tempDev_MicroRImageV1_ref_ptr'),'ex':att.get('exception')},ensure_ascii=False))
    args.out.mkdir(parents=True,exist_ok=True)
    out=args.out/(args.jpeg.stem+'_member_probe.json')
    out.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    print('saved:',out)
if __name__=='__main__': main()
