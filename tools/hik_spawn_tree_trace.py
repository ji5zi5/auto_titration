#!/usr/bin/env python3
"""Spawn RunAnalyzerExe under Frida spawn-gating and trace Analyzer/Pixler children.

This catches the file-open path from the official shell helper, so Pixler is
instrumented from process birth instead of after the radiometric JPEG was loaded.
"""
from __future__ import annotations
import argparse, json, signal, sys, time
from datetime import datetime
from pathlib import Path

# Reuse the large hook script and message writer from the existing tracer.
import hik_analyzer_sdk_trace as base

DEFAULT_RUNNER = Path(r"C:\Users\Public\AnalyzerTool\RunAnalyzerExe\RunAnalyzerExe.exe")
DEFAULT_IMG = Path("data/fixtures/mini2/IR_00001.jpeg")
TARGET_WORDS = ("hikamicro", "hikmicro", "pixler", "runcanalyzer", "runanalyzer", "analyzer", "explorer")


def proc_label(identifier: str, pid: int) -> str:
    stem = Path(identifier.replace('\\', '/')).name or identifier or 'process'
    safe = ''.join(ch if ch.isalnum() or ch in '._-' else '_' for ch in stem)
    return f"{safe}_{pid}"


def is_target(identifier: str) -> bool:
    low = (identifier or '').lower()
    return any(w in low for w in TARGET_WORDS)


def attach_trace(device, pid: int, identifier: str, out_root: Path, sessions: list):
    out_dir = out_root / proc_label(identifier, pid)
    blob_dir = out_dir / 'payloads'
    blob_dir.mkdir(parents=True, exist_ok=True)
    events_path = out_dir / 'events.jsonl'
    print(f"TRACE attach pid={pid} id={identifier} -> {events_path}", flush=True)
    try:
        session = device.attach(pid)
    except Exception as e:
        print(f"attach failed pid={pid}: {e}", flush=True)
        return None
    try:
        try:
            session.enable_child_gating()
        except Exception as e:
            print(f"child gating unavailable pid={pid}: {e}", flush=True)
        script = session.create_script(base.FRIDA_JS)
        script.on('message', base.on_message_factory(events_path, blob_dir))
        script.load()
        sessions.append((session, script, pid, identifier))
        return session
    except Exception as e:
        print(f"script load failed pid={pid}: {e}", flush=True)
        try: session.detach()
        except Exception: pass
        return None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--runner', type=Path, default=DEFAULT_RUNNER)
    ap.add_argument('--image', type=Path, default=DEFAULT_IMG)
    ap.add_argument('--out', type=Path, default=Path('data') / f"trace_spawn_tree_{datetime.now().strftime('%Y%m%d-%H%M%S')}")
    ap.add_argument('--duration', type=float, default=45.0)
    args = ap.parse_args(argv)

    import frida  # type: ignore
    device = frida.get_local_device()
    out_root = args.out.resolve()
    out_root.mkdir(parents=True, exist_ok=True)
    sessions = []
    stop = {'flag': False}

    def on_spawn(spawn):
        ident = getattr(spawn, 'identifier', '') or getattr(spawn, 'path', '') or ''
        pid = spawn.pid
        print(f"SPAWN pid={pid} id={ident}", flush=True)
        if is_target(ident):
            attach_trace(device, pid, ident, out_root, sessions)
        try:
            device.resume(pid)
        except Exception as e:
            print(f"resume failed pid={pid}: {e}", flush=True)

    def on_child(child):
        ident = getattr(child, 'identifier', '') or getattr(child, 'path', '') or ''
        pid = child.pid
        print(f"CHILD pid={pid} id={ident}", flush=True)
        if is_target(ident):
            attach_trace(device, pid, ident, out_root, sessions)
        try:
            device.resume(pid)
        except Exception as e:
            print(f"child resume failed pid={pid}: {e}", flush=True)

    # Windows Frida does not support global spawn gating, but child gating
    # on the spawned runner is supported and catches Pixler/Analyzer children.
    try:
        device.on('child-added', on_child)
    except Exception:
        pass

    def end(*_): stop['flag'] = True
    signal.signal(signal.SIGINT, end)
    signal.signal(signal.SIGTERM, end)

    argv_spawn = [str(args.runner), str(args.image)]
    print('Spawning runner:', argv_spawn, flush=True)
    pid = device.spawn(argv_spawn)
    attach_trace(device, pid, str(args.runner), out_root, sessions)
    device.resume(pid)
    started = time.time()
    try:
        while not stop['flag'] and time.time() - started < args.duration:
            time.sleep(0.2)
    finally:
        for session, script, pid, ident in sessions:
            try: script.unload()
            except Exception: pass
            try: session.detach()
            except Exception: pass
    print('Trace tree saved:', out_root, flush=True)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
