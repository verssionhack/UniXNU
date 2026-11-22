#!/usr/bin/env python3
"""Volatile fastboot boot runner for r102-gpu SM8475 / Adreno 730.1 KMD bring-up.

Never flashes. Captures USB CDC ACM log until LQ102GPU DONE (or STOP/panic/timeout)
and cleanly returns the tablet to fastboot.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import importlib.util
import json
import re
import subprocess
import time
from pathlib import Path

ROOT = Path('/home/kurumin/github/UniXNU')
WORK = Path('/media/disk_4/unixnu_workspace/r102-gpu')
EV = WORK / 'evidence'
OUT = ROOT / 'out/liuqin-r102-gpu'


def sha(p: Path) -> str:
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def load_mod(name: str, p: Path):
    spec = importlib.util.spec_from_file_location(name, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--desktop', action='store_true', help='Do not stop on LQ102GPU DONE; capture WindowServer/Metal/desktop for --duration seconds')
    ap.add_argument('--duration', type=int, default=90, help='Max capture duration in seconds')
    ap.add_argument('--stay-up', action='store_true', help='Leave macOS running on screen instead of rebooting to fastboot at end')
    cli_args = ap.parse_args()

    val = json.loads((EV / 'validation-summary.json').read_text())
    boot_img = Path(val['boot_img'])
    assert val['status'] == 'PASS' and sha(boot_img) == val['boot_sha256'], 'Validation hash mismatch'

    common = load_mod('device', ROOT / 'out/liuqin-r100-work/evidence/device_runner.py')
    if not common.fastboot_present():
        raise SystemExit('Expected be7ca114 in fastboot; refusing to boot')

    ts = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    run_dir = EV / f'boot-gpu-{ts}'
    run_dir.mkdir(parents=True)
    OUT.mkdir(parents=True, exist_ok=True)
    print(f'Booting volatile {boot_img} (sha256={val["boot_sha256"][:16]}...) -> {run_dir}', flush=True)

    proc = subprocess.Popen(
        ['fastboot', '-s', common.SERIAL, 'boot', str(boot_img)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    start = time.monotonic()
    serial = None
    replayed = False
    tail = b''
    finished = False
    finished_at = None
    last_print = start
    max_seconds = cli_args.duration

    with (run_dir / 'usb.log').open('wb', buffering=0) as log:
        try:
            while True:
                now = time.monotonic() - start
                if proc.poll() is not None and proc.returncode != 0:
                    raise RuntimeError(f'fastboot boot failed ({proc.returncode})')
                if serial is None:
                    try:
                        serial = common.open_debug()
                    except Exception:
                        serial = None
                    if serial:
                        serial.dtr = True
                        serial.rts = True
                        if not replayed:
                            serial.write(b'replay\n')
                            serial.flush()
                            replayed = True
                            print(f'[{now:.1f}s] USB LIQDBG001 opened & replay requested', flush=True)
                data = b''
                if serial:
                    try:
                        data = serial.read(8192)
                    except Exception:
                        serial.close()
                        serial = None
                else:
                    time.sleep(0.1)

                if data:
                    log.write(data)
                    tail = (tail + data)[-65536:]
                    if not cli_args.desktop:
                        for marker in (b'LQ102GPU DONE', b'LQ102GPU STOP'):
                            if marker in tail and not finished:
                                finished = True
                                finished_at = now
                                print(f'[{now:.1f}s] Observed {marker.decode()}! Draining 3 s...', flush=True)
                    if re.search(rb'panic\(cpu|PANICc[0-9]+', tail) and not finished:
                        finished = True
                        finished_at = now
                        print(f'[{now:.1f}s] PANIC observed, draining 4 s...', flush=True)
                if finished and finished_at is not None and (now - finished_at >= 3.0):
                    break
                if now >= max_seconds:
                    print(f'[{now:.1f}s] Reached {max_seconds}s ceiling', flush=True)
                    break
                if time.monotonic() - last_print >= 15:
                    print(f'[{now:.1f}s] captured {(run_dir / "usb.log").stat().st_size} bytes', flush=True)
                    last_print = time.monotonic()
        finally:
            if serial:
                serial.close()
            if proc.poll() is None:
                proc.kill()
            out_b, err_b = proc.communicate()
            (run_dir / 'fastboot.log').write_bytes(out_b + err_b)
            if not cli_args.stay_up:
                try:
                    common.bootloader(run_dir)
                    fb_ok = common.fastboot_present()
                except Exception as exc:
                    fb_ok = False
                    print(f'WARN: return to fastboot error: {exc}', flush=True)
                print(f'Returned to fastboot: {fb_ok}', flush=True)
            else:
                print('Left device running (--stay-up)', flush=True)

    txt = (run_dir / 'usb.log').read_text(errors='replace')
    gpu_lines = [ln.strip() for ln in txt.splitlines()
                 if any(k in ln for k in ('LQ102GPU ', 'NativeAdreno', 'AGX', 'WindowServer', 'NativeLegacy', 'GPUBundle', 'panic('))]
    (OUT / f'gpu-lines-{ts}.txt').write_text('\n'.join(gpu_lines) + '\n')
    print('=== LQ102GPU CAPTURE ===')
    for ln in gpu_lines:
        print(' ', ln)


if __name__ == '__main__':
    main()
