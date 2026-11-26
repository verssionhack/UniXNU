#!/usr/bin/env python3
"""Compile existing frozen comparator sources only, never an A730 driver/image."""
from pathlib import Path
import concurrent.futures
import hashlib
import json
import struct
import subprocess

R = Path(__file__).resolve().parents[4]
B = R / 'out/liuqin-r101-gpu-host-gates'
O = B / 'objects'
O.mkdir(parents=True, exist_ok=True)
S = R / 'out/liuqin-r101-gpu-m1/unixnu-comparator'
T = R / 'out/liuqin/macos-27.3-26C5035r/liuqin/tree'
recipe = T / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/iokit/DEVELOPMENT/IOPlatformExpert.cpo.json'
rec = json.loads(recipe.read_text().strip().rstrip(','))
groups = ['Adreno740', 'Sm8550Platform', 'AdrenoFirmware', 'AdrenoPM4', 'ArmSmmu4K']
sources = [p for group in groups for p in sorted((S/group).iterdir())
           if p.suffix in ('.cpp', '.c') and not p.name.startswith(('test_', 'test-')) and not p.stem.endswith('Test')]

def measure(raw):
    assert struct.unpack_from('<I', raw)[0] == 0xfeedfacf
    at = 32
    rows = []
    for _ in range(struct.unpack_from('<I', raw, 16)[0]):
        cmd, size = struct.unpack_from('<II', raw, at)
        if cmd == 0x19:
            for i in range(struct.unpack_from('<I', raw, at+64)[0]):
                q = at+72+80*i
                name = raw[q:q+16].split(b'\0')[0].decode()
                seg = raw[q+16:q+32].split(b'\0')[0].decode()
                length = struct.unpack_from('<Q', raw, q+40)[0]
                flags = struct.unpack_from('<I', raw, q+64)[0]
                rows.append({'segment': seg, 'section': name, 'bytes': length, 'flags': hex(flags)})
        at += size
    return rows

def build(src):
    out = O / src.parent.name / (src.name+'.o')
    out.parent.mkdir(exist_ok=True)
    args = rec['arguments']
    cmd = []
    i = 0
    while i < len(args):
        v = args[i]
        if v == rec['file']:
            cmd.append(str(src))
        elif v == '-o':
            cmd += ['-o', str(out)]
            i += 1
        elif v in ('-MF', '-MJ'):
            i += 1
        elif v in ('-MD', '-MP'):
            pass
        elif v == '-xc++' and src.suffix == '.c':
            cmd.append('-xc')
        elif src.suffix == '.c' and v.startswith('-std='):
            cmd.append('-std=gnu11')
        elif v.startswith('-W'):
            pass
        else:
            cmd.append(v)
        i += 1
    cmd += ['-Wno-everything', '-I', str(T/'.cache/xnu-work/osfmk')]
    for group in groups:
        cmd += ['-I', str(S/group)]
    result = subprocess.run(cmd, cwd=rec['directory'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    (out.with_suffix('.log')).write_text(result.stdout)
    (out.with_suffix('.command.json')).write_text(json.dumps(cmd, indent=2)+'\n')
    row = {'source': str(src.relative_to(R)), 'sha256': hashlib.sha256(src.read_bytes()).hexdigest(), 'group': src.parent.name, 'returncode': result.returncode}
    if result.returncode == 0:
        row.update(object=str(out.relative_to(R)), sections=measure(out.read_bytes()))
    else:
        row['diagnostic_tail'] = result.stdout[-1500:]
    return row

with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
    rows = list(executor.map(build, sources))
summary = {}
for group in groups:
    members = [x for x in rows if x['group'] == group]
    totals = {}
    for member in members:
        for section in member.get('sections', []):
            name = section['segment']+','+section['section']
            totals[name] = totals.get(name, 0) + section['bytes']
    summary[group] = {'attempted': len(members), 'compiled': sum(x['returncode'] == 0 for x in members), 'section_sum_bytes': totals}
(B/'evidence/compiled-reference.json').write_text(json.dumps({'scope': 'unmodified frozen reference sources; exact per-object sizes, not a linked closure or A730 fit proof; warnings suppressed for measurement', 'recipe': str(recipe.relative_to(R)), 'groups': summary, 'objects': rows}, indent=2)+'\n')
print(json.dumps(summary, indent=2))
print('Failures:', [(x['group'], Path(x['source']).name) for x in rows if x['returncode']])
