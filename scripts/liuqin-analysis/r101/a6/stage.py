#!/usr/bin/env python3
"""A6 public publication-state observation; behavior remains accepted A3r1."""
from pathlib import Path
import difflib,hashlib,json,shutil
R=Path(__file__).resolve().parents[4];H=Path(__file__).resolve().parent;A=R/'out/liuqin-r101-a5r1-work';W=R/'out/liuqin-r101-a6-work'
assert not W.exists();W.mkdir();E=W/'evidence';E.mkdir()
assert json.loads((A/'evidence/a/boot-A5r1-20261121-102912/boot-record.json').read_text())['capture_status']=='complete-observer-capture'
for v in ['a','b']:shutil.copytree(A/f'device-{v}',W/f'device-{v}',symlinks=True)
(W/'frozen-r100b-source').symlink_to(A/'frozen-r100b-source',target_is_directory=True);shutil.copy2(A/'frozen-r100b-source-sha256.json',W/'frozen-r100b-source-sha256.json')
p=json.loads((A/'preparation.json').read_text());texts={r:(A/'evidence/a/sources'/r).read_text() for r in p['changed_kernel_files']}
r='iokit/Kernel/IOUserClient.cpp';s=texts[r];needle='extern "C" void liuqin_r104_timesync_dump(void) {';assert s.count(needle)==1;s=s.replace(needle,(H/'publication-observer.inc').read_text()+'\n'+needle)
needle='    }\n    liuqin_r101_emit(1,"LQ102 TIMESYNC_COVERAGE:';assert s.count(needle)==1;s=s.replace(needle,'        r106_publication(OSDynamicCast(IOService,node));\n'+needle);texts[r]=s
patch='';delta=''
for rel,new in texts.items():
 oldpath=W/'frozen-r100b-source'/rel;old=oldpath.read_text() if oldpath.exists() else '';before=(A/'evidence/a/sources'/rel).read_text()
 patch+=''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/'+rel if old else '/dev/null',tofile='b/'+rel));delta+=''.join(difflib.unified_diff(before.splitlines(True),new.splitlines(True),fromfile='a/'+rel,tofile='b/'+rel))
 dest=W/'staged-sources'/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(new)
(W/'observer.patch').write_text(patch);(E/'A5r1-to-A6.patch').write_text(delta)
for v in ['a','b']:next((W/f'device-{v}/patches/xnu').glob('*liuqin-r101.patch')).write_text(patch)
p.update(observer_revision='A6',parent_A5r1_boot_sha256='013687e48b19f1e17f3de8d8dff5d31fabf3f2f23cb182f4f4a98142aa10a434',observer_patch_sha256=hashlib.sha256(patch.encode()).hexdigest());(W/'preparation.json').write_text(json.dumps(p,indent=2)+'\n')
for n in ['analysis-rule.json','analysis-rule-frozen.py.txt','host-inputs.json']:shutil.copy2(A/'evidence'/n,E/n)
print(W)
