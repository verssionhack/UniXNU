#!/usr/bin/env python3
from pathlib import Path
import hashlib,json
R=Path(__file__).resolve().parents[4];H=Path(__file__).resolve().parent;W=R/'out/liuqin-r101-a4-work';E=W/'evidence'
assert json.loads((E/'host-verification.json').read_text())['status']=='PASS'
assert not (E/'review-manifest.json').exists()
files=[p for p in H.rglob('*') if p.is_file() and '__pycache__' not in p.parts]
files += [p for p in E.rglob('*') if p.is_file()]
files += [W/n for n in ['preparation.json','observer.patch','build.log','build-attempt1.log','package.log','verify.log']]
files += [R/'scripts/liuqin-analysis/r101'/n for n in ['guards.py','analyze.py','replay-exact.py','validate-user-frames.py','a2/analyze-a2.py','a2/coverage.py','a2r1/assessment.py']]
manifest={}
for p in files:
 with p.open('rb') as f:manifest[str(p.relative_to(R))]=hashlib.file_digest(f,'sha256').hexdigest()
(E/'review-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print('Frozen',len(manifest),'files')
