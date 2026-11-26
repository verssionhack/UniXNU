#!/usr/bin/env python3
"""Host-only A730 GMU parser contract and malformed-input controls."""
from pathlib import Path
import hashlib
import json
import struct

R = Path(__file__).resolve().parents[4]
E = R / 'out/liuqin-r101-gpu-host-gates/evidence'
P = R / 'out/liuqin-r101-gpu-m1/evidence/firmware/gmu_gen70000.bin'
EXPECTED = 'b2d3f0e2a98fd6259ab9ffef16df63265542e6cc9a970d53d476e823d432042a'
# Source-qualified A730 allocations. These are GMU virtual addresses, not CPU PAs.
REGIONS = [('ITCM', 0, 0x4000), ('icache', 0x4000, 0xffc000),
           ('DTCM', 0x10004000, 0x4000), ('dummy', 0x60000000, 0x2000),
           ('debug', 0x60400000, 0x7000)]

def parse(data):
    if not 16 <= len(data) <= 128*1024:
        raise ValueError('file extent')
    at = 0
    rows = []
    spans = []
    while at < len(data):
        if len(data)-at < 16 or len(rows) >= 32:
            raise ValueError('header extent/count')
        addr, size, kind, value = struct.unpack_from('<4I', data, at)
        if addr & 3 or size & 3:
            raise ValueError('alignment')
        if size > len(data)-at-16:
            raise ValueError('payload extent')
        extent = size if size else value
        if not extent or extent > 0x100000000-addr:
            raise ValueError('address overflow/zero extent')
        hits = [name for name, base, length in REGIONS
                if base <= addr and addr-base <= length and extent <= length-(addr-base)]
        if len(hits) != 1:
            raise ValueError('unmatched/cross-region extent')
        if size:
            if kind != 0xefbeadde or value != 0xefbeadde:
                raise ValueError('unexpected data header policy')
            if any(addr < end and begin < addr+size for begin, end in spans):
                raise ValueError('overlapping data payloads')
            spans.append((addr, addr+size))
        elif kind not in (1, 7):
            raise ValueError('unknown metadata kind')
        if not size and (value & 3):
            raise ValueError('metadata extent alignment')
        rows.append({'file_offset': at, 'address': hex(addr), 'size': size,
                     'kind': hex(kind), 'value': value, 'region': hits[0]})
        at += 16+size
    return rows

data = P.read_bytes()
assert hashlib.sha256(data).hexdigest() == EXPECTED
rows = parse(data)
assert len(rows) == 15 and sum(bool(x['size']) for x in rows) == 4
controls = {}
cases = {'truncated_payload': data[:-1], 'trailing_partial_header': data+b'\0'}
def modified(at, fmt, *words):
    copy = bytearray(data)
    struct.pack_into(fmt, copy, at, *words)
    return bytes(copy)
cases['unaligned_address'] = modified(16, '<I', 0x4001)
cases['unknown_metadata'] = modified(8, '<I', 8)
cases['cross_region_payload'] = modified(176, '<I', 0x3ff0)
cases['address_wrap'] = modified(176, '<I', 0xfffffffc)
cases['overlap'] = modified(668, '<I', 0)
for name, blob in cases.items():
    try:
        parse(blob)
    except ValueError as error:
        controls[name] = str(error)
    else:
        raise AssertionError('malformed input accepted: '+name)
result = {'scope': 'host parser design only; does not execute firmware or prove HFI queue-count acceptance',
          'sha256': EXPECTED, 'blocks': rows, 'negative_controls': controls,
          'hfi_three_queue_acceptance': 'initializer accepts three per separate hfi-table-init-contract.json; operational behavior untested',
          'hfi_first_A730_design': 'preserve source-qualified Linux two-queue layout; no claim firmware strictly requires two',
          'security_boundary': 'future runtime must verify full pinned digest plus parser contract and allocation/ownership; parser success does not prove safe MMIO/SMC/DMA'}
(E/'firmware-parser-contract.json').write_text(json.dumps(result, indent=2)+'\n')
print('PASS: 15 real headers, 4 data blocks; rejected', len(controls), 'malformed controls')
