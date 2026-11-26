#!/usr/bin/env python3
"""Stage A5 only after pinned host-layout audit; no target action."""
from pathlib import Path
import difflib,hashlib,json,shutil
R=Path(__file__).resolve().parents[4];H=Path(__file__).resolve().parent;A=R/'out/liuqin-r101-a4-work';W=R/'out/liuqin-r101-a5-work'
assert (H/'liuqin-r101-a5-host-audit.md').is_file() and (R/'out/liuqin-r101-a5-audit/isa-masks.txt').is_file()
assert not W.exists();W.mkdir();E=W/'evidence';E.mkdir()
shutil.copytree(R/'out/liuqin-r101-a5-audit',E/'host-audit')
for v in ['a','b']:shutil.copytree(A/f'device-{v}',W/f'device-{v}',symlinks=True)
(W/'frozen-r100b-source').symlink_to(A/'frozen-r100b-source',target_is_directory=True)
shutil.copy2(A/'frozen-r100b-source-sha256.json',W/'frozen-r100b-source-sha256.json')
p=json.loads((A/'preparation.json').read_text());texts={r:(A/'evidence/a/sources'/r).read_text() for r in p['changed_kernel_files']}
r='osfmk/kern/liuqin_r101_walk.inc';s=texts[r].replace('static void r104_main_uuid(', 'static int r104_main_uuid(')
needle='    vm_map_deallocate(map);\n}\n';assert s.endswith(needle)
s=s[:-len(needle)]+'''    vm_map_deallocate(map);
    return found && subtype==0x80000002 && !strcmp(uuid,"91f59f6a64c3321c88b00cc7a485ab1c");
}
'''
s+='\n'+(H/'state-reader.inc').read_text();texts[r]=s
r='osfmk/kern/liuqin_r101_waits.inc';s=texts[r];needle='    r104_main_uuid(task,r104_main_base[slot]);';assert s.count(needle)==1
s=s.replace(needle,'''    int identity=r104_main_uuid(task,r104_main_base[slot]);
    if(slot==1){
        if(identity)r105_state(task,r104_main_base[slot]);
        else liuqin_r101_emit(1,"LQ102 STATE_END: status=main-identity-mismatch");
    }''');texts[r]=s
patch='';delta=''
for rel,new in texts.items():
 oldpath=W/'frozen-r100b-source'/rel;old=oldpath.read_text() if oldpath.exists() else '';before=(A/'evidence/a/sources'/rel).read_text()
 patch+=''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/'+rel if old else '/dev/null',tofile='b/'+rel));delta+=''.join(difflib.unified_diff(before.splitlines(True),new.splitlines(True),fromfile='a/'+rel,tofile='b/'+rel))
 dest=W/'staged-sources'/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(new)
(W/'observer.patch').write_text(patch);(E/'A4-to-A5.patch').write_text(delta)
for v in ['a','b']:next((W/f'device-{v}/patches/xnu').glob('*liuqin-r101.patch')).write_text(patch)
p.update(observer_revision='A5',parent_A4_boot_sha256='61dc0156e78e9d179216a7db48a27b629a16df1de22a80eee0ae5f758ac5f467',behavior_changes=[],observer_patch_sha256=hashlib.sha256(patch.encode()).hexdigest());(W/'preparation.json').write_text(json.dumps(p,indent=2)+'\n')
for n in ['analysis-rule.json','analysis-rule-frozen.py.txt']:shutil.copy2(A/'evidence'/n,E/n)
print(W)
