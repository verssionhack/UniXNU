#!/usr/bin/env python3
"""Populate already isolated A7 staging; never changes A6 or shared sources."""
from pathlib import Path
import difflib,hashlib,json,shutil
R=Path(__file__).resolve().parents[4];H=Path(__file__).resolve().parent;W=R/'out/liuqin-r101-a7-work';A=R/'out/liuqin-r101-a6-work';D=W/'device-a'
assert not (W/'observer.patch').exists(),'staging already prepared'
driver=D/'drivers/LiuqinIdentityEthernet';driver.mkdir()
shutil.copy2(H/'LiuqinIdentityEthernet.cpp',driver/'LiuqinIdentityEthernet.cpp')
headers=driver/'network';headers.mkdir()
for p in (W/'IONetworkingFamily-188').glob('*.h'):shutil.copy2(p,headers/p.name)
for n in ['net-ether-26C5035r.json','controller-slots.json','metaclass-Dispatch.json']:shutil.copy2(W/'evidence/host'/n,D/'scripts'/n)
shutil.copy2(H/'build-identity-ethernet.py',D/'scripts/build-identity-ethernet.py')
b=D/'board.toml';s=b.read_text();needle='  "build-liuqin-legacy-display.py",';assert s.count(needle)==1
b.write_text(s.replace(needle,needle+'\n  "build-identity-ethernet.py",'))
b=D/'configs/liuqin_defconfig';s=b.read_text();needle='-Wl,-force_load,{tree}/build/apple-key-store-state/libAppleKeyStoreState.a"';assert s.count(needle)==1
b.write_text(s.replace(needle,needle[:-1]+' -Wl,-force_load,{tree}/build/liuqin-identity-ethernet/libLiuqinIdentityEthernet.a"'))
p=json.loads((W/'preparation.json').read_text());rel='bsd/kern/bsd_init.c'
old=(W/'frozen-r100b-source'/rel).read_text();needle='\tnet_init_run();\n'
assert old.count(needle)==1
new=old.replace(needle,needle+'\t/* A7: spawn only; all native-family work/waits occur on its worker. */\n\textern void liuqin_identity_ethernet_start(void);\n\tliuqin_identity_ethernet_start();\n')
q=W/'staged-sources'/rel;q.parent.mkdir(parents=True,exist_ok=True);q.write_text(new)
p['changed_kernel_files'].append(rel);patch='';delta=''
for rel in p['changed_kernel_files']:
 q=W/'frozen-r100b-source'/rel;original=q.read_text() if q.exists() else ''
 text=(W/'staged-sources'/rel).read_text()
 patch+=''.join(difflib.unified_diff(original.splitlines(True),text.splitlines(True),fromfile='a/'+rel if original else '/dev/null',tofile='b/'+rel))
 parent=A/'evidence/a/sources'/rel;before=parent.read_text() if parent.exists() else original
 delta+=''.join(difflib.unified_diff(before.splitlines(True),text.splitlines(True),fromfile='a/'+rel,tofile='b/'+rel))
(W/'observer.patch').write_text(patch);(W/'evidence/A6-to-A7.patch').write_text(delta)
next((D/'patches/xnu').glob('*liuqin-r101.patch')).write_text(patch)
p['observer_patch_sha256']=hashlib.sha256(patch.encode()).hexdigest();(W/'preparation.json').write_text(json.dumps(p,indent=2)+'\n')
print('A7 staged; only kernel-source delta is the post-net_init_run worker hook')
