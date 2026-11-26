#!/usr/bin/env python3
"""Reusable host-side Phase 2 SM8475/A730 Command-DB parser and HFI vote calculator.

Strictly validates a captured 128 KiB Qualcomm RPMh Command-DB snapshot (no hardware
access, no vote issuance, fail-closed on every bounds/format/overlap/duplicate error).

Extracts only the public GPU/GMU resource records required for SM8475/A730:
  - BCM addresses: SH0, MC0, ACV, CN0
  - ARC level arrays: gfx.lvl, cx.lvl, mx.lvl, and optional gmxc.lvl
    (distinguishes authoritatively absent gmxc.lvl from corrupt/unreadable input)

Computes:
  - GX and CX ARC vote words using exact Linux a6xx_gmu_rpmh_arc_votes_init /
    kits/AdrenoFirmware/AdrenoHfiVotes.c semantics, preserving provenance (primary
    and secondary rail names, indices, and matched levels) for every word.
  - A730 static HFI bandwidth table (12 DDR levels, 3 DDR commands SH0/MC0/ACV,
    1 CNOC command CN0, wait masks 0x7 / 0x1) populated with parsed cmd-db addresses.
"""
from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

CMD_DB_EXPECTED_SIZE = 0x20000  # 128 KiB
CMD_DB_MAGIC = b'\xdb\x30\x03\x0c'
CMD_DB_MAX_SLV_ID = 8
CMD_DB_HEADER_SIZE = 8 + CMD_DB_MAX_SLV_ID * 16 + 8  # 144 bytes
ENTRY_HEADER_SIZE = 24  # id[8], priority[2]*u32, addr u32, len u16, offset u16

SLV_ARC = 3
SLV_VRM = 4
SLV_BCM = 5
VALID_SLV_IDS = {SLV_ARC, SLV_VRM, SLV_BCM}

REQUIRED_BCM_KEYS = ('SH0', 'MC0', 'ACV', 'CN0')
REQUIRED_ARC_KEYS = ('gfx.lvl', 'cx.lvl', 'mx.lvl')
OPTIONAL_ARC_KEYS = ('gmxc.lvl',)

# Source-verified Linux drivers/gpu/drm/msm/adreno/a6xx_hfi.c:a730_build_bw_table()
# and out/liuqin-r101-gpu-m1/evidence/a730-bandwidth-table.json
A730_STATIC_DDR_DATA = (
    (0x40000000, 0x40000000, 0x40000000),
    (0x600002e8, 0x600003d0, 0x60000008),
    (0x6000068d, 0x6000089a, 0x60000008),
    (0x600007f2, 0x60000a6e, 0x60000008),
    (0x600009e5, 0x60000cfd, 0x60000008),
    (0x60000b29, 0x60000ea6, 0x60000008),
    (0x60001698, 0x60001da8, 0x60000008),
    (0x600018d2, 0x60002093, 0x60000008),
    (0x60001e66, 0x600027e6, 0x60000008),
    (0x600027c2, 0x6000342f, 0x60000008),
    (0x60002e71, 0x60003cf5, 0x60000008),
    (0x600030ae, 0x60003fe5, 0x60000008),
)
A730_STATIC_CNOC_DATA = ((0x40000000,), (0x60000001,))
A730_DDR_WAIT_MASK = 0x7
A730_CNOC_WAIT_MASK = 0x1


class CmdDbError(ValueError):
    """Fail-closed error raised on any malformed, corrupt, or out-of-bounds cmd-db input."""


def _validate_id_bytes(raw_id: bytes) -> str:
    if len(raw_id) != 8:
        raise CmdDbError('Invalid entry id length')
    # Find first NUL; all trailing bytes after NUL must also be NUL
    if b'\x00' in raw_id:
        nul = raw_id.index(b'\x00')
        if any(b != 0 for b in raw_id[nul:]):
            raise CmdDbError(f'Non-zero trailing bytes after NUL in entry id {raw_id!r}')
        name_bytes = raw_id[:nul]
    else:
        name_bytes = raw_id
    if not name_bytes:
        raise CmdDbError('Empty entry id')
    if not all(0x21 <= b <= 0x7E for b in name_bytes):
        raise CmdDbError(f'Non-printable ASCII in entry id {raw_id!r}')
    return name_bytes.decode('ascii')


def parse_cmd_db(blob: bytes, require_exact_128k: bool = True) -> dict:
    """Strictly parse and validate a raw Qualcomm Command-DB snapshot."""
    if not isinstance(blob, (bytes, bytearray, memoryview)):
        raise CmdDbError('Input must be bytes-like')
    blob = bytes(blob)
    if require_exact_128k:
        if len(blob) != CMD_DB_EXPECTED_SIZE:
            raise CmdDbError(f'Expected exact {CMD_DB_EXPECTED_SIZE} B cmd-db snapshot, got {len(blob)} B')
    elif len(blob) < CMD_DB_HEADER_SIZE:
        raise CmdDbError(f'Buffer smaller than cmd_db_header ({len(blob)} < {CMD_DB_HEADER_SIZE})')

    version, magic = struct.unpack_from('<I4s', blob, 0)
    if magic != CMD_DB_MAGIC:
        raise CmdDbError(f'Bad cmd-db magic {magic.hex()}, expected {CMD_DB_MAGIC.hex()}')
    if version == 0:
        raise CmdDbError('Zero cmd-db header version')

    checksum, reserved = struct.unpack_from('<2I', blob, 8 + CMD_DB_MAX_SLV_ID * 16)
    data_cap = len(blob) - CMD_DB_HEADER_SIZE

    slaves = []
    seen_slv_ids = set()
    seen_entry_ids: dict[str, dict] = {}
    occupied_spans: list[tuple[int, int, str]] = []
    terminated = False

    def add_span(start: int, end: int, label: str) -> None:
        if start < 0 or end < start or end > data_cap:
            raise CmdDbError(f'Out-of-bounds span {label}: [{start}, {end}) vs data_cap={data_cap}')
        for s0, e0, lbl0 in occupied_spans:
            if start < e0 and s0 < end:
                raise CmdDbError(f'Overlapping spans {label} [{start},{end}) and {lbl0} [{s0},{e0})')
        if end > start:
            occupied_spans.append((start, end, label))

    for i in range(CMD_DB_MAX_SLV_ID):
        off = 8 + i * 16
        slv_id, hdr_off, data_off, cnt, slv_ver, r0, r1, r2 = struct.unpack_from('<8H', blob, off)
        if slv_id == 0:
            terminated = True
            # Ensure no non-zero junk after terminator in active header slots?
            # Linux cmd-db breaks at first slv_id == 0; reject non-zero fields inside the terminator slot itself
            if any((hdr_off, data_off, cnt, slv_ver, r0, r1, r2)):
                raise CmdDbError(f'Non-zero fields in zero-slv_id terminator slot {i}')
            continue
        if terminated:
            raise CmdDbError(f'Non-zero slv_id={slv_id} found after zero terminator at slot {i}')
        if slv_id not in VALID_SLV_IDS:
            raise CmdDbError(f'Unsupported slv_id={slv_id} at slot {i}')
        if slv_id in seen_slv_ids:
            raise CmdDbError(f'Duplicate slv_id={slv_id} at slot {i}')
        seen_slv_ids.add(slv_id)
        if cnt == 0:
            raise CmdDbError(f'Slave slv_id={slv_id} has zero entries')

        ent_start = hdr_off
        ent_end = hdr_off + cnt * ENTRY_HEADER_SIZE
        add_span(ent_start, ent_end, f'slv{slv_id}_entries')

        entries = []
        for j in range(cnt):
            eoff = CMD_DB_HEADER_SIZE + hdr_off + j * ENTRY_HEADER_SIZE
            raw_id, pri0, pri1, addr, aux_len, aux_rel = struct.unpack_from('<8s3I2H', blob, eoff)
            name = _validate_id_bytes(raw_id)
            if name in seen_entry_ids:
                raise CmdDbError(f'Duplicate resource id {name!r}')
            if addr == 0:
                raise CmdDbError(f'Resource {name!r} has zero address')
            addr_slv = (addr >> 16) & 0x7
            if addr_slv != slv_id:
                raise CmdDbError(f'Resource {name!r} addr {addr:#x} slave bits ({addr_slv}) != rsc_hdr slv_id ({slv_id})')

            aux_bytes = b''
            if aux_len > 0:
                a_start = data_off + aux_rel
                a_end = a_start + aux_len
                add_span(a_start, a_end, f'aux:{name}')
                aux_bytes = blob[CMD_DB_HEADER_SIZE + a_start:CMD_DB_HEADER_SIZE + a_end]

            rec = {
                'id': name,
                'slv_id': slv_id,
                'addr': addr,
                'addr_hex': hex(addr),
                'priority': [pri0, pri1],
                'aux_len': aux_len,
                'aux_offset_in_data': data_off + aux_rel if aux_len else None,
                'aux_hex': aux_bytes.hex(),
            }
            seen_entry_ids[name] = rec
            entries.append(rec)

        slaves.append({
            'slot': i,
            'slv_id': slv_id,
            'version_major': slv_ver >> 8,
            'version_minor': slv_ver & 0xFF,
            'header_offset': hdr_off,
            'data_offset': data_off,
            'entry_count': cnt,
            'entries': entries,
        })

    if not slaves:
        raise CmdDbError('No valid resource slaves in cmd-db')

    return {
        'snapshot_bytes': len(blob),
        'snapshot_sha256': hashlib.sha256(blob).hexdigest(),
        'version': version,
        'magic_hex': magic.hex(),
        'checksum_field': hex(checksum),
        'reserved_field': hex(reserved),
        'slave_count': len(slaves),
        'total_entry_count': len(seen_entry_ids),
        'slaves': slaves,
        'entries_by_id': seen_entry_ids,
    }


def validate_arc_rail(aux: bytes, name: str) -> list[int]:
    """Validate an ARC rail byte array per kits/AdrenoFirmware/AdrenoHfiVotes.c:rail()."""
    if not aux or (len(aux) & 1) or len(aux) > 512:
        raise CmdDbError(f'ARC rail {name!r} invalid byte length {len(aux)}')
    vals = [struct.unpack_from('<H', aux, i)[0] for i in range(0, len(aux), 2)]
    if vals[0] != 0:
        raise CmdDbError(f'ARC rail {name!r} entry 0 must be 0 (off), got {vals[0]}')
    padding = False
    last = 0
    for idx, v in enumerate(vals[1:], start=1):
        if v == 0:
            padding = True
        elif padding or v < last:
            raise CmdDbError(f'ARC rail {name!r} non-monotonic or non-zero after zero padding at idx {idx}: {v} after {last}')
        last = v
    return vals


def compute_arc_votes(levels: list[int], primary_name: str, primary_vals: list[int], secondary_name: str, secondary_vals: list[int]) -> list[dict]:
    """Compute ARC vote words with full index/level provenance."""
    if not levels or len(levels) > 16 or levels[0] != 0:
        raise CmdDbError('OPP level list must start with 0 (off) and have 1..16 entries')
    out = []
    for i, lvl in enumerate(levels):
        if lvl < 0 or lvl > 0xFFFF or (i > 0 and lvl < levels[i - 1]):
            raise CmdDbError(f'Invalid OPP level ordering/range at index {i}: {lvl}')
        p_idx = None
        for j, pv in enumerate(primary_vals):
            if pv >= lvl:
                p_idx = j
                break
        if p_idx is None:
            raise CmdDbError(f'Requested level {lvl} exceeds max of primary rail {primary_name!r}')
        s_idx = 0
        for j, sv in enumerate(secondary_vals):
            if sv >= lvl:
                s_idx = j
                break
            if sv != 0:
                s_idx = j
        word = ((primary_vals[p_idx] & 0xFFFF) << 16) | ((s_idx & 0xFF) << 8) | (p_idx & 0xFF)
        out.append({
            'opp_index': i,
            'requested_level': lvl,
            'primary_rail': primary_name,
            'primary_index': p_idx,
            'primary_matched_level': primary_vals[p_idx],
            'secondary_rail': secondary_name,
            'secondary_index': s_idx,
            'secondary_matched_level': secondary_vals[s_idx],
            'vote_word': word,
            'vote_hex': f'{word:#010x}',
        })
    return out


def extract_sm8475_gpu_inputs(parsed: dict, gpu_opps: list[tuple[int, int]], gmu_opps: list[tuple[int, int]]) -> dict:
    """Extract required SM8475/A730 GPU/GMU cmd-db records and build ARC + static BW tables.

    gpu_opps / gmu_opps: list of (hz, opp_level) tuples including (0, 0) as entry 0.
    """
    entries = parsed['entries_by_id']

    # 1. Required BCM addresses
    bcm_addrs = {}
    for key in REQUIRED_BCM_KEYS:
        if key not in entries:
            raise CmdDbError(f'Missing required BCM key {key!r}')
        rec = entries[key]
        if rec['slv_id'] != SLV_BCM:
            raise CmdDbError(f'Key {key!r} has slv_id={rec["slv_id"]}, expected BCM ({SLV_BCM})')
        if (rec['addr'] & 3) != 0:
            raise CmdDbError(f'BCM key {key!r} address {rec["addr_hex"]} is not 4-byte aligned')
        bcm_addrs[key] = {'addr': rec['addr'], 'addr_hex': rec['addr_hex'], 'aux_len': rec['aux_len'], 'aux_hex': rec['aux_hex']}
    if len({v['addr'] for v in bcm_addrs.values()}) != len(REQUIRED_BCM_KEYS):
        raise CmdDbError('Duplicate physical RPMh addresses among SH0/MC0/ACV/CN0')

    # 2. Required ARC rails + authoritative gmxc.lvl detection
    arc_rails = {}
    for key in REQUIRED_ARC_KEYS:
        if key not in entries:
            raise CmdDbError(f'Missing required ARC rail {key!r}')
        rec = entries[key]
        if rec['slv_id'] != SLV_ARC:
            raise CmdDbError(f'Key {key!r} has slv_id={rec["slv_id"]}, expected ARC ({SLV_ARC})')
        aux = bytes.fromhex(rec['aux_hex'])
        arc_rails[key] = {'addr_hex': rec['addr_hex'], 'aux_bytes': len(aux), 'levels': validate_arc_rail(aux, key), 'aux_hex': rec['aux_hex']}

    if 'gmxc.lvl' in entries:
        rec = entries['gmxc.lvl']
        if rec['slv_id'] != SLV_ARC:
            raise CmdDbError(f'Key gmxc.lvl has slv_id={rec["slv_id"]}, expected ARC ({SLV_ARC})')
        aux = bytes.fromhex(rec['aux_hex'])
        arc_rails['gmxc.lvl'] = {'addr_hex': rec['addr_hex'], 'aux_bytes': len(aux), 'levels': validate_arc_rail(aux, 'gmxc.lvl'), 'aux_hex': rec['aux_hex']}
        gmxc_status = 'present'
        secondary_rail_name = 'gmxc.lvl'
    else:
        gmxc_status = 'authoritatively_absent'
        secondary_rail_name = 'mx.lvl'

    # 3. Validate OPP frequency monotonicity and compute ARC votes
    for name, opps, max_n in (('gpu', gpu_opps, 16), ('gmu', gmu_opps, 4)):
        if len(opps) < 2 or len(opps) > max_n or opps[0] != (0, 0):
            raise CmdDbError(f'{name} OPPs must start with (0, 0) and have 2..{max_n} entries')
        for i in range(1, len(opps)):
            if opps[i][0] <= opps[i - 1][0] or (opps[i][0] % 1000) != 0:
                raise CmdDbError(f'{name} OPP[{i}] frequency {opps[i][0]} not strictly ascending kHz-aligned')

    gx_votes = compute_arc_votes(
        [lvl for _, lvl in gpu_opps],
        'gfx.lvl', arc_rails['gfx.lvl']['levels'],
        secondary_rail_name, arc_rails[secondary_rail_name]['levels'],
    )
    for row, (hz, _) in zip(gx_votes, gpu_opps):
        row['hz'] = hz
        row['khz'] = hz // 1000

    cx_votes = compute_arc_votes(
        [lvl for _, lvl in gmu_opps],
        'cx.lvl', arc_rails['cx.lvl']['levels'],
        secondary_rail_name, arc_rails[secondary_rail_name]['levels'],
    )
    for row, (hz, _) in zip(cx_votes, gmu_opps):
        row['hz'] = hz
        row['khz'] = hz // 1000

    # 4. A730 static HFI bandwidth table populated with cmd-db addresses
    bw_table = {
        'mode': 'a730_static_table_with_cmddb_addresses',
        'source_ref': 'linux-release-clean/drivers/gpu/drm/msm/adreno/a6xx_hfi.c:a730_build_bw_table',
        'bandwidth_count': len(A730_STATIC_DDR_DATA),
        'ddr_count': 3,
        'ddr_wait_mask': A730_DDR_WAIT_MASK,
        'ddr_keys': ['SH0', 'MC0', 'ACV'],
        'ddr_addresses': [bcm_addrs['SH0']['addr'], bcm_addrs['MC0']['addr'], bcm_addrs['ACV']['addr']],
        'ddr_addresses_hex': [bcm_addrs['SH0']['addr_hex'], bcm_addrs['MC0']['addr_hex'], bcm_addrs['ACV']['addr_hex']],
        'ddr_data': [[f'{w:#010x}' for w in row] for row in A730_STATIC_DDR_DATA],
        'cnoc_count': 1,
        'cnoc_wait_mask': A730_CNOC_WAIT_MASK,
        'cnoc_keys': ['CN0'],
        'cnoc_addresses': [bcm_addrs['CN0']['addr']],
        'cnoc_addresses_hex': [bcm_addrs['CN0']['addr_hex']],
        'cnoc_data': [[f'{w:#010x}' for w in row] for row in A730_STATIC_CNOC_DATA],
    }

    return {
        'snapshot_sha256': parsed['snapshot_sha256'],
        'snapshot_bytes': parsed['snapshot_bytes'],
        'cmd_db_version': parsed['version'],
        'slave_count': parsed['slave_count'],
        'total_entry_count': parsed['total_entry_count'],
        'gmxc_status': gmxc_status,
        'selected_secondary_rail': secondary_rail_name,
        'bcm_resources': bcm_addrs,
        'arc_rails': arc_rails,
        'gx_arc_votes': gx_votes,
        'cx_arc_votes': cx_votes,
        'a730_bandwidth_table': bw_table,
    }


def main() -> None:
    if len(sys.argv) != 2:
        print('Usage: sm8475_cmddb_tool.py <128KiB-cmd-db-snapshot.bin>', file=sys.stderr)
        sys.exit(2)
    blob = Path(sys.argv[1]).read_bytes()
    parsed = parse_cmd_db(blob, require_exact_128k=True)
    # Default active SM8450/SM8475 compiled DTB OPPs (off + 12 active GPU, off + 2 active GMU)
    gpu_opps = [
        (0, 0),
        (220000000, 56), (285000000, 56), (317000000, 64), (350000000, 64),
        (421000000, 80), (492000000, 128), (545000000, 144), (599000000, 192),
        (640000000, 224), (734000000, 256), (791000000, 320), (818000000, 384),
    ]
    gmu_opps = [(0, 0), (200000000, 64), (500000000, 128)]
    result = extract_sm8475_gpu_inputs(parsed, gpu_opps, gmu_opps)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
