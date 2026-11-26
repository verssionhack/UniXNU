#!/usr/bin/env python3
"""A5 host gates, preserving accepted A3r1 behavior and A4 observers/transport."""
from pathlib import Path
import ast,hashlib,json,subprocess,sys
R=Path(__file__).resolve().parents[4];H=Path(__file__).resolve().parent;A=R/'out/liuqin-r101-a4-work';W=R/'out/liuqin-r101-a5-work';E=W/'evidence';a=A/'evidence/a';b=E/'a'
def sha(p):
 with p.open('rb') as s:return hashlib.file_digest(s,'sha256').hexdigest()
x=json.loads((a/'validation-summary.json').read_text());y=json.loads((b/'validation-summary.json').read_text());prep=json.loads((W/'preparation.json').read_text());changes=[]
for k in ['kernel_args','kernel_args_len','adt_sha256','trust_cache_sha256','segments']:assert x[k]==y[k],k
source=R/'out/liuqin/macos-27.3-26C5035r/liuqin/tree/.cache/xnu-work'
for rel in prep['changed_kernel_files']:
 assert sha(source/rel)==sha(b/'sources'/rel)==sha(W/'staged-sources'/rel),rel
 if sha(a/'sources'/rel)!=sha(b/'sources'/rel):changes.append(rel)
assert set(changes)=={'osfmk/kern/liuqin_r101_walk.inc','osfmk/kern/liuqin_r101_waits.inc'}
for p in (A/'device-a').rglob('*'):
 if p.is_file() and not p.is_symlink() and p.suffix!='.patch':assert sha(p)==sha(W/'device-a'/p.relative_to(A/'device-a')),str(p)
assert (b/'sources/osfmk/kern/liuqin_r101_walk.inc').read_text().endswith((H/'state-reader.inc').read_text())
s=(b/'sources/osfmk/kern/liuqin_r101_waits.inc').read_text();assert 'if(slot==1)' in s and 'if(identity)r105_state' in s
s=(b/'sources/osfmk/kern/liuqin_r101_walk.inc').read_text();assert 'return found && subtype==0x80000002 && !strcmp(uuid,"91f59f6a64c3321c88b00cc7a485ab1c")' in s
for forbidden in ['copyout(', 'vm_fault(', 'task_suspend(', 'pmap_enter(', 'r101_clean(']:assert forbidden not in (H/'state-reader.inc').read_text(),forbidden
s=(H/'state-reader.inc').read_text();assert '++r105_requests<=64' in s and 'address<=vm_map_max(r->map)-16' in s and 'r101_read_user_frame' in s
assert 'memcmp(uuid,expected,16)' in s and 'task_shared_region_slide' in s
assert sha(a/'sources/bsd/dev/liuqin_r101.inc')==sha(b/'sources/bsd/dev/liuqin_r101.inc') # unchanged fence and early sampler orchestration

def monitor(p):return ast.dump(next(n for n in ast.parse(p.read_text()).body if isinstance(n,ast.ClassDef) and n.name=='Monitor'),include_attributes=False)
assert monitor(H/'run-a5.py')==monitor(H.parent/'a4/run-a4.py')
for n in ['test-main-header.py','test-state-reader.py','test-decode-state.py']:subprocess.run([sys.executable,H/n],check=True)
subprocess.run([sys.executable,H.parent/'a2r1/test_assessment.py'],check=True)
subprocess.run([sys.executable,H.parent/'replay-exact.py',a/'boot-A4-20261121-094931'],check=True)
subprocess.run([sys.executable,H/'run-a5.py','--check'],check=True)
# Previously accepted evidence is immutable, including A4's raw exit5 assessment.
checked=0
for name in ['out/liuqin-r101-a3r1-work/evidence/review-manifest.json','out/liuqin-r101-a4-work/evidence/result-manifest.json']:
 manifest=json.loads((R/name).read_text())
 for rel,digest in manifest['files'].items():assert sha(R/rel)==digest,rel;checked+=1
report={'status':'PASS','hardware_boots':0,'parent_A4_boot_sha256':x['boot_sha256'],'boot_sha256':y['boot_sha256'],'kernel_sha256':y['kernel_sha256'],'changed_sources':changes,'behavior_baseline':'accepted A3r1 nTWE=1; nTWI, Data512MiB, args/ADT/trust/device sources unchanged','A4_USB_early_sampler_and_fence':'source-identical','state_reads':'64 attempts/1024 bytes maximum; actual fixed chain worst38 reads plus independent invalid-address probe; nonfaulting','identity_gates':'main UUID+subtype then this task shared-cache UUID; own main relocation and own shared slide','decode_qualification':'ISA constants, ivar offsets and collection class checked live; no guessed pointer normalization; read errors remain unknown','native_reader_validated':False,'guard_Monitor_AST_equal':True,'A4_exact_guard_replay_steps':2203,'prior_immutable_manifest_entries_checked':checked,'tests':{'main_header_and_identity_gate':10,'state_reader_cases':5,'state_decoder_cases':11,'inherited_assessment_cases':6},'segments':y['segments'],'text_const_vma':y['text_const_vma'],'const_gate_headroom_bytes':int(y['text_const_vma'],16)-0xfffffff007005900,'scope':'volatile observer-only; no flash/key/signing/network/display/Data change'}
(E/'host-verification.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
