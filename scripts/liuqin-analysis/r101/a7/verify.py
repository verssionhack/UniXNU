#!/usr/bin/env python3
"""Freeze A7 host comparison and hard-stop on layout failure. Never boots."""
from pathlib import Path
import hashlib,json,subprocess,sys,shutil
R=Path(__file__).resolve().parents[4];H=Path(__file__).resolve().parent;W=R/'out/liuqin-r101-a7-work';A=R/'out/liuqin-r101-a6-work';E=W/'evidence';e=E/'a'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
manifest=json.loads((A/'evidence/result-manifest.json').read_text())['files']
for n,h in manifest.items():assert sha(R/n)==h,n
prep=json.loads((W/'preparation.json').read_text());parent=json.loads((A/'preparation.json').read_text());changes=[]
for rel in prep['changed_kernel_files']:
    assert sha(W/'staged-sources'/rel)==sha(e/'sources'/rel),rel
    if rel in parent['changed_kernel_files']:assert sha(e/'sources'/rel)==sha(A/'evidence/a/sources'/rel),rel
    else:changes.append(rel)
assert changes==['bsd/kern/bsd_init.c'],changes
allowed={'board.toml','configs/liuqin_defconfig'}
allowed|={str(p.relative_to(A/'device-a')) for p in (A/'device-a/patches/xnu').glob('*liuqin-r101.patch')}
device_changes=[]
for p in (A/'device-a').rglob('*'):
    if p.is_file() and not p.is_symlink():
        rel=str(p.relative_to(A/'device-a'));other=W/'device-a'/rel
        assert other.is_file(),rel
        if sha(p)!=sha(other):device_changes.append(rel);assert rel in allowed,rel
assert set(device_changes)==allowed,device_changes
archive=R/'out/liuqin/macos-27.3-26C5035r/liuqin/tree/build/liuqin-identity-ethernet'
out=E/'archive';out.mkdir(exist_ok=True)
for p in archive.iterdir():
    if p.is_file():shutil.copy2(p,out/p.name)
abi=json.loads((out/'build-report.json').read_text());assert abi['status']=='PASS' and abi['vtable_slots']==400 and abi['pure_slots_implemented']==[362]
assert sha(H/'LiuqinIdentityEthernet.cpp')==abi['source_sha256']==sha(W/'device-a/drivers/LiuqinIdentityEthernet/LiuqinIdentityEthernet.cpp')
layout=subprocess.run([sys.executable,H/'check-layout.py'])
r={'status':'REJECTED-layout-gate' if layout.returncode else 'layout-pass-packaging-pending','hardware_boots':0,'A6_manifest_entries_verified':len(manifest),'A6_observer_sources_byte_identical':True,'changed_kernel_sources':changes,'existing_device_files_changed':device_changes,'archive_vtable_slots':400,'archive_bindings':len(abi['bindings']),'source_header_reserved_Dispatch_correction':abi['inherited_Dispatch_projection'],'layout':json.loads((e/'layout-gate.json').read_text()),'A6_runner_parsers_and_guards':'unchanged; frozen manifest verified','native_reader_validated':False,'observer_retirement':False,'caps_relaxed':False}
if not layout.returncode:
    candidate=json.loads((e/'kernel.json').read_text());assert not candidate['missing']
    r['prelink_mapping_complete']=candidate['mapping_complete']
(E/'host-verification.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2))
sys.exit(2 if layout.returncode else 0)
