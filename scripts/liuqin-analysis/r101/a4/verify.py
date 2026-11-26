#!/usr/bin/env python3
"""Host gates for A4 observer-only TimeSync capture; no device mutation."""
from pathlib import Path
import ast,hashlib,json,subprocess,sys
R=Path(__file__).resolve().parents[4];H=Path(__file__).resolve().parent;A=R/'out/liuqin-r101-a3r1-work';W=R/'out/liuqin-r101-a4-work';E=W/'evidence';a=A/'evidence/a';b=E/'a'
def sha(p):
 with p.open('rb') as s:return hashlib.file_digest(s,'sha256').hexdigest()
x=json.loads((a/'validation-summary.json').read_text());y=json.loads((b/'validation-summary.json').read_text());prep=json.loads((W/'preparation.json').read_text())
for key in ['kernel_args','kernel_args_len','adt_sha256','trust_cache_sha256']:assert x[key]==y[key],key
assert x['boot_sha256']==prep['parent_A3r1_boot_sha256']
changes=[]
source=R/'out/liuqin/macos-27.3-26C5035r/liuqin/tree/.cache/xnu-work'
for rel in prep['changed_kernel_files']:
 assert sha(source/rel)==sha(b/'sources'/rel)==sha(W/'staged-sources'/rel),rel
 if sha(a/'sources'/rel)!=sha(b/'sources'/rel):changes.append(rel)
assert set(changes)=={'bsd/dev/liuqin_r101.inc','osfmk/kern/liuqin_r101_waits.inc','osfmk/kern/liuqin_r101_walk.inc','iokit/Kernel/IOUserClient.cpp'}
assert sha(a/'sources/osfmk/arm64/start.s')==sha(b/'sources/osfmk/arm64/start.s')
for p in (A/'device-a').rglob('*'):
 if p.is_file() and not p.is_symlink() and p.suffix!='.patch':assert sha(p)==sha(W/'device-a'/p.relative_to(A/'device-a')),str(p)
for rel,digest in json.loads((A/'frozen-r100b-source-sha256.json').read_text()).items():assert sha(A/'frozen-r100b-source'/rel)==digest
s=(b/'sources/bsd/dev/liuqin_r101.inc').read_text();s=s[s.index('static void r101_snapshot('):s.index('static void r101_space(')]
needles=['stage=waits','liuqin_r101_task_waits(task,r101_ms(),0)','liuqin_r101_task_waits(clocktask,r101_ms(),1)','stage=histories','stage=storage','liuqin_r104_timesync_dump();','stage=walker-begin','uint64_t fence=liuqin_debug_total()','if(liuqin_r102_usb_completed()>=fence)','liuqin_r102_task_walk(task,0)','liuqin_r102_task_walk(clocktask,1)','task_deallocate(clocktask)']
positions=[s.index(v) for v in needles];assert positions==sorted(positions)
assert 'waited<2000' in s
s=(b/'sources/osfmk/kern/liuqin_r101_waits.inc').read_text();assert 'r102_walk_saved[2][64]' in s and 'r102_walk_count[slot]' in s and 'task->mach_header_vm_address' in s
assert 'r101_walk_user(' not in s[:s.index('void liuqin_r102_task_walk')]
s=(b/'sources/iokit/Kernel/IOUserClient.cpp').read_text().split('extern "C" void liuqin_r104_timesync_dump(void) {')[1]
for forbidden in ['setProperty','registerService','waitForService','getMatchingServices','serviceMatching','loadKext']:assert forbidden not in s,forbidden
assert 'visited<4096' in s and 'printed>=64' in s and 'it->isValid()' in s

def monitor(path):return ast.dump(next(n for n in ast.parse(path.read_text()).body if isinstance(n,ast.ClassDef) and n.name=='Monitor'),include_attributes=False)
assert monitor(H/'run-a4.py')==monitor(H.parent/'a3r1/run-a3r1.py')
for test in ['test-main-header.py','test-target-frames.py']:subprocess.run([sys.executable,H/test],check=True)
subprocess.run([sys.executable,H.parent/'a2r1/test_assessment.py'],check=True)
subprocess.run([sys.executable,H.parent/'replay-exact.py',a/'boot-A3r1-20261121-091739'],check=True)
subprocess.run([sys.executable,H/'run-a4.py','--check'],check=True)
report={'status':'PASS','hardware_boots':0,'parent_boot_sha256':x['boot_sha256'],'boot_sha256':y['boot_sha256'],'kernel_sha256':y['kernel_sha256'],'changed_sources':changes,'behavior_frozen':'A3r1; start.s nTWE=1 source identical; nTWI unchanged; args/ADT/trust/Data/device sources identical','USB_source':'byte-identical to accepted A3r1','snapshot_target_buffers':'independent 2x64 saved scalar entries','walker_bound':'16 deep; 64 candidate frames per target, max128 per snapshot; unavailable reads explicit','main_image_identity':'native task exec header; bounded nonfaulting LC_UUID and subtype; host UUID/SHA selected image','registry':'read-only IOService-plane iterator; visit4096/hit64 caps plus coverage/validity','guard_AST_equal':True,'tests':'8 exact native header cases; real slice UUID/SHA/relocation and target isolation; inherited assessment tests; exact A3r1 guard replay','log_budget':{'total':524288,'detail':458752,'snapshot_reserve_each':98304,'line_max_with_newline':253,'actual_capture_validation_required':True},'segments':y['segments'],'text_const_vma':y['text_const_vma'],'native_reader_validated':False}
(E/'host-verification.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
