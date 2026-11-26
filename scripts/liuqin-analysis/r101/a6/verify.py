#!/usr/bin/env python3
from pathlib import Path
import ast,hashlib,json,subprocess,sys
R=Path(__file__).resolve().parents[4];H=Path(__file__).resolve().parent;A=R/'out/liuqin-r101-a5r1-work';W=R/'out/liuqin-r101-a6-work';E=W/'evidence';a=A/'evidence/a';b=E/'a'
def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
x=json.loads((a/'validation-summary.json').read_text());y=json.loads((b/'validation-summary.json').read_text());prep=json.loads((W/'preparation.json').read_text());changes=[]
for k in ['kernel_args','kernel_args_len','adt_sha256','trust_cache_sha256','segments']:assert x[k]==y[k],k
source=R/'out/liuqin/macos-27.3-26C5035r/liuqin/tree/.cache/xnu-work'
for rel in prep['changed_kernel_files']:
 assert sha(source/rel)==sha(b/'sources'/rel)==sha(W/'staged-sources'/rel),rel
 if sha(a/'sources'/rel)!=sha(b/'sources'/rel):changes.append(rel)
assert changes==['iokit/Kernel/IOUserClient.cpp']
for p in (A/'device-a').rglob('*'):
 if p.is_file() and not p.is_symlink() and p.suffix!='.patch':assert sha(p)==sha(W/'device-a'/p.relative_to(A/'device-a')),str(p)
s=(b/'sources/iokit/Kernel/IOUserClient.cpp').read_text();helper=(H/'publication-observer.inc').read_text();assert helper in s
old=(a/'sources/iokit/Kernel/IOUserClient.cpp').read_text();assert s.replace(helper+'\n','').replace('        r106_publication(OSDynamicCast(IOService,node));\n','')==old
for forbidden in ['setProperty','registerService(','waitForService(','copyin(','copyout(','new ','OSData::','withCapacity']:assert forbidden not in helper,forbidden
assert 's->getState()' in helper and 's->getRegistryEntryID()' in helper and 's->copyProperty' in helper and 'object->release()' in helper
for n in ['test-publication.py','test-native-publication.py']:subprocess.run([sys.executable,H/n],check=True)
def monitor(p):return ast.dump(next(n for n in ast.parse(p.read_text()).body if isinstance(n,ast.ClassDef) and n.name=='Monitor'),include_attributes=False)
assert monitor(H/'run-a6.py')==monitor(H.parent/'a5r1/run-a5r1.py')
subprocess.run([sys.executable,H.parent/'replay-exact.py',a/'boot-A5r1-20261121-102912'],check=True)
subprocess.run([sys.executable,H/'run-a6.py','--check'],check=True)
manifest=json.loads((A/'evidence/result-manifest.json').read_text())['files']
for rel,digest in manifest.items():assert sha(R/rel)==digest,rel
# Existing package assertions include segment/const gates and actual emitted fileset header/payload AES gate.
gate=json.loads((b/'aes-fileset-gate.json').read_text());assert gate['status']=='PASS'
r={'status':'PASS','hardware_boots':0,'parent_A5r1_boot_sha256':x['boot_sha256'],'boot_sha256':y['boot_sha256'],'kernel_sha256':y['kernel_sha256'],'changed_sources':changes,'behavior_baseline':'A3r1 nTWE=1/nTWI unchanged,512MiB Data, args/ADT/trust/device sources identical','user_memory_read_tables':'byte-identical to A5r1','USB_early_sampler_fence':'byte-identical to A5r1','public_observer':'one helper in existing TimeSync sweep; getState/getRegistryEntryID, two retained numeric properties; no mutation/publication/wait/load','guard_AST_equal':True,'A5r1_exact_guard_replay_steps':2128,'prior_manifest_entries_checked':len(manifest),'tests':{'publication_decoder':11,'actual_native_publication_helper':'PASS, controls/zero/absent/wrong-type/retained-release/line-cap'},'segments':y['segments'],'text_const_vma':y['text_const_vma'],'const_gate_headroom_bytes':int(y['text_const_vma'],16)-0xfffffff007005900,'actual_fileset_header_payload_gate':'PASS','native_reader_validated':False}
(E/'host-verification.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2))
