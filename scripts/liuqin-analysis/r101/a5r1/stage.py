#!/usr/bin/env python3
"""Correct active notifier ownership; retain accepted kernel behavior and A5 bounds."""
from pathlib import Path
import difflib,hashlib,json,shutil
R=Path(__file__).resolve().parents[4];H=Path(__file__).resolve().parent;A=R/'out/liuqin-r101-a5-work';W=R/'out/liuqin-r101-a5r1-work'
assert (H/'liuqin-r101-a5r1-host-audit.md').is_file();assert not W.exists();W.mkdir();E=W/'evidence';E.mkdir()
shutil.copytree(R/'out/liuqin-r101-a5-audit',E/'host-audit')
for v in ['a','b']:shutil.copytree(A/f'device-{v}',W/f'device-{v}',symlinks=True)
(W/'frozen-r100b-source').symlink_to(A/'frozen-r100b-source',target_is_directory=True);shutil.copy2(A/'frozen-r100b-source-sha256.json',W/'frozen-r100b-source-sha256.json')
p=json.loads((A/'preparation.json').read_text());texts={r:(A/'evidence/a/sources'/r).read_text() for r in p['changed_kernel_files']}
r='osfmk/kern/liuqin_r101_walk.inc';s=texts[r].replace('version=5','version=6')
for old,new in [('0x275739790','0x6e180'),('0x2757397a0','0x6e190'),('0x275739818','0x6e1a0'),('0x275739828','0x6e1b0'),('0x2757397d0','0x6e0d8')]:s=s.replace(old,new)
s=s.replace('globals[i].address+slide','globals[i].address+(i<5?base:slide)').replace('slide+0x6e1a0','base+0x6e1a0').replace('slide+0x6e180','base+0x6e180')
s=s.replace('        {"IVAR0",0x2728f5438},{"IVAR1",0x2728f5448},{"ARRIV",0x1eb1deb78},{"SETIV",0x1eb1dee90}', '        {"ARRIV",0x1eb1deb78},{"SETIV",0x1eb1dee90}')
texts[r]=s
patch='';delta=''
for rel,new in texts.items():
 oldpath=W/'frozen-r100b-source'/rel;old=oldpath.read_text() if oldpath.exists() else '';before=(A/'evidence/a/sources'/rel).read_text()
 patch+=''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/'+rel if old else '/dev/null',tofile='b/'+rel));delta+=''.join(difflib.unified_diff(before.splitlines(True),new.splitlines(True),fromfile='a/'+rel,tofile='b/'+rel))
 dest=W/'staged-sources'/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(new)
(W/'observer.patch').write_text(patch);(E/'A5-to-A5r1.patch').write_text(delta)
for v in ['a','b']:next((W/f'device-{v}/patches/xnu').glob('*liuqin-r101.patch')).write_text(patch)
p.update(observer_revision='A5r1',parent_A5_boot_sha256='c9b607731daa319bc599b6c8adf5b6d3bbb3d1daa8dcf471fa3787829e18ff5d',observer_patch_sha256=hashlib.sha256(patch.encode()).hexdigest());(W/'preparation.json').write_text(json.dumps(p,indent=2)+'\n')
for n in ['analysis-rule.json','analysis-rule-frozen.py.txt','host-inputs.json']:shutil.copy2(A/'evidence'/n,E/n)
print(W)
