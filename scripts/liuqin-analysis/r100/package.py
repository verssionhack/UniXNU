#!/usr/bin/env python3
"""Package r100a candidate boot image (r99p 8-core SMP + EPSS + GopFramebuffer CPU present + Internal scratch disk)."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import struct
import subprocess
import sys

import tomllib

R = Path(__file__).resolve().parents[3]
W = R / 'out/liuqin-r100-work'
E = W / 'evidence'
D = W / 'device'
WORK = R / 'out/liuqin/macos-27.3-26C5035r/liuqin'
TREE = WORK / 'tree'
R88_ADT = R / 'out/liuqin-r88-work/evidence/candidate/kernel.macho.adt'
R86_APPLE_TRUST = R / 'out/liuqin-r86-work/evidence/r86a/apple-ipsw-trust.bin'
APPLE_TRUST_SHA256 = '002db2e6ee9000c891bad43247bfa9c55ad6d3b2ee62e6c0b9e1965e78926da6'
R71_CDHASH = '702ea6d34a300a91517727bd4c8611f310f68bdc'
PARKD_CDHASH = '85fa9571f12906b13a9e413565c56f4e749a1c88'

TEXT_CAP = 0x1d8000
DATA_CAP = 0x284000
MIN_TEXT_CONST_VMA = 0xfffffff007005900
EXPECTED_MAXVNODES = 66560
SIDECAR_JSON = R / 'out/liuqin-r95-work/evidence/cs4k-sidecar.json'


def sha(path: Path) -> str:
    with path.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def parse_macho_segments(path: Path) -> tuple[dict[str, dict[str, int]], dict[str, int]]:
    hdr = path.read_bytes()[:65536]
    _, _, _, _, ncmds, _, _, _ = struct.unpack_from('<IIIIIIII', hdr, 0)
    off = 32
    segs = {}
    sections = {}
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from('<II', hdr, off)
        if cmd == 0x19:
            name = hdr[off + 8:off + 24].split(b'\x00', 1)[0].decode(errors='replace')
            vmaddr, vmsize, fileoff, filesize = struct.unpack_from('<QQQQ', hdr, off + 24)
            nsects = struct.unpack_from('<I', hdr, off + 64)[0]
            segs[name] = {'vmaddr': vmaddr, 'vmsize': vmsize, 'fileoff': fileoff, 'filesize': filesize}
            for i in range(nsects):
                at = off + 72 + 80 * i
                sname = hdr[at:at + 16].split(b'\x00', 1)[0].decode(errors='replace')
                sva = struct.unpack_from('<Q', hdr, at + 32)[0]
                sections[f'{name},{sname}'] = sva
        off += cmdsize
    return segs, sections


def parse_adt(b: bytes, off: int = 0, path: str = ''):
    props_n, kids_n = struct.unpack_from('<II', b, off)
    off += 8
    props = {}
    for _ in range(props_n):
        k, sz = struct.unpack_from('<32sI', b, off)
        off += 36
        name = k.split(b'\0', 1)[0].decode('latin1')
        val = b[off:off + sz]
        off += sz + (-sz % 4)
        props[name] = val
    nname = props.get('name', b'?').split(b'\0', 1)[0].decode('latin1')
    cur = path + '/' + nname if path else '/'
    res = {cur: props}
    for _ in range(kids_n):
        off, child_res = parse_adt(b, off, cur)
        res.update(child_res)
    return off, res


def verify_adt(adt_bytes: bytes, expected_owned: int) -> dict:
    ref_bytes = R88_ADT.read_bytes()
    off1, ref = parse_adt(ref_bytes)
    off2, cur = parse_adt(adt_bytes)
    assert off1 == len(ref_bytes) and off2 == len(adt_bytes)
    added_nodes = sorted(set(cur) - set(ref))
    removed_nodes = sorted(set(ref) - set(cur))
    assert not added_nodes and not removed_nodes, (added_nodes, removed_nodes)
    sc = json.loads(SIDECAR_JSON.read_text())['signed_metadata']['sidecar_sha256']
    for k in sorted(ref):
        added_props = sorted(set(cur[k]) - set(ref[k]))
        removed_props = sorted(set(ref[k]) - set(cur[k]))
        assert not removed_props, (k, removed_props)
        if k == '//defaults':
            assert added_props == ['kern.maxvnodes'], (k, added_props)
            assert struct.unpack('<I', cur[k]['kern.maxvnodes'])[0] == EXPECTED_MAXVNODES
        elif k == '//chosen':
            assert added_props == ['cs4k-sidecar-sha256'], (k, added_props)
            assert cur[k]['cs4k-sidecar-sha256'].hex() == sc
            assert struct.unpack('<Q', cur[k]['unique-chip-id'])[0] == 0x84750A0B0C0D0001
            assert struct.unpack('<I', cur[k]['chip-id'])[0] == 4
        else:
            assert not added_props, (k, added_props)
        for pk in sorted(ref[k]):
            if pk == 'random-seed':
                assert len(cur[k][pk]) == 256
                continue
            if k == '//chosen' and pk == 'darwinboot-memory-size':
                assert struct.unpack('<Q', cur[k][pk])[0] == expected_owned
                continue
            assert ref[k][pk] == cur[k][pk], (k, pk)
    return {'node_count': len(cur), 'all_other_properties_identical': True}


def build_content_trust(apple_bundle: Path, entries: list[dict], out_dir: Path) -> tuple[Path, dict]:
    tmp = out_dir / '.tmp-trust.bin'
    subprocess.run([
        'python3', str(R / 'scripts/trust-append-module.py'),
        str(apple_bundle), str(tmp),
        *[e['cdhash'] for e in entries],
    ], check=True)
    digest = sha(tmp)
    final_path = out_dir / f'trust-{digest[:12]}.bin'
    shutil.move(str(tmp), str(final_path))
    return final_path, {
        'trust_mode': 'content-addressed',
        'final_bundle': str(final_path),
        'final_bundle_sha256': digest,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--mode', default='r100a')
    ap.add_argument('--seconds', type=int, default=120)
    ap.add_argument('--epss-step', type=int, default=4)
    ap.add_argument('--unit-scale', type=int, default=2)
    args_cli = ap.parse_args()

    source = WORK / 'kernel/kernel.macho'
    assert source.is_file(), f'Missing {source}'
    spec = tomllib.loads((R / 'profiles/os/macos-27.3-26C5035r/profile.toml').read_text())['kernel']['prelink']
    native = TREE / spec['kernel']
    segs, sections = parse_macho_segments(native)
    text_sz = segs['__TEXT']['vmsize']
    data_sz = segs['__DATA']['vmsize']
    text_const_va = sections['__TEXT,__const']
    assert text_sz <= TEXT_CAP, f'__TEXT {text_sz:#x} exceeds cap {TEXT_CAP:#x}'
    assert data_sz <= DATA_CAP, f'__DATA {data_sz:#x} exceeds cap {DATA_CAP:#x}'
    assert text_const_va >= MIN_TEXT_CONST_VMA, (
        f'__TEXT,__const VMA {text_const_va:#x} < {MIN_TEXT_CONST_VMA:#x} (headerpad risk)'
    )

    kbytes = source.read_bytes()
    for marker in (
        b'LIUQIN SCRATCH: published',
        b'LIUQIN EPSS_STEP:',
        b'Native keystore state service',
        b'NativeLegacyDisplay',
        b'offline-legacy-cpu-present',
        b'Physical Interconnect Location',
    ):
        assert marker in kbytes, f'missing kernel marker {marker!r}'

    E.mkdir(parents=True, exist_ok=True)
    for p, name in [
        (native, 'standalone.macho'),
        (source, 'kernel.macho'),
        (WORK / 'kernel/kernel.json', 'kernel.json'),
        (WORK / 'kernel/kernel.map.json', 'kernel.map.json'),
        (TREE / 'scripts/data/native-aes-original-bindings.S', 'original-bindings.S'),
    ]:
        shutil.copy2(p, E / name)

    with (E / 'nm.txt').open('w') as f:
        subprocess.run(['llvm-nm', '-n', str(E / 'kernel.macho')], stdout=f, check=True)
    subprocess.run([
        'python3', str(R / 'scripts/liuqin-analysis/aes_fileset_gate.py'),
        '--kernel', str(E / 'kernel.macho'),
        '--standalone', str(E / 'standalone.macho'),
        '--nm', str(E / 'nm.txt'),
        '--bindings', str(E / 'original-bindings.S'),
        '--report', str(E / 'aes-fileset-gate.json'),
    ], check=True)

    fd = E / 'SILICIUM_UEFI.fd'
    if not fd.is_file():
        r95_fd = R / 'out/liuqin-r95-work/evidence/SILICIUM_UEFI.fd'
        assert r95_fd.is_file(), f'Missing {r95_fd}'
        shutil.copy2(r95_fd, fd)

    assert sha(R86_APPLE_TRUST) == APPLE_TRUST_SHA256
    trust_entries = [
        {'role': 'r71_mount_adapter', 'cdhash': R71_CDHASH},
        {'role': 'r91_parkd', 'cdhash': PARKD_CDHASH},
    ]
    trust_bundle, prov = build_content_trust(R86_APPLE_TRUST, trust_entries, E)

    deny_list = [
        '/usr/libexec/mobileactivationd',
        '/usr/libexec/cryptexd',
        '/usr/libexec/watchdogd',
        '/usr/libexec/fskitd',
        '/usr/sbin/bluetoothd',
        '/usr/sbin/coreaudiod',
        '/usr/libexec/audiomxd',
    ]

    kargs = [
        'liuqin_caches=1',
        'apfs_swcrypto_sbufcount=32',
        'apfs_swcrypto_lbufcount=256',
        'liuqin-data-populate=1',
        'liuqin-data-layout=1',
        'liuqin_el0_access=1',
        'liuqin_spec_ra_off=1',
        'liuqin_n4k_pageable=1',
        'vm_compressor=2',
        'liuqin-mount-adapter=1',
        'liuqin-disable-daemons=1',
        'liuqin_n4k_cdhash_cache=1',
        'exec-stand-in=/private/var/liuqin/parkd',
        'deny-exec-vnode=1',
        'lq_cs4k=1',
        'aks=1',
        'smp=1',
        'armcpu-self-ipi=1',
        f'epss_step={args_cli.epss_step}',
        f'deny-exec={",".join(deny_list)}',
        'offline-mobile-graphics-load=1',
        'offline-legacy-register=1',
        'offline-legacy-gop=1',
        f'offline-legacy-unit-scale={args_cli.unit_scale}',
        'offline-legacy-pm=1',
        'offline-legacy-validate=1',
        'offline-legacy-transfer=1',
        'offline-legacy-cpu-present=1',
        'offline-legacy-phase=4',
    ]

    sys.path.insert(0, str(R / 'scripts'))
    from unixnu import cli, feeds
    feeds.update_submodules = lambda ctx: None

    cli.main([
        'build', 'payload', '-D', str(D),
        '--kernel', str(E / 'kernel.macho'),
        '--unique-chip-id', '0x84750A0B0C0D0001',
        '--owner-trust-cache', str(trust_bundle),
        *sum((['--kernel-arg', x] for x in kargs), []),
    ])

    pj = WORK / 'payload/payload.json'
    j = json.loads(pj.read_text())
    kargs_len = len(j['kernel_args'])
    assert kargs_len <= 1000, f'kernel_args too long ({kargs_len} > 1000): {j["kernel_args"]}'

    adt_bytes = subprocess.run(
        ['mcopy', '-i', str(WORK / 'payload/payload.img'), '::/EFI/UNIXNU/Payloads/kernel.macho.adt', '-'],
        capture_output=True, check=True,
    ).stdout
    adt_diff = verify_adt(adt_bytes, 0x100000000)

    adt_out = E / 'kernel.macho.adt'
    adt_out.write_bytes(adt_bytes)
    j.update(adt_sha256=sha(adt_out), owned_memory_size='0x100000000', payload_sha256=sha(WORK / 'payload/payload.img'))
    pj.write_text(json.dumps(j, indent=2) + '\n')

    subprocess.run(
        ['python3', str(D / 'scripts/wrap-payload-mbr.py'), str(WORK / 'payload/payload.img'), str(WORK / 'payload/payload-mbr.img')],
        check=True,
    )
    cli.main([
        'bootimg', '-D', str(D),
        '--uefi', '/home/kurumin/Codes/Github/uefi-sheng',
        '--fd', str(fd),
        '--dtb', str(D / 'dts/liuqin-cape.dtb'),
        '--ramdisk', str(WORK / 'payload/payload-mbr.img'),
    ])

    cand = E / 'candidate'
    cand.mkdir(exist_ok=True)
    for src_p, name in [
        (pj, 'payload.json'),
        (WORK / 'boot/boot.img', 'boot.img'),
        (WORK / 'boot/boot.json', 'boot.json'),
        (adt_out, 'kernel.macho.adt'),
    ]:
        shutil.copy2(src_p, cand / name)
    shutil.copy2(R / 'scripts/liuqin-analysis/r85/device_runner.py', E / 'device_runner.py')
    shutil.copy2(R / 'scripts/liuqin-analysis/r100/run-r100.py', E / 'run-r100.py')

    report = {
        'status': 'PASS',
        'experiment': args_cli.mode,
        'kernel_segment_sizes': {
            '__TEXT': hex(text_sz),
            '__TEXT_const_vma': hex(text_const_va),
            '__DATA': hex(data_sz),
            '__DATA_cap': hex(DATA_CAP),
        },
        'kernel_args_len': kargs_len,
        'kernel_args': j['kernel_args'],
        'kernel_sha256': sha(E / 'kernel.macho'),
        'boot_sha256': sha(cand / 'boot.img'),
        'adt_diff': adt_diff,
    }
    (E / f'validation-summary-{args_cli.mode}.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
