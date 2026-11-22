#!/usr/bin/env python3
"""Build NativeAdrenoMetal.bundle for macOS 27.3 (26C5035r, arm64e) 100% on Linux x86_64.

Consumes:
  - /media/disk_4/unixnu_workspace/macos27-cross/sdk/MacOSX27.3-26C5035r.sdk
  - /media/disk_4/unixnu_workspace/macos27-cross/build/mesa-tu-macos27/src/freedreno/vulkan/libvulkan_freedreno.dylib
  - /media/disk_4/unixnu_workspace/macos27-cross/build/m2v-target/arm64e-apple-darwin/release/libadreno_metal_bridge.a
  - /media/disk_4/unixnu_workspace/macos27-cross/build/turnip-smoke/NativeTurnipShaders.h

Produces:
  - /media/disk_4/unixnu_workspace/macos27-cross/build/adreno-metal-plugin-macos27/NativeAdrenoMetal.bundle (4 KiB-page ad-hoc signed)
  - /media/disk_4/unixnu_workspace/macos27-cross/build/adreno-metal-plugin-macos27/trust.json (CDHashes)
  - /media/disk_4/unixnu_workspace/macos27-cross/build/adreno-metal-plugin-macos27/kernel.macho.gpuaddon (NGPUADD2)
"""
from __future__ import annotations

import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path('/home/kurumin/github/UniXNU')
BASE = Path('/media/disk_4/unixnu_workspace/macos27-cross')
SDK = BASE / 'sdk/MacOSX27.3-26C5035r.sdk'
CLT = Path('/opt/unixnu-linux/CommandLineTools/usr/bin')
CLANG = BASE / 'bin/macos27-clang'
CLANGXX = BASE / 'bin/macos27-clang++'
RCODESIGN = BASE / 'bin/rcodesign'
OBJCOPY = Path(shutil.which('llvm-objcopy') or '/usr/bin/llvm-objcopy')
VULKAN_INCLUDE = BASE / 'src/mesa/include'
SMOKE_INCLUDE = BASE / 'build/turnip-smoke'
TURNIP = BASE / 'build/mesa-tu-macos27/src/freedreno/vulkan/libvulkan_freedreno.dylib'
BRIDGE = BASE / 'build/m2v-target/arm64e-apple-darwin/release/libadreno_metal_bridge.a'
OUT = BASE / 'build/adreno-metal-plugin-macos27'


def run(cmd, **kw):
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


def parse_rcodesign_cdhash_and_check_4k(path: Path) -> str:
    out = subprocess.check_output([str(RCODESIGN), 'print-signature-info', str(path)], text=True)
    # Extract CodeDirectory (slot 0) sha256 -> first 40 hex chars = 20-byte CDHash
    m_cd = re.search(r'slot:\s*CodeDirectory \(0\).*?sha256:\s*([0-9a-f]{64})', out, re.S)
    assert m_cd, f'Failed to parse CodeDirectory sha256 for {path}:\n{out[:1200]}'
    cdhash = m_cd.group(1)[:40]
    m_sz = re.search(r'signed_entity_size:\s*(\d+)', out)
    m_cnt = re.search(r'code_digests_count:\s*(\d+)', out)
    assert m_sz and m_cnt, f'Missing signed_entity_size / code_digests_count for {path}'
    sz, cnt = int(m_sz.group(1)), int(m_cnt.group(1))
    expected_4k = (sz + 4095) // 4096
    assert cnt == expected_4k, f'Expected 4 KiB pages ({expected_4k} digests for {sz} bytes), got {cnt} on {path}'
    return cdhash


def main() -> None:
    assert TURNIP.is_file(), f'Missing Turnip dylib: {TURNIP}'
    assert BRIDGE.is_file(), f'Missing Rust bridge archive: {BRIDGE}'
    assert (SMOKE_INCLUDE / 'NativeTurnipShaders.h').is_file(), 'Missing NativeTurnipShaders.h'

    if OUT.exists():
        shutil.rmtree(OUT)
    bundle = OUT / 'NativeAdrenoMetal.bundle'
    contents = bundle / 'Contents'
    code_dir = contents / 'MacOS'
    resources = contents / 'Resources'
    code_dir.mkdir(parents=True)
    resources.mkdir(parents=True)

    source_hash = hashlib.sha256()
    for path in sorted((ROOT / 'drivers/AdrenoMetal').rglob('*')):
        if path.is_file() and '.git' not in path.parts and path.suffix in ('.h', '.mm', '.cpp', '.rs', '.patch'):
            source_hash.update(str(path.relative_to(ROOT / 'drivers/AdrenoMetal')).encode())
            source_hash.update(path.read_bytes())
    metal_build_id = source_hash.hexdigest()
    (resources / 'gpu-build.json').write_text(
        json.dumps({'metal_source_sha256': metal_build_id, 'target': 'macos27', 'board': 'liuqin-sm8475'}, indent=2) + '\n'
    )

    c_flags = ['-O2', '-g', '-Wall', '-Wextra', '-Werror', '-Wno-unused-but-set-global', '-fstack-protector-strong',
               f'-DNATIVE_METAL_BUILD_ID="{metal_build_id}"']

    # 1. PAC symbol renames on libadreno_metal_bridge.a (ensure Darwin TOC via llvm-ar/ranlib)
    pac_renames = {
        '_pthread_create': '_nmb_pac_pthread_create',
        '__tlv_atexit': '_nmb_pac_tlv_atexit',
        '_atexit': '_nmb_pac_atexit',
        '__dyld_register_func_for_add_image': '_nmb_pac_dyld_register_func_for_add_image',
        '__Unwind_Backtrace': '_nmb_pac_Unwind_Backtrace',
        '_dlsym': '_nmb_pac_dlsym',
    }
    pac_bridge = OUT / 'libadreno_metal_bridge_pac.a'
    run([OBJCOPY, *[f'--redefine-sym={a}={b}' for a, b in pac_renames.items()], BRIDGE, pac_bridge])
    run([CLT / 'ranlib', pac_bridge])

    # 2. Compile RustPacBoundary.c and AdrenoPM4.c
    boundary = OUT / 'RustPacBoundary.o'
    run([CLANG, *c_flags, '-std=c11', '-I', VULKAN_INCLUDE, '-c',
         ROOT / 'drivers/AdrenoMetal/bridge/RustPacBoundary.c', '-o', boundary])
    pm4 = OUT / 'AdrenoPM4.o'
    run([CLANG, *c_flags, '-std=c11', '-c', ROOT / 'kits/AdrenoPM4/AdrenoPM4.c', '-o', pm4])

    # 3. Link NativeAdrenoMetal bundle executable (arm64e macOS 27.0)
    exe = code_dir / 'NativeAdrenoMetal'
    link_map = OUT / 'NativeAdrenoMetal.map'
    run([
        CLANGXX, *c_flags, '-std=c++17', '-fobjc-arc', '-Wno-deprecated-declarations', '-bundle',
        '-I', ROOT / 'drivers/Adreno740',
        '-I', ROOT / 'kits/AdrenoPM4',
        '-I', VULKAN_INCLUDE,
        '-I', SMOKE_INCLUDE,
        '-x', 'objective-c++',
        ROOT / 'drivers/AdrenoMetal/NativeAdrenoMetalPlugin.mm',
        ROOT / 'drivers/AdrenoMetal/NativeBridgeMetalFrontend.mm',
        '-x', 'none',
        pm4, pac_bridge, boundary,
        f'-Wl,-map,{link_map}',
        '-Wl,-dead_strip',
        '-lobjc',
        '-framework', 'Foundation',
        '-framework', 'Metal',
        '-framework', 'IOSurface',
        '-F', str(SDK / 'System/Library/PrivateFrameworks'),
        '-framework', 'IOGPU',
        '-framework', 'IOKit',
        '-o', exe,
    ])

    # 4. Route Rust indirect branches through PAC stripping trampolines
    run(['python3', ROOT / 'scripts/rust-pac-rewrite.py', exe, link_map, 'libadreno_metal_bridge_pac.a'])
    run([CLT / 'strip', '-x', exe])
    # Move dSYM out of the bundle so rcodesign doesn't try to sign DWARF symbols
    dsym = code_dir / 'NativeAdrenoMetal.dSYM'
    if dsym.exists():
        shutil.move(str(dsym), str(OUT / 'NativeAdrenoMetal.dSYM'))

    # Verify arm64e Mach-O header
    hdr = exe.read_bytes()[:16]
    magic, cputype, subtype = (
        int.from_bytes(hdr[0:4], 'little'),
        int.from_bytes(hdr[4:8], 'little'),
        int.from_bytes(hdr[8:12], 'little'),
    )
    assert (magic, cputype, subtype & 0xffffff) == (0xfeedfacf, 0x100000c, 2), f'Expected arm64e Mach-O, got {(hex(magic), hex(cputype), hex(subtype))}'

    # 5. Copy & strip Turnip beside NativeAdrenoMetal, 4 KiB ad-hoc sign with rcodesign
    turnip_lib = code_dir / 'libvulkan_freedreno.dylib'
    shutil.copyfile(TURNIP, turnip_lib)
    run([CLT / 'strip', '-x', turnip_lib])
    run([RCODESIGN, 'sign', '--binary-identifier', 'org.blu-sharky.turnip', turnip_lib])
    turnip_cdhash = parse_rcodesign_cdhash_and_check_4k(turnip_lib)

    # 6. Write Info.plist & 4 KiB ad-hoc sign the bundle
    (contents / 'Info.plist').write_bytes(plistlib.dumps(dict(
        CFBundleIdentifier='org.blu-sharky.NativeAdrenoMetal',
        CFBundleExecutable='NativeAdrenoMetal',
        CFBundlePackageType='BNDL',
        CFBundleVersion='1',
        CFBundleShortVersionString='1',
        NSPrincipalClass='NativeAdrenoMetalDevice',
        LSMinimumSystemVersion='27.0',
    ), fmt=plistlib.FMT_XML))

    # Sign the bundle executable & seal resources (preserve Turnip's standalone signature if needed, or let rcodesign sign bundle)
    run([RCODESIGN, 'sign', bundle])
    # Re-read BOTH CDHashes AFTER bundle signing (in case rcodesign re-signed nested Turnip dylib!)
    turnip_cdhash = parse_rcodesign_cdhash_and_check_4k(turnip_lib)
    plugin_cdhash = parse_rcodesign_cdhash_and_check_4k(exe)

    trust = {
        'cdhash': plugin_cdhash,
        'turnip_cdhash': turnip_cdhash,
        'bundle': 'NativeAdrenoMetal.bundle',
        'executable_bytes': exe.stat().st_size,
        'turnip_bytes': turnip_lib.stat().st_size,
    }
    (OUT / 'trust.json').write_text(json.dumps(trust, indent=2) + '\n')

    # 7. Pack NGPUADD2 gpuaddon with --prefix GPUBundles --publish --no-daemon
    addon = OUT / 'kernel.macho.gpuaddon'
    env = dict(os.environ, ADRENO_PLUGIN_DIR=str(OUT))
    run(['python3', ROOT / 'scripts/make-gpu-addon.py', '--prefix', 'GPUBundles', '--publish', '--no-daemon', addon], env=env)

    print('PASS: NativeAdrenoMetal.bundle + kernel.macho.gpuaddon built on Linux!')
    print(json.dumps(trust, indent=2))


if __name__ == '__main__':
    main()
