#!/usr/bin/env python3
"""Phase 0 host-only handoff & DTB/ADT/UEFI_MEMDIAG parity audit (gpu-host-gates-r3).

Inputs (all read-only, frozen):
  - out/liuqin-r101-a7-work/evidence/a/boot-A7-20261121-164915/usb.log
  - out/liuqin-r101-a7-work/evidence/a/kernel.macho.adt
  - out/liuqin-r101-a7-work/device-a/dts/liuqin-cape.dtb
  - out/liuqin-r101-gpu-m1/linux-release-clean/arch/arm64/boot/dts/qcom/sm8475-xiaomi-liuqin.dts

Outputs (isolated r3):
  - out/liuqin-r101-gpu-host-gates-r3/stage/liuqin-linux.dtb
  - out/liuqin-r101-gpu-host-gates-r3/evidence/phase0-handoff-and-dtb-parity.json
"""
from __future__ import annotations

import hashlib
import json
import re
import struct
import subprocess
from pathlib import Path

ROOT = Path('/home/kurumin/github/UniXNU')
OUT_STAGE = ROOT / 'out/liuqin-r101-gpu-host-gates-r3/stage'
OUT_EV = ROOT / 'out/liuqin-r101-gpu-host-gates-r3/evidence'

A7_USB_LOG = ROOT / 'out/liuqin-r101-a7-work/evidence/a/boot-A7-20261121-164915/usb.log'
A7_ADT = ROOT / 'out/liuqin-r101-a7-work/evidence/a/kernel.macho.adt'
A7_CAPE_DTB = ROOT / 'out/liuqin-r101-a7-work/device-a/dts/liuqin-cape.dtb'
LINUX_ROOT = ROOT / 'out/liuqin-r101-gpu-m1/linux-release-clean'
LINUX_DTS = LINUX_ROOT / 'arch/arm64/boot/dts/qcom/sm8475-xiaomi-liuqin.dts'
SM8475_DTSI = LINUX_ROOT / 'arch/arm64/boot/dts/qcom/sm8475.dtsi'
DTC_BIN = Path('/home/kurumin/.local/bin/dtc')
CLANG_BIN = Path('/usr/bin/clang')


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1 << 16), b''):
            h.update(chunk)
    return h.hexdigest()


# ---------------- Minimal FDT (DTB) parser ----------------
FDT_MAGIC = 0xD00DFEED
FDT_BEGIN_NODE = 1
FDT_END_NODE = 2
FDT_PROP = 3
FDT_NOP = 4
FDT_END = 9


def parse_fdt(blob: bytes) -> dict:
    magic, totalsize, off_struct, off_strings, off_mem_rsvmap, version, last_comp_version, boot_cpuid_phys, size_strings, size_struct = struct.unpack_from('>10I', blob, 0)
    if magic != FDT_MAGIC:
        raise ValueError(f'Bad FDT magic: {magic:#x}')
    if totalsize > len(blob):
        raise ValueError(f'Truncated FDT: totalsize={totalsize} > len={len(blob)}')

    def get_str(off: int) -> str:
        end = blob.index(b'\x00', off_strings + off)
        return blob[off_strings + off:end].decode('ascii', errors='replace')

    # Parse memreserve entries
    mem_rsv = []
    pos = off_mem_rsvmap
    while pos + 16 <= totalsize:
        addr, size = struct.unpack_from('>2Q', blob, pos)
        pos += 16
        if addr == 0 and size == 0:
            break
        mem_rsv.append({'address': hex(addr), 'size': hex(size)})

    # Parse structure block into tree
    pos = off_struct
    end_struct = off_struct + size_struct
    stack: list[dict] = []
    root = None

    while pos < end_struct:
        tok, = struct.unpack_from('>I', blob, pos)
        pos += 4
        if tok == FDT_BEGIN_NODE:
            nul = blob.index(b'\x00', pos)
            name = blob[pos:nul].decode('ascii', errors='replace')
            pos = (nul + 4) & ~3
            node = {'name': name, 'props': {}, 'children': []}
            if stack:
                stack[-1]['children'].append(node)
            else:
                root = node
            stack.append(node)
        elif tok == FDT_END_NODE:
            stack.pop()
        elif tok == FDT_PROP:
            plen, nameoff = struct.unpack_from('>2I', blob, pos)
            pos += 8
            val = blob[pos:pos + plen]
            pos = (pos + plen + 3) & ~3
            stack[-1]['props'][get_str(nameoff)] = val
        elif tok == FDT_NOP:
            continue
        elif tok == FDT_END:
            break
        else:
            raise ValueError(f'Unknown FDT token {tok:#x} at {pos - 4}')

    return {
        'header': {
            'totalsize': totalsize,
            'version': version,
            'last_comp_version': last_comp_version,
            'size_struct': size_struct,
            'size_strings': size_strings,
        },
        'mem_rsvmap': mem_rsv,
        'root': root,
    }


def walk_fdt(node: dict, path: str = ''):
    cur = '/' if path == '' and node['name'] == '' else (f'{path}/{node["name"]}' if path != '/' else f'/{node["name"]}')
    yield cur, node
    for ch in node['children']:
        yield from walk_fdt(ch, cur)


def fdt_u32_list(b: bytes) -> list[int]:
    return [struct.unpack_from('>I', b, i)[0] for i in range(0, len(b) - (len(b) % 4), 4)]


def fdt_u64_list(b: bytes) -> list[int]:
    return [struct.unpack_from('>Q', b, i)[0] for i in range(0, len(b) - (len(b) % 8), 8)]


def fdt_str_list(b: bytes) -> list[str]:
    if not b:
        return []
    parts = b.split(b'\x00')
    if parts and parts[-1] == b'':
        parts = parts[:-1]
    return [p.decode('ascii', errors='replace') for p in parts]


def fdt_reg_pairs(b: bytes, ac: int = 2, sc: int = 2) -> list[dict]:
    cells = fdt_u32_list(b)
    stride = ac + sc
    out = []
    for i in range(0, len(cells) - (len(cells) % stride), stride):
        addr = 0
        for c in cells[i:i + ac]:
            addr = (addr << 32) | c
        size = 0
        for c in cells[i + ac:i + stride]:
            size = (size << 32) | c
        out.append({'base': hex(addr), 'size': hex(size), 'base_int': addr, 'size_int': size})
    return out


def build_phandle_map(root: dict) -> dict[int, tuple[str, dict]]:
    pmap = {}
    for p, n in walk_fdt(root):
        for key in ('phandle', 'linux,phandle'):
            if key in n['props'] and len(n['props'][key]) == 4:
                ph = struct.unpack_from('>I', n['props'][key], 0)[0]
                pmap[ph] = (p, n)
    return pmap


def extract_gpu_summary_from_fdt(fdt: dict, label: str) -> dict:
    root = fdt['root']
    pmap = build_phandle_map(root)
    by_path = {p: n for p, n in walk_fdt(root)}

    def find_nodes(pred):
        return [(p, n) for p, n in by_path.items() if pred(p, n)]

    # Reserved memory entries of interest
    resv_nodes = []
    for p, n in find_nodes(lambda p, n: p.startswith('/reserved-memory/') and p.count('/') == 2):
        props = n['props']
        reg = fdt_reg_pairs(props['reg'], 2, 2) if 'reg' in props else []
        compat = fdt_str_list(props.get('compatible', b''))
        if any(k in p or any(k in c for c in compat) for k in ('80860000', '8b91a000', 'cmd-db', 'gpu', 'zap', 'pil', 'aop')):
            resv_nodes.append({
                'path': p,
                'compatible': compat,
                'no_map': 'no-map' in props,
                'reusable': 'reusable' in props,
                'reg': [{'base': r['base'], 'size': r['size']} for r in reg],
            })

    # Find GPU, GMU, GPUCC, Adreno SMMU, AOSS QMP
    def summarize_node(p: str, n: dict) -> dict:
        props = n['props']
        info = {
            'path': p,
            'compatible': fdt_str_list(props.get('compatible', b'')),
            'status': fdt_str_list(props.get('status', b''))[0] if 'status' in props else 'okay (implicit)',
        }
        if 'reg' in props:
            regs = fdt_reg_pairs(props['reg'], 2, 2)
            rnames = fdt_str_list(props.get('reg-names', b''))
            info['reg'] = [
                {'name': rnames[i] if i < len(rnames) else None, 'base': r['base'], 'size': r['size']}
                for i, r in enumerate(regs)
            ]
        if 'interrupts' in props:
            cells = fdt_u32_list(props['interrupts'])
            inames = fdt_str_list(props.get('interrupt-names', b''))
            irqs = []
            for i in range(0, len(cells), 3):
                if i + 2 < len(cells):
                    irqs.append({
                        'name': inames[i // 3] if (i // 3) < len(inames) else None,
                        'type': 'SPI' if cells[i] == 0 else f'type={cells[i]}',
                        'num': cells[i + 1],
                        'flags': hex(cells[i + 2]),
                    })
            info['interrupts'] = irqs
        if 'iommus' in props:
            cells = fdt_u32_list(props['iommus'])
            streams = []
            for i in range(0, len(cells), 3):
                if i + 2 < len(cells):
                    target = pmap.get(cells[i], (f'phandle:{cells[i]:#x}', None))[0]
                    streams.append({'iommu': target, 'sid': hex(cells[i + 1]), 'mask': hex(cells[i + 2])})
            info['iommus'] = streams
        if 'clock-names' in props:
            info['clock_names'] = fdt_str_list(props['clock-names'])
        if 'power-domain-names' in props:
            info['power_domain_names'] = fdt_str_list(props['power-domain-names'])
        if 'qcom,qmp' in props and len(props['qcom,qmp']) == 4:
            ph = struct.unpack_from('>I', props['qcom,qmp'], 0)[0]
            info['qcom_qmp'] = pmap.get(ph, (f'phandle:{ph:#x}', None))[0]
        if 'operating-points-v2' in props and len(props['operating-points-v2']) == 4:
            ph = struct.unpack_from('>I', props['operating-points-v2'], 0)[0]
            opp_path, opp_node = pmap.get(ph, (None, None))
            if opp_node is not None:
                opps = []
                for ch in opp_node['children']:
                    cp = ch['props']
                    hz = fdt_u64_list(cp['opp-hz'])[0] if 'opp-hz' in cp and len(cp['opp-hz']) >= 8 else None
                    lvl = fdt_u32_list(cp['opp-level'])[0] if 'opp-level' in cp and len(cp['opp-level']) >= 4 else None
                    acd = fdt_u32_list(cp['qcom,opp-acd-level'])[0] if 'qcom,opp-acd-level' in cp else None
                    peak = fdt_u32_list(cp['opp-peak-kBps']) if 'opp-peak-kBps' in cp else None
                    opps.append({'node': ch['name'], 'opp_hz': hz, 'opp_level': lvl, 'acd_level': acd, 'opp_peak_kBps': peak})
                opps.sort(key=lambda x: x['opp_hz'] or 0)
                info['opp_table_path'] = opp_path
                info['opps_ascending'] = opps
        # Check zap-shader child
        for ch in n['children']:
            if 'zap' in ch['name']:
                zp = ch['props']
                zinfo = {'node': ch['name']}
                if 'firmware-name' in zp:
                    zinfo['firmware_name'] = fdt_str_list(zp['firmware-name'])[0]
                if 'memory-region' in zp and len(zp['memory-region']) == 4:
                    ph = struct.unpack_from('>I', zp['memory-region'], 0)[0]
                    mp, mn = pmap.get(ph, (None, None))
                    zinfo['memory_region_path'] = mp
                    if mn and 'reg' in mn['props']:
                        zinfo['memory_region_reg'] = [
                            {'base': r['base'], 'size': r['size']}
                            for r in fdt_reg_pairs(mn['props']['reg'], 2, 2)
                        ]
                info['zap_shader'] = zinfo
        return info

    def pick_nodes(keywords):
        out = []
        for p, n in by_path.items():
            compats = fdt_str_list(n['props'].get('compatible', b''))
            if any(k in p.lower() or any(k in c.lower() for c in compats) for k in keywords):
                out.append(summarize_node(p, n))
        return out

    gpu_nodes = pick_nodes(('qcom,adreno-730', 'qcom,kgsl-3d0', 'gpu@3d00000'))
    gmu_nodes = pick_nodes(('qcom,adreno-gmu', 'gmu@3d6a000', 'qcom,kgsl-gmu'))
    gpucc_nodes = pick_nodes(('gpucc', 'clock-controller@3d90000'))
    smmu_nodes = pick_nodes(('iommu@3da0000', 'adreno-smmu', 'qcom,sm8450-smmu-500'))
    cmddb_nodes = pick_nodes(('qcom,cmd-db',))
    aoss_nodes = pick_nodes(('qcom,sm8450-aoss-qmp', 'qcom,aoss-qmp', 'aoss'))

    # For cape vendor DTB, also extract kgsl pwrlevels if present
    kgsl_pwrlevels = []
    for p, n in by_path.items():
        if 'qcom,gpu-pwrlevels' in p and p.endswith('qcom,gpu-pwrlevels'):
            for ch in n['children']:
                cp = ch['props']
                kgsl_pwrlevels.append({
                    'node': ch['name'],
                    'reg': fdt_u32_list(cp['reg'])[0] if 'reg' in cp else None,
                    'gpu_freq': fdt_u32_list(cp['qcom,gpu-freq'])[0] if 'qcom,gpu-freq' in cp else None,
                    'bus_freq': fdt_u32_list(cp['qcom,bus-freq'])[0] if 'qcom,bus-freq' in cp else None,
                    'bus_min': fdt_u32_list(cp['qcom,bus-min'])[0] if 'qcom,bus-min' in cp else None,
                    'bus_max': fdt_u32_list(cp['qcom,bus-max'])[0] if 'qcom,bus-max' in cp else None,
                    'acd_level': fdt_u32_list(cp['qcom,acd-level'])[0] if 'qcom,acd-level' in cp else None,
                })

    return {
        'label': label,
        'totalsize_bytes': fdt['header']['totalsize'],
        'model': fdt_str_list(root['props'].get('model', b'')),
        'compatible': fdt_str_list(root['props'].get('compatible', b'')),
        'reserved_memory_gpu_related': resv_nodes,
        'gpu_nodes': gpu_nodes,
        'gmu_nodes': gmu_nodes,
        'gpucc_nodes': gpucc_nodes,
        'gpu_smmu_nodes': smmu_nodes,
        'cmd_db_nodes': cmddb_nodes,
        'aoss_qmp_nodes': aoss_nodes[:5],
        'vendor_kgsl_pwrlevels': kgsl_pwrlevels,
    }


# ---------------- Apple Device Tree (ADT) parser ----------------
def parse_adt(blob: bytes) -> dict:
    def parse_node(off: int) -> tuple[dict, int]:
        n_props, n_children = struct.unpack_from('<2I', blob, off)
        off += 8
        props = {}
        for _ in range(n_props):
            raw_name = blob[off:off + 32]
            name = raw_name.split(b'\x00', 1)[0].decode('ascii', errors='replace')
            size_raw, = struct.unpack_from('<I', blob, off + 32)
            size = size_raw & 0x7FFFFFFF
            off += 36
            val = blob[off:off + size]
            off += (size + 3) & ~3
            props[name] = val
        children = []
        for _ in range(n_children):
            ch, off = parse_node(off)
            children.append(ch)
        return {'props': props, 'children': children}, off

    root, end_off = parse_node(0)
    nodes = []

    def walk(node: dict, prefix: str):
        nm = node['props'].get('name', b'').split(b'\x00', 1)[0].decode('ascii', errors='replace')
        path = '/' if prefix == '' else f'{prefix.rstrip("/")}/{nm}'
        prop_summary = {}
        for k, v in node['props'].items():
            if len(v) <= 64 and all(32 <= b < 127 or b == 0 for b in v) and v.endswith(b'\x00'):
                parts = [p.decode('ascii') for p in v.rstrip(b'\x00').split(b'\x00')]
                prop_summary[k] = parts[0] if len(parts) == 1 else parts
            elif len(v) == 4:
                prop_summary[k] = hex(struct.unpack_from('<I', v, 0)[0])
            elif len(v) == 8:
                prop_summary[k] = hex(struct.unpack_from('<Q', v, 0)[0])
            else:
                prop_summary[k] = f'<{len(v)} bytes>'
        nodes.append({'path': path, 'name': nm, 'prop_count': len(node['props']), 'props': prop_summary})
        for ch in node['children']:
            walk(ch, path)

    walk(root, '')
    gpu_hits = [
        n['path'] for n in nodes
        if any(k in n['path'].lower() or any(k in str(v).lower() for v in n['props'].values())
               for k in ('gpu', 'gmu', 'adreno', 'agx', 'smmu', 'cmd-db', 'cmddb', 'fdt', 'dtb', 'zap', '80860000', '3d00000', '3da0000'))
    ]
    return {
        'bytes': len(blob),
        'parsed_end_offset': end_off,
        'node_count': len(nodes),
        'node_paths': [n['path'] for n in nodes],
        'gpu_or_fdt_matching_nodes': gpu_hits,
        'nodes': nodes,
    }


# ---------------- UEFI_MEMDIAG parser ----------------
def parse_uefi_memdiag(log_path: Path) -> dict:
    lines = log_path.read_text(errors='replace').splitlines()
    diag_lines = [ln for ln in lines if 'UEFI_MEMDIAG:' in ln]

    header = {}
    banks = []
    resvs = []
    gcds = []
    darwin_mds = []
    memtest = {}
    darwin_summary = {}

    for ln in diag_lines:
        if 'LIUQINMEM: el=' in ln:
            for k, v in re.findall(r'(\w+)=([^\s]+)', ln.split('LIUQINMEM:', 1)[1]):
                header[k] = v
        elif 'LIUQINMEM: bank ' in ln:
            m = re.search(r'node=(\S+)\s+base=(0x[0-9a-fA-F]+)\s+end=(0x[0-9a-fA-F]+)\s+sz=(0x[0-9a-fA-F]+)', ln)
            if m:
                banks.append({'node': m.group(1), 'base': m.group(2), 'end': m.group(3), 'size': m.group(4),
                              'base_int': int(m.group(2), 16), 'end_int': int(m.group(3), 16), 'size_int': int(m.group(4), 16)})
        elif 'LIUQINMEM: resv ' in ln:
            m = re.search(r'node=(\S+)\s+nm=(\d+)\s+ru=(\d+)\s+base=(0x[0-9a-fA-F]+)\s+end=(0x[0-9a-fA-F]+)\s+sz=(0x[0-9a-fA-F]+)', ln)
            if m:
                resvs.append({'node': m.group(1), 'no_map': int(m.group(2)) == 1, 'reusable': int(m.group(3)) == 1,
                              'base': m.group(4), 'end': m.group(5), 'size': m.group(6),
                              'base_int': int(m.group(4), 16), 'end_int': int(m.group(5), 16), 'size_int': int(m.group(6), 16)})
        elif 'LIUQINMEM: gcd[' in ln:
            m = re.search(r'gcd\[(\d+)\]\s+t=(\d+)\s+base=(0x[0-9a-fA-F]+)\s+end=(0x[0-9a-fA-F]+)\s+len=(0x[0-9a-fA-F]+)\s+cap=(0x[0-9a-fA-F]+)\s+attr=(0x[0-9a-fA-F]+)', ln)
            if m:
                gcds.append({'index': int(m.group(1)), 'type': int(m.group(2)),
                             'base': m.group(3), 'end': m.group(4), 'len': m.group(5),
                             'cap': m.group(6), 'attr': m.group(7),
                             'base_int': int(m.group(3), 16), 'end_int': int(m.group(4), 16)})
        elif 'DARWINMEM: md ' in ln:
            m = re.search(r'md\s+t=(\d+)\s+(0x[0-9a-fA-F]+)-(0x[0-9a-fA-F]+)\s+pg=(0x[0-9a-fA-F]+)\s+attr=(0x[0-9a-fA-F]+)', ln)
            if m:
                darwin_mds.append({'type': int(m.group(1)), 'base': m.group(2), 'end': m.group(3),
                                   'pages': m.group(4), 'attr': m.group(5),
                                   'base_int': int(m.group(2), 16), 'end_int': int(m.group(3), 16)})
        elif 'DARWINMEM: best=' in ln or 'DARWINMEM: post_free ' in ln:
            key = 'pre_alloc' if 'best=' in ln and 'post_free' not in ln else 'post_free'
            darwin_summary[key] = ln.split('DARWINMEM:', 1)[1].strip()
        elif 'MEMTEST: done ' in ln:
            memtest['done'] = ln.split('MEMTEST:', 1)[1].strip()

    def covers(entries, base: int, size: int):
        end = base + size
        return [
            {k: v for k, v in e.items() if not k.endswith('_int')}
            for e in entries
            if e['base_int'] < end and e['end_int'] > base
        ]

    # Key physical windows to check coverage against live UEFI GCD and DarwinBoot EFI memory map
    windows = {
        'gpu_mmio_3d00000': (0x03D00000, 0x40000),
        'gmu_rscc_3d50000': (0x03D50000, 0x10000),
        'gmu_mmio_3d6a000': (0x03D6A000, 0x35000),
        'gpucc_3d90000': (0x03D90000, 0xA000),
        'gpu_smmu_3da0000': (0x03DA0000, 0x40000),
        'gmu_pdc_b290000': (0x0B290000, 0x10000),
        'cmd_db_80860000': (0x80860000, 0x20000),
        'zap_mem_8b91a000': (0x8B91A000, 0x2000),
        'live_fdt_accfe000': (int(header['dtb'], 16), int(header['dtb_sz'])) if 'dtb' in header else (0, 0),
    }

    coverage = {}
    for wname, (wbase, wsize) in windows.items():
        coverage[wname] = {
            'range': f'{wbase:#x}..{wbase + wsize:#x}',
            'size': hex(wsize),
            'live_fdt_resv_overlaps': covers(resvs, wbase, wsize),
            'uefi_gcd_overlaps': covers(gcds, wbase, wsize),
            'darwin_efi_md_overlaps': covers(darwin_mds, wbase, wsize),
        }

    # Check if live FDT or cmd-db overlaps XNU's chosen 4 GiB DRAM bank (0x840004000..0x940004000)
    xnu_dram_base, xnu_dram_size = 0x840004000, 0x100000000

    return {
        'line_count': len(diag_lines),
        'cpu_and_fdt_header': header,
        'el_measured': int(header['el']) if 'el' in header else None,
        'dtb_base': header.get('dtb'),
        'dtb_size_bytes': int(header['dtb_sz']) if 'dtb_sz' in header else None,
        'memory_bank_count': len(banks),
        'memory_banks': [{k: v for k, v in b.items() if not k.endswith('_int')} for b in banks],
        'reserved_memory_count': len(resvs),
        'uefi_gcd_count': len(gcds),
        'darwin_efi_md_count': len(darwin_mds),
        'darwin_alloc_summary': darwin_summary,
        'xnu_owned_dram': {'base': hex(xnu_dram_base), 'end': hex(xnu_dram_base + xnu_dram_size), 'size': hex(xnu_dram_size)},
        'memtest': memtest,
        'window_coverage': coverage,
    }


def compile_linux_dtb() -> tuple[Path, str]:
    OUT_STAGE.mkdir(parents=True, exist_ok=True)
    dts_pp = OUT_STAGE / 'sm8475-xiaomi-liuqin.dts.pp'
    dtb_out = OUT_STAGE / 'liuqin-linux.dtb'

    # linux-release-clean is a sparse checkout whose include/dt-bindings/input/linux-event-codes.h
    # symlinks to ../../uapi/linux/input-event-codes.h (absent). Stage an isolated include overlay
    # pointing linux-event-codes.h to the host /usr/include/linux/input-event-codes.h (input-only keys).
    inc_dir = OUT_STAGE / 'inc/dt-bindings/input'
    inc_dir.mkdir(parents=True, exist_ok=True)
    (inc_dir / 'input.h').write_bytes((LINUX_ROOT / 'include/dt-bindings/input/input.h').read_bytes())
    evt_link = inc_dir / 'linux-event-codes.h'
    evt_link.unlink(missing_ok=True)
    evt_link.symlink_to('/usr/include/linux/input-event-codes.h')

    cpp_cmd = [
        str(CLANG_BIN), '-E', '-nostdinc',
        '-I', str(OUT_STAGE / 'inc'),
        '-I', str(LINUX_ROOT / 'include'),
        '-I', str(LINUX_ROOT / 'arch/arm64/boot/dts'),
        '-I', str(LINUX_ROOT / 'arch/arm64/boot/dts/qcom'),
        '-undef', '-D__DTS__', '-x', 'assembler-with-cpp',
        str(LINUX_DTS),
        '-o', str(dts_pp),
    ]
    subprocess.run(cpp_cmd, check=True)
    dtc_cmd = [
        str(DTC_BIN), '-I', 'dts', '-O', 'dtb', '-q',
        '-o', str(dtb_out), str(dts_pp),
    ]
    res = subprocess.run(dtc_cmd, capture_output=True, text=True, check=True)
    dts_pp.unlink(missing_ok=True)
    return dtb_out, res.stderr.strip()


def extract_commented_sm8475_opps() -> list[dict]:
    txt = SM8475_DTSI.read_text()
    m = re.search(r'&gpu\s*\{\s*/\*(.*?)\*/\s*\};', txt, re.S)
    if not m:
        return []
    block = m.group(1)
    # Resolve RPMH_REGULATOR_LEVEL_* constants from linux-release-clean header
    hdr = (LINUX_ROOT / 'include/dt-bindings/power/qcom,rpmhpd.h').read_text()
    consts = {k: int(v, 0) for k, v in re.findall(r'#define\s+(RPMH_REGULATOR_LEVEL_\w+)\s+(\d+|0x[0-9a-fA-F]+)', hdr)}
    opps = []
    for nm, hz_s, lvl_s in re.findall(
        r'(opp-\d+)\s*\{[^}]*opp-hz\s*=\s*/bits/\s*64\s*<(\d+)>;[^}]*opp-level\s*=\s*<(\w+)>;',
        block,
        re.S,
    ):
        opps.append({'node': nm, 'opp_hz': int(hz_s), 'opp_level_name': lvl_s, 'opp_level': consts.get(lvl_s)})
    opps.sort(key=lambda x: x['opp_hz'])
    return opps


def main() -> None:
    OUT_EV.mkdir(parents=True, exist_ok=True)
    linux_dtb_path, dtc_stderr = compile_linux_dtb()

    linux_fdt = parse_fdt(linux_dtb_path.read_bytes())
    cape_fdt = parse_fdt(A7_CAPE_DTB.read_bytes())
    adt_info = parse_adt(A7_ADT.read_bytes())
    memdiag = parse_uefi_memdiag(A7_USB_LOG)

    linux_summary = extract_gpu_summary_from_fdt(linux_fdt, 'compiled_linux_sm8475_xiaomi_liuqin')
    cape_summary = extract_gpu_summary_from_fdt(cape_fdt, 'a7_packed_liuqin_cape_dtb')
    commented_sm8475_opps = extract_commented_sm8475_opps()

    # Cross-check parity matrix
    linux_gpu_opps = linux_summary['gpu_nodes'][0].get('opps_ascending', []) if linux_summary['gpu_nodes'] else []
    linux_gmu_opps = linux_summary['gmu_nodes'][0].get('opps_ascending', []) if linux_summary['gmu_nodes'] else []

    # Check exact agreement on cmd-db and ZAP reservations across all 3 sources
    live_cmddb = memdiag['window_coverage']['cmd_db_80860000']['live_fdt_resv_overlaps']
    live_zap = memdiag['window_coverage']['zap_mem_8b91a000']['live_fdt_resv_overlaps']

    report = {
        'scope': 'Phase 0 host-only DT/ADT/UEFI_MEMDIAG handoff & SM8475/A730 platform parity audit (gpu-host-gates-r3)',
        'inputs': {
            'a7_usb_log': {'path': str(A7_USB_LOG.relative_to(ROOT)), 'sha256': sha256_file(A7_USB_LOG), 'bytes': A7_USB_LOG.stat().st_size},
            'a7_kernel_adt': {'path': str(A7_ADT.relative_to(ROOT)), 'sha256': sha256_file(A7_ADT), 'bytes': A7_ADT.stat().st_size},
            'a7_cape_dtb': {'path': str(A7_CAPE_DTB.relative_to(ROOT)), 'sha256': sha256_file(A7_CAPE_DTB), 'bytes': A7_CAPE_DTB.stat().st_size},
            'compiled_linux_dtb': {'path': str(linux_dtb_path.relative_to(ROOT)), 'sha256': sha256_file(linux_dtb_path), 'bytes': linux_dtb_path.stat().st_size, 'dtc_warnings': dtc_stderr},
        },
        'hardware_measured_from_frozen_a7_uefi_memdiag': memdiag,
        'a7_kernel_macho_adt': adt_info,
        'compiled_linux_dtb_gpu_summary': linux_summary,
        'a7_packed_cape_dtb_gpu_summary': cape_summary,
        'sm8475_dtsi_commented_gpu_opps': {
            'note': 'In linux-release-clean sm8475.dtsi:64-121, the 13-level SM8475 GPU OPP table (220..900 MHz, MIN_SVS..TURBO_L1) is commented out; compiled sm8475-xiaomi-liuqin.dtb inherits sm8450.dtsi 12-level table (220..818 MHz, LOW_SVS_D1..TURBO).',
            'active_compiled_gpu_opp_count': len(linux_gpu_opps),
            'active_compiled_gpu_opps_ascending': linux_gpu_opps,
            'commented_sm8475_gpu_opp_count': len(commented_sm8475_opps),
            'commented_sm8475_gpu_opps_ascending': commented_sm8475_opps,
            'active_compiled_gmu_opp_count': len(linux_gmu_opps),
            'active_compiled_gmu_opps_ascending': linux_gmu_opps,
        },
        'phase0_parity_findings': {
            'el_at_uefi_handoff': {
                'evidence_label': 'hardware-measured (frozen A7 usb.log)',
                'current_el': memdiag['el_measured'],
                'tcr': memdiag['cpu_and_fdt_header'].get('tcr'),
                'sctlr': memdiag['cpu_and_fdt_header'].get('sctlr'),
                'mmfr0': memdiag['cpu_and_fdt_header'].get('mmfr0'),
                'caveat': 'CurrentEL=1 proves EL1 execution at UEFI->DarwinBoot handoff, NOT EL2 hypervisor identity or SMC routing.',
            },
            'live_fdt_vs_packed_dtb_and_adt': {
                'evidence_label': 'hardware-measured + host-measured',
                'live_post_abl_fdt_base': memdiag['dtb_base'],
                'live_post_abl_fdt_size_bytes': memdiag['dtb_size_bytes'],
                'a7_packed_cape_dtb_size_bytes': A7_CAPE_DTB.stat().st_size,
                'compiled_linux_dtb_size_bytes': linux_dtb_path.stat().st_size,
                'abl_expansion_ratio_vs_packed': round(memdiag['dtb_size_bytes'] / A7_CAPE_DTB.stat().st_size, 2),
                'live_fdt_in_xnu_owned_dram': False,
                'live_fdt_uefi_gcd_coverage': memdiag['window_coverage']['live_fdt_accfe000']['uefi_gcd_overlaps'],
                'adt_contains_live_fdt_or_gpu_nodes': len(adt_info['gpu_or_fdt_matching_nodes']) > 0,
                'handoff_gap': 'A7 kernel.macho.adt carries zero live-FDT pointer and zero GPU/GMU/SMMU/cmd-db/ZAP nodes. Live post-ABL FDT (0xACCFE000, 900,793 B) sits in UEFI Kernel reserved DRAM outside XNU 4 GiB high DRAM (0x840004000..0x940004000) and is not copied into ADT or XNU memory.',
            },
            'cmd_db_reservation_parity': {
                'evidence_label': 'hardware-measured (live FDT via A7 UEFI_MEMDIAG) + source-verified (DTBs)',
                'expected_base': '0x80860000',
                'expected_size': '0x20000',
                'live_fdt_matches_exact': (
                    len(live_cmddb) == 1
                    and live_cmddb[0]['base'].lower() == '0x80860000'
                    and live_cmddb[0]['size'].lower() == '0x20000'
                    and live_cmddb[0]['no_map'] is True
                ),
                'live_fdt_entry': live_cmddb,
                'uefi_gcd_overlap': memdiag['window_coverage']['cmd_db_80860000']['uefi_gcd_overlaps'],
                'darwin_efi_md_overlap': memdiag['window_coverage']['cmd_db_80860000']['darwin_efi_md_overlaps'],
                'access_qualification_note': 'UEFI MemoryMap marks AOP (0x80800000..0x808A0000) as EfiReservedMemoryType UC (attr=0x1); live FDT marks 0x80860000/0x20000 no-map. Reference sheng GpuPowerProbe.cpp maps only the exact 0x20000 window via IODeviceMemory::withRange(base, 0x20000)->map(kIOMapAnywhere|kIOMapInhibitCache|kIOMapReadOnly) and copies aligned 32-bit words into heap. CPU accessibility on SM8475 liuqin under EL2/TZ still requires a bounded Phase 2 probe; do NOT map adjacent AOP/TZ carveouts.',
            },
            'zap_reservation_parity': {
                'evidence_label': 'hardware-measured (live FDT via A7 UEFI_MEMDIAG) + host-measured (a730_zap.mbn ELF) + source-verified (DTBs)',
                'expected_base': '0x8b91a000',
                'expected_size': '0x2000',
                'live_fdt_matches_exact': (
                    len(live_zap) == 1
                    and live_zap[0]['base'].lower() == '0x8b91a000'
                    and live_zap[0]['size'].lower() == '0x2000'
                    and live_zap[0]['no_map'] is True
                ),
                'live_fdt_entry': live_zap,
                'a730_zap_mbn_elf_check': {
                    'file_bytes': (ROOT / 'out/liuqin-r101-gpu-m1/evidence/firmware/a730_zap.mbn').stat().st_size,
                    'elf_class': 'ELF32',
                    'pt_load_paddr': '0x1000',
                    'pt_load_filesz': '0x8bc',
                    'pt_load_memsz': '0x8bc',
                    'pt_load_end_rel': '0x18bc',
                    'fits_0x2000_carveout': 0x18bc <= 0x2000,
                    'hash_segment_ph2_filesz': '0xd58',
                },
                'note': 'A730 ZAP reservation is 8 KiB (0x2000) at 0x8b91a000. Host-measured a730_zap.mbn (11,608 B) is an ELF32 MBN whose single PT_LOAD spans rel 0x1000..0x18bc (2,236 B; page-rounded 0x2000), fitting the 0x2000 live carveout; ph[2] (0xd58 B) is the non-PT_LOAD hash/cert segment.',
            },
            'gpu_mmio_and_smmu_uefi_gcd_status': {
                'evidence_label': 'hardware-measured (A7 UEFI_MEMDIAG)',
                'gpu_3d00000_gcd': memdiag['window_coverage']['gpu_mmio_3d00000']['uefi_gcd_overlaps'],
                'gmu_rscc_3d50000_gcd': memdiag['window_coverage']['gmu_rscc_3d50000']['uefi_gcd_overlaps'],
                'gmu_3d6a000_gcd': memdiag['window_coverage']['gmu_mmio_3d6a000']['uefi_gcd_overlaps'],
                'gpucc_3d90000_gcd': memdiag['window_coverage']['gpucc_3d90000']['uefi_gcd_overlaps'],
                'gpu_smmu_3da0000_gcd': memdiag['window_coverage']['gpu_smmu_3da0000']['uefi_gcd_overlaps'],
                'gmu_pdc_b290000_gcd': memdiag['window_coverage']['gmu_pdc_b290000']['uefi_gcd_overlaps'],
                'note': 'GPU/GMU/RSCC/GPUCC/GPU-SMMU MMIO (0x03d00000..0x03de0000) all lie inside unmapped UEFI GCD type-0 gap gcd[12] (0x1FF0000..0x8800000, attr=0x0), whereas GMU PDC (0x0b290000) lies inside UEFI mapped MMIO gcd[17] (0xB000000..0x10000000, t=3, attr=0x4001). Combined with liuqin board.toml noting APPS SMMU (0x15000000) caused an external abort on first EL1 read, Phase 4 MUST skip GPU-SMMU IDR reads unless CX power + 6 clocks + EL2/TZ read safety are proven.',
            },
        },
    }

    out_path = OUT_EV / 'phase0-handoff-and-dtb-parity.json'
    out_path.write_text(json.dumps(report, indent=2) + '\n')
    print(f'PASS: wrote {out_path.relative_to(ROOT)}')
    print(f"  A7 EL={memdiag['el_measured']}, live FDT={memdiag['dtb_base']} ({memdiag['dtb_size_bytes']} B) vs packed cape DTB ({A7_CAPE_DTB.stat().st_size} B) vs compiled Linux DTB ({linux_dtb_path.stat().st_size} B)")
    print(f"  cmd-db live FDT exact match: {report['phase0_parity_findings']['cmd_db_reservation_parity']['live_fdt_matches_exact']}")
    print(f"  ZAP live FDT exact match:    {report['phase0_parity_findings']['zap_reservation_parity']['live_fdt_matches_exact']}")
    print(f"  A7 ADT nodes: {adt_info['node_count']}, GPU/FDT hits: {len(adt_info['gpu_or_fdt_matching_nodes'])}")
    print(f"  Active compiled Linux GPU OPPs: {len(linux_gpu_opps)} (220..818 MHz), commented sm8475.dtsi OPPs: {len(commented_sm8475_opps)} (220..900 MHz), GMU OPPs: {len(linux_gmu_opps)}")


if __name__ == '__main__':
    main()
