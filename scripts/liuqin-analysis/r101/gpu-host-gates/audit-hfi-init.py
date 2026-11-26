#!/usr/bin/env python3
"""Bounded CM3 Thumb initializer audit; static predicates, no firmware execution."""
from pathlib import Path
import hashlib
import json
import struct
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB, CS_MODE_LITTLE_ENDIAN

R = Path(__file__).resolve().parents[4]
E = R / 'out/liuqin-r101-gpu-host-gates/evidence'
raw = (R/'out/liuqin-r101-gpu-m1/evidence/firmware/gmu_gen70000.bin').read_bytes()
assert hashlib.sha256(raw).hexdigest() == 'b2d3f0e2a98fd6259ab9ffef16df63265542e6cc9a970d53d476e823d432042a'
blocks = []
at = 0
while at < len(raw):
    address, size, kind, value = struct.unpack_from('<4I', raw, at)
    if size:
        blocks.append((address, raw[at+16:at+16+size]))
    at += 16+size
def read(address, size):
    hits = [(base, data) for base, data in blocks if base <= address and address+size <= base+len(data)]
    assert len(hits) == 1
    base, data = hits[0]
    return data[address-base:address-base+size]
cs = Cs(CS_ARCH_ARM, CS_MODE_THUMB | CS_MODE_LITTLE_ENDIAN)
insns = {i.address: i for i in cs.disasm(read(0x8cd0, 0x64), 0x8cd0)}
expected = {0x8cde: ('ldr', 'r0, [r0]'), 0x8ce0: ('ldr', 'r1, [r0, #8]'),
            0x8ce2: ('add.w', 'r4, r0, r1, lsl #2'),
            0x8ce6: ('ldrh', 'r0, [r0, #0x10]'),
            0x8cee: ('cmp', 'r0, #0x14'), 0x8cf0: ('bls', '#0x8cf6'),
            0x8cf2: ('movs', 'r0, #0x70'),
            0x8cfa: ('add.w', 'r1, r2, r2, lsl #1'),
            0x8cfe: ('add.w', 'r3, r4, r1, lsl #4'),
            0x8d02: ('ldrb', 'r1, [r3, #8]'),
            0x8d04: ('cmp', 'r0, r1'), 0x8d06: ('bhi', '#0x8d0c'),
            0x8d08: ('movs', 'r0, #0x70'),
            0x8d2a: ('ldrh', 'r0, [r5]'), 0x8d2c: ('cmp', 'r0, r2'),
            0x8d2e: ('bhi', '#0x8cfa'), 0x8d30: ('movs', 'r0, #0')}
for address, pair in expected.items():
    i = insns[address]
    assert (i.mnemonic, i.op_str) == pair, (hex(address), i.mnemonic, i.op_str)
with (E/'hfi-table-init.asm.txt').open('w') as f:
    for start, size in [(0x8cd0, 0x64), (0x8fa4, 0x24), (0x8f04, 0xc)]:
        f.write(f'\nCM3 VA {start:#x}, pinned firmware bytes:\n')
        for i in cs.disasm(read(start, size), start):
            f.write(f'{i.address:#010x}: {i.bytes.hex():12} {i.mnemonic} {i.op_str}\n')
mmio_info = struct.unpack('<I', read(0x8d34, 4))[0]
assert mmio_info == 0x1807e610
# The native-side Linux GMU offsets independently agree with the aperture suffix.
assert (0x03d6a000-0x03d00000) + 0x5184*4 == mmio_info-0x18000000
def initializer_predicate(count, types):
    if count > 20:
        return 0x70
    for queue_type in types[:count]:
        if queue_type & 255 >= count:
            return 0x70
    return 0
results = {'Linux_two': initializer_predicate(2, [0xa00, 0xa01]),
           'native_three': initializer_predicate(3, [0xa00, 0xa01, 0xa02]),
           'count_twenty_one': initializer_predicate(21, [0xa00]*21),
           'id_out_of_range': initializer_predicate(3, [0xa00, 0xa01, 0xa03])}
assert results == {'Linux_two': 0, 'native_three': 0, 'count_twenty_one': 0x70, 'id_out_of_range': 0x70}
out = {'scope': 'static binary initializer predicate qualification; no CM3 execution, ABI emulator or operational HFI claim',
       'initializer': '0x8cd0', 'caller': '0x8fa4 (calls initializer at 0x8fb0 and publishes ready/error)',
       'source_MMIO_consistency': {'CM3_HFI_QTBL_INFO': hex(mmio_info), 'Linux_GMU_dword': '0x5184'},
       'verified_instruction_predicates': len(expected), 'maximum_count': 20, 'queue_header_stride_bytes': 48,
       'queue_count_field': 'low 16 bits at table+16', 'first_header': 'table + 4 * u32(table+8)',
       'id_predicate': 'u8(queue_header+8) < count', 'failure_return': '0x70',
       'modeled_predicate_results': results,
       'conclusion': 'three valid native queue headers are accepted by this initializer; no strict-two initializer requirement',
       'limits': 'count-predicate model assumes valid readable mapped table/headers and does not execute caller, prove all later queue uses, IRQ behavior, memory coherence or wakeup'}
(E/'hfi-table-init-contract.json').write_text(json.dumps(out, indent=2)+'\n')
print('PASS: pinned initializer predicates accept two and three; reject count 21 and ID outside count')
