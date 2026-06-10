#!/usr/bin/env python3
"""Directly probe MicroJPEG MicroRImageV2/V1 creation paths.

No CSV/answer fitting: this only asks the vendor DLL whether our JPEG or its
embedded SDMP blocks are recognized as radiometric image objects and whether
raw/temp parameter getters return populated SDK structs.
"""
from __future__ import annotations

import argparse, ctypes, json, os, struct
from dataclasses import dataclass
from pathlib import Path

DLL_DIR_DEFAULT = Path(r"C:\Program Files\HIKMICRO Analyzer\HIKMICRO Analyzer")

class BareBlock(ctypes.Structure):
    _fields_ = [("data", ctypes.c_void_p), ("size", ctypes.c_uint32), ("pad", ctypes.c_uint32)]

@dataclass(frozen=True)
class Segment:
    marker_start:int; marker:int; payload_start:int; payload:bytes

def iter_jpeg_segments(data: bytes):
    if not data.startswith(b"\xff\xd8"):
        return
    pos=2
    while pos < len(data)-1:
        if data[pos] != 0xff:
            pos += 1; continue
        marker_start=pos
        while pos < len(data) and data[pos] == 0xff:
            pos += 1
        if pos >= len(data): break
        marker=data[pos]; pos += 1
        if marker in {0xd8,0xd9}: continue
        if marker == 0xda: break
        if pos+2 > len(data): break
        length=int.from_bytes(data[pos:pos+2], 'big')
        payload_start=pos+2
        payload_end=pos+length
        yield Segment(marker_start, marker, payload_start, data[payload_start:payload_end])
        pos=payload_end

def parse_sdmp_entries(payload: bytes):
    if not payload.startswith(b"SDMP") or len(payload) < 0x12: return []
    count=int.from_bytes(payload[0x10:0x12], 'little')
    if not (0 < count < 256): return []
    out=[]; type_sizes={1:1,2:1,3:2,4:4,5:8,7:1,9:4,10:8}
    for i in range(count):
        off=0x12+12*i
        if off+12 > len(payload): break
        tag,typ,item_count,value=struct.unpack_from('<HHII', payload, off)
        size=type_sizes.get(typ,0)*item_count
        data_off=0x10+value if size > 4 else None
        out.append((tag,typ,item_count,value,size,data_off))
    return out

def input_variants(jpeg: Path):
    data=jpeg.read_bytes()
    variants={"full_jpeg": data, "without_soi": data[2:]}
    app3_payloads=[]; app3_with_marker=[]; sdmp_datas=[]
    for idx,seg in enumerate(iter_jpeg_segments(data) or []):
        label=f"seg{idx:02d}_APP{seg.marker-0xe0:x}" if 0xe0 <= seg.marker <= 0xef else f"seg{idx:02d}_{seg.marker:02x}"
        variants[label+"_payload"] = seg.payload
        variants[label+"_with_marker_len"] = data[seg.marker_start:seg.payload_start+len(seg.payload)]
        if seg.marker == 0xe3 and seg.payload.startswith(b"SDMP"):
            app3_payloads.append(seg.payload)
            app3_with_marker.append(data[seg.marker_start:seg.payload_start+len(seg.payload)])
            for tag,typ,cnt,val,size,doff in parse_sdmp_entries(seg.payload):
                if doff is not None and size and doff+size <= len(seg.payload):
                    variants[f"{label}_tag{tag}_data"] = seg.payload[doff:doff+size]
                    sdmp_datas.append(seg.payload[doff:doff+size])
    if app3_payloads:
        variants["concat_app3_payloads"] = b"".join(app3_payloads)
        variants["concat_app3_with_marker_len"] = b"".join(app3_with_marker)
    if sdmp_datas:
        variants["concat_sdmp_tag_datas"] = b"".join(sdmp_datas)
    return variants

def add_dll_dir(dll_dir: Path):
    if hasattr(os, 'add_dll_directory'):
        os.add_dll_directory(str(dll_dir))
    ctypes.windll.kernel32.SetDllDirectoryW(str(dll_dir))

def get_proc(dll, name: bytes) -> int:
    k32=ctypes.windll.kernel32
    k32.GetProcAddress.argtypes=[ctypes.c_void_p, ctypes.c_char_p]
    k32.GetProcAddress.restype=ctypes.c_void_p
    addr=k32.GetProcAddress(dll._handle, name)
    if not addr: raise RuntimeError(f"missing {name!r}")
    return int(addr)

def make_block(data: bytes):
    buf=ctypes.create_string_buffer(data)
    blk=BareBlock(ctypes.cast(buf, ctypes.c_void_p), len(data), 0)
    return buf, blk

def u32s(raw: bytes, n=256):
    return [int.from_bytes(raw[i:i+4], 'little') for i in range(0, min(n, len(raw)), 4)]

def nonzero(raw: bytes, n=512, limit=80):
    out=[]
    for i,v in enumerate(u32s(raw,n)):
        if v:
            out.append({"idx":i,"value":v,"hex":hex(v)})
            if len(out)>=limit: break
    return out

def call_ret_struct(dll, name: bytes, ptr: int, outsize=0x2000):
    out=ctypes.create_string_buffer(outsize)
    fn=ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)(get_proc(dll,name))
    rv=fn(ctypes.byref(out), ctypes.c_void_p(ptr))  # return-by-value hidden sret first, this second
    return {"rv":hex(rv) if rv else None,"u32_prefix":u32s(out.raw,256),"nonzero_u32":nonzero(out.raw,1024),"hex_prefix":bytes(out.raw[:256]).hex(' ')}

def main(argv=None):
    ap=argparse.ArgumentParser()
    ap.add_argument('--dll-dir',type=Path,default=DLL_DIR_DEFAULT)
    ap.add_argument('--jpeg',type=Path,required=True)
    ap.add_argument('--out',type=Path,default=Path('data/mini2_microjpeg_direct_v2_probe'))
    args=ap.parse_args(argv)
    add_dll_dir(args.dll_dir)
    dll=ctypes.WinDLL(str(args.dll_dir/'MicroJPEG_Release_x64.dll'))
    names={
        'v1_is': b'?is@MicroRImageV1@MicroSDK@@SA_NAEBUBareBlock@2@@Z',
        'v2_is': b'?is@MicroRImageV2@MicroSDK@@SA_NAEBUBareBlock@2@@Z',
        'std_create_ret': b'?createStandardRImage@ImageFactory@MicroSDK@@SAPEAVStandardRImage@2@AEBUBareBlock@2@@Z',
        'v1_create_ret': b'?createMicroRImageV1@ImageFactory@MicroSDK@@SAPEAVMicroRImageV1@2@AEBUBareBlock@2@@Z',
        'v2_create_ret': b'?createMicroRImageV2@ImageFactory@MicroSDK@@SAPEAVMicroRImageV2@2@AEBUBareBlock@2@@Z',
        'v1_create_bool': b'?createMicroRImageV1@ImageFactory@MicroSDK@@SA_NPEAPEAVMicroRImageV1@2@AEBUBareBlock@2@@Z',
        'v2_create_bool': b'?createMicroRImageV2@ImageFactory@MicroSDK@@SA_NPEAPEAVMicroRImageV2@2@AEBUBareBlock@2@@Z',
    }
    funcs={}
    for k,n in names.items():
        try: funcs[k]=get_proc(dll,n)
        except Exception as e: funcs[k]=None
    ftype=ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p)(get_proc(dll,b'?type@BaseImage@MicroSDK@@QEBA?AW4FileType@2@XZ'))
    raw_methods={
      'v1_rawDataInfo': b'?rawDataInfo@MicroRImageV1@MicroSDK@@UEBA?AURawDataInfo@2@XZ',
      'v2_rawDataInfo': b'?rawDataInfo@MicroRImageV2@MicroSDK@@UEBA?AURawDataInfo@2@XZ',
      'v1_tempDevice': b'?tempDeviceConfigParams@MicroRImageV1@MicroSDK@@UEBA?AUTempDeviceConfigParams@2@XZ',
      'v2_tempDevice': b'?tempDeviceConfigParams@MicroRImageV2@MicroSDK@@UEBA?AUTempDeviceConfigParams@2@XZ',
      'v1_tempMeasure': b'?tempMeasurementParams@MicroRImageV1@MicroSDK@@UEBA?AUTempMeasurementParameters@2@XZ',
      'v2_tempMeasure': b'?tempMeasurementParams@MicroRImageV2@MicroSDK@@UEBA?AUTempMeasurementParameters@2@XZ',
    }
    out=[]
    for label,data in input_variants(args.jpeg).items():
        if len(data)==0: continue
        # Vendor JPEG constructors can call libjpeg fatal-exit on non-JPEG
        # inputs, so only call them on complete JPEGs. Non-full variants were
        # already tested earlier and are unsafe for in-process probing.
        if label != 'full_jpeg':
            continue
        buf,blk=make_block(data)
        rec={"variant":label,"size":len(data),"magic":data[:16].hex(' '),"is":{},"creates":[]}
        for which in ['v1_is','v2_is']:
            if funcs.get(which):
                try:
                    fn=ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.POINTER(BareBlock))(funcs[which])
                    rec['is'][which]=bool(fn(ctypes.byref(blk)))
                except Exception as e: rec['is'][which]=repr(e)
        for which,cls in [('std_create_ret','std'),('v1_create_ret','v1'),('v2_create_ret','v2')]:
            if not funcs.get(which): continue
            cre={"call":which,"ptr":None,"methods":{}}
            try:
                fn=ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.POINTER(BareBlock))(funcs[which])
                ptr=fn(ctypes.byref(blk)) or 0
                cre['ptr']=hex(ptr) if ptr else None
                if ptr:
                    try: cre['type']=int(ftype(ctypes.c_void_p(ptr)))
                    except Exception as e: cre['type_exception']=repr(e)
                    for mlabel,mname in raw_methods.items():
                        if not mlabel.startswith(cls+'_'): continue
                        try: cre['methods'][mlabel]=call_ret_struct(dll,mname,ptr)
                        except Exception as e: cre['methods'][mlabel]={"exception":repr(e)}
            except Exception as e: cre['exception']=repr(e)
            rec['creates'].append(cre)
        for which,cls in [('v1_create_bool','v1'),('v2_create_bool','v2')]:
            if not funcs.get(which): continue
            cre={"call":which,"ok":None,"ptr":None,"methods":{}}
            try:
                fn=ctypes.CFUNCTYPE(ctypes.c_bool, ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(BareBlock))(funcs[which])
                op=ctypes.c_void_p()
                ok=fn(ctypes.byref(op), ctypes.byref(blk)); ptr=op.value or 0
                cre['ok']=bool(ok); cre['ptr']=hex(ptr) if ptr else None
                if ptr:
                    try: cre['type']=int(ftype(ctypes.c_void_p(ptr)))
                    except Exception as e: cre['type_exception']=repr(e)
                    for mlabel,mname in raw_methods.items():
                        if not mlabel.startswith(cls+'_'): continue
                        try: cre['methods'][mlabel]=call_ret_struct(dll,mname,ptr)
                        except Exception as e: cre['methods'][mlabel]={"exception":repr(e)}
            except Exception as e: cre['exception']=repr(e)
            rec['creates'].append(cre)
        # keep only variants that look relevant or succeeded, plus full jpeg
        if label=='full_jpeg' or rec['is'].get('v1_is') or rec['is'].get('v2_is') or any(c.get('ptr') or c.get('ok') for c in rec['creates']):
            out.append(rec)
    report={"jpeg":str(args.jpeg),"variant_count":len(input_variants(args.jpeg)),"records":out}
    args.out.mkdir(parents=True,exist_ok=True)
    op=args.out/(args.jpeg.stem+'_direct_v2_probe.json')
    op.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False,indent=2)[:30000])
    print('saved:',op)
    return 0
if __name__=='__main__': raise SystemExit(main())
