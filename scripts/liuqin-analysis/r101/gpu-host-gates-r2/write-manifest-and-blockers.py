#!/usr/bin/env python3
"""Record concrete Linux-host userspace build blockers and generate r2 SHA256 audit manifest.

Also verifies that all previously frozen r101/M1/host-gate/layout/skylight/A7 manifests
remain byte-for-byte unchanged.
"""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[4]
EV = ROOT / 'out/liuqin-r101-gpu-host-gates-r2/evidence'
SCRIPTS = ROOT / 'scripts/liuqin-analysis/r101/gpu-host-gates-r2'


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def record_userspace_blockers():
    sdk_dir = Path('/opt/unixnu-linux/CommandLineTools/SDKs/MacOSX.sdk')
    # Note: when run sandboxed, sdk_dir may not be visible; pass observed inventory or inspect if accessible
    sdk_accessible = sdk_dir.exists()
    sdk_top = sorted(p.name for p in sdk_dir.iterdir()) if sdk_accessible else ['usr (observed outside sandbox; no System/Library/Frameworks or PrivateFrameworks)']
    codesign_shim = (ROOT / 'scripts/linux/codesign').read_text().strip()
    blockers = {
        'scope': 'Verified Linux-host blockers preventing full macOS 27.3 (26C5035r) arm64e Turnip / metal2vulkan / NativeAdrenoMetal.bundle userspace build & import qualification',
        'host_platform': 'Linux x86_64',
        'macOS_27_3_userspace_SDK': {
            'status': 'MISSING',
            'local_sdk_path': str(sdk_dir),
            'local_sdk_contents': sdk_top,
            'missing_frameworks_and_tbds': [
                'Foundation.framework',
                'Metal.framework',
                'IOSurface.framework',
                'IOKit.framework',
                'CoreGraphics.framework',
                'QuartzCore.framework',
                'PrivateFrameworks/IOGPU.framework (IOGPU.tbd)',
                'Darwin arm64e libSystem / libobjc TBDs and ObjC runtime headers',
            ],
            'reference_ci_note': 'UniXNU-sheng builds userspace artifacts on a macOS runner with Xcode SDK.',
        },
        'codesign_and_4k_page_cdhash': {
            'status': 'MISSING_ON_LINUX',
            'linux_shim_path': 'scripts/linux/codesign',
            'linux_shim_behavior': 'No-op (exit 0) for XNU host tools; cannot generate 4 KiB-page ad-hoc Mach-O code signatures or CDHashes',
            'owner_key_required': False,
        },
        'rust_arm64e_darwin_toolchain': {
            'status': 'MISSING',
            'required_by': 'scripts/build-adreno-metal-bridge.py (cargo +1.98.0 -Z build-std=std,panic_unwind --target arm64e-apple-darwin)',
            'installed_toolchains_observed': ['stable-x86_64-unknown-linux-gnu', '1.81.0-x86_64-unknown-linux-gnu', '1.96.0-x86_64-unknown-linux-gnu'],
        },
        'vulkan_shader_compiler_tool': {
            'status': 'MISSING',
            'tool': 'glslangValidator',
            'required_by': 'scripts/build-turnip-darwin.py',
        },
        'external_userspace_source_trees': {
            'mesa_pinned_commit': '85fda3b36405bcaea8bffc64aa4f2651dc90770d',
            'mesa_local_checkout_present': (ROOT / '.cache/mesa-work').exists(),
            'mesa_patches_present_locally': len(list((ROOT / 'patches/mesa').glob('*.patch'))),
            'metal2vulkan_pinned_commit': '963f0e64f103d2e682cd0cc454a8fe50f52c8cbb',
            'metal2vulkan_local_checkout_present': (ROOT / '.cache/gpu-reference/metal2vulkan').exists(),
            'metal2vulkan_patches_present_locally': len(list((ROOT / 'drivers/AdrenoMetal/bridge/patches').glob('*.patch'))),
        },
        'host_disk_constraint': {
            'filesystem': '/home (/dev/nvme0n1p7)',
            'approximate_free_space': '~2.3 GiB',
            'implication': 'Do not clone full Mesa (~1.5+ GiB) or build Rust std/LTO artifacts under /home; any future cross-build or macOS SDK staging must live on /media/disk_4 (122 GiB free) or a macOS build host.',
        },
        'userspace_ABI_gate_disposition': 'OPEN (source/binary contracts audited to maximum extent possible on Linux; full target build, import/PAC/codesign/CDHash and runtime qualification remain blocked on macOS 27 SDK + Rust 1.98 arm64e-apple-darwin + glslangValidator + patched Mesa/metal2vulkan checkouts)',
    }
    (EV / 'userspace-build-blockers.json').write_text(json.dumps(blockers, indent=2) + '\n')


def verify_frozen_manifests():
    frozen = [
        ('out/liuqin-r101-gpu-host-gates/evidence/audit-manifest.json', '2973fe3ceb19c62ff29f813c178c52d01167810660f4a1c0a6812e667aa72204'),
        ('out/liuqin-r101-gpu-m1/evidence/research-manifest.json', 'dd2707afdeff822a06f4f85833b013ce92d6fafa59ffbe61e4e530cfbafbd5ac'),
        ('out/liuqin-r101-layout-audit/evidence/audit-manifest.json', 'be61f7510a83701f04fdc9557b53ca6326365358e1f0ccd878a3e0ad15af9878'),
        ('out/liuqin-r101-skylight-audit/evidence/audit-manifest.json', '102e9d8289e925999ef5bba888e7a9679fc1d4f5a28d20203153e7c0f5c7eaf4'),
        ('out/liuqin-r101-a7-work/evidence/result-manifest.json', 'fba43e50f7e9b9c493166b2fb768bed08dbf3241f6e83cc33f03dfc328661afb'),
        ('out/liuqin-r101-a7-work/evidence/host-manifest.json', 'cfae2cc7a720b7e5e5350b5b24e79e9efe9d29b927e0f2e07f2c282aaedc948b'),
    ]
    checked = {}
    for rel, expected in frozen:
        actual = sha(ROOT / rel)
        assert actual == expected, f'Frozen manifest changed! {rel}: {actual} != {expected}'
        checked[rel] = actual
    return checked


def main():
    record_userspace_blockers()
    frozen_ok = verify_frozen_manifests()
    files = {}
    for base in (EV, SCRIPTS):
        for p in sorted(base.rglob('*')):
            if p.is_file() and p.name != 'audit-manifest.json' and '__pycache__' not in p.parts:
                files[str(p.relative_to(ROOT))] = sha(p)
    # Also hash the 3 built diagnostic archives and generated headers
    for p in sorted((ROOT / 'out/liuqin-r101-gpu-host-gates-r2').glob('*.a')):
        files[str(p.relative_to(ROOT))] = sha(p)
    for rel in [
        'out/liuqin-r101-gpu-host-gates-r2/stage/build/sheng-gmu/ShengGmuSource.h',
        'out/liuqin-r101-gpu-host-gates-r2/stage/build/sheng-gmu/ShengGmuVotesSource.h',
        'out/liuqin-r101-gpu-host-gates-r2/stage/build/sheng-gmu/ShengGmuCommandDbSource.h',
        'out/liuqin-r101-gpu-host-gates-r2/stage/build/sheng-gpu-smmu/ShengGpuSmmuSource.h',
    ]:
        p = ROOT / rel
        if p.is_file():
            files[rel] = sha(p)
    manifest = {
        'scope': 'r101 GPU host-gates r2 evidence, scripts, generated headers, and archives; frozen prior manifests verified untouched',
        'frozen_manifests_verified': frozen_ok,
        'files': files,
    }
    mpath = EV / 'audit-manifest.json'
    mpath.write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'PASS: wrote {mpath.relative_to(ROOT)} ({len(files)} files), SHA256={sha(mpath)}')
    print(f'PASS: all {len(frozen_ok)} previously frozen manifests verified intact')


if __name__ == '__main__':
    main()
