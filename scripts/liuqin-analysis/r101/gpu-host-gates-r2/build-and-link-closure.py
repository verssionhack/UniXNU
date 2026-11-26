#!/usr/bin/env python3
"""Isolated r2 full reference KMD closure build, real standalone link, and fileset placement audit.

Uses unmodified local UniXNU-sheng (6bc0ce1e8c...) and UniXNU-sm8550-common (97665e2857...)
plus SHA-pinned upstream sources to run the real unmodified sheng generators (no fabricated
headers!), compile the full Adreno740 + kits + staged AGXAccelerator + firmware closure with
the actual 26C5035r arm64e kernel toolchain (-Wall -Wextra -Werror), perform real ld64
standalone links against A7's exact link.filelist & archives, and validate fileset placement
with XnuPrelink Layout.validate() and A7 policy caps.

Never modifies A7, frozen M1/host-gate directories, or any driver/XNU source.
"""
from pathlib import Path
import hashlib
import json
import os
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[4]
SHENG = Path('/home/kurumin/Codes/Github/UniXNU-sheng')
SM8550 = Path('/home/kurumin/Codes/Github/UniXNU-sm8550-common')
TREE = ROOT / 'out/liuqin/macos-27.3-26C5035r/liuqin/tree'
XNU_OBJ = TREE / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837'
A7_EV = ROOT / 'out/liuqin-r101-a7-work/evidence/a'
KC_PATH = Path('/media/disk_4/unixnu_workspace/ramdisk_dir/unixnu/ipsw/26C5035r/kernelcache.decompressed')
OUT = ROOT / 'out/liuqin-r101-gpu-host-gates-r2'
STAGE = OUT / 'stage'
EV = OUT / 'evidence'
EV.mkdir(parents=True, exist_ok=True)

CLT_BIN = Path('/opt/unixnu-linux/CommandLineTools/usr/bin')
CLANG_BIN = Path('/opt/unixnu-linux/llvm/bin/clang')
CLANGXX_BIN = Path('/opt/unixnu-linux/llvm/bin/clang++')
LD64_CLANGXX = CLT_BIN / 'clang++'
AR_BIN = CLT_BIN / 'ar'
NM_BIN = CLT_BIN / 'nm'
OBJCOPY_BIN = Path(shutil.which('llvm-objcopy') or '/usr/bin/llvm-objcopy')

# A7 layout policy caps (from r100/package.py & layout-audit)
TEXT_CAP = 0x1d8000
DATA_CAP = 0x284000
MIN_TEXT_CONST_VMA = 0xfffffff007005900


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def ensure_symlink(link: Path, target: Path):
    link.parent.mkdir(parents=True, exist_ok=True)
    if link.is_symlink():
        if link.resolve() == target.resolve():
            return
        link.unlink()
    elif link.exists():
        raise RuntimeError(f'Unexpected real path at symlink slot {link}')
    link.symlink_to(target)


def parse_macho_sections(raw: bytes):
    assert struct.unpack_from('<I', raw)[0] == 0xfeedfacf
    at = 32
    rows = []
    for _ in range(struct.unpack_from('<I', raw, 16)[0]):
        cmd, size = struct.unpack_from('<II', raw, at)
        if cmd == 0x19:
            for i in range(struct.unpack_from('<I', raw, at + 64)[0]):
                q = at + 72 + 80 * i
                name = raw[q:q + 16].split(b'\0')[0].decode()
                seg = raw[q + 16:q + 32].split(b'\0')[0].decode()
                length = struct.unpack_from('<Q', raw, q + 40)[0]
                flags = struct.unpack_from('<I', raw, q + 64)[0]
                rows.append({'segment': seg, 'section': name, 'bytes': length, 'flags': hex(flags)})
        at += size
    return rows


def setup_stage():
    """Populate isolated stage tree with read-only symlinks to unmodified sources."""
    ensure_symlink(STAGE / 'scripts/data', ROOT / 'scripts/data')
    ensure_symlink(STAGE / 'kits/sheng', SHENG / 'package')
    ensure_symlink(STAGE / 'kits/Sm8550Platform', SM8550 / 'kits/Sm8550Platform')
    ensure_symlink(STAGE / 'kits/AdrenoFirmware', ROOT / 'kits/AdrenoFirmware')
    ensure_symlink(STAGE / 'kits/AdrenoPM4', ROOT / 'kits/AdrenoPM4')
    ensure_symlink(STAGE / 'kits/ArmSmmu4K', ROOT / 'kits/ArmSmmu4K')
    ensure_symlink(STAGE / 'drivers/Adreno740', ROOT / 'drivers/Adreno740')
    ensure_symlink(STAGE / 'drivers/AdrenoMetal', ROOT / 'drivers/AdrenoMetal')
    ensure_symlink(STAGE / '.cache/xnu-work', TREE / '.cache/xnu-work')
    for gen in ('prepare-sheng-gmu.py', 'prepare-sheng-gpu-smmu.py', 'prepare-sheng-gmu-votes.py'):
        dst = STAGE / 'scripts' / gen
        dst.parent.mkdir(parents=True, exist_ok=True)
        if dst.is_symlink():
            dst.unlink()
        shutil.copyfile(SHENG / 'scripts' / gen, dst)


def run_generators():
    """Run the unmodified upstream sheng generators inside the isolated stage tree."""
    env = dict(os.environ, PATH=f'/home/kurumin/.local/bin:{os.environ.get("PATH", "")}')
    logs = {}
    for script in ('prepare-sheng-gmu.py', 'prepare-sheng-gpu-smmu.py', 'prepare-sheng-gmu-votes.py'):
        res = subprocess.run([sys.executable, str(STAGE / 'scripts' / script)], cwd=STAGE, env=env,
                             capture_output=True, text=True)
        logs[script] = {'returncode': res.returncode, 'stdout': res.stdout, 'stderr': res.stderr}
        if res.returncode != 0:
            raise RuntimeError(f'Generator {script} failed:\n{res.stdout}\n{res.stderr}')
    gen_headers = {
        'ShengGmuSource.h': STAGE / 'build/sheng-gmu/ShengGmuSource.h',
        'ShengGmuVotesSource.h': STAGE / 'build/sheng-gmu/ShengGmuVotesSource.h',
        'ShengGmuCommandDbSource.h': STAGE / 'build/sheng-gmu/ShengGmuCommandDbSource.h',
        'ShengGpuSmmuSource.h': STAGE / 'build/sheng-gpu-smmu/ShengGpuSmmuSource.h',
    }
    return logs, {k: {'path': str(v.relative_to(ROOT)), 'bytes': v.stat().st_size, 'sha256': sha(v)}
                  for k, v in gen_headers.items()}


def make_compile_cmd(recipe, source: Path, out_obj: Path, extra_flags):
    args = recipe['arguments']
    cmd, i = [], 0
    while i < len(args):
        v = args[i]
        if v == recipe['file']:
            cmd.append(str(source))
        elif v == '-o':
            cmd += ['-o', str(out_obj)]
            i += 1
        elif v in ('-MF', '-MJ'):
            i += 1
        elif v == '-Xclang' and i + 1 < len(args) and args[i + 1].startswith('-W'):
            i += 1
        elif not v.startswith('-W') and v not in ('-MD', '-MP'):
            cmd.append(v)
        i += 1
    cmd += extra_flags
    return cmd


def compile_closure():
    c_recipe = json.loads((XNU_OBJ / 'bsd/DEVELOPMENT/bsd_init.o.json').read_text().strip().rstrip(','))
    cxx_recipe = json.loads((XNU_OBJ / 'iokit/DEVELOPMENT/IOPlatformExpert.cpo.json').read_text().strip().rstrip(','))

    obj_dir = OUT / 'objects'
    obj_dir.mkdir(parents=True, exist_ok=True)

    # Exact trace_id calculation from UniXNU-sheng/scripts/build-adreno740-kits.py
    trace_hash = hashlib.sha256()
    for p in sorted((STAGE / 'drivers/Adreno740').glob('Native*')):
        if p.is_file():
            trace_hash.update(p.name.encode())
            trace_hash.update(p.read_bytes())
    trace_id = trace_hash.hexdigest()[:16]

    common_inc = [
        '-I', str(STAGE / 'kits/sheng'),
        '-I', str(STAGE / 'kits/Sm8550Platform'),
        '-I', str(STAGE / 'kits/AdrenoFirmware'),
        '-I', str(STAGE / 'build/sheng-gmu'),
        '-I', str(STAGE / 'build/sheng-gpu-smmu'),
        '-I', str(STAGE / 'kits/AdrenoPM4'),
        '-I', str(STAGE / 'kits/ArmSmmu4K'),
        '-I', str(TREE / '.cache/xnu-work/osfmk'),
        '-I', str(STAGE / 'drivers/Adreno740'),
    ]
    werror_flags = [
        '-Wall', '-Wextra', '-Werror',
        '-Wno-unused-parameter', '-Wno-incompatible-sysroot',
        '-Wno-c99-designator', '-Wno-reorder-init-list',
        '-Wno-deprecated-enum-enum-conversion', '-Wno-unnecessary-virtual-specifier',
        '-Wno-overriding-option', '-Wno-missing-designated-field-initializers',
        '-Wno-unused-but-set-variable', '-Wno-unused-but-set-global',
    ]

    # Exact build-arm-driver.py (NativeAdrenoService.cpp) + build-adreno740-kits.py member list
    service_src = STAGE / 'drivers/Adreno740/NativeAdrenoService.cpp'
    kit_sources = [STAGE / 'kits/Sm8550Platform' / n for n in ('ShengGmu.c', 'ShengGmuCommandDb.c')]
    kit_sources += [STAGE / 'kits/sheng/ShengGmuVotes.c']
    kit_sources += [STAGE / 'kits/AdrenoFirmware' / n for n in ('AdrenoHfi.c', 'AdrenoHfiStartup.c', 'AdrenoHfiVotes.c', 'AdrenoFirmware.c')]
    kit_sources += sorted(p for p in (STAGE / 'kits/ArmSmmu4K').glob('ArmSmmu4K*.c'))
    kit_sources += [STAGE / 'kits/AdrenoPM4/AdrenoPM4.c']
    kit_sources += sorted(p for p in (STAGE / 'drivers/Adreno740').glob('NativeAdreno*.cpp')
                          if p.name not in ('NativeAdrenoClient.cpp', 'NativeAdrenoService.cpp', 'NativeAdrenoAccelerator.cpp'))
    # Also compile ShengGpuSmmu.c separately to measure it (note: omitted from sheng's build-adreno740-kits.py)
    extra_smmu_src = STAGE / 'kits/Sm8550Platform/ShengGpuSmmu.c'

    compiled = []
    archive_objs = []

    def compile_one(src: Path, out_name: str, extra=None):
        rec = c_recipe if src.suffix == '.c' else cxx_recipe
        out_o = obj_dir / out_name
        flags = common_inc + ['-DNATIVE_GPU_BUILD_ID=0x' + trace_id + 'ULL'] + werror_flags + (extra or [])
        cmd = make_compile_cmd(rec, src, out_o, flags)
        res = subprocess.run(cmd, cwd=rec['directory'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        row = {
            'source': src.name,
            'source_path': str(src.resolve()),
            'source_sha256': sha(src),
            'object': out_name,
            'returncode': res.returncode,
            'warning_count': sum('warning:' in ln for ln in res.stdout.splitlines()),
        }
        if res.returncode != 0:
            row['diagnostic_tail'] = res.stdout[-2500:]
            raise RuntimeError(f'Compile failed for {src.name}:\n{res.stdout[-2500:]}')
        row['object_sha256'] = sha(out_o)
        row['sections'] = parse_macho_sections(out_o.read_bytes())
        compiled.append(row)
        return out_o

    # 1. NativeAdrenoService.cpp
    archive_objs.append(compile_one(service_src, 'NativeAdreno.o'))
    # 2. All build-adreno740-kits.py objects
    for s in kit_sources:
        out_name = s.stem + ('.kit.o' if s.suffix == '.c' else '.o')
        archive_objs.append(compile_one(s, out_name))
    # 3. ShengGpuSmmu.c (separate diagnostic measurement)
    smmu_obj = compile_one(extra_smmu_src, 'ShengGpuSmmu.kit.o')

    # 4. Staged AGXAccelerator (exact build-adreno740-accelerator.py recipe for 26C5035r arm64e fileset)
    plan = json.loads((ROOT / 'scripts/data/ioaccelerator-base-abi-26C5035r.json').read_text())
    assert not plan['operational_overrides'] and plan['instance_bytes'] == 136 and plan['virtual_entries'] == 272
    accel_src = STAGE / 'drivers/Adreno740/NativeAdrenoAccelerator.cpp'
    accel_o = compile_one(accel_src, 'NativeAdrenoAccelerator.o', extra=['-Wno-overloaded-virtual'])

    # Inspect undefined IOAccelerator imports and verify exact match with 26C5035r plan
    nm_u = set(subprocess.check_output([str(NM_BIN), '-j', '-u', str(accel_o)], text=True).splitlines())
    mangled = '13IOAccelerator'
    bindings = {
        f'__ZN{mangled}C2EPK11OSMetaClass': int(plan['protected_compatible_constructor_aliases'][0], 16),
        f'__ZN{mangled}D2Ev': int(plan['nondeleting_destructor'], 16),
        f'__ZN{mangled}10gMetaClassE': int(plan['metaclass'], 16),
    }
    undef_accel = {s for s in nm_u if mangled in s}
    assert undef_accel and not (undef_accel - set(bindings)), f'Unexpected IOAccelerator imports: {undef_accel}'

    slide = int(plan['collection_slide'], 16)
    text_s, addr_s = '.text\n.p2align 2\n', ''
    for sym, va in sorted(bindings.items()):
        if sym not in undef_accel:
            continue
        if sym.endswith('gMetaClassE'):
            addr_s += f'.globl {sym}\n.set {sym}, {va + slide:#x}\n'
        else:
            addr_s += f'.globl {sym}.original\n.set {sym}.original, {va + slide:#x}\n'
            text_s += f'.globl {sym}\n{sym}:\n bti c\n b {sym}.original\n'
    (obj_dir / 'accel-original-bindings.S').write_text(text_s)
    (obj_dir / 'accel-original-addresses.S').write_text(addr_s)
    for stem in ('accel-original-bindings', 'accel-original-addresses'):
        subprocess.run([str(CLANG_BIN), '-target', 'arm64e-apple-ios27.0', '-c',
                        str(obj_dir / f'{stem}.S'), '-o', str(obj_dir / f'{stem}.o')], check=True)
    accel_late = obj_dir / 'NativeAdrenoAccelerator.late.o'
    subprocess.run([str(OBJCOPY_BIN), '--remove-section=__DATA,__mod_init_func',
                    '--globalize-symbol=__GLOBAL__sub_I_NativeAdrenoAccelerator.cpp',
                    str(accel_o), str(accel_late)], check=True)
    accel_objs = [accel_late, obj_dir / 'accel-original-bindings.o', obj_dir / 'accel-original-addresses.o']

    # 5. Firmware objects in __DATA_CONST,__const (4 KiB aligned + 8-byte size symbols)
    def build_fw_obj(tag: str, blobs):
        asm = ['.section __DATA_CONST,__const']
        meta = []
        for label, path in blobs:
            assert path.is_file(), f'Missing firmware blob {path}'
            asm += ['.p2align 12', f'.globl {label}', f'{label}:',
                    f'.incbin {json.dumps(str(path))}', f'{label}_end:',
                    '.p2align 3', f'.globl {label}_size', f'{label}_size:', f'.quad {label}_end-{label}']
            meta.append({'label': label, 'file': path.name, 'bytes': path.stat().st_size, 'sha256': sha(path)})
        s_path = obj_dir / f'firmware-{tag}.S'
        o_path = obj_dir / f'firmware-{tag}.o'
        s_path.write_text('\n'.join(asm) + '\n')
        subprocess.run([str(CLANG_BIN), '-target', 'arm64e-apple-ios27.0', '-c', str(s_path), '-o', str(o_path)], check=True)
        return o_path, meta, parse_macho_sections(o_path.read_bytes())

    fw_sheng_o, fw_sheng_meta, fw_sheng_secs = build_fw_obj('sheng', [
        ('_native_adreno_firmware_image', STAGE / '.cache/firmware/sheng-gpu/qcom/gmu_gen70200.bin'),
        ('_native_adreno_sqe_firmware_image', STAGE / '.cache/firmware/sheng-gpu/qcom/a740_sqe.fw'),
        ('_native_adreno_zap_image', STAGE / '.cache/firmware/sheng-gpu/qcom/sm8550/sheng/a740_zap.mbn'),
    ])
    fw_a730_o, fw_a730_meta, fw_a730_secs = build_fw_obj('a730', [
        ('_native_adreno_firmware_image', ROOT / 'out/liuqin-r101-gpu-m1/evidence/firmware/gmu_gen70000.bin'),
        ('_native_adreno_sqe_firmware_image', ROOT / 'out/liuqin-r101-gpu-host-gates/evidence/a730_sqe.fw'),
        ('_native_adreno_zap_image', ROOT / 'out/liuqin-r101-gpu-m1/evidence/firmware/a730_zap.mbn'),
    ])

    def make_archive(name: str, objs):
        arch = OUT / name
        arch.unlink(missing_ok=True)
        subprocess.run([str(AR_BIN), 'rcs', str(arch), *[str(o) for o in objs]], check=True)
        defined = subprocess.check_output([str(NM_BIN), '-g', str(arch)], text=True)
        req = ('_ShengGmuColdStart', '_ShengGmuBuildStartup', '_ShengGmuCommandDbInputs',
               '_AdrenoFirmwarePlanGmu', '_ArmSmmu4KAttachStreams', '_ArmSmmu4KBindMmio',
               '_AdrenoPM4Type7', '_NativeAdrenoGmuContextBringup',
               '__GLOBAL__sub_I_NativeAdrenoAccelerator.cpp',
               '_native_adreno_firmware_image', '_native_adreno_sqe_firmware_image', '_native_adreno_zap_image')
        missing = [s for s in req if (' T ' + s) not in defined and (' S ' + s) not in defined and (' D ' + s) not in defined]
        assert not missing, f'{name} missing required definitions: {missing}'
        return arch

    arch_sheng = make_archive('libAdreno740-sheng-closure.a', archive_objs + accel_objs + [fw_sheng_o])
    arch_a730 = make_archive('libAdreno740-a730blobs-closure.a', archive_objs + accel_objs + [fw_a730_o])
    arch_a730_smmu = make_archive('libAdreno740-a730blobs-plus-smmu.a', archive_objs + [smmu_obj] + accel_objs + [fw_a730_o])

    return {
        'trace_id': trace_id,
        'compiled_objects_count': len(compiled),
        'total_warnings': sum(r['warning_count'] for r in compiled),
        'compiled_objects': compiled,
        'accel_bindings': {k: hex(v) for k, v in bindings.items()},
        'accel_undefined_checked': sorted(undef_accel),
        'firmware_sheng': {'blobs': fw_sheng_meta, 'sections': fw_sheng_secs},
        'firmware_a730': {'blobs': fw_a730_meta, 'sections': fw_a730_secs},
        'archives': {
            'sheng_closure': str(arch_sheng),
            'a730blobs_closure': str(arch_a730),
            'a730blobs_plus_smmu': str(arch_a730_smmu),
        },
    }


def evaluate_standalone_layout(macho_path: Path, cache_img, closure_set, a7_standalone_img):
    sys.path.insert(0, str(ROOT / 'kits/XnuPrelink'))
    from kc_image import Image
    from fileset_layout import Layout

    raw = macho_path.read_bytes()
    native = Image(raw)
    layout = Layout(cache_img, native, closure_set)
    validate_error = None
    try:
        layout.validate()
        validated = True
    except Exception as exc:
        validated = False
        validate_error = str(exc)

    def seg_map(img):
        return {s['name']: {'va': hex(s['va']), 'size': s['size'], 'size_hex': hex(s['size']), 'filesize': s['filesize']}
                for s in img.segments if s['size']}

    segs = seg_map(native)
    a7_segs = seg_map(a7_standalone_img)
    text_const = next(s for s in native.sections if s['segment'] == '__TEXT' and s['name'] == '__const')
    a7_text_const = next(s for s in a7_standalone_img.sections if s['segment'] == '__TEXT' and s['name'] == '__const')

    # Check header-to-first-backed-section gap
    first_offs = []
    for cmd, at, _ in native.commands:
        if cmd != 0x19:
            continue
        for i in range(struct.unpack_from('<I', native.data, at + 64)[0]):
            s = at + 72 + i * 80
            sz, off = struct.unpack_from('<QI', native.data, s + 40)
            if sz and off:
                first_offs.append(off)
    ncmds, sizeofcmds = struct.unpack_from('<II', native.data, native.at + 16)
    header_gap = min(first_offs) - (native.at + 32 + sizeofcmds)

    # Check remaining space to next retained kext in each key window
    occupied = []
    for name, (_, at) in cache_img.entries.items():
        if name == 'com.apple.kernel' or name not in closure_set:
            continue
        for s in Image(cache_img.data, at).segments:
            if s['size'] and s['name'] != '__LINKEDIT':
                occupied.append({'owner': name, **s})

    def next_retained_gap(seg_name, root_name):
        start = layout.placements[seg_name]
        sz = next(s['size'] for s in native.segments if s['name'] == seg_name)
        end = start + sz
        root_seg = next(s for s in cache_img.segments if s['name'] == root_name)
        cands = [s for s in occupied if end <= s['va'] < root_seg['va'] + root_seg['size']]
        nxt = min(cands, key=lambda s: s['va']) if cands else None
        return {
            'placement_start': hex(start),
            'placement_end': hex(end),
            'size': sz,
            'next_retained_owner': nxt['owner'] if nxt else None,
            'next_retained_start': hex(nxt['va']) if nxt else None,
            'remaining_bytes_to_next_retained': (nxt['va'] - end) if nxt else None,
        }

    # Const tail (LASTDATA_CONST) to first retained DATA_CONST
    lastdc_start = layout.placements['__LASTDATA_CONST']
    lastdc_sz = next(s['size'] for s in native.segments if s['name'] == '__LASTDATA_CONST')
    lastdc_end = lastdc_start + lastdc_sz
    first_ret_dc = min((s for s in occupied if s['name'] == '__DATA_CONST' and s['va'] >= lastdc_start), key=lambda s: s['va'])

    # Code/KLD tail to native DATA start
    kld_end = layout.placements['__KLD'] + next(s['size'] for s in native.segments if s['name'] == '__KLD')
    data_start = layout.placements['__DATA']

    deltas = {}
    for k in ('__TEXT', '__DATA_CONST', '__TEXT_EXEC', '__DATA', '__LASTDATA_CONST'):
        if k in segs and k in a7_segs:
            deltas[k] = segs[k]['size'] - a7_segs[k]['size']

    return {
        'standalone_sha256': hashlib.sha256(raw).hexdigest(),
        'standalone_bytes': len(raw),
        'segments': {k: segs[k] for k in ('__TEXT', '__DATA_CONST', '__TEXT_EXEC', '__DATA', '__LASTDATA_CONST', '__KLD') if k in segs},
        'deltas_vs_A7_bytes': deltas,
        'policy_gates': {
            'TEXT_size': hex(segs['__TEXT']['size']),
            'TEXT_cap': hex(TEXT_CAP),
            'TEXT_slack_bytes': TEXT_CAP - segs['__TEXT']['size'],
            'TEXT_pass': segs['__TEXT']['size'] <= TEXT_CAP,
            'DATA_size': hex(segs['__DATA']['size']),
            'DATA_cap': hex(DATA_CAP),
            'DATA_slack_bytes': DATA_CAP - segs['__DATA']['size'],
            'DATA_pass': segs['__DATA']['size'] <= DATA_CAP,
            'first_const_vma': hex(text_const['va']),
            'a7_first_const_vma': hex(a7_text_const['va']),
            'const_vma_floor': hex(MIN_TEXT_CONST_VMA),
            'const_vma_margin_bytes': text_const['va'] - MIN_TEXT_CONST_VMA,
            'const_vma_pass': text_const['va'] >= MIN_TEXT_CONST_VMA,
            'header_to_first_section_gap_bytes': header_gap,
            'header_gap_pass': header_gap >= 0,
        },
        'fileset_layout': {
            'validate_passed': validated,
            'validate_error': validate_error,
            'TEXT_window': next_retained_gap('__TEXT', '__PRELINK_TEXT'),
            'DATA_window': next_retained_gap('__DATA', '__DATA'),
            'const_tail_end': hex(lastdc_end),
            'first_retained_DATA_CONST_owner': first_ret_dc['owner'],
            'first_retained_DATA_CONST_start': hex(first_ret_dc['va']),
            'const_tail_to_first_retained_bytes': first_ret_dc['va'] - lastdc_end,
            'kld_end_to_native_DATA_bytes': data_start - kld_end,
            'describe': layout.describe(),
        },
    }


def run_links(closure_info):
    # Reconstruct exact A7 link command from saved .LDFLAGS + linkarchives + link.filelist
    ldflags = shlex.split((XNU_OBJ / '.LDFLAGS').read_text().replace('\0', ''))
    linkarchives = shlex.split((XNU_OBJ / 'mach.development.bcm2837.link/mach.development.bcm2837.linkarchives').read_text().replace('\0', ''))
    # MakeInc.kernel links: $(LD) $(LDFLAGS_KERNEL) $(LDFLAGS_KERNEL_ONLY) -filelist link.filelist lastkernelconstructor.o lastkerneldataconst.o -o $@ $(LD_KERNEL_LIBS) $(LD_KERNEL_ARCHIVES)
    # Note .LDFLAGS already starts with /opt/unixnu-linux/CommandLineTools/usr/bin/clang++ and includes libcc_kext.a!
    base_cmd = list(ldflags)
    # Remove any duplicate -nostdlib if present; keep exact invocation
    filelist = str(XNU_OBJ / 'link.filelist')
    extra_objs = [str(XNU_OBJ / 'version.o'), str(XNU_OBJ / 'lastkernelconstructor.o'), str(XNU_OBJ / 'lastkerneldataconst.o')]

    env = dict(os.environ,
               PATH=f'/opt/unixnu-linux/CommandLineTools/usr/bin:/opt/unixnu-linux/XcodeDefault.xctoolchain/usr/bin:{os.environ.get("PATH", "")}',
               CROSS_CLANG=str(CLANG_BIN),
               DARWIN_TRIPLE='arm64e-apple-ios27.0',
               XNU_TOOLCHAIN_BIN='/opt/unixnu-linux/CommandLineTools/usr/bin /opt/unixnu-linux/XcodeDefault.xctoolchain/usr/bin',
               UNIXNU_SDKROOT=str(TREE / '.cache/fakeroot'))

    def do_link(out_path: Path, extra_archives):
        cmd = [base_cmd[0], '--ld-path=/opt/unixnu-linux/CommandLineTools/usr/bin/ld'] + base_cmd[1:] + ['-filelist', filelist] + extra_objs + ['-o', str(out_path)] + linkarchives + extra_archives
        return subprocess.run(cmd, cwd=XNU_OBJ, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

    sys.path.insert(0, str(ROOT / 'kits/XnuPrelink'))
    from kc_image import Image

    kc_raw = KC_PATH.read_bytes()
    assert hashlib.sha256(kc_raw).hexdigest() == 'd1003b5143ffd88439b4d45b6017f587171cfe6855660bed05370a2ea5db9fe9'
    cache_img = Image(kc_raw)
    closure_set = set(json.loads((A7_EV / 'kernel.json').read_text())['closure'])
    a7_standalone_img = Image((A7_EV / 'standalone.macho').read_bytes())

    link_results = {}
    with tempfile.TemporaryDirectory(prefix='r101-gpu-r2-link-', dir='/tmp') as tmp:
        tmp_dir = Path(tmp)

        # 1. Baseline A7 reproduction link (sanity check: must match A7 standalone segment sizes!)
        base_out = tmp_dir / 'baseline-a7.macho'
        r_base = do_link(base_out, [])
        if r_base.returncode != 0:
            raise RuntimeError('Baseline A7 link reproduction failed:\n' + r_base.stdout[-3000:])
        link_results['a7_baseline_repro'] = evaluate_standalone_layout(base_out, cache_img, closure_set, a7_standalone_img)

        # 2. Unmodified real link attempt with full sheng closure (to record exact unresolved/duplicate symbols)
        raw_out = tmp_dir / 'raw-sheng-closure.macho'
        r_raw = do_link(raw_out, [f'-Wl,-force_load,{closure_info["archives"]["sheng_closure"]}'])
        def parse_ld_diagnostics(text):
            undefs, dups = [], []
            in_undef = False
            for line in text.splitlines():
                if 'Undefined symbols for architecture' in line:
                    in_undef = True
                    continue
                if in_undef:
                    if line.startswith('ld:'):
                        in_undef = False
                    elif line.startswith('  "') and '", referenced from:' in line:
                        undefs.append(line.split('"')[1])
                if line.startswith("duplicate symbol '"):
                    dups.append(line.split("'")[1])
            return undefs, dups

        raw_undefs, raw_dups = parse_ld_diagnostics(r_raw.stdout)
        # Check if resolving undefs exposes duplicate symbols (ld64 reports undefs and dups in separate passes)
        stub_c = tmp_dir / 'measurement_only_board_stubs.c'
        stub_lines = ['/* MEASUREMENT-ONLY DIAGNOSTIC STUBS FOR UNRESOLVED BOARD HOOKS; NEVER FOR BOOT */', '#include <stdint.h>']
        for sym in raw_undefs:
            c_name = sym[1:] if sym.startswith('_') else sym
            if c_name == 'native_gpu_dcvs':
                stub_lines.append('volatile uint32_t native_gpu_dcvs[15] = {0};')
            else:
                stub_lines.append(f'int {c_name}(void) {{ return 0; }}')
        stub_c.write_text('\n'.join(stub_lines) + '\n')
        stub_o = tmp_dir / 'measurement_only_board_stubs.o'
        subprocess.run([str(CLANG_BIN), '-target', 'arm64e-apple-ios27.0', '-O2', '-c', str(stub_c), '-o', str(stub_o)], check=True)
        stub_args = [str(stub_o)] if raw_undefs else []

        # Probe link with stubs only to capture any duplicate symbols vs A7 archives
        dup_probe_out = tmp_dir / 'dup-probe.macho'
        r_dup = do_link(dup_probe_out, [f'-Wl,-force_load,{closure_info["archives"]["sheng_closure"]}'] + stub_args)
        _, probed_dups = parse_ld_diagnostics(r_dup.stdout)
        all_dups = sorted(set(raw_dups) | set(probed_dups))

        link_results['unmodified_sheng_closure_link'] = {
            'linked_without_stubs': r_raw.returncode == 0,
            'unresolved_symbols': raw_undefs,
            'duplicate_symbols_against_A7_archives': all_dups,
            'raw_linker_output': r_raw.stdout[-3000:],
            'dup_probe_linker_output': r_dup.stdout[-3000:] if r_dup.returncode != 0 else '',
        }
        link_results['measurement_only_stubs'] = {
            'needed': bool(raw_undefs),
            'purpose': 'measurement-only diagnostic placeholders for unresolved board hooks; not a driver or bootable kernel',
            'symbols': raw_undefs,
            'stub_object_sections': parse_macho_sections(stub_o.read_bytes()) if raw_undefs else [],
        }

        # If A7's libNativeLegacyDisplay.late.a defines stub copies of symbols now owned by NativeAdrenoPublish.o,
        # prepare an isolated /tmp copy of that archive with ONLY those duplicate symbols weakened so Adreno's real
        # definitions resolve cleanly without altering A7's frozen tree or distorting linked size.
        linkarchives_for_gpu = list(linkarchives)
        weakened_dups_info = {'needed': False}
        if all_dups:
            orig_legacy_idx = next(i for i, a in enumerate(linkarchives_for_gpu) if 'libNativeLegacyDisplay.late.a' in a)
            orig_legacy = Path(linkarchives_for_gpu[orig_legacy_idx].split(',')[-1])
            work_legacy = tmp_dir / 'legacy_unpack'
            work_legacy.mkdir()
            subprocess.run([str(AR_BIN), 'x', str(orig_legacy)], cwd=work_legacy, check=True)
            for obj_f in sorted(work_legacy.glob('*.o')):
                defined_here = set(subprocess.check_output([str(NM_BIN), '-j', '-g', '-U', str(obj_f)], text=True).splitlines())
                to_weaken = sorted(set(all_dups) & defined_here)
                if to_weaken:
                    subprocess.run([str(OBJCOPY_BIN), *[f'--weaken-symbol={s}' for s in to_weaken], str(obj_f), str(obj_f)], check=True)
            patched_legacy = tmp_dir / 'libNativeLegacyDisplay.late.weakdups.a'
            subprocess.run([str(AR_BIN), 'rcs', str(patched_legacy), *[str(p) for p in sorted(work_legacy.glob('*.o'))]], check=True)
            linkarchives_for_gpu[orig_legacy_idx] = f'-Wl,-force_load,{patched_legacy}'
            weakened_dups_info = {
                'needed': True,
                'original_archive': str(orig_legacy),
                'weakened_duplicate_symbols': all_dups,
                'reason': 'A7 libNativeLegacyDisplay.late.a carries non-Adreno stub definitions that collide with NativeAdrenoPublish.o; weakened only in /tmp copy for isolated measurement',
            }
        link_results['measurement_only_weakened_duplicates'] = weakened_dups_info

        def do_gpu_link(out_path: Path, extra_archives):
            cmd = [base_cmd[0], '--ld-path=/opt/unixnu-linux/CommandLineTools/usr/bin/ld'] + base_cmd[1:] + ['-filelist', filelist] + extra_objs + ['-o', str(out_path)] + linkarchives_for_gpu + extra_archives
            return subprocess.run(cmd, cwd=XNU_OBJ, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

        # 3. Link all three closure variants and run full Layout.validate() + A7 policy gates
        for key, arch_path in closure_info['archives'].items():
            out_m = tmp_dir / f'{key}.macho'
            res = do_gpu_link(out_m, [f'-Wl,-force_load,{arch_path}'] + stub_args)
            if res.returncode != 0:
                link_results[key] = {'returncode': res.returncode, 'linker_output': res.stdout[-4000:]}
            else:
                link_results[key] = evaluate_standalone_layout(out_m, cache_img, closure_set, a7_standalone_img)

    return link_results


def main():
    setup_stage()
    gen_logs, gen_headers = run_generators()
    closure_info = compile_closure()
    link_results = run_links(closure_info)

    sheng_rev = subprocess.check_output(['git', '-C', str(SHENG), 'rev-parse', 'HEAD'], text=True).strip()
    sm8550_rev = subprocess.check_output(['git', '-C', str(SM8550), 'rev-parse', 'HEAD'], text=True).strip()
    adreno740_rev = subprocess.check_output(['git', '-C', str(ROOT / 'drivers/Adreno740'), 'rev-parse', 'HEAD'], text=True).strip()

    report = {
        'scope': 'Isolated r2 full reference KMD closure build (-Werror), real standalone arm64e link, and XnuPrelink fileset placement validation; host-only, no boot image or driver edit',
        'revisions': {
            'UniXNU_sheng': sheng_rev,
            'UniXNU_sm8550_common': sm8550_rev,
            'Adreno740': adreno740_rev,
        },
        'generators': gen_logs,
        'generated_headers': gen_headers,
        'closure_compile': closure_info,
        'standalone_links_and_fileset_placement': link_results,
    }
    (EV / 'reference-closure-link-placement.json').write_text(json.dumps(report, indent=2) + '\n')

    print('PASS: generators produced all 4 headers without fabrication')
    print(f'PASS: compiled {closure_info["compiled_objects_count"]} objects with -Werror (warnings={closure_info["total_warnings"]})')
    unmod = link_results['unmodified_sheng_closure_link']
    print('Unmodified link without stubs:', unmod['linked_without_stubs'], 'unresolved:', unmod['unresolved_symbols'])
    for key in ('a7_baseline_repro', 'sheng_closure', 'a730blobs_closure', 'a730blobs_plus_smmu'):
        r = link_results[key]
        if 'policy_gates' in r:
            pg = r['policy_gates']
            fl = r['fileset_layout']
            print(f'  {key}: deltas={r["deltas_vs_A7_bytes"]} TEXT_pass={pg["TEXT_pass"]}(slack={pg["TEXT_slack_bytes"]}) '
                  f'DATA_pass={pg["DATA_pass"]}(slack={pg["DATA_slack_bytes"]}) const_pass={pg["const_vma_pass"]}(margin={pg["const_vma_margin_bytes"]}) '
                  f'layout_validate={fl["validate_passed"]} dc_tail_gap={fl["const_tail_to_first_retained_bytes"]} kld_to_data={fl["kld_end_to_native_DATA_bytes"]}')
        else:
            print(f'  {key}: LINK FAILED rc={r.get("returncode")}')


if __name__ == '__main__':
    main()
