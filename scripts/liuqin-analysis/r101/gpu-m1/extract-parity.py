#!/usr/bin/env python3
"""Extract reference data only. Never emits driver code or a boot image."""
from pathlib import Path
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[4]
BASE = ROOT / 'out/liuqin-r101-gpu-m1'
LINUX = BASE / 'linux-release-clean'
OUT = BASE / 'evidence'
ADRENO = LINUX / 'drivers/gpu/drm/msm/adreno'
XML = LINUX / 'drivers/gpu/drm/msm/registers/adreno'
NATIVE = BASE / 'unixnu-comparator/Adreno740'

def strip_comments(s):
    return re.sub(r'/\*.*?\*/|//[^\n]*', '', s, flags=re.S)

def block(text, name):
    m = re.search(r'\b' + re.escape(name) + r'\s*\[\s*\](?:\[\d+\])?\s*=\s*\{(.*?)\};', text, re.S)
    assert m, name
    return strip_comments(m[1])

def write(name, data):
    (OUT / name).write_text(json.dumps(data, indent=2) + '\n')

order = ['A2XX', 'A3XX', 'A4XX', 'A5XX', 'A6XX', 'A7XX', 'A8XX']
def matches(v):
    if not v:
        return True
    if '-' in v:
        a, b = v.split('-', 1)
        return (order.index(a) if a else 0) <= order.index('A7XX') <= (order.index(b) if b else 6)
    return v == 'A7XX'

registers = {}
for filename in ['a6xx.xml', 'a6xx_gmu.xml', 'adreno_common.xml']:
    text = (XML / filename).read_text()
    for m in re.finditer(r'<reg(?:32|64)\s+offset="(0x[\da-fA-F]+)"\s+name="([^"]+)"([^>]*)>', text):
        domain = list(re.finditer(r'<domain\s+name="([^"]+)"', text[:m.start()]))
        if not domain or domain[-1][1] != 'A6XX':
            continue
        variant = re.search(r'variants="([^"]+)"', m[3])
        if matches(variant[1] if variant else None):
            registers.setdefault(m[2], []).append({'dword': int(m[1], 16), 'xml': filename})

def resolve(name):
    name = re.sub(r'^REG_A\dXX_', '', name)
    hits = registers.get(name, [])
    offsets = {x['dword'] for x in hits}
    assert len(offsets) == 1, (name, hits)
    return offsets.pop()

catalog = (ADRENO / 'a6xx_catalog.c').read_text()
hwcg = {}
for chip in ['a730', 'a740']:
    rows = []
    for m in re.finditer(r'\{\s*(REG_\w+)\s*,\s*(0x[\da-fA-F]+)\s*\}', block(catalog, chip + '_hwcg')):
        rows.append({'name': m[1], 'dword': resolve(m[1]), 'byte_offset': resolve(m[1]) * 4, 'value': int(m[2], 16)})
    assert rows
    hwcg[chip] = rows
native = (NATIVE / 'NativeAdrenoA740HwInit.h').read_text()
native_hwcg = [(int(a, 16), int(b, 16)) for a, b in re.findall(r'\{(0x[\da-f]+),(0x[\da-f]+)\}', block(native, 'NativeAdrenoA740Hwcg'))]
linux_hwcg = [(x['dword'], x['value']) for x in hwcg['a740']]
hwcg['native_a740_equal_linux_a740'] = native_hwcg == linux_hwcg
a = {x['dword']: x for x in hwcg['a730']}
b = {x['dword']: x for x in hwcg['a740']}
hwcg['a730_to_a740_changes'] = [{'dword': k, 'a730': a.get(k), 'a740': b.get(k)} for k in sorted(a.keys() | b.keys()) if a.get(k) != b.get(k)]
write('clock-gating-parity.json', hwcg)

protect = []
for i, line in enumerate([x.strip() for x in block(catalog, 'a730_protect_regs').splitlines() if x.strip()]):
    m = re.fullmatch(r'A6XX_PROTECT_(RDONLY|NORDWR)\((0x[\da-fA-F]+),\s*(0x[\da-fA-F]+)\),?', line)
    if not m:
        assert line.rstrip(',') == '0', line
        protect.append({'index': i, 'written': False})
        continue
    reg, length = int(m[2], 16), int(m[3], 16)
    value = reg | (length << 18) | ((1 << 31) if m[1] == 'NORDWR' else 0)
    protect.append({'index': i, 'written': True, 'access': m[1], 'start_dword': reg, 'range_length_field': length, 'encoded': value})
native_protect = [(int(a), int(b, 16)) for a, b in re.findall(r'\{\s*(\d+),(0x[\da-f]+)\}', block(native, 'NativeAdrenoA740Protect'))]
assert len(protect) == 48
write('protection-parity.json', {'shared_by_linux_a730_and_a740': True, 'slots': protect, 'native_a740_equal': native_protect == [(x['index'], x['encoded']) for x in protect if x['written']]})

power = []
for expr in block(catalog, 'a7xx_pwrup_reglist_regs').split(','):
    expr = expr.strip()
    if not expr:
        continue
    m = re.fullmatch(r'(REG_\w+)(?:\s*\+\s*(\d+))?', expr)
    assert m, expr
    value = resolve(m[1]) + int(m[2] or 0)
    power.append({'expression': expr, 'dword': value, 'byte_offset': value * 4})
native_power = [int(x, 16) for x in re.findall(r'0x([\da-fA-F]{8}),', (NATIVE / 'NativeAdrenoPwrupRegs.h').read_text())]
write('powerup-parity.json', {'linux_shared_a730_a740': power, 'native_a740_dwords': native_power, 'linux_only_dwords': sorted({x['dword'] for x in power} - set(native_power)), 'native_only_dwords': sorted(set(native_power) - {x['dword'] for x in power}), 'lock_header_bytes': 16, 'linux_pair_bytes': len(power) * 8, 'native_pair_bytes': len(native_power) * 8})

hfi = (ADRENO / 'a6xx_hfi.c').read_text()
m = re.search(r'static void a730_build_bw_table\(.*?\n\}', hfi, re.S)
assert m
bw = [[0] * 3 for _ in range(12)]
for level, command, value in re.findall(r'ddr_cmds_data\[(\d+)\]\[(\d+)\] = (0x[\da-f]+);', m[0]):
    bw[int(level)][int(command)] = int(value, 16)
write('a730-bandwidth-table.json', {'ddr_runtime_cmd_db_keys': ['SH0', 'MC0', 'ACV'], 'ddr_commands': 3, 'ddr_wait_mask': 7, 'levels': bw, 'cnoc_runtime_key': 'CN0', 'cnoc_wait_mask': 1, 'cnoc_data': [[0x40000000], [0x60000001]], 'arc_vote_formula': '(primary_level << 16) | (secondary_index << 8) | primary_index', 'arc_primary_keys': ['gfx.lvl', 'cx.lvl'], 'arc_secondary': ['gmxc.lvl', 'mx.lvl fallback'], 'runtime_command_database_captured': False})

# Scalar offsets named in both the Linux XML and existing generated XNU header.
offsets = []
for name, value in re.findall(r'^#define A740_(\w+) (0x[\da-fA-F]+)$', native, re.M):
    entries = registers.get(name, [])
    hits = {x['dword'] for x in entries}
    delta = (0x03d6a000 - 0x03d00000) // 4 if entries and all(x['xml'] == 'a6xx_gmu.xml' for x in entries) else 0
    if name == 'CP_PROTECT':
        hits = {int(re.search(r'<array offset="(0x[\da-f]+)" name="CP_PROTECT"', (XML / 'a6xx.xml').read_text())[1], 16)}
    offsets.append({'name': name, 'native_gpu_relative_dword': int(value, 16), 'linux_xml_dwords': sorted(hits), 'gmu_to_gpu_dword_delta': delta, 'equal_after_coordinate_normalization': {x + delta for x in hits} == {int(value, 16)}})
write('register-offset-parity.json', offsets)
print(json.dumps({'a730_hwcg_rows': len(hwcg['a730']), 'a740_hwcg_rows': len(hwcg['a740']), 'hwcg_changes': len(hwcg['a730_to_a740_changes']), 'native_hwcg_equal': hwcg['native_a740_equal_linux_a740'], 'protect_equal': native_protect == [(x['index'], x['encoded']) for x in protect if x['written']], 'linux_powerup_rows': len(power), 'native_powerup_rows': len(native_power), 'offsets_compared': len(offsets)}, indent=2))
