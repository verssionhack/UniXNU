#!/usr/bin/env python3
"""Volatile fastboot boot runner for r102-p12 read-only SM8475 GPU platform discovery.

Never flashes. Captures USB CDC ACM log until LQ102 GPUDISC_END (or timeout),
reconstructs and SHA-256 verifies the 128 KiB cmd-db snapshot, runs sm8475_cmddb_tool.py
on the real hardware bytes, and cleanly returns the tablet to fastboot.
"""
from __future__ import annotations

import datetime
import hashlib
import importlib.util
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path('/home/kurumin/github/UniXNU')
WORK = Path('/media/disk_4/unixnu_workspace/r102-p12')
EV = WORK / 'evidence'
OUT_R102 = ROOT / 'out/liuqin-r102-p12'


def sha(p: Path) -> str:
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def load_mod(name: str, p: Path):
    spec = importlib.util.spec_from_file_location(name, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def parse_and_verify_capture(usb_log: Path, out_dir: Path) -> dict:
    txt = usb_log.read_text(errors='replace')
    lines = [ln.strip() for ln in txt.splitlines() if 'LQ102 ' in ln]
    (out_dir / 'lq102-lines.txt').write_text('\n'.join(lines) + '\n')

    # Reconstruct 128 KiB cmd-db from LQ102 CMDDB_BLK lines
    hdr_m = re.search(r'LQ102 CMDDB_HDR base=(\S+) size=(\S+) ver=(\S+) magic=(\S+) sha256=([0-9a-f]{64})', txt)
    end_m = re.search(r'LQ102 CMDDB_END nonzero_blocks=(\d+) sha256=([0-9a-f]{64})', txt)
    scm_m = re.search(r'LQ102 SCM_AVAIL (.+)', txt)
    cpu_m = re.search(r'LQ102 GPUDISC_BEGIN (.+)', txt)
    fdt_m = re.search(r'LQ102 FDT_HDR (.+)', txt)
    done_m = re.search(r'LQ102 GPUDISC_END (.+)', txt)

    cmddb_parsed_report = None
    cmddb_verified = False
    reconstructed_sha = None
    blk_count = 0

    if hdr_m and end_m:
        expected_sha = hdr_m.group(5)
        assert expected_sha == end_m.group(2), 'HDR/END SHA256 mismatch'
        buf = bytearray(0x20000)
        seen_offs = set()
        for m in re.finditer(r'LQ102 CMDDB_BLK off=0x([0-9a-fA-F]+) hex=([0-9a-fA-F]{64})', txt):
            off = int(m.group(1), 16)
            chunk = bytes.fromhex(m.group(2))
            if off % 32 == 0 and off + 32 <= 0x20000:
                buf[off:off + 32] = chunk
                seen_offs.add(off)
        blk_count = len(seen_offs)
        reconstructed_sha = hashlib.sha256(buf).hexdigest()
        cmddb_bin = out_dir / 'sm8475-liuqin-cmddb-128k.bin'
        cmddb_bin.write_bytes(buf)
        cmddb_verified = (reconstructed_sha == expected_sha)
        if cmddb_verified:
            sys.path.insert(0, str(ROOT / 'scripts/liuqin-analysis/r101/gpu-host-gates-r3'))
            import sm8475_cmddb_tool as tool
            parsed = tool.parse_cmd_db(bytes(buf), require_exact_128k=True)
            # Compute votes for BOTH active sm8450 (12+1) and sm8475 (13+1) OPP tables!
            opps_8450 = [
                (0, 0),
                (220000000, 56), (285000000, 56), (317000000, 64), (350000000, 64),
                (421000000, 80), (492000000, 128), (545000000, 144), (599000000, 192),
                (640000000, 224), (734000000, 256), (791000000, 320), (818000000, 384),
            ]
            opps_8475 = [
                (0, 0),
                (220000000, 48), (285000000, 56), (324000000, 64), (364000000, 80),
                (439000000, 96), (515000000, 128), (580000000, 144), (645000000, 192),
                (710000000, 224), (765000000, 256), (815000000, 320), (862000000, 384),
                (900000000, 416),
            ]
            gmu_opps = [(0, 0), (200000000, 64), (500000000, 128)]
            cmddb_parsed_report = {
                'all_resource_ids': sorted(parsed['entries_by_id'].keys()),
                'sm8450_opp_profile': tool.extract_sm8475_gpu_inputs(parsed, opps_8450, gmu_opps),
            }
            try:
                cmddb_parsed_report['sm8475_opp_profile'] = tool.extract_sm8475_gpu_inputs(parsed, opps_8475, gmu_opps)
            except Exception as exc:
                cmddb_parsed_report['sm8475_opp_profile_error'] = str(exc)

    result = {
        'lq102_line_count': len(lines),
        'cpu_begin': cpu_m.group(1) if cpu_m else None,
        'fdt_header': fdt_m.group(1) if fdt_m else None,
        'cmddb_header': hdr_m.group(0) if hdr_m else None,
        'cmddb_blocks_reconstructed': blk_count,
        'cmddb_reconstructed_sha256': reconstructed_sha,
        'cmddb_sha256_verified_bit_exact': cmddb_verified,
        'scm_is_call_avail': scm_m.group(1) if scm_m else None,
        'gpudisc_end': done_m.group(1) if done_m else None,
        'cmddb_hardware_parsed': cmddb_parsed_report,
    }
    (out_dir / 'hardware-discovery-result.json').write_text(json.dumps(result, indent=2) + '\n')
    return result


def main() -> None:
    val = json.loads((EV / 'validation-summary.json').read_text())
    boot_img = Path(val['boot_img'])
    assert val['status'] == 'PASS' and sha(boot_img) == val['boot_sha256'], 'Validation hash mismatch'

    common = load_mod('device', ROOT / 'out/liuqin-r100-work/evidence/device_runner.py')
    if not common.fastboot_present():
        raise SystemExit('Expected be7ca114 in fastboot; refusing to boot')

    ts = datetime.datetime.now().strftime('%Y%m%d-%H%M%S')
    run_dir = EV / f'boot-p12-{ts}'
    run_dir.mkdir(parents=True)
    OUT_R102.mkdir(parents=True, exist_ok=True)
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
    fatal = None
    last_print = start
    max_seconds = 180

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
                    if b'LQ102 GPUDISC_END' in tail and not finished:
                        finished = True
                        finished_at = now
                        print(f'[{now:.1f}s] Observed LQ102 GPUDISC_END! Draining 3 s...', flush=True)
                    if re.search(rb'panic\(cpu|PANICc[0-9]+', tail) and not fatal:
                        fatal = 'panic observed'
                        print(f'[{now:.1f}s] PANIC observed, draining 5 s...', flush=True)
                        finished = True
                        finished_at = now
                if finished and finished_at is not None and (now - finished_at >= 3.0):
                    break
                if now >= max_seconds:
                    print(f'[{now:.1f}s] Reached {max_seconds}s capture ceiling', flush=True)
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
            # Cleanly return tablet to fastboot
            try:
                common.bootloader(run_dir)
                fb_ok = common.fastboot_present()
            except Exception as exc:
                fb_ok = False
                print(f'WARN: return to fastboot error: {exc}', flush=True)
            print(f'Returned to fastboot: {fb_ok}', flush=True)

    res = parse_and_verify_capture(run_dir / 'usb.log', OUT_R102)
    print('=== HARDWARE DISCOVERY SUMMARY ===')
    print(json.dumps({k: v for k, v in res.items() if k != 'cmddb_hardware_parsed'}, indent=2))
    if res['cmddb_hardware_parsed']:
        p = res['cmddb_hardware_parsed']['sm8450_opp_profile']
        print('REAL HARDWARE cmd-db parsed OK!')
        print('  gmxc_status:', p['gmxc_status'], 'selected_secondary:', p['selected_secondary_rail'])
        print('  BCM addrs:', {k: v['addr_hex'] for k, v in p['bcm_resources'].items()})
        print('  ARC rails:', {k: v['levels'] for k, v in p['arc_rails'].items()})
        print('  GX votes (sm8450 OPPs):', [r['vote_hex'] for r in p['gx_arc_votes']])
        print('  CX votes:', [r['vote_hex'] for r in p['cx_arc_votes']])


if __name__ == '__main__':
    main()
