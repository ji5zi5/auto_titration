#!/usr/bin/env python3
"""Launch official RunAnalyzerExe and attach to HIKMICRO/Pixler as soon as they appear."""
from __future__ import annotations
import argparse, subprocess, time, signal
from datetime import datetime
from pathlib import Path
import hik_analyzer_sdk_trace as base

DEFAULT_RUNNER = Path(r"C:\Users\Public\AnalyzerTool\RunAnalyzerExe\RunAnalyzerExe.exe")
DEFAULT_IMG = Path("data/fixtures/mini2/IR_00001.jpeg")
TARGETS = ("pixler",)

def safe_name(name, pid):
    return ''.join(ch if ch.isalnum() or ch in '._-' else '_' for ch in name) + f'_{pid}'

def attach(device, proc, out_root, sessions):
    name = proc.name
    pid = proc.pid
    out_dir = out_root / safe_name(name, pid)
    blob_dir = out_dir / 'payloads'
    blob_dir.mkdir(parents=True, exist_ok=True)
    events = out_dir / 'events.jsonl'
    print(f'ATTACH {name} pid={pid} -> {events}', flush=True)
    try:
        sess = device.attach(pid)
        try: sess.enable_child_gating()
        except Exception: pass
        scr = sess.create_script(base.FRIDA_JS)
        scr.on('message', base.on_message_factory(events, blob_dir))
        scr.load()
        sessions[pid] = (sess, scr, name)
    except Exception as e:
        print(f'ATTACH_FAIL {name} pid={pid}: {e}', flush=True)

def main(argv=None):
    ap=argparse.ArgumentParser()
    ap.add_argument('--runner', type=Path, default=DEFAULT_RUNNER)
    ap.add_argument('--image', type=Path, default=DEFAULT_IMG)
    ap.add_argument('--out', type=Path, default=Path('data')/f'trace_launch_poll_{datetime.now().strftime("%Y%m%d-%H%M%S")}')
    ap.add_argument('--duration', type=float, default=60)
    ap.add_argument('--poll-ms', type=float, default=10)
    args=ap.parse_args(argv)
    import frida  # type: ignore
    dev=frida.get_local_device()
    out=args.out.resolve(); out.mkdir(parents=True, exist_ok=True)
    sessions={}
    stop={'flag':False}
    def end(*_): stop['flag']=True
    signal.signal(signal.SIGINT,end); signal.signal(signal.SIGTERM,end)
    print('START', args.runner, args.image, flush=True)
    subprocess.Popen([str(args.runner), str(args.image)], cwd=str(args.runner.parent))
    started=time.time()
    while not stop['flag'] and time.time()-started < args.duration:
        try:
            procs=dev.enumerate_processes()
        except Exception as e:
            print('enumerate error', e, flush=True); time.sleep(.1); continue
        for proc in procs:
            low=proc.name.lower()
            if any(t in low for t in TARGETS) and proc.pid not in sessions:
                attach(dev, proc, out, sessions)
        time.sleep(args.poll_ms/1000.0)
    for pid,(sess,scr,name) in list(sessions.items()):
        try: scr.unload()
        except Exception: pass
        try: sess.detach()
        except Exception: pass
    print('DONE', out, flush=True)
    return 0
if __name__=='__main__': raise SystemExit(main())
