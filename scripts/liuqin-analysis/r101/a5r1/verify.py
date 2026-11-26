#!/usr/bin/env python3
from pathlib import Path
import ast,hashlib,json,re,subprocess,sys
R=Path(__file__).resolve().parents[4];H=Path(__file__).resolve().parent;A=R/'out/liuqin-r101-a5-work';W=R/'out/liuqin-r101-a5r1-work';E=W/'evidence';a=A/'evidence/a';b=E/'a'
def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
x=json.loads((a/'validation-summary.json').read_text());y=json.loads((b/'validation-summary.json').read_text());prep=json.loads((W/'preparation.json').read_text());changes=[]
for key in ['kernel_args','kernel_args_len','adt_sha256','trust_cache_sha256','segments']:assert x[key]==y[key],key
source=R/'out/liuqin/macos-27.3-26C5035r/liuqin/tree/.cache/xnu-work'
for rel in prep['changed_kernel_files']:
 assert sha(source/rel)==sha(b/'sources'/rel)==sha(W/'staged-sources'/rel),rel
 if sha(a/'sources'/rel)!=sha(b/'sources'/rel):changes.append(rel)
assert changes==['osfmk/kern/liuqin_r101_walk.inc']
for p in (A/'device-a').rglob('*'):
 if p.is_file() and not p.is_symlink() and p.suffix!='.patch':assert sha(p)==sha(W/'device-a'/p.relative_to(A/'device-a')),str(p)
s=(b/'sources/osfmk/kern/liuqin_r101_walk.inc').read_text();assert s.endswith((H/'state-reader.inc').read_text())
assert 'version=6' in s and 'globals[i].address+(i<5?base:slide)' in s and 'base+0x6e1a0' in s and 'base+0x6e180' in s and '0x275739' not in s
assert 'IVAR0' not in s and '++r105_requests<=64' in s
fixups=(E/'host-audit/local-daemon/fixups.txt').read_text()
for address,target in [('100063448','10006d918'),('100063498','10006d8c8'),('100062c80','10006ce28')]:assert re.search('0x'+address+r':[^\n]*target: 0x'+target,fixups),address
# Original A5 inputs stay immutable even while its first capture is running.
old=json.loads((A/'evidence/review-manifest.json').read_text())
for rel,digest in old.items():assert sha(R/rel)==digest,rel
for n in ['test-main-header.py','test-state-reader.py','test-decode-state.py']:subprocess.run([sys.executable,H/n],check=True)
def monitor(p):return ast.dump(next(n for n in ast.parse(p.read_text()).body if isinstance(n,ast.ClassDef) and n.name=='Monitor'),include_attributes=False)
assert monitor(H/'run-a5r1.py')==monitor(H.parent/'a5/run-a5.py')
subprocess.run([sys.executable,H.parent/'replay-exact.py',R/'out/liuqin-r101-a4-work/evidence/a/boot-A4-20261121-094931'],check=True)
subprocess.run([sys.executable,H/'run-a5r1.py','--check'],check=True)
r={'status':'PASS','hardware_boots':0,'parent_A5_boot_sha256':x['boot_sha256'],'boot_sha256':y['boot_sha256'],'kernel_sha256':y['kernel_sha256'],'changed_sources':changes,'behavior_baseline':'accepted A3r1 nTWE=1; all behavior/device/args/ADT/trust/Data unchanged','correction':'active local notifier ownership and own-executable relocation, proven by GOT rebases; framework addresses were wrong implementation','state_reads':'same bounded nonfaulting chain; cap64 plus explicit invalid probe; worst36 requests plus probe','USB_sampler_snapshot_fence':'source-identical to A5/A4','Monitor_AST_equal':True,'A4_exact_guard_replay_steps':2203,'prior_A5_manifest_entries_checked':len(old),'tests':{'header_and_identity':10,'native_state_reader':5,'state_decoder':12},'native_reader_validated':False,'segments':y['segments'],'text_const_vma':y['text_const_vma'],'const_gate_headroom_bytes':int(y['text_const_vma'],16)-0xfffffff007005900}
(E/'host-verification.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2))
