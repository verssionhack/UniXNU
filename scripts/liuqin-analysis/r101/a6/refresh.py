#!/usr/bin/env python3
from pathlib import Path
import difflib,hashlib,json
R=Path(__file__).resolve().parents[4];W=R/'out/liuqin-r101-a6-work';A=R/'out/liuqin-r101-a5r1-work';p=json.loads((W/'preparation.json').read_text());patch='';delta=''
assert not (W/'evidence/a/validation-summary.json').exists(),'Preserve packaged images'
for rel in p['changed_kernel_files']:
 path=W/'frozen-r100b-source'/rel;old=path.read_text() if path.exists() else '';new=(W/'staged-sources'/rel).read_text();before=(A/'evidence/a/sources'/rel).read_text()
 patch+=''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/'+rel if old else '/dev/null',tofile='b/'+rel));delta+=''.join(difflib.unified_diff(before.splitlines(True),new.splitlines(True),fromfile='a/'+rel,tofile='b/'+rel))
(W/'observer.patch').write_text(patch);(W/'evidence/A5r1-to-A6.patch').write_text(delta)
for v in ['a','b']:next((W/f'device-{v}/patches/xnu').glob('*liuqin-r101.patch')).write_text(patch)
p['observer_patch_sha256']=hashlib.sha256(patch.encode()).hexdigest();(W/'preparation.json').write_text(json.dumps(p,indent=2)+'\n')
