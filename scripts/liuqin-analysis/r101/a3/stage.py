#!/usr/bin/env python3
"""Freeze A3 from finalized A2; one behavior change: SCTLR_EL1.nTWE."""
from pathlib import Path
import difflib,hashlib,json,shutil
R=Path(__file__).resolve().parents[4];A=R/'out/liuqin-r101-a2-work';W=R/'out/liuqin-r101-a3-work';W.mkdir(exist_ok=True)
assert (A/'evidence/host-verification-a2.json').is_file(), 'Verify finalized A2 first'
assert not (W/'preparation.json').exists(), 'Do not overwrite a staged A3'
for v in ['a','b']:shutil.copytree(A/f'device-{v}',W/f'device-{v}',symlinks=True)
(W/'frozen-r100b-source').symlink_to(A/'frozen-r100b-source',target_is_directory=True)
shutil.copy2(A/'frozen-r100b-source-sha256.json',W/'frozen-r100b-source-sha256.json')
rel='osfmk/arm64/start.s';old=(A/'frozen-r100b-source'/rel).read_text();needle='Lq76AfterToken:\n\tdsb sy';assert old.count(needle)==1
new=old.replace(needle,'Lq76AfterToken:\n\torr x0, x0, #0x40000\t// A3: EL0 WFE enabled; preserve nTWI\n\tdsb sy')
diff=''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/'+rel,tofile='b/'+rel))
patch=(A/'observer.patch').read_text()+diff;(W/'observer.patch').write_text(patch)
for v in ['a','b']:
 paths=list((W/f'device-{v}/patches/xnu').glob('*liuqin-r101.patch'));assert len(paths)==1;paths[0].write_text(patch)
p=json.loads((A/'preparation.json').read_text());p['changed_kernel_files'].append(rel);p['observer_revision']='A3';p['behavior_changes']=['SCTLR_EL1.nTWE=1, bit18 only, common cold/secondary/reset path'];p['observer_patch_sha256']=hashlib.sha256(patch.encode()).hexdigest();(W/'preparation.json').write_text(json.dumps(p,indent=2)+'\n')
e=W/'evidence';e.mkdir(exist_ok=True);(e/'A2-to-A3.patch').write_text(diff)
for n in ['analysis-rule.json','analysis-rule-frozen.py.txt']:shutil.copy2(A/'evidence'/n,e/n)
print(W)
