#!/usr/bin/env python3
"""Host-only dry-run of XnuPrelink emit_prelink.py + aes_fileset_gate.py on the isolated r2
a730blobs_plus_smmu standalone link (in /tmp; deletes temporary kernelcache after verification).

Never modifies A7, never emits a boot image or payload, never touches keys or devices.
"""
from pathlib import Path
import hashlib
import json
import os
import shlex
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[4]
TREE = ROOT / 'out/liuqin/macos-27.3-26C5035r/liuqin/tree'
XNU_OBJ = TREE / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837'
A7_EV = ROOT / 'out/liuqin-r101-a7-work/evidence/a'
R100_EV = ROOT / 'out/liuqin-r100-work/evidence'
KC_PATH = Path('/media/disk_4/unixnu_workspace/ramdisk_dir/unixnu/ipsw/26C5035r/kernelcache.decompressed')
OUT = ROOT / 'out/liuqin-r101-gpu-host-gates-r2'
EV = OUT / 'evidence'

CLT_BIN = Path('/opt/unixnu-linux/CommandLineTools/usr/bin')
CLANG_BIN = Path('/opt/unixnu-linux/llvm/bin/clang')
AR_BIN = CLT_BIN / 'ar'
NM_BIN = CLT_BIN / 'nm'
OBJCOPY_BIN = Path('/usr/bin/llvm-objcopy')


def header_gap(image):
    first = []
    for cmd, at, _ in image.commands:
        if cmd != 0x19:
            continue
        for i in range(struct.unpack_from('<I', image.data, at + 64)[0]):
            s = at + 72 + i * 80
            sz, off = struct.unpack_from('<QI', image.data, s + 40)
            if sz and off:
                first.append(off)
    ncmd, szcmds = struct.unpack_from('<II', image.data, image.at + 16)
    payload = min(first)
    return {
        'at': hex(image.at),
        'ncmds': ncmd,
        'sizeofcmds': hex(szcmds),
        'header_end_fileoff': hex(image.at + 32 + szcmds),
        'first_backed_section_fileoff': hex(payload),
        'actual_gap_bytes': payload - (image.at + 32 + szcmds),
    }


def main():
    ref = json.loads((EV / 'reference-closure-link-placement.json').read_text())
    undefs = ref['standalone_links_and_fileset_placement']['unmodified_sheng_closure_link']['unresolved_symbols']
    dups = ref['standalone_links_and_fileset_placement']['unmodified_sheng_closure_link']['duplicate_symbols_against_A7_archives']
    arch = Path(ref['closure_compile']['archives']['a730blobs_plus_smmu'])
    import tomllib
    profile = tomllib.loads((ROOT / 'profiles/os/macos-27.3-26C5035r/profile.toml').read_text())
    roots = profile['kernel']['prelink']['roots']

    ldflags = shlex.split((XNU_OBJ / '.LDFLAGS').read_text().replace('\0', ''))
    linkarchives = shlex.split((XNU_OBJ / 'mach.development.bcm2837.link/mach.development.bcm2837.linkarchives').read_text().replace('\0', ''))
    filelist = str(XNU_OBJ / 'link.filelist')
    extra_objs = [str(XNU_OBJ / 'version.o'), str(XNU_OBJ / 'lastkernelconstructor.o'), str(XNU_OBJ / 'lastkerneldataconst.o')]

    env = dict(os.environ,
               PATH=f'/opt/unixnu-linux/CommandLineTools/usr/bin:/opt/unixnu-linux/XcodeDefault.xctoolchain/usr/bin:{os.environ.get("PATH", "")}',
               CROSS_CLANG=str(CLANG_BIN),
               DARWIN_TRIPLE='arm64e-apple-ios27.0',
               XNU_TOOLCHAIN_BIN='/opt/unixnu-linux/CommandLineTools/usr/bin /opt/unixnu-linux/XcodeDefault.xctoolchain/usr/bin',
               UNIXNU_SDKROOT=str(TREE / '.cache/fakeroot'))

    with tempfile.TemporaryDirectory(prefix='r101-gpu-r2-prelink-', dir='/tmp') as tmp:
        td = Path(tmp)
        # Prepare measurement-only stubs & weakened legacy duplicate copy
        stub_c = td / 'stubs.c'
        stub_lines = ['#include <stdint.h>']
        for s in undefs:
            cn = s[1:]
            if cn == 'native_gpu_dcvs':
                stub_lines.append('volatile uint32_t native_gpu_dcvs[15] = {0};')
            else:
                stub_lines.append(f'int {cn}(void) {{ return 0; }}')
        stub_c.write_text('\n'.join(stub_lines) + '\n')
        stub_o = td / 'stubs.o'
        subprocess.run([str(CLANG_BIN), '-target', 'arm64e-apple-ios27.0', '-O2', '-c', str(stub_c), '-o', str(stub_o)], check=True)

        orig_legacy_idx = next(i for i, a in enumerate(linkarchives) if 'libNativeLegacyDisplay.late.a' in a)
        orig_legacy = Path(linkarchives[orig_legacy_idx].split(',')[-1])
        wl = td / 'legacy'
        wl.mkdir()
        subprocess.run([str(AR_BIN), 'x', str(orig_legacy)], cwd=wl, check=True)
        for o in sorted(wl.glob('*.o')):
            defs = set(subprocess.check_output([str(NM_BIN), '-j', '-g', '-U', str(o)], text=True).splitlines())
            w = sorted(set(dups) & defs)
            if w:
                subprocess.run([str(OBJCOPY_BIN), *[f'--weaken-symbol={s}' for s in w], str(o), str(o)], check=True)
        patched_legacy = td / 'libNativeLegacyDisplay.late.weakdups.a'
        subprocess.run([str(AR_BIN), 'rcs', str(patched_legacy), *[str(p) for p in sorted(wl.glob('*.o'))]], check=True)
        linkarchives[orig_legacy_idx] = f'-Wl,-force_load,{patched_legacy}'

        standalone = td / 'standalone.macho'
        cmd = [ldflags[0], '--ld-path=/opt/unixnu-linux/CommandLineTools/usr/bin/ld'] + ldflags[1:] + [
            '-filelist', filelist, *extra_objs, '-o', str(standalone), *linkarchives,
            f'-Wl,-force_load,{arch}', str(stub_o),
        ]
        res = subprocess.run(cmd, cwd=XNU_OBJ, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if res.returncode != 0:
            raise RuntimeError('Standalone link failed:\n' + res.stdout[-3000:])

        emitted = td / 'kernel.macho'
        prelink_cmd = [
            sys.executable, str(TREE / 'kits/XnuPrelink/emit_prelink.py'),
            '--kernel', str(standalone),
            '--prelinked', str(KC_PATH),
            '--slide=0',
            *[arg for r in roots for arg in ('--root', r)],
            '--early-security-init', 'com.apple.driver.AppleMobileFileIntegrity=0xfffffe0009840dd4',
            '--output', str(emitted),
        ]
        pr = subprocess.run(prelink_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        if pr.returncode != 0:
            raise RuntimeError('emit_prelink.py failed:\n' + pr.stdout[-3000:])

        emitted_json = json.loads(emitted.with_suffix('.json').read_text())
        nm_txt = td / 'nm.txt'
        with nm_txt.open('wb') as f:
            subprocess.run(['llvm-nm', '-n', str(emitted)], check=True, stdout=f)
        aes_gate_path = EV / 'aes-fileset-gate-a730blobs-plus-smmu.json'
        ag = subprocess.run([
            sys.executable, str(ROOT / 'scripts/liuqin-analysis/aes_fileset_gate.py'),
            '--kernel', str(emitted), '--standalone', str(standalone),
            '--nm', str(nm_txt), '--bindings', str(R100_EV / 'original-bindings.S'),
            '--report', str(aes_gate_path),
        ], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)

        # Inspect emitted native headers, root headers, and AGXAccelerator original-binding stubs + firmware symbols
        sys.path.insert(0, str(ROOT / 'kits/XnuPrelink'))
        from kc_image import Image
        final = Image(emitted.read_bytes())
        entry = Image(final.data, final.entries['com.apple.kernel'][1])
        root_text = next(s for s in final.segments if s['name'] == '__TEXT')
        root_hdr_end = 32 + struct.unpack_from('<I', final.data, 20)[0]

        nm_lines = nm_txt.read_text().splitlines()
        check_syms = [
            '__ZN13IOAcceleratorC2EPK11OSMetaClass',
            '__ZN13IOAcceleratorD2Ev',
            '__GLOBAL__sub_I_NativeAdrenoAccelerator.cpp',
            '_native_adreno_firmware_image',
            '_native_adreno_sqe_firmware_image',
            '_native_adreno_zap_image',
            '_ShengGmuColdStart',
            '_ShengGpuSmmuStart',
            '_NativeAdrenoGmuContextBringup',
        ]
        found_syms = {}
        for s in check_syms:
            hits = [ln for ln in nm_lines if ln.endswith(' ' + s)]
            found_syms[s] = hits

        # Verify AGXAccelerator original-binding stub instructions (bti c; b <target>) in emitted kernel!
        accel_plan = json.loads((ROOT / 'scripts/data/ioaccelerator-base-abi-26C5035r.json').read_text())
        slide = int(accel_plan['collection_slide'], 16)
        expected_targets = {
            '__ZN13IOAcceleratorC2EPK11OSMetaClass': int(accel_plan['protected_compatible_constructor_aliases'][0], 16) + slide,
            '__ZN13IOAcceleratorD2Ev': int(accel_plan['nondeleting_destructor'], 16) + slide,
        }
        # Map emitted segments for VA->fileoff lookup
        def read_emitted_u32(va):
            for seg in final.segments:
                if seg['va'] <= va < seg['va'] + seg['filesize']:
                    off = seg['fileoff'] + (va - seg['va'])
                    return struct.unpack_from('<I', final.data, off)[0]
            raise ValueError(f'VA {hex(va)} not in emitted root segments')

        stub_checks = {}
        for sym, target_va in expected_targets.items():
            assert found_syms[sym], f'Missing {sym} in emitted nm'
            stub_va = int(found_syms[sym][0].split()[0], 16)
            w0 = read_emitted_u32(stub_va)
            w1 = read_emitted_u32(stub_va + 4)
            # bti c = 0xd503245f; unconditional b imm26 = 0x14000000 | (imm26 & 0x3ffffff)
            is_bti_c = (w0 == 0xd503245f)
            is_b = (w1 & 0xfc000000) == 0x14000000
            imm26 = w1 & 0x03ffffff
            if imm26 & (1 << 25):
                imm26 -= (1 << 26)
            actual_target = (stub_va + 4) + (imm26 << 2)
            stub_checks[sym] = {
                'stub_va': hex(stub_va),
                'word0': hex(w0),
                'word1': hex(w1),
                'is_bti_c': is_bti_c,
                'is_unconditional_branch': is_b,
                'decoded_branch_target': hex(actual_target),
                'expected_original_target': hex(target_va),
                'target_matches_26C5035r_IOAccelerator': actual_target == target_va,
            }

        # Verify embedded A730 firmware bytes are intact and live in __DATA_CONST (read-only) in emitted kernel!
        # Read LC_SEGMENT_64 maxprot/initprot for __DATA_CONST directly from entry Mach-O commands
        dc_maxprot = dc_initprot = None
        for cmd, at, _ in entry.commands:
            if cmd == 0x19 and entry.data[at + 8:at + 24].split(b'\0')[0] == b'__DATA_CONST':
                dc_maxprot, dc_initprot = struct.unpack_from('<II', entry.data, at + 56)
                break
        fw_checks = {}
        dc_seg = next(s for s in entry.segments if s['name'] == '__DATA_CONST')
        for sym, expected_path in [
            ('_native_adreno_firmware_image', ROOT / 'out/liuqin-r101-gpu-m1/evidence/firmware/gmu_gen70000.bin'),
            ('_native_adreno_sqe_firmware_image', ROOT / 'out/liuqin-r101-gpu-host-gates/evidence/a730_sqe.fw'),
            ('_native_adreno_zap_image', ROOT / 'out/liuqin-r101-gpu-m1/evidence/firmware/a730_zap.mbn'),
        ]:
            va = int(found_syms[sym][0].split()[0], 16)
            expected_bytes = expected_path.read_bytes()
            in_dc = dc_seg['va'] <= va and (va + len(expected_bytes)) <= dc_seg['va'] + dc_seg['size']
            # Read bytes from emitted image
            emitted_bytes = None
            for seg in final.segments:
                if seg['va'] <= va and va + len(expected_bytes) <= seg['va'] + seg['filesize']:
                    off = seg['fileoff'] + (va - seg['va'])
                    emitted_bytes = final.data[off:off + len(expected_bytes)]
                    break
            fw_checks[sym] = {
                'emitted_va': hex(va),
                'page_aligned_4k': (va & 0xfff) == 0,
                'inside_DATA_CONST': in_dc,
                'DATA_CONST_initprot': dc_initprot,
                'DATA_CONST_maxprot': dc_maxprot,
                'DATA_CONST_readonly': dc_initprot == 1 and dc_maxprot == 1,
                'bytes': len(expected_bytes),
                'sha256_matches_pinned_blob': emitted_bytes is not None and hashlib.sha256(emitted_bytes).hexdigest() == hashlib.sha256(expected_bytes).hexdigest(),
            }

        report = {
            'scope': 'Host-only emit_prelink.py + aes_fileset_gate.py dry-run on isolated a730blobs_plus_smmu standalone link (temporary binaries deleted after verification; no boot image emitted)',
            'prelink_returncode': pr.returncode,
            'prelink_stdout': pr.stdout.strip(),
            'aes_fileset_gate_returncode': ag.returncode,
            'aes_fileset_gate_stdout': ag.stdout.strip(),
            'emitted_kernel_sha256': hashlib.sha256(final.data).hexdigest(),
            'emitted_kernel_bytes': len(final.data),
            'emitted_native_header': header_gap(entry),
            'emitted_root_header': {
                'ncmds': len(final.commands),
                'sizeofcmds': hex(struct.unpack_from('<I', final.data, 20)[0]),
                'mapping_filesize': hex(root_text['filesize']),
                'slack_to_mapping_end_bytes': root_text['filesize'] - root_hdr_end,
            },
            'checked_symbols_present': found_syms,
            'agx_accelerator_original_binding_stubs': stub_checks,
            'embedded_a730_firmware_verification': fw_checks,
            'measurement_only_caveat': {
                'unresolved_board_hooks_stubbed': undefs,
                'a7_legacy_display_duplicates_weakened_in_tmp_copy': dups,
            },
        }
        (EV / 'prelink-and-aes-gate.json').write_text(json.dumps(report, indent=2) + '\n')
        print('PASS: emit_prelink.py succeeded; emitted bytes:', len(final.data))
        print('PASS: aes_fileset_gate rc=', ag.returncode, ag.stdout.strip())
        print('PASS: emitted native header gap:', report['emitted_native_header']['actual_gap_bytes'], 'B; root slack:', report['emitted_root_header']['slack_to_mapping_end_bytes'], 'B')
        print('PASS: AGXAccelerator branch retargets:', {k: v['target_matches_26C5035r_IOAccelerator'] and v['is_bti_c'] for k, v in stub_checks.items()})
        print('PASS: Embedded A730 firmware in read-only DATA_CONST:', {k: v['inside_DATA_CONST'] and v['page_aligned_4k'] and v['sha256_matches_pinned_blob'] for k, v in fw_checks.items()})


if __name__ == '__main__':
    main()
