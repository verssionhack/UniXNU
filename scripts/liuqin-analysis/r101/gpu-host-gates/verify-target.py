#!/usr/bin/env python3
"""Verify saved target disassembly against pinned cache bytes, without imports with side effects."""
from pathlib import Path
import hashlib
import json
import mmap
import re
import struct

R = Path(__file__).resolve().parents[4]
E = R / 'out/liuqin-r101-gpu-host-gates/evidence'
C = Path('/media/disk_4/unixnu_workspace/ramdisk_dir/liuqin-r101-host-cache')
manifest = json.loads((R/'out/liuqin-r101-work/evidence/review-A1/host-cache-manifest.json').read_text())
maps = []
entries = {}
opened = {}
verified = {}
for entry in manifest:
    p = C / Path(entry['path']).name
    entries[p] = entry
    with p.open('rb') as f:
        header = f.read(104)
        assert header[:7] == b'dyld_v1' and header[88:104].hex() == entry['uuid']
        offset, count = struct.unpack_from('<II', header, 16)
        f.seek(offset)
        for base, size, off, _, prot in struct.iter_unpack('<QQQII', f.read(count*32)):
            maps.append((base, size, off, p))
def read(address, length):
    hits = [m for m in maps if m[0] <= address and address+length <= m[0]+m[1]]
    assert len(hits) == 1
    base, _, off, p = hits[0]
    if p not in opened:
        with p.open('rb') as f:
            digest = hashlib.file_digest(f, 'sha256').hexdigest()
            assert digest == entries[p]['sha256']
            opened[p] = mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ)
        verified[str(p)] = {'sha256': digest, 'uuid': entries[p]['uuid']}
    return opened[p][off+address-base:off+address-base+length]
counts = {}
for path in sorted(E.glob('*.asm.txt')):
    if path.name == 'hfi-table-init.asm.txt':
        continue  # CM3 Thumb bytes are independently checked by audit-hfi-init.py.
    count = 0
    for line in path.read_text().splitlines():
        m = re.match(r'0x([\da-f]+):\s+((?:[\da-f]{2} ){3}[\da-f]{2})\s', line)
        if m:
            assert read(int(m[1], 16), 4) == bytes.fromhex(m[2]), (path, line)
            count += 1
    assert count
    counts[path.name] = count
images = {}
for name in ['IOGPU', 'Metal', 'IOSurface']:
    data = json.loads((E/(name+'.toc.json')).read_text())
    images[name] = {cmd['load_cmd']: cmd for cmd in data['loads'] if cmd['load_cmd'] in ['LC_UUID', 'LC_ID_DYLIB', 'LC_SOURCE_VERSION']}
    segments = [cmd for cmd in data['loads'] if cmd['load_cmd'] == 'LC_SEGMENT_64']
    for segment in segments:
        begin, size = segment['addr'], segment['memsz']
        if size:
            # Hash every backing mapping touched by this image, including ObjC
            # metadata and shared LINKEDIT, rather than just its instructions.
            end = begin+size
            for base, length, _, _ in maps:
                if begin < base+length and base < end:
                    read(max(begin, base), 1)
    base = next(cmd['addr'] for cmd in segments if cmd['name'] == '__TEXT')
    header = read(base, 32)
    commands = read(base+32, struct.unpack_from('<I', header, 20)[0])
    pos = 0
    found_uuid = None
    for _ in range(struct.unpack_from('<I', header, 16)[0]):
        cmd, size = struct.unpack_from('<II', commands, pos)
        if cmd == 0x1b:
            found_uuid = commands[pos+8:pos+24].hex()
        pos += size
    assert found_uuid == images[name]['LC_UUID']['uuid'].replace('-', '').lower()
source = (R/'drivers/AdrenoMetal/NativeBridgeMetalFrontend.mm').read_text() + (R/'drivers/AdrenoMetal/OfflineMetalFrontend.mm').read_text()
calls = sorted(set(re.findall(r'\b(IOSurface[A-Za-z0-9]+)\(', source)))
symbols = (E/'IOSurface.symbols.txt').read_text()
surface = {name: bool(re.search(r'\t_'+re.escape(name)+r'\s*$', symbols, re.M)) for name in calls}
result = {'scope': 'pinned binary identities, instruction bytes, source discovery contract and symbol-presence audit; not a full build/runtime ABI qualification',
          'images': images, 'cache_files_verified': verified, 'assembly_instructions_verified': counts,
          'IOSurface_called_function_symbol_presence': surface,
          'missing_framework_SDK': ['Metal.framework', 'IOGPU.framework'],
          'patched_Darwin_Mesa_tree_present': False, 'full_ABI_gate': 'OPEN'}
(E/'target-abi-verification.json').write_text(json.dumps(result, indent=2)+'\n')
print('PASS: pinned instruction bytes', sum(counts.values()), '; IOSurface symbol checks', len(surface))
print('Missing IOSurface symbols:', [name for name, present in surface.items() if not present])
