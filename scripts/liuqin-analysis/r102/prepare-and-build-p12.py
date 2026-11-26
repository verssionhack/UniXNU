#!/usr/bin/env python3
"""Prepare, build, verify (layout + AES gate), and package r102-p12 volatile boot.img.

All large artifacts go under /media/disk_4/unixnu_workspace/r102-p12/ to protect /home free space.
Never touches any frozen r101/A7/r2/r3 files or owner.key.
"""
from __future__ import annotations

import difflib
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path('/home/kurumin/github/UniXNU')
A7_WORK = ROOT / 'out/liuqin-r101-a7-work'
R100_OLD = ROOT / 'out/liuqin-r100-work/evidence'
WORK = Path('/media/disk_4/unixnu_workspace/r102-p12')
SCRIPT_DIR = Path(__file__).resolve().parent


def sha(p: Path) -> str:
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def run(args) -> bytes:
    return subprocess.run([str(x) for x in args], check=True, capture_output=True).stdout


def load_mod(name: str, p: Path):
    spec = importlib.util.spec_from_file_location(name, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> None:
    WORK.mkdir(parents=True, exist_ok=True)
    dev = WORK / 'device-p12'
    if dev.exists():
        shutil.rmtree(dev)
    shutil.copytree(A7_WORK / 'device-a', dev, symlinks=True)

    # 1. Stage LiuqinGpuDiscovery driver & build script in isolated device-p12
    drv_dir = dev / 'drivers/LiuqinGpuDiscovery'
    drv_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(SCRIPT_DIR / 'LiuqinGpuDiscovery.cpp', drv_dir / 'LiuqinGpuDiscovery.cpp')
    shutil.copy2(SCRIPT_DIR / 'build-gpu-discovery.py', dev / 'scripts/build-gpu-discovery.py')

    # Wire into device-p12/board.toml and device-p12/configs/liuqin_defconfig
    bt = dev / 'board.toml'
    bts = bt.read_text()
    needle_bt = '  "build-identity-ethernet.py",'
    assert bts.count(needle_bt) == 1
    bt.write_text(bts.replace(needle_bt, needle_bt + '\n  "build-gpu-discovery.py",'))

    dc = dev / 'configs/liuqin_defconfig'
    dcs = dc.read_text()
    needle_dc = '-Wl,-force_load,{tree}/build/liuqin-identity-ethernet/libLiuqinIdentityEthernet.a"'
    assert dcs.count(needle_dc) == 1
    dc.write_text(
        dcs.replace(
            needle_dc,
            needle_dc[:-1] + ' -Wl,-force_load,{tree}/build/liuqin-gpu-discovery/libLiuqinGpuDiscovery.a"',
        )
    )

    # Extend isolated device-p12's xnu patch with the 2-line post-ethernet worker spawn hook
    staged_bsd = (A7_WORK / 'staged-sources/bsd/kern/bsd_init.c').read_text()
    orig_bsd = (A7_WORK / 'frozen-r100b-source/bsd/kern/bsd_init.c').read_text()
    hook_needle = '\tliuqin_identity_ethernet_start();\n'
    assert staged_bsd.count(hook_needle) == 1
    new_bsd = staged_bsd.replace(
        hook_needle,
        hook_needle
        + '\t/* r102-p12: read-only SM8475 GPU platform discovery worker. */\n'
        + '\textern void liuqin_gpu_discovery_start(void);\n'
        + '\tliuqin_gpu_discovery_start();\n',
    )

    prep = json.loads((A7_WORK / 'preparation.json').read_text())
    patch_chunks = []
    for rel in prep['changed_kernel_files']:
        orig_p = A7_WORK / 'frozen-r100b-source' / rel
        original = orig_p.read_text() if orig_p.exists() else ''
        text = new_bsd if rel == 'bsd/kern/bsd_init.c' else (A7_WORK / 'staged-sources' / rel).read_text()
        patch_chunks.append(
            ''.join(
                difflib.unified_diff(
                    original.splitlines(True),
                    text.splitlines(True),
                    fromfile='a/' + rel if original else '/dev/null',
                    tofile='b/' + rel,
                )
            )
        )
    full_patch = ''.join(patch_chunks)
    patch_file = next((dev / 'patches/xnu').glob('*liuqin-r101.patch'))
    patch_file.write_text(full_patch)

    # 2. Build kernel using UniXNU CLI (reuses warm tree, outputs to out/liuqin/...)
    sys.path.insert(0, str(ROOT / 'scripts'))
    from unixnu import cli, feeds
    feeds.update_submodules = lambda ctx: None
    cli.main(['defconfig', 'liuqin_defconfig', '-D', str(dev)])
    cli.main([
        'build', 'kernel', '-D', str(dev), '--jobs', '4',
        '--kernelcache', '/media/disk_4/unixnu_workspace/ramdisk_dir/unixnu/ipsw/26C5035r/kernelcache.decompressed',
    ])

    ev = WORK / 'evidence'
    ev.mkdir(parents=True, exist_ok=True)
    xnu_out = ROOT / 'out/liuqin/macos-27.3-26C5035r/liuqin'
    for name in ('kernel.macho', 'kernel.json', 'kernel.map.json'):
        shutil.copy2(xnu_out / 'kernel' / name, ev / name)
    shutil.copy2(
        xnu_out / 'tree/build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837.unstripped.noctf',
        ev / 'standalone.macho',
    )

    # 3. Verify layout caps + AES fileset gate (exact r100/r101 gates)
    layout = load_mod('layout', ROOT / 'scripts/liuqin-analysis/r100/package.py')
    segments, sections = layout.parse_macho_segments(ev / 'standalone.macho')
    print(
        f"Layout: __TEXT={segments['__TEXT']['vmsize']:#x} (cap {layout.TEXT_CAP:#x}), "
        f"__DATA={segments['__DATA']['vmsize']:#x} (cap {layout.DATA_CAP:#x}), "
        f"__TEXT,__const={sections['__TEXT,__const']:#x} (floor {layout.MIN_TEXT_CONST_VMA:#x})"
    )
    assert segments['__TEXT']['vmsize'] <= layout.TEXT_CAP, 'TEXT cap exceeded'
    assert segments['__DATA']['vmsize'] <= layout.DATA_CAP, 'DATA cap exceeded'
    assert sections['__TEXT,__const'] >= layout.MIN_TEXT_CONST_VMA, 'TEXT const VMA floor violated'

    nm = ev / 'nm.txt'
    with nm.open('wb') as f:
        subprocess.run(['llvm-nm', '-n', str(ev / 'kernel.macho')], check=True, stdout=f)
    gate = ev / 'aes-fileset-gate.json'
    run([
        'python3', ROOT / 'scripts/liuqin-analysis/aes_fileset_gate.py',
        '--kernel', ev / 'kernel.macho',
        '--standalone', ev / 'standalone.macho',
        '--nm', nm,
        '--bindings', R100_OLD / 'original-bindings.S',
        '--report', gate,
    ])
    gate_j = json.loads(gate.read_text())
    assert gate_j['status'] == 'PASS', f'AES gate failed: {gate_j}'

    # 4. Package volatile boot.img on /media/disk_4 (unchanged A7 kernel_args, ADT, trustcache)
    fat = ev / 'payload.img'
    ref_fat = ROOT / 'out/liuqin/macos-27.3-26C5035r/liuqin/payload/payload.img'
    shutil.copyfile(ref_fat, fat)
    a7_val = json.loads((A7_WORK / 'evidence/a/validation-summary.json').read_text())
    args = a7_val['kernel_args']
    raw_adt = (A7_WORK / 'evidence/a/kernel.macho.adt').read_bytes()
    config = run(['mtype', '-i', fat, '::/EFI/UniXNU/unixnu.toml']).decode()
    current = tomllib.loads(config)['entry'][0]['args']
    config = config.replace(current, args)
    (ev / 'unixnu.toml').write_text(config)
    (ev / 'kernel.macho.adt').write_bytes(raw_adt)
    for src, dest in (
        (ev / 'kernel.macho', '::/EFI/UniXNU/Payloads/kernel.macho'),
        (ev / 'kernel.macho.adt', '::/EFI/UniXNU/Payloads/kernel.macho.adt'),
        (ev / 'unixnu.toml', '::/EFI/UniXNU/unixnu.toml'),
    ):
        run(['mcopy', '-o', '-i', fat, src, dest])
        assert hashlib.sha256(run(['mtype', '-i', fat, dest])).hexdigest() == sha(src)
    trust_sha = hashlib.sha256(run(['mtype', '-i', fat, '::/EFI/UniXNU/Payloads/kernel.macho.trustcache'])).hexdigest()
    assert trust_sha == a7_val['trust_cache_sha256']

    run(['python3', dev / 'scripts/wrap-payload-mbr.py', fat, ev / 'payload-mbr.img'])
    pkg_out = WORK / 'package-out'
    pkg_out.mkdir(exist_ok=True)
    cli.main([
        'bootimg', '-D', str(dev), '--out', str(pkg_out),
        '--uefi', '/home/kurumin/Codes/Github/uefi-sheng',
        '--fd', str(R100_OLD / 'SILICIUM_UEFI.fd'),
        '--dtb', str(dev / 'dts/liuqin-cape.dtb'),
        '--ramdisk', str(ev / 'payload-mbr.img'),
        '--output', str(ev / 'boot.img'),
    ])

    summary = {
        'status': 'PASS',
        'profile': 'r102-p12-readonly-gpu-discovery',
        'boot_img': str(ev / 'boot.img'),
        'boot_sha256': sha(ev / 'boot.img'),
        'kernel_sha256': sha(ev / 'kernel.macho'),
        'segments': {k: hex(segments[k]['vmsize']) for k in ('__TEXT', '__DATA', '__TEXT_EXEC')},
        'text_const_vma': hex(sections['__TEXT,__const']),
        'aes_gate': gate_j['status'],
        'trust_cache_sha256': trust_sha,
    }
    (ev / 'validation-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
