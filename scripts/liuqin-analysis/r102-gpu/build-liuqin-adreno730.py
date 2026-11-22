#!/usr/bin/env python3
"""Build libLiuqinAdreno730.a: SM8475 / Adreno 730.1 full KMD + staged AGXAccelerator + firmware archive."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path('/home/kurumin/github/UniXNU')
SM8550 = Path('/home/kurumin/github/UniXNU-sm8550-common')
CLT_BIN = Path('/opt/unixnu-linux/CommandLineTools/usr/bin')
CLANG_BIN = Path('/opt/unixnu-linux/llvm/bin/clang')
AR_BIN = CLT_BIN / 'ar'
NM_BIN = CLT_BIN / 'nm'
OBJCOPY_BIN = Path(shutil.which('llvm-objcopy') or '/usr/bin/llvm-objcopy')


def make_cmd(recipe, src: Path, out_o: Path, extra_flags):
    cmd, args, i = [], recipe['arguments'], 0
    while i < len(args):
        v = args[i]
        if v == recipe['file']:
            cmd.append(str(src))
        elif v == '-o':
            cmd += ['-o', str(out_o)]
            i += 1
        elif v in ('-MF', '-MT', '-MJ'):
            i += 1
        elif v == '-Xclang' and i + 1 < len(args) and args[i + 1].startswith('-W'):
            i += 1
        elif not v.startswith('-W') and v not in ('-MD', '-MP'):
            cmd.append(v)
        i += 1
    cmd += extra_flags
    return cmd


def main() -> None:
    tree = Path.cwd()
    device = Path(os.environ['UNIXNU_DEVICE'])
    drv_dir = device / 'drivers/LiuqinAdreno730'
    out = tree / 'build/liuqin-adreno730'
    out.mkdir(parents=True, exist_ok=True)
    xnu_obj = tree / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837'

    c_rec = json.loads((xnu_obj / 'bsd/DEVELOPMENT/bsd_init.o.json').read_text().strip().rstrip(','))
    cxx_rec = json.loads((xnu_obj / 'iokit/DEVELOPMENT/IOPlatformExpert.cpo.json').read_text().strip().rstrip(','))

    trace_hash = hashlib.sha256()
    for p in sorted((ROOT / 'drivers/Adreno740').glob('Native*')):
        if p.is_file():
            trace_hash.update(p.name.encode())
            trace_hash.update(p.read_bytes())
    trace_id = trace_hash.hexdigest()[:16]

    common_inc = [
        '-I', str(drv_dir / 'headers'),
        '-I', str(drv_dir),
        '-I', str(SM8550 / 'kits/Sm8550Platform'),
        '-I', str(ROOT / 'kits/AdrenoFirmware'),
        '-I', str(ROOT / 'kits/AdrenoPM4'),
        '-I', str(ROOT / 'kits/ArmSmmu4K'),
        '-I', str(ROOT / 'drivers/Adreno740'),
        '-I', str(tree / '.cache/xnu-work/osfmk'),
    ]
    werror_flags = [
        '-Wall', '-Wextra', '-Werror',
        '-Wno-unused-parameter', '-Wno-incompatible-sysroot',
        '-Wno-c99-designator', '-Wno-reorder-init-list',
        '-Wno-deprecated-enum-enum-conversion', '-Wno-deprecated-anon-enum-enum-conversion',
        '-Wno-unnecessary-virtual-specifier', '-Wno-overriding-option',
        '-Wno-missing-designated-field-initializers', '-Wno-deprecated-declarations',
        '-Wno-unused-but-set-variable', '-Wno-unused-but-set-global',
    ]

    def compile_one(src: Path, name: str, extra=None) -> Path:
        rec = c_rec if src.suffix == '.c' else cxx_rec
        dst = out / name
        flags = common_inc + ['-DNATIVE_GPU_BUILD_ID=0x' + trace_id + 'ULL'] + werror_flags + (extra or [])
        cmd = make_cmd(rec, src, dst, flags)
        res = subprocess.run(cmd, cwd=rec['directory'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if res.returncode != 0:
            raise SystemExit(f'Compile failed for {src}:\n{res.stdout[-5000:]}')
        return dst

    objs = []
    # 1. Board bring-up + A730 GMU votes + isolated SM8475 GMU loader + Sm8550Platform cmd-db
    objs.append(compile_one(drv_dir / 'LiuqinGpuBringup.cpp', 'LiuqinGpuBringup.o'))
    objs.append(compile_one(drv_dir / 'LiuqinGmuVotes.c', 'LiuqinGmuVotes.kit.o'))
    objs.append(compile_one(drv_dir / 'LiuqinGmu.c', 'LiuqinGmu.kit.o'))
    objs.append(compile_one(SM8550 / 'kits/Sm8550Platform/ShengGmuCommandDb.c', 'ShengGmuCommandDb.kit.o'))

    # 2. Core AdrenoFirmware, ArmSmmu4K, AdrenoPM4 kits
    for n in ('AdrenoHfi.c', 'AdrenoHfiStartup.c', 'AdrenoHfiVotes.c', 'AdrenoFirmware.c'):
        objs.append(compile_one(ROOT / 'kits/AdrenoFirmware' / n, Path(n).stem + '.kit.o'))
    for p in sorted((ROOT / 'kits/ArmSmmu4K').glob('ArmSmmu4K*.c')):
        if p.name == 'ArmSmmu4KStreams.c':
            objs.append(compile_one(drv_dir / 'LiuqinSmmu4KStreams.c', 'LiuqinSmmu4KStreams.kit.o'))
        else:
            objs.append(compile_one(p, p.stem + '.kit.o'))
    objs.append(compile_one(ROOT / 'kits/AdrenoPM4/AdrenoPM4.c', 'AdrenoPM4.kit.o'))

    # 3. Core NativeAdreno C++ modules (omit Service/Client/Accelerator; Accelerator built staged below)
    for p in sorted((ROOT / 'drivers/Adreno740').glob('NativeAdreno*.cpp')):
        if p.name in ('NativeAdrenoClient.cpp', 'NativeAdrenoService.cpp', 'NativeAdrenoAccelerator.cpp'):
            continue
        objs.append(compile_one(p, p.stem + '.o'))

    # 4. Staged AGXAccelerator subclassing 26C5035r IOGraphicsFamily IOAccelerator
    plan = json.loads((ROOT / 'scripts/data/ioaccelerator-base-abi-26C5035r.json').read_text())
    accel_o = compile_one(ROOT / 'drivers/Adreno740/NativeAdrenoAccelerator.cpp', 'NativeAdrenoAccelerator.o',
                          extra=['-Wno-overloaded-virtual'])
    nm_u = set(subprocess.check_output([str(NM_BIN), '-j', '-u', str(accel_o)], text=True).splitlines())
    mangled = '13IOAccelerator'
    bindings = {
        f'__ZN{mangled}C2EPK11OSMetaClass': int(plan['protected_compatible_constructor_aliases'][0], 16),
        f'__ZN{mangled}D2Ev': int(plan['nondeleting_destructor'], 16),
        f'__ZN{mangled}10gMetaClassE': int(plan['metaclass'], 16),
    }
    undef = {s for s in nm_u if mangled in s}
    assert undef and not (undef - set(bindings)), f'Unexpected IOAccelerator imports: {undef}'
    slide = int(plan['collection_slide'], 16)
    text_s, addr_s = '.text\n.p2align 2\n', ''
    for sym, va in sorted(bindings.items()):
        if sym not in undef:
            continue
        if sym.endswith('gMetaClassE'):
            addr_s += f'.globl {sym}\n.set {sym}, {va + slide:#x}\n'
        else:
            addr_s += f'.globl {sym}.original\n.set {sym}.original, {va + slide:#x}\n'
            text_s += f'.globl {sym}\n{sym}:\n bti c\n b {sym}.original\n'
    (out / 'accel-bindings.S').write_text(text_s)
    (out / 'accel-addresses.S').write_text(addr_s)
    for stem in ('accel-bindings', 'accel-addresses'):
        subprocess.run([str(CLANG_BIN), '-target', 'arm64e-apple-ios27.0', '-c',
                        str(out / f'{stem}.S'), '-o', str(out / f'{stem}.o')], check=True)
        objs.append(out / f'{stem}.o')
    accel_late = out / 'NativeAdrenoAccelerator.late.o'
    subprocess.run([str(OBJCOPY_BIN), '--remove-section=__DATA,__mod_init_func',
                    '--globalize-symbol=__GLOBAL__sub_I_NativeAdrenoAccelerator.cpp',
                    str(accel_o), str(accel_late)], check=True)
    objs.append(accel_late)

    # 5. Embedded A730 firmware blobs in __DATA_CONST,__const
    blobs = [
        ('_native_adreno_firmware_image', ROOT / 'out/liuqin-r101-gpu-m1/evidence/firmware/gmu_gen70000.bin'),
        ('_native_adreno_sqe_firmware_image', ROOT / 'out/liuqin-r101-gpu-host-gates/evidence/a730_sqe.fw'),
        ('_native_adreno_zap_image', ROOT / 'out/liuqin-r101-gpu-m1/evidence/firmware/a730_zap.mbn'),
    ]
    asm = ['.section __DATA_CONST,__const']
    for label, path in blobs:
        assert path.is_file(), f'Missing firmware blob {path}'
        asm += ['.p2align 12', f'.globl {label}', f'{label}:',
                f'.incbin {json.dumps(str(path))}', f'{label}_end:',
                '.p2align 3', f'.globl {label}_size', f'{label}_size:', f'.quad {label}_end-{label}']
    fw_s = out / 'firmware-a730.S'
    fw_o = out / 'firmware-a730.o'
    fw_s.write_text('\n'.join(asm) + '\n')
    subprocess.run([str(CLANG_BIN), '-target', 'arm64e-apple-ios27.0', '-c', str(fw_s), '-o', str(fw_o)], check=True)
    objs.append(fw_o)

    archive = out / 'libLiuqinAdreno730.a'
    archive.unlink(missing_ok=True)
    subprocess.run([str(AR_BIN), 'rcs', str(archive), *[str(o) for o in objs]], check=True)
    print(f'PASS: built {archive} ({len(objs)} objects, {archive.stat().st_size} bytes)')


if __name__ == '__main__':
    main()
