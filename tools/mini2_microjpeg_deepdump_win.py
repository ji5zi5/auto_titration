#!/usr/bin/env python3
from __future__ import annotations
import argparse, ctypes, json, os, struct
from pathlib import Path
DLL_DIR_DEFAULT=Path(r"C:\Program Files\HIKMICRO Analyzer\HIKMICRO Analyzer")
class BareBlock(ctypes.Structure): _fields_=[('data',ctypes.c_void_p),('size',ctypes.c_uint32),('pad',ctypes.c_uint32)]
def add_dll_dir(p):
    if hasattr(os,'add_dll_directory'): os.add_dll_directory(str(p))
    ctypes.windll.kernel32.SetDllDirectoryW(str(p))
def get_proc(dll,name):
    k32=ctypes.windll.kernel32; k32.GetProcAddress.argtypes=[ctypes.c_void_p,ctypes.c_char_p]; k32.GetProcAddress.restype=ctypes.c_void_p
    a=k32.GetProcAddress(dll._handle,name)
    if not a: raise RuntimeError(name)
    return int(a)
def make_block(data):
    buf=ctypes.create_string_buffer(data); return buf,BareBlock(ctypes.cast(buf,ctypes.c_void_p),len(data),0)
def rd(addr,n):
    try: return ctypes.string_at(addr,n)
    except Exception: return None
def ptrs(raw,base):
    out=[]
    for off in range(0,len(raw)-7,8):
        v=struct.unpack_from('<Q',raw,off)[0]
        if 0x10000 < v < 0x0000800000000000:
            out.append((off,v))
    return out
def summarize(raw):
    if raw is None: return None
    return {'len':len(raw),'hex64':raw[:64].hex(' '),'ascii': ''.join(chr(b) if 32<=b<127 else '.' for b in raw[:128]), 'u32':[struct.unpack_from('<I',raw,i)[0] for i in range(0,min(len(raw),128),4)]}
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--dll-dir',type=Path,default=DLL_DIR_DEFAULT); ap.add_argument('--jpeg',type=Path,default=Path('data/fixtures/mini2/IR_00001.jpeg')); ap.add_argument('--out',type=Path,default=Path('data/mini2_microjpeg_deepdump'))
    args=ap.parse_args(); add_dll_dir(args.dll_dir); dll=ctypes.WinDLL(str(args.dll_dir/'MicroJPEG_Release_x64.dll'))
    create=ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.POINTER(BareBlock), ctypes.c_int32)(get_proc(dll,b'?createImage@ImageFactory@MicroSDK@@SAPEAVBaseImage@2@AEBUBareBlock@2@W4FileType@2@@Z'))
    typefn=ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p)(get_proc(dll,b'?type@BaseImage@MicroSDK@@QEBA?AW4FileType@2@XZ'))
    ref_dev=ctypes.CFUNCTYPE(ctypes.c_void_p, ctypes.c_void_p)(get_proc(dll,b'?tempDeviceConfigParams@MicroRImageV1@MicroSDK@@QEAAAEBUTempDeviceConfigParams@2@XZ'))
    data=args.jpeg.read_bytes(); buf,bb=make_block(data); ptr=create(ctypes.byref(bb),1)
    args.out.mkdir(parents=True,exist_ok=True)
    report={'jpeg':str(args.jpeg),'ptr':hex(ptr) if ptr else None,'type':None,'dumps':[]}
    if not ptr: raise SystemExit('no ptr')
    report['type']=int(typefn(ctypes.c_void_p(ptr)))
    dev=ref_dev(ctypes.c_void_p(ptr)); report['dev_ptr']=hex(dev) if dev else None; report['dev_off']=hex(dev-ptr) if dev else None
    roots=[('obj',ptr,0x3000),('dev',dev,0x2000)]
    seen=set()
    # dump root and pointers within root/dev blocks one level, then pointers within internal object at obj+0x18 etc.
    for label,addr,n in list(roots):
        raw=rd(addr,n)
        if raw is None: continue
        (args.out/f'{args.jpeg.stem}_{label}_{addr:x}_{n}.bin').write_bytes(raw)
        report['dumps'].append({'label':label,'addr':hex(addr),'n':n,'summary':summarize(raw),'ptrs':[(hex(o),hex(v)) for o,v in ptrs(raw,addr)[:200]]})
        for off,v in ptrs(raw,addr)[:120]:
            if v in seen: continue
            seen.add(v)
            # Try small and larger reads. Some pointers are module code/vtables; still okay if readable.
            for sz in (0x400,0x4000,0x20000):
                r=rd(v,sz)
                if r is not None:
                    fn=f'{args.jpeg.stem}_{label}_ptr{off:04x}_{v:x}_{sz}.bin'
                    (args.out/fn).write_bytes(r)
                    s=summarize(r)
                    # Mark if looks relevant
                    hits=[]
                    for needle in [b'SDMP',b'Radiometric',b'P20',b'IOS',b'\x00\x01\x00\x00', data[:8]]:
                        if needle and needle in r: hits.append(needle.hex() if len(needle)<5 else needle.decode(errors='ignore'))
                    # raw first 16 u16 from decompressed raw maybe 5338,5353...
                    if b'\xda\x14\xe9\x14\xec\x14' in r: hits.append('raw_first_u16')
                    if hits or sz==0x400:
                        report['dumps'].append({'label':f'{label}+{off:#x}->', 'addr':hex(v),'n':sz,'file':fn,'hits':hits,'summary':s,'ptrs':[(hex(o),hex(x)) for o,x in ptrs(r,v)[:50]]})
                    break
    out=args.out/(args.jpeg.stem+'_deepdump.json'); out.write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding='utf-8')
    print(json.dumps({k:report[k] for k in ['jpeg','ptr','type','dev_ptr','dev_off']},ensure_ascii=False))
    print('saved',out,'dumps',len(report['dumps']))
if __name__=='__main__': main()
