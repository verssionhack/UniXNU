#!/usr/bin/env python3
"""Rehash the frozen Milestone-1 artifacts, including symlink target bytes."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parents[4]
manifest = ROOT / 'out/liuqin-r101-gpu-m1/evidence/research-manifest.json'
data = json.loads(manifest.read_text())
for name, expected in data['files'].items():
    p = ROOT / name
    assert p.is_file() and not p.is_symlink(), name
    assert hashlib.sha256(p.read_bytes()).hexdigest() == expected, name
for name, expected in data['symlinks'].items():
    p = ROOT / name
    assert p.is_symlink() and str(p.readlink()) == expected, name
print(f"PASS: {len(data['files'])} regular files and {len(data['symlinks'])} symlink targets match the frozen manifest")
