#!/usr/bin/env python3
"""Fail closed on NativeAES absolute references in a finished fileset.

Use the standalone executable from the same build, its final fileset, the
build's llvm-nm output, and the exact assembly bindings used at link time.
"""
import argparse
import json
from pathlib import Path
import re
import struct
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'kits/XnuPrelink'))
from kc_image import Image, scan, signed


def require(condition, message):
    if not condition:
        raise ValueError(message)


def named_symbols(image):
    return {name: address for address, names in image.symbols().items() for name in names}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kernel', type=Path, required=True)
    parser.add_argument('--standalone', type=Path, required=True)
    parser.add_argument('--nm', type=Path, required=True)
    parser.add_argument('--bindings', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--expected-branches', type=int, default=8)
    parser.add_argument('--expected-absolute-pointers', type=int, default=8)
    args = parser.parse_args()

    data = args.kernel.read_bytes()
    image = Image(data)
    native = Image(args.standalone.read_bytes())
    require('com.apple.kernel' in image.entries, 'final image has no native fileset entry')
    entry = Image(data, image.entries['com.apple.kernel'][1])
    source_symbols = named_symbols(native)
    final_symbols = {}
    final_types = {}
    for line in args.nm.read_text().splitlines():
        match = re.match(r'^([0-9a-fA-F]+)\s+([A-Za-z])\s+(\S+)$', line)
        if match:
            address, kind, name = int(match[1], 16), match[2], match[3]
            if kind != 'A':
                final_symbols[name] = address
                final_types[name] = kind
    bindings = {}
    for line in args.bindings.read_text().splitlines():
        match = re.match(r'^\s*\.set\s+(\S+?)\s*,\s*(0x[0-9a-fA-F]+)\s*$', line)
        if match:
            bindings[match[1]] = int(match[2], 16)
    require(len(bindings) == 22, f'expected 22 AES bindings, found {len(bindings)}')
    for name, address in bindings.items():
        require(final_symbols.get(name) == address,
                f'binding differs from final symbol: {name} {address:#x} != {final_symbols.get(name)}')

    old_text = next(s for s in native.segments if s['name'] == '__TEXT_EXEC')
    new_text = next(s for s in entry.segments if s['name'] == '__TEXT_EXEC')
    delta = new_text['va'] - old_text['va']
    samples = []
    for name in ('_mach_gss_init_sec_context', '__ZN9NativeAES9MetaClassC1Ev',
                 '__ZN9NativeAES5startEP9IOService', '__GLOBAL__sub_I_NativeAES.cpp'):
        require(name in source_symbols and name in final_symbols, f'missing delta anchor: {name}')
        offset = final_symbols[name] - source_symbols[name]
        require(offset == delta, f'nonuniform text placement at {name}: {offset:#x} != {delta:#x}')
        samples.append(dict(name=name, old=hex(source_symbols[name]), final=hex(final_symbols[name])))

    start = final_symbols['__ZN9NativeAES9MetaClassC1Ev']
    end = final_symbols['__GLOBAL__sub_I_NativeAES.cpp'] + 0x4c
    require(start < end and image.offset(start, end-start) >= 0, 'NativeAES code range unavailable')
    fixups = image.fixups()
    mapped = image.mapped()
    def inside(address):
        return any(begin <= address < finish for begin, finish in mapped)
    target_names = {}
    for name, address in bindings.items():
        target_names.setdefault(address, []).append(name)
    consumers = {name: [] for name in bindings}
    transfers = []
    pc_references = []
    for site in range(start, end, 4):
        word, = struct.unpack_from('<I', data, image.offset(site, 4))
        opcode = word & 0xfc000000
        if opcode in (0x14000000, 0x94000000):
            target = site + signed(word & 0x3ffffff, 26) * 4
            require(inside(target), f'unmapped direct transfer {site:#x} -> {target:#x}')
            require(target not in {address+delta for address in bindings.values()},
                    f'unrepaired absolute transfer {site:#x} -> {target:#x}')
            if target in target_names:
                operation = 'BL' if opcode == 0x94000000 else 'B'
                transfers.append(dict(site=hex(site), target=hex(target), operation=operation,
                                      names=target_names[target]))
                for name in target_names[target]:
                    consumers[name].append(f'{operation} {site:#x}')
        elif word & 0x9f000000 in (0x10000000, 0x90000000):
            immediate = signed(((word >> 5) & 0x7ffff) << 2 | ((word >> 29) & 3), 21)
            adrp = bool(word & 0x80000000)
            target = (site & ~4095) + (immediate << 12) if adrp else site + immediate
            require(inside(target), f'unmapped PC reference {site:#x} -> {target:#x}')
            if adrp:
                require(not any(target == ((address+delta) & ~4095) for address in bindings.values()),
                        f'unrepaired ADRP page {site:#x} -> {target:#x}')
            else:
                require(target not in {address+delta for address in bindings.values()},
                        f'unrepaired ADR {site:#x} -> {target:#x}')
            pc_references.append(dict(site=hex(site), target=hex(target), kind='ADRP' if adrp else 'ADR'))
        elif word & 0x3b000000 == 0x18000000:
            target = site + signed((word >> 5) & 0x7ffff, 19) * 4
            require(inside(target), f'unmapped literal load {site:#x} -> {target:#x}')
            pc_references.append(dict(site=hex(site), target=hex(target), kind='LDR-literal'))
    require(len(transfers) == args.expected_branches,
            f'expected {args.expected_branches} direct AES bindings, found {len(transfers)}')
    _, resolved_refs, _ = scan(image.read(start, end-start), start)
    for site, target, kind in resolved_refs:
        require(inside(target), f'unmapped resolved {kind} reference {site:#x} -> {target:#x}')
        require(target not in {address+delta for address in bindings.values()},
                f'unrepaired resolved {kind} reference {site:#x} -> {target:#x}')
        for name in target_names.get(target, []):
            consumers[name].append(f'{kind} {site:#x}')

    meta = final_symbols['__ZN9NativeAES9metaClassE']
    superclass = final_symbols['__ZN9NativeAES10superClassE']
    family_meta = bindings['__ZN16IOAESAccelerator10gMetaClassE']
    require(struct.unpack('<Q', image.read(superclass, 8))[0] == family_meta,
            'NativeAES superclass pointer differs from original family metaclass')
    require(fixups[meta][0] == final_symbols['__ZN9NativeAES10gMetaClassE'],
            'NativeAES metaclass pointer is wrong')
    ctor = bindings['__ZN16IOAESAcceleratorC2EPK11OSMetaClass']
    dtor = bindings['__ZN16IOAESAcceleratorD2Ev']
    for name, address in (('constructor', ctor), ('destructor', dtor)):
        require(image.read(address, 4) == struct.pack('<I', 0xd503245f),
                f'original {name} lacks BTI c at {address:#x}')
    # MetaClass constructors load size 0x120 before calling OSMetaClass.
    class_size_words = [struct.unpack_from('<I', data, image.offset(site, 4))[0]
                        for site in (start+0x1c, final_symbols['__ZN9NativeAES9MetaClassC2Ev']+0x1c)]
    require(all(word == 0x52802403 for word in class_size_words),
            'NativeAES metaclass constructors do not encode class size 0x120')
    family_ctor = final_symbols['__ZN16IOAESAccelerator9MetaClassC1Ev']
    require(struct.unpack('<I', image.read(family_ctor+0x20, 4))[0] == 0x52802403,
            'original IOAESAccelerator metaclass does not encode class size 0x120')

    vtable = final_symbols['__ZTV9NativeAES']
    family_vtable = final_symbols['__ZTV16IOAESAccelerator']
    next_table = final_symbols['__ZTVN9NativeAES9MetaClassE']
    slots = (next_table - vtable - 16) // 8 - 1  # trailing zero word
    require(slots == 285, f'unexpected NativeAES vtable size: {slots}')
    differences = []
    absolute_pointers = []
    for index in range(slots):
        site = vtable + 16 + index*8
        original_site = family_vtable + 16 + index*8
        own = fixups.get(site)
        family = fixups.get(original_site)
        require(own is not None and family is not None, f'vtable slot {index} has no chain fixup')
        require(inside(own[0]), f'vtable slot {index} points outside mapped image')
        if own[0] != family[0]:
            differences.append(dict(slot=index, own=hex(own[0]), family=hex(family[0])))
        else:
            for name in target_names.get(own[0], []):
                consumers[name].append(f'vtable[{index}]')
        if own[0] in target_names:
            absolute_pointers.append(index)
    require([d['slot'] for d in differences] == [0, 1, 7, 16, 190, 215, 221, 272, 273, 274, 275, 276],
            f'unexpected NativeAES vtable differences: {differences}')
    require(len(absolute_pointers) == args.expected_absolute_pointers,
            f'expected {args.expected_absolute_pointers} inherited AES pointers, found {len(absolute_pointers)}')
    consumers['__ZN16IOAESAccelerator10gMetaClassE'].append(f'superClass {superclass:#x}')
    unused = [name for name, sites in consumers.items() if not sites]
    overridden = {
        '__ZN16IOAESAcceleratorD0Ev', '__ZN16IOAESAcceleratorD1Ev',
        '__ZN16IOAESAccelerator5startEP9IOService',
        '__ZN16IOAESAccelerator14isKeySupportedEj',
        '__ZN16IOAESAccelerator16getAlgorithmNameEv',
        '__ZN16IOAESAccelerator19getSupportedOptionsEv',
        '__ZN16IOAESAccelerator20callPlatformFunctionEPK8OSSymbolbPvS3_S3_S3_',
        '__ZNK16IOAESAccelerator11getWorkLoopEv',
        '__ZNK16IOAESAccelerator12getMetaClassEv',
    }
    overridden.update(name for name in bindings if name.startswith('__ZN16IOAESAccelerator10performAESE'))
    require(set(unused) == overridden,
            f'unexplained unused bindings: {set(unused) ^ overridden}')
    report = dict(status='PASS', kernel=str(args.kernel), standalone=str(args.standalone),
                  delta=hex(delta), anchors=samples, bindings=len(bindings),
                  direct_transfers=transfers, pc_references=pc_references,
                  inherited_aes_vtable_slots=absolute_pointers,
                  vtable_differences=differences,
                  consumers=consumers, unused_bindings={name: 'overridden by NativeAES' for name in unused},
                  class_size='0x120', superclass=hex(family_meta))
    args.report.write_text(json.dumps(report, indent=2) + '\n')
    print(f'PASS: 22 bindings, {len(transfers)} transfers, {len(absolute_pointers)} inherited pointers, '
          f'{slots} vtable slots, delta {delta:#x}; report {args.report}')


if __name__ == '__main__':
    try:
        main()
    except (ValueError, KeyError, IndexError) as error:
        raise SystemExit(f'FAIL: {error}')
