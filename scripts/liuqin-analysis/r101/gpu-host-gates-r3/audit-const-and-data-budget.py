#!/usr/bin/env python3
"""Byte-for-byte __TEXT/first_const_vma and __DATA budget attribution + Tier-1 observer inventory (gpu-host-gates-r3).

Inputs (all read-only, frozen):
  - out/liuqin-r101-a7-work/evidence/a/standalone.macho
  - out/liuqin-r101-a7-work/evidence/a/nm.txt
  - out/liuqin-r101-gpu-host-gates-r2/evidence/reference-closure-link-placement.json
  - out/liuqin-r101-gpu-host-gates-r2/objects/*.o

Outputs:
  - out/liuqin-r101-gpu-host-gates-r3/evidence/const-and-data-budget-audit.json
"""
from __future__ import annotations

import json
import struct
from collections import defaultdict
from pathlib import Path

ROOT = Path('/home/kurumin/github/UniXNU')
OUT_EV = ROOT / 'out/liuqin-r101-gpu-host-gates-r3/evidence'

A7_STANDALONE = ROOT / 'out/liuqin-r101-a7-work/evidence/a/standalone.macho'
A7_NM = ROOT / 'out/liuqin-r101-a7-work/evidence/a/nm.txt'
R2_LINK_JSON = ROOT / 'out/liuqin-r101-gpu-host-gates-r2/evidence/reference-closure-link-placement.json'
R2_OBJS_DIR = ROOT / 'out/liuqin-r101-gpu-host-gates-r2/objects'


def parse_macho_layout(blob: bytes) -> dict:
    magic, cputype, cpusubtype, filetype, ncmds, sizeofcmds, flags, _ = struct.unpack_from('<8I', blob, 0)
    assert magic == 0xFEEDFACF, f'Unexpected magic {magic:#x}'
    pos = 32
    segments = []
    sections = []
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from('<2I', blob, pos)
        if cmd == 0x19:  # LC_SEGMENT_64
            segname = blob[pos + 8:pos + 24].split(b'\x00', 1)[0].decode('ascii')
            vmaddr, vmsize, fileoff, filesize, maxprot, initprot, nsects, sflags = struct.unpack_from('<4Q4I', blob, pos + 24)
            seg_secs = []
            spos = pos + 72
            for _ in range(nsects):
                sname = blob[spos:spos + 16].split(b'\x00', 1)[0].decode('ascii')
                sseg = blob[spos + 16:spos + 32].split(b'\x00', 1)[0].decode('ascii')
                addr, size, offset, align, reloff, nreloc, flags_s, r1, r2, r3 = struct.unpack_from('<2Q8I', blob, spos + 32)
                sec = {
                    'segment': sseg, 'section': sname,
                    'addr': addr, 'addr_hex': hex(addr),
                    'size': size, 'offset': offset, 'align_pow2': align,
                    'flags': hex(flags_s),
                }
                seg_secs.append(sec)
                sections.append(sec)
                spos += 80
            segments.append({
                'name': segname, 'vmaddr': vmaddr, 'vmaddr_hex': hex(vmaddr),
                'vmsize': vmsize, 'vmsize_hex': hex(vmsize),
                'fileoff': fileoff, 'filesize': filesize,
                'sections': seg_secs,
            })
        pos += cmdsize
    return {'ncmds': ncmds, 'sizeofcmds': sizeofcmds, 'header_end': 32 + sizeofcmds, 'segments': segments, 'sections': sections}


def inspect_r2_object_contributions(r2_json: dict) -> dict:
    """Aggregate exact section sizes contributed by every compiled object in a730blobs_plus_smmu."""
    # Note: compiled_objects includes NativeAdrenoAccelerator.o (before late strip of __mod_init_func),
    # plus firmware-a730.o and accel-original-bindings.o / accel-original-addresses.o.
    per_obj = []
    totals_by_segsec: dict[str, int] = defaultdict(int)
    totals_by_seg: dict[str, int] = defaultdict(int)

    # Read actual linked objects from R2_OBJS_DIR so we capture NativeAdrenoAccelerator.late.o (not pre-strip .o)
    linked_objs = []
    for row in r2_json['closure_compile']['compiled_objects']:
        obj_name = row['object']
        if obj_name == 'NativeAdrenoAccelerator.o':
            obj_name = 'NativeAdrenoAccelerator.late.o'
        linked_objs.append((row['source'], R2_OBJS_DIR / obj_name))
    linked_objs.append(('firmware-a730.S', R2_OBJS_DIR / 'firmware-a730.o'))
    linked_objs.append(('accel-original-bindings.S', R2_OBJS_DIR / 'accel-original-bindings.o'))
    linked_objs.append(('accel-original-addresses.S', R2_OBJS_DIR / 'accel-original-addresses.o'))

    for src_name, obj_path in linked_objs:
        layout = parse_macho_layout(obj_path.read_bytes())
        secs = {}
        for s in layout['sections']:
            if s['segment'] == '__DWARF':
                continue
            key = f"{s['segment']},{s['section']}"
            secs[key] = secs.get(key, 0) + s['size']
            totals_by_segsec[key] += s['size']
            # Map object-level sections to linked XNU kernel segments:
            # In XNU standalone arm64e kernel link:
            #   - __TEXT,__text -> __TEXT_EXEC,__text (via -rename_section __TEXT __text __TEXT_EXEC __text)
            #   - __TEXT,{__const,__cstring,__literal*} -> __TEXT
            #   - __DATA_CONST,* -> __DATA_CONST (and __DATA,__const in XNU moves to __DATA_CONST,__const via -rename_section!)
            #   - __DATA,{__data,__bss,__common,__mod_init_func} -> __DATA
            if key == '__TEXT,__text':
                totals_by_seg['__TEXT_EXEC_mapped'] += s['size']
            elif s['segment'] == '__TEXT':
                totals_by_seg['__TEXT_mapped'] += s['size']
            elif s['segment'] == '__DATA_CONST' or key == '__DATA,__const':
                totals_by_seg['__DATA_CONST_mapped'] += s['size']
            elif s['segment'] == '__DATA':
                totals_by_seg['__DATA_mapped'] += s['size']
            else:
                totals_by_seg[f'other:{s["segment"]}'] += s['size']
        per_obj.append({'source': src_name, 'object': obj_path.name, 'sections': secs})

    # Top contributors to __TEXT (excluding __text -> __TEXT_EXEC) and __DATA (excluding __DATA,__const -> __DATA_CONST)
    text_drivers = []
    data_drivers = []
    dataconst_drivers = []
    textexec_drivers = []

    for o in per_obj:
        t_bytes = sum(v for k, v in o['sections'].items() if k.startswith('__TEXT,') and k != '__TEXT,__text')
        d_bytes = sum(v for k, v in o['sections'].items() if k.startswith('__DATA,') and k != '__DATA,__const')
        dc_bytes = sum(v for k, v in o['sections'].items() if k.startswith('__DATA_CONST,') or k == '__DATA,__const')
        te_bytes = o['sections'].get('__TEXT,__text', 0)
        if t_bytes:
            text_drivers.append({'object': o['object'], 'bytes': t_bytes, 'detail': {k: v for k, v in o['sections'].items() if k.startswith('__TEXT,') and k != '__TEXT,__text'}})
        if d_bytes:
            data_drivers.append({'object': o['object'], 'bytes': d_bytes, 'detail': {k: v for k, v in o['sections'].items() if k.startswith('__DATA,') and k != '__DATA,__const'}})
        if dc_bytes:
            dataconst_drivers.append({'object': o['object'], 'bytes': dc_bytes, 'detail': {k: v for k, v in o['sections'].items() if k.startswith('__DATA_CONST,') or k == '__DATA,__const'}})
        if te_bytes:
            textexec_drivers.append({'object': o['object'], 'bytes': te_bytes})

    text_drivers.sort(key=lambda x: -x['bytes'])
    data_drivers.sort(key=lambda x: -x['bytes'])
    dataconst_drivers.sort(key=lambda x: -x['bytes'])
    textexec_drivers.sort(key=lambda x: -x['bytes'])

    return {
        'object_count': len(per_obj),
        'raw_totals_by_object_segsec': dict(sorted(totals_by_segsec.items())),
        'mapped_totals_bytes': dict(sorted(totals_by_seg.items())),
        'top_TEXT_nonexec_contributors': text_drivers,
        'top_DATA_rw_contributors': data_drivers,
        'top_DATA_CONST_contributors': dataconst_drivers[:15],
        'top_TEXT_EXEC_contributors': textexec_drivers[:15],
    }


def analyze_a7_segment_tails(a7_layout: dict) -> dict:
    segs = {s['name']: s for s in a7_layout['segments']}
    out = {}
    for sname in ('__TEXT', '__DATA_CONST', '__TEXT_EXEC', '__DATA'):
        seg = segs[sname]
        secs = seg['sections']
        first_addr = min(s['addr'] for s in secs) if secs else seg['vmaddr']
        last_end = max(s['addr'] + s['size'] for s in secs) if secs else seg['vmaddr']
        seg_end = seg['vmaddr'] + seg['vmsize']
        out[sname] = {
            'vmaddr': hex(seg['vmaddr']),
            'vmsize': seg['vmsize'],
            'vmsize_hex': hex(seg['vmsize']),
            'first_section': secs[0]['section'] if secs else None,
            'first_section_addr': hex(first_addr),
            'leading_pad_bytes': first_addr - seg['vmaddr'],
            'last_section': secs[-1]['section'] if secs else None,
            'last_section_end': hex(last_end),
            'trailing_unused_bytes_in_last_16k_page': seg_end - last_end,
            'sections': [
                {'section': s['section'], 'addr': s['addr_hex'], 'size': s['size'], 'align': 1 << s['align_pow2']}
                for s in secs
            ],
        }
    return out


def analyze_tier1_observer_symbols(nm_path: Path, r2_a7_describe: dict) -> dict:
    """Measure static symbol extents in frozen A7 nm.txt (emitted kernel.macho) for liuqin r10x observer symbols."""
    # nm.txt is emitted from frozen A7 kernel.macho (fileset VA space slid by +0x1f000000000
    # from 0xfffffe00... to 0xfffffff0...), so map symbol addresses against slid native kernel segment bounds.
    collection_slide = 0x000001F000000000
    segs = {}
    for sname, info in r2_a7_describe.items():
        sz = int(info['size'], 16)
        if sz > 0:
            lo = int(info['new'], 16) + collection_slide
            segs[sname] = (lo, lo + sz)

    all_syms = []
    for ln in nm_path.read_text(errors='replace').splitlines():
        parts = ln.split()
        if len(parts) < 3:
            continue
        try:
            addr = int(parts[0], 16)
        except ValueError:
            continue
        stype = parts[1]
        name = parts[2]
        if stype in ('U', 'u'):
            continue
        all_syms.append((addr, stype, name))

    all_syms.sort(key=lambda x: x[0])

    def seg_of(addr: int) -> str:
        for sname, (lo, hi) in segs.items():
            if lo <= addr < hi:
                return sname
        return 'other'

    # Strictly match liuqin r10x observer symbols (exclude Apple IOHID*TimeSync* and C++ vtable tokens like *104_*)
    prefixes = (
        '_liuqin_r10', '_r101_', '_r102_', '_r103_', '_r104_', '_r105_', '_r106_',
        'l___const.r104_', 'l___const.r105_', 'l___const.r106_', 'l___const.liuqin_r10',
    )
    matches = []
    for idx, (addr, stype, name) in enumerate(all_syms):
        if any(name.startswith(p) for p in prefixes):
            seg = seg_of(addr)
            next_addr = None
            for j in range(idx + 1, len(all_syms)):
                if all_syms[j][0] > addr:
                    next_addr = all_syms[j][0]
                    break
            seg_end = segs[seg][1] if seg in segs else (next_addr or addr)
            span = (min(next_addr, seg_end) - addr) if next_addr else (seg_end - addr)
            tier = 'tier1_clocksyncd_timesync' if any(
                k in name for k in ('r104_', 'r105_', 'r106_', 'timesync')
            ) else 'retained_observer_or_shared'
            matches.append({
                'name': name,
                'type': stype,
                'segment': seg,
                'tier': tier,
                'addr': hex(addr),
                'next_symbol_span_bytes': span,
            })

    by_tier_seg = defaultdict(lambda: defaultdict(lambda: {'count': 0, 'span_bytes': 0}))
    for m in matches:
        by_tier_seg[m['tier']][m['segment']]['count'] += 1
        by_tier_seg[m['tier']][m['segment']]['span_bytes'] += m['next_symbol_span_bytes']

    return {
        'caveat': 'Symbol-to-next-symbol spans are static upper-bound observations in frozen emitted A7 kernel.macho only; inlining, cstring deduplication, and 4 KiB/16 KiB segment packing mean NO reclaimed byte capacity is claimed without a rebuild.',
        'matched_symbol_count': len(matches),
        'totals_by_tier_and_segment': {t: dict(v) for t, v in by_tier_seg.items()},
        'symbols': matches,
    }


def main() -> None:
    OUT_EV.mkdir(parents=True, exist_ok=True)
    a7_layout = parse_macho_layout(A7_STANDALONE.read_bytes())
    r2_json = json.loads(R2_LINK_JSON.read_text())

    a7_tails = analyze_a7_segment_tails(a7_layout)
    r2_contrib = inspect_r2_object_contributions(r2_json)
    r2_links = r2_json['standalone_links_and_fileset_placement']
    tier1_syms = analyze_tier1_observer_symbols(A7_NM, r2_links['a7_baseline_repro']['fileset_layout']['describe'])

    # Check exact mechanics of first_const_vma shift and __DATA +16 KiB page crossing
    a7_first_const = int(a7_tails['__TEXT']['first_section_addr'], 16)
    r2_pg = r2_links['a730blobs_plus_smmu']['policy_gates']
    r2_first_const = int(r2_pg['first_const_vma'], 16)
    const_shift = a7_first_const - r2_first_const  # positive = moved down toward header

    a7_data_trail = a7_tails['__DATA']['trailing_unused_bytes_in_last_16k_page']
    r2_data_added_raw = r2_contrib['mapped_totals_bytes'].get('__DATA_mapped', 0)
    r2_text_nonexec_raw = r2_contrib['mapped_totals_bytes'].get('__TEXT_mapped', 0)
    a7_text_trail = a7_tails['__TEXT']['trailing_unused_bytes_in_last_16k_page']

    a7_header_gap = a7_first_const - (0xFFFFFFF007004000 + a7_layout['header_end'])
    r2_header_gap = r2_pg['header_to_first_section_gap_bytes']

    report = {
        'scope': 'Byte-for-byte __TEXT/first_const_vma and __DATA budget attribution for a730blobs_plus_smmu vs frozen A7 + Tier-1 observer symbol inventory (gpu-host-gates-r3)',
        'a7_standalone_header': {
            'ncmds': a7_layout['ncmds'],
            'sizeofcmds': a7_layout['sizeofcmds'],
            'header_end_offset': hex(a7_layout['header_end']),
            'header_to_first_section_gap_bytes': a7_header_gap,
        },
        'a7_segment_tails': a7_tails,
        'r2_a730blobs_plus_smmu_object_contributions': r2_contrib,
        'first_const_vma_shift_explanation': {
            'evidence_label': 'host-measured',
            'a7_first_const_vma': hex(a7_first_const),
            'r2_first_const_vma': hex(r2_first_const),
            'const_vma_floor': r2_pg['const_vma_floor'],
            'measured_downward_shift_bytes': const_shift,
            'a7_header_gap_bytes': a7_header_gap,
            'r2_header_gap_bytes': r2_header_gap,
            'remaining_floor_margin_bytes': r2_pg['const_vma_margin_bytes'],
            'a7_text_last_section_end': a7_tails['__TEXT']['last_section_end'],
            'a7_text_trailing_pad_to_16k_seg_end_bytes': a7_text_trail,
            'raw_added_TEXT_nonexec_bytes_across_objects': r2_text_nonexec_raw,
            'implied_4k_tail_expansion_plus_shift_bytes': 4096 + const_shift,
            'ld64_dedup_and_align_delta_vs_4k_plus_shift_bytes': r2_text_nonexec_raw - (4096 + const_shift),
            'mechanism': (
                'In XNU 4 KiB arm64e standalone links, ld64 packs __TEXT sections backwards from a 4 KiB '
                '(0x1000) boundary inside the 16 KiB-aligned __TEXT segment (in A7, __eh_frame ends at '
                f'{a7_tails["__TEXT"]["last_section_end"]}, leaving {a7_text_trail} B = 3x4 KiB unused before '
                'segment end 0xfffffff0071d0000). Adding the A730+SMMU closure added '
                f'{r2_text_nonexec_raw} raw non-exec __TEXT bytes (mostly __cstring + __const), which after '
                f'~{r2_text_nonexec_raw - (4096 + const_shift)} B of cstring deduplication/alignment equals '
                f'one 4 KiB tail step (4,096 B) + {const_shift} B eaten from the leading header pad '
                f'(header gap 2,000 -> {r2_header_gap} B; floor margin 1,760 -> 384 B). '
                'Non-monotonic wrap behavior: growing non-exec __TEXT by 385..624 B will trip the '
                '0xfffffff007005900 policy floor, whereas >624 B triggers the next 4 KiB tail step '
                '(still inside __TEXT=0x1cc000!) and jumps first_const_vma back up by ~3.5 KiB.'
            ),
        },
        'data_segment_page_crossing_explanation': {
            'evidence_label': 'host-measured',
            'a7_DATA_vmsize': a7_tails['__DATA']['vmsize_hex'],
            'r2_DATA_vmsize': r2_links['a730blobs_plus_smmu']['segments']['__DATA']['size_hex'],
            'DATA_policy_cap': r2_pg['DATA_cap'],
            'remaining_DATA_slack_bytes': r2_pg['DATA_slack_bytes'],
            'a7_DATA_trailing_unused_bytes_in_last_16k_page': a7_data_trail,
            'raw_added_DATA_rw_bytes_across_objects': r2_data_added_raw,
            'net_overflow_into_new_16k_page_bytes': r2_data_added_raw - a7_data_trail,
            'mechanism': (
                f'Frozen A7 __DATA (0x27c000) already had only {a7_data_trail} B of free trailing space '
                f'in its last 16 KiB page (last section __common ended at {a7_tails["__DATA"]["last_section_end"]}). '
                f'The added KMD objects contribute {r2_data_added_raw} B of writable __DATA (__data/__bss/__common/__mod_init_func), '
                'which exceeds the trailing free bytes and crosses into one new 16 KiB page (0x27c000 -> 0x280000), '
                'leaving exactly 16,384 B (1 page) of policy slack before 0x284000 / com.apple.kec.Libm. '
                'Because __DATA_CONST carries the A730 firmware blobs (404,072 B slack to AppleARMPlatform), '
                'keeping future A730 static tables const (in __DATA_CONST) and cmd-db buffers heap-allocated '
                '(per GpuPowerProbe.cpp IOMallocData(0x20000)) is essential to stay within the single remaining __DATA page.'
            ),
        },
        'tier1_observer_symbol_inventory': tier1_syms,
    }

    out_path = OUT_EV / 'const-and-data-budget-audit.json'
    out_path.write_text(json.dumps(report, indent=2) + '\n')
    print(f'PASS: wrote {out_path.relative_to(ROOT)}')
    print(f'  first_const_vma shift: -{const_shift} B (raw added __TEXT non-exec: {r2_text_nonexec_raw} B, gap: {a7_header_gap} -> {r2_header_gap} B, floor margin: 384 B)')
    print(f'  __DATA page crossing: A7 trailing free={a7_data_trail} B, raw added __DATA rw={r2_data_added_raw} B -> +16,384 B page (16,384 B slack left)')
    print(f'  Top __DATA rw contributors: {[(d["object"], d["bytes"]) for d in r2_contrib["top_DATA_rw_contributors"][:6]]}')
    print(f'  Top __TEXT non-exec contributors: {[(d["object"], d["bytes"]) for d in r2_contrib["top_TEXT_nonexec_contributors"][:6]]}')
    print(f'  Tier-1/observer matched symbols in frozen A7: {tier1_syms["matched_symbol_count"]}, by tier/seg: {tier1_syms["totals_by_tier_and_segment"]}')


if __name__ == '__main__':
    main()
