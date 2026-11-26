#!/usr/bin/env python3
"""Host acceptance of the fence-only A2r1 revision; no device access."""
from pathlib import Path
import ast,hashlib,importlib.util,json,subprocess,sys
H=Path(__file__).resolve().parent;R=H.parents[3];W=R/'out/liuqin-r101-a2r1-work';A=R/'out/liuqin-r101-a2-work';E=W/'evidence';a=A/'evidence/a';b=E/'a'
def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
x=json.loads((a/'validation-summary.json').read_text());y=json.loads((b/'validation-summary.json').read_text());pa=json.loads((A/'preparation.json').read_text());p=json.loads((W/'preparation.json').read_text())
for k in ['kernel_args','kernel_args_len','adt_sha256','trust_cache_sha256','segments','text_const_vma']:assert x[k]==y[k],k
assert p['behavior_changes']==[]
assert p['changed_kernel_files']==pa['changed_kernel_files']+['bsd/dev/liuqin_r103_usb_fence.h']
for rel in pa['changed_kernel_files']:
 if rel!='bsd/dev/liuqin_usb_debug.c':assert sha(a/'sources'/rel)==sha(b/'sources'/rel),rel
for f in (A/'device-a').rglob('*'):
 if f.is_file() and not f.is_symlink() and f.suffix!='.patch':assert sha(f)==sha(W/'device-a'/f.relative_to(A/'device-a')),str(f)
for rel in ['osfmk/arm64/start.s','osfmk/arm64/proc_reg.h','osfmk/arm/caches.c','bsd/kern/kern_exec.c','bsd/kern/kern_proc.c','osfmk/mach/arm/vm_param.h']:
 generated=R/'out/liuqin/macos-27.3-26C5035r/liuqin/tree/.cache/xnu-work'/rel;assert sha(generated)==sha(A/'frozen-r100b-source'/rel),rel
assert sha(H/'kernel/liuqin_r103_usb_fence.h')==sha(b/'sources/bsd/dev/liuqin_r103_usb_fence.h')
# Remove observer-only calls and compare transport policy to the original A1
# code. This covers all affected transport functions, not the bookkeeping itself.
old=(A/'frozen-r100b-source/bsd/dev/liuqin_usb_debug.c').read_text();new=(b/'sources/bsd/dev/liuqin_usb_debug.c').read_text()
def body(s,start,end):return s[s.index(start):s.index(end,s.index(start))]
for start,end in [('static void\nfail(', 'static int\nepcmd('),('static int\ncomplete(', 'static void\nsetup_arm('),('static void\ntransmit(', '/* Interrupt-context transmit:'),('static void\nnote_push(', '\nvoid\nliuqin_usb_isr_note('),('static void\nevent(', 'static void\nusb_pump_events(')]:
 before=body(old,start,end);after=body(new,start,end)
 after='\n'.join(l for l in after.split('\n') if not any(t in l for t in ['r103_fence_lost(','r103_fence_complete(','r103_fence_copy(','r103_fence_ring(','r103_fence_note(','r102_before_copy=']))
 after=after.replace('complete(unsigned ep,unsigned event_status)','complete(unsigned ep)').replace('complete(ep,status);','complete(ep);')
 assert before==after,start
# Guard decisions themselves remain byte-for-byte equivalent AST.
def monitor(path):return ast.dump(next(n for n in ast.parse(path.read_text()).body if isinstance(n,ast.ClassDef) and n.name=='Monitor'),include_attributes=False)
assert monitor(H/'run-a2r1.py')==monitor(H.parent/'a2/run-a2.py')
subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',H/'test_usb_fence.c','-o',W/'test-usb-fence'],check=True);subprocess.run([W/'test-usb-fence'],check=True)
subprocess.run([sys.executable,H/'test_assessment.py'],check=True)
subprocess.run([sys.executable,H.parent/'replay-exact.py',a/'boot-A2-20261120-231726'],check=True)
q=subprocess.run([sys.executable,H/'assessment.py',a/'boot-A2-20261120-231726','--output',E/'executed-A2-assessment.json']);assert q.returncode==5
subprocess.run([sys.executable,H/'run-a2r1.py','--check'],check=True)
report={'status':'PASS','hardware_boots':0,'boot_sha256':y['boot_sha256'],'kernel_sha256':y['kernel_sha256'],'observer_patch_sha256':y['observer_patch_sha256'],'sampler_and_CPU_hook_unchanged':True,'other_kernel_observers_unchanged':True,'storage_driver_inputs_identical':True,'args_ADT_trust_Data_identical':True,'start_s_and_nTWE_nTWI_unchanged':True,'transport_policy_source_equal_after_removing_observer_calls':True,'fence_tests':'PASS: full, short, bus error, sticky loss, takeover, note, gap, contention, failure','assessment_tests':6,'executed_A2_capture_assessment_exit':5,'guard_Monitor_AST_equal':True,'exact_A2_guard_replay_calls':4721,'segments':y['segments'],'const_vma':y['text_const_vma'],'const_gate_headroom_bytes':int(y['text_const_vma'],16)-0xfffffff007005900,'failure_cause':'unattributed; fence safety repairs do not establish cause of early disconnect','next_boot_authorized':False}
(E/'host-verification.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
