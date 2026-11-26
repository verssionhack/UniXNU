#!/usr/bin/env python3
"""Freeze r3 SHA256 audit manifest and re-verify all 7 previously frozen r101/M1/r2 manifests."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[4]
EV = ROOT / 'out/liuqin-r101-gpu-host-gates-r3/evidence'
STAGE = ROOT / 'out/liuqin-r101-gpu-host-gates-r3/stage'
SCRIPTS = ROOT / 'scripts/liuqin-analysis/r101/gpu-host-gates-r3'


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def verify_prior_manifests() -> dict[str, str]:
    frozen = [
        ('out/liuqin-r101-gpu-host-gates-r2/evidence/audit-manifest.json', '774b0e8d0671bacf3f240b1518e4f0903932c4e3cfa8c6804f70a99e8eab5512'),
        ('out/liuqin-r101-gpu-host-gates/evidence/audit-manifest.json', '2973fe3ceb19c62ff29f813c178c52d01167810660f4a1c0a6812e667aa72204'),
        ('out/liuqin-r101-gpu-m1/evidence/research-manifest.json', 'dd2707afdeff822a06f4f85833b013ce92d6fafa59ffbe61e4e530cfbafbd5ac'),
        ('out/liuqin-r101-layout-audit/evidence/audit-manifest.json', 'be61f7510a83701f04fdc9557b53ca6326365358e1f0ccd878a3e0ad15af9878'),
        ('out/liuqin-r101-skylight-audit/evidence/audit-manifest.json', '102e9d8289e925999ef5bba888e7a9679fc1d4f5a28d20203153e7c0f5c7eaf4'),
        ('out/liuqin-r101-a7-work/evidence/result-manifest.json', 'fba43e50f7e9b9c493166b2fb768bed08dbf3241f6e83cc33f03dfc328661afb'),
        ('out/liuqin-r101-a7-work/evidence/host-manifest.json', 'cfae2cc7a720b7e5e5350b5b24e79e9efe9d29b927e0f2e07f2c282aaedc948b'),
    ]
    checked = {}
    for rel, expected in frozen:
        actual = sha(ROOT / rel)
        assert actual == expected, f'Frozen manifest changed! {rel}: {actual} != {expected}'
        checked[rel] = actual
    return checked


def main() -> None:
    frozen_ok = verify_prior_manifests()

    # Also verify r2 manifest's hashed files remain intact
    r2_m = json.loads((ROOT / 'out/liuqin-r101-gpu-host-gates-r2/evidence/audit-manifest.json').read_text())
    for rel, expected in r2_m['files'].items():
        actual = sha(ROOT / rel)
        assert actual == expected, f'Frozen r2 file changed! {rel}: {actual} != {expected}'

    # Run M1 verifier (read-only)
    m1_res = subprocess.run(
        ['python3', str(ROOT / 'scripts/liuqin-analysis/r101/gpu-m1/verify-research.py')],
        capture_output=True, text=True, check=True,
    )

    files = {}
    for base in (EV, STAGE, SCRIPTS):
        if not base.exists():
            continue
        for p in sorted(base.rglob('*')):
            if p.is_file() and p.name != 'audit-manifest.json' and '__pycache__' not in p.parts:
                files[str(p.relative_to(ROOT))] = sha(p)

    manifest = {
        'scope': 'r101 GPU host-gates r3 evidence, scripts, report, and compiled reference DTB; all 7 prior frozen manifests and r2 files verified intact',
        'frozen_manifests_verified': frozen_ok,
        'r2_files_verified_count': len(r2_m['files']),
        'gpu_m1_verify_stdout_tail': m1_res.stdout.strip().splitlines()[-3:],
        'files': files,
    }
    mpath = EV / 'audit-manifest.json'
    mpath.write_text(json.dumps(manifest, indent=2) + '\n')
    print(f'PASS: wrote {mpath.relative_to(ROOT)} ({len(files)} files), SHA256={sha(mpath)}')
    print(f'PASS: all {len(frozen_ok)} prior frozen manifests + {len(r2_m["files"])} r2 files verified intact')
    print(f'PASS: gpu-m1/verify-research.py -> {manifest["gpu_m1_verify_stdout_tail"]}')


if __name__ == '__main__':
    main()
