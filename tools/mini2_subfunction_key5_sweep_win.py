#!/usr/bin/env python3
from __future__ import annotations
import argparse, json, subprocess, sys, csv, math, os
from pathlib import Path
# Lightweight wrapper: call probe with raw key5 value, parse saved JSON summaries.
# Intended for diagnostic only; CSV is validation only.

def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--jpeg', required=True); ap.add_argument('--start',type=float,default=20); ap.add_argument('--stop',type=float,default=36); ap.add_argument('--step',type=float,default=0.25); ap.add_argument('--out',type=Path,default=Path('data/mini2_key5_sweep'))
    a=ap.parse_args(); a.out.mkdir(parents=True,exist_ok=True)
    rows=[]; x=a.start
    while x <= a.stop + 1e-9:
        raw=int(round(x*1000))
        cmd=[sys.executable, str(Path(__file__).with_name('mini2_mtlib_subfunction11_probe_win.py')), '--jpeg', a.jpeg, '--variant','raw','--radiometric-profile','none','--set-key-raw',f'5={raw}','--out',str(a.out/'runs')]
        res=subprocess.run(cmd,capture_output=True,text=True,encoding='utf-8',errors='replace')
        # find output path from stdout json prefix by scanning last "out"
        outp=None
        for line in res.stdout.splitlines():
            if '"out"' in line:
                outp=line.split(':',1)[1].strip().strip('" ,')
        # safer glob newest for stem
        stem=Path(a.jpeg).stem
        files=sorted((a.out/'runs').glob(f'{stem}_raw_none_1keys_subfunction11.json'), key=lambda p:p.stat().st_mtime)
        if files: outp=str(files[-1])
        if outp and Path(outp).exists():
            d=json.load(open(outp,encoding='utf-8'))
            v=d['validation_vs_csv']['f32']
            rows.append({'key5_c':x,'raw':raw,**v})
            print(rows[-1])
        else:
            print('failed',x,res.stdout[-1000:],res.stderr[-1000:])
        x=round(x+a.step,10)
    best=min(rows,key=lambda r:r['mae']) if rows else None
    out=a.out/(Path(a.jpeg).stem+'_key5_sweep.json')
    out.write_text(json.dumps({'best':best,'rows':rows},indent=2),encoding='utf-8')
    print('BEST',best,'out',out)
if __name__=='__main__': main()
