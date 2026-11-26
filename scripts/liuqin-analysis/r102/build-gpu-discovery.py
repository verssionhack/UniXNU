#!/usr/bin/env python3
"""Compile r102-p12 read-only SM8475 GPU platform discovery probe archive (libLiuqinGpuDiscovery.a)."""
from pathlib import Path
import json
import os
import subprocess


def main():
    tree = Path.cwd()
    device = Path(os.environ['UNIXNU_DEVICE'])
    out = tree / 'build/liuqin-gpu-discovery'
    out.mkdir(parents=True, exist_ok=True)
    source = device / 'drivers/LiuqinGpuDiscovery/LiuqinGpuDiscovery.cpp'
    record = json.loads(
        (tree / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/iokit/DEVELOPMENT/IOPlatformExpert.cpo.json')
        .read_text().strip().rstrip(',')
    )
    obj = out / 'LiuqinGpuDiscovery.o'
    cmd = []
    args = record['arguments']
    i = 0
    while i < len(args):
        v = args[i]
        if v == record['file']:
            cmd.append(str(source))
        elif v == '-o':
            cmd += ['-o', str(obj)]
            i += 1
        elif v in ('-MF', '-MT', '-MJ'):
            i += 1
        elif v == '-Xclang' and args[i + 1].startswith('-W'):
            i += 1
        elif not v.startswith('-W'):
            cmd.append(v)
        i += 1
    cmd += [
        '-I', str(tree / '.cache/xnu-work/osfmk'),
        '-Wall', '-Wextra', '-Werror',
        '-Wno-unused-parameter', '-Wno-deprecated-declarations',
        '-Wno-overriding-option', '-Wno-c99-designator',
        '-Wno-missing-designated-field-initializers',
        '-Wno-deprecated-enum-enum-conversion',
        '-Wno-deprecated-anon-enum-enum-conversion',
    ]
    res = subprocess.run(cmd, cwd=record['directory'], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    (out / 'compile.log').write_text(res.stdout)
    if res.returncode != 0:
        raise SystemExit(f'LiuqinGpuDiscovery compile failed:\n{res.stdout[-5000:]}')
    archive = out / 'libLiuqinGpuDiscovery.a'
    archive.unlink(missing_ok=True)
    subprocess.run(['llvm-ar', 'rcsD', str(archive), str(obj)], check=True)
    print(f'PASS: built {archive} ({archive.stat().st_size} B, 0 warnings)')


if __name__ == '__main__':
    main()
