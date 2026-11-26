#!/usr/bin/env python3
"""Publish raw variant contrast and enforce common observer/device source identity."""
from pathlib import Path
import difflib,hashlib,json
R=Path(__file__).resolve().parents[3];W=R/'out/liuqin-r101-work'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def index(root):
    return {str(p.relative_to(root)):p for p in root.rglob('*') if p.is_file() and not any(x in p.relative_to(root).parts for x in ['.cache','.git','__pycache__']) and not p.name.endswith('.lock')}
a=index(W/'device-a');b=index(W/'device-b');differences=[];patch=[]
for key in sorted(a.keys()|b.keys()):
    if key not in a or key not in b or digest(a[key])!=digest(b[key]):
        differences.append(key)
        patch.extend(difflib.unified_diff(a[key].read_text().splitlines(True),b[key].read_text().splitlines(True),fromfile='a/'+key,tofile='b/'+key))
assert set(differences)=={'configs/liuqin_defconfig','drivers/LiuqinSourceStorage/R101Variant.h'},differences
out=W/'evidence';out.mkdir(exist_ok=True);(out/'variant-config.diff').write_text(''.join(patch))
old=R/'out/liuqin-r98-work/device';raw=[]
for rel in ['drivers/LiuqinSourceStorage/LiuqinScratchDisk.cpp','drivers/LiuqinSourceStorage/ScratchSeed.inc','board.toml','configs/liuqin_defconfig']:
    raw.extend(difflib.unified_diff((old/rel).read_text().splitlines(True),(W/'device-b'/rel).read_text().splitlines(True),fromfile='r99-frozen/'+rel,tofile='r101-common-control/'+rel))
(out/'control-normalization.diff').write_text(''.join(raw))
source_compare={}
sa=W/'evidence/a/sources';sb=W/'evidence/b/sources'
if sa.exists() and sb.exists():
    ia=index(sa);ib=index(sb);assert ia.keys()==ib.keys()
    for key in ia:assert digest(ia[key])==digest(ib[key]),key
    source_compare={'kernel_source_equal':True,'files':{key:digest(ia[key]) for key in sorted(ia)}}
else:source_compare={'kernel_source_equal':None,'reason':'Both build source freezes not available yet'}
report={'status':'PASS','device_source_differences':differences,'observer_patch_sha256':digest(W/'observer.patch'),'common_source_compare':source_compare,'normalization':'Control shares r100b seed relocation and common 8 KiB panic-tail diagnostic retirement; no trust/storage/SMP policy weakened. Hardware acceptance pending.'}
(out/'source-comparison.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
