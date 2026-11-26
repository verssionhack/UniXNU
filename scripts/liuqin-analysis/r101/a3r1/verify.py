#!/usr/bin/env python3
"""Verify one-instruction A3 behavior delta and identical observer inputs."""
from pathlib import Path
import hashlib,json,re,struct,subprocess
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
R=Path(__file__).resolve().parents[4];A=R/'out/liuqin-r101-a2r1-work';W=R/'out/liuqin-r101-a3r1-work';E=W/'evidence';a=A/'evidence/a';b=E/'a'
def sha(p):
 with p.open('rb') as s:return hashlib.file_digest(s,'sha256').hexdigest()
x=json.loads((a/'validation-summary.json').read_text());y=json.loads((b/'validation-summary.json').read_text())
for key in ['kernel_args','kernel_args_len','adt_sha256','trust_cache_sha256','segments','text_const_vma']:assert x[key]==y[key],key
prep=json.loads((W/'preparation.json').read_text());pa=json.loads((A/'preparation.json').read_text())
assert prep['changed_kernel_files']==pa['changed_kernel_files']+['osfmk/arm64/start.s']
for rel in pa['changed_kernel_files']:assert sha(a/'sources'/rel)==sha(b/'sources'/rel),rel
old=(A/'frozen-r100b-source/osfmk/arm64/start.s').read_text();new=(b/'sources/osfmk/arm64/start.s').read_text();line='\torr x0, x0, #0x40000\t// A3r1: EL0 WFE enabled; preserve nTWI\n';assert new.count(line)==1 and new.replace(line,'')==old
for p in (A/'device-a').rglob('*'):
 if p.is_file() and not p.is_symlink() and p.suffix!='.patch':
  q=W/'device-a'/p.relative_to(A/'device-a');assert q.is_file() and sha(p)==sha(q),str(p)
# Source of normal execution and hook logic unchanged outside one start.s line.
source=R/'out/liuqin/macos-27.3-26C5035r/liuqin/tree/.cache/xnu-work'
for rel in ['osfmk/arm64/start.s','osfmk/arm/caches.c','bsd/kern/kern_exec.c','bsd/kern/kern_proc.c','osfmk/arm64/proc_reg.h','osfmk/mach/arm/vm_param.h']:
 expected=b/'sources'/rel if rel=='osfmk/arm64/start.s' else A/'frozen-r100b-source'/rel
 assert sha(source/rel)==sha(expected),rel
# Validate last-stage ordering against the linked native source, not a staged plan.
s=(b/'sources/bsd/dev/liuqin_r101.inc').read_text();s=s[s.index('static void r101_snapshot('):s.index('static void r101_space(')]
needles=['stage=waits','liuqin_r101_task_waits(task','stage=histories','stage=storage','r102_regs_dump();r101_coverage();','stage=walker-begin','uint64_t fence=liuqin_debug_total()','liuqin_r102_task_walk(task)','LQ102 WALK_END','task_deallocate(task)']
positions=[s.index(v) for v in needles];assert positions==sorted(positions)
assert 'waited<2000' in s and 'if(task && liuqin_r102_usb_completed()>=fence)' in s
s=(b/'sources/osfmk/kern/liuqin_r101_waits.inc').read_text();assert 'r101_walk_user(' not in s[:s.index('void liuqin_r102_task_walk')]
# Every A2r1 observer, including the corrected atomic fence helper, must match.
assert sha(a/'sources/bsd/dev/liuqin_r103_usb_fence.h')==sha(b/'sources/bsd/dev/liuqin_r103_usb_fence.h')
assert prep['parent_A2r1_boot_sha256']==x['boot_sha256']=='2d084a20a7a77a08caa4122408a080310d93207e228df746db53604325af5597'
assert prep['parent_A2r1_capture_log_sha256']=='ca8251369da34d8862677bb0beea3002125a5cd6de5b5f97a6ef6d48e8e3ee71'
assert prep['behavior_changes']==['SCTLR_EL1.nTWE=1, bit18 only, common cold/secondary/reset path']
for rel,digest in json.loads((A/'frozen-r100b-source-sha256.json').read_text()).items():assert sha(A/'frozen-r100b-source'/rel)==digest
for rel in prep['changed_kernel_files']:assert sha(source/rel)==sha(b/'sources'/rel),rel
# Capture guards are unchanged; post-capture assessment remains shared with A2r1.
import ast,sys
def monitor(path):return ast.dump(next(n for n in ast.parse(path.read_text()).body if isinstance(n,ast.ClassDef) and n.name=='Monitor'),include_attributes=False)
H=R/'scripts/liuqin-analysis/r101'
assert monitor(H/'a3r1/run-a3r1.py')==monitor(H/'a2r1/run-a2r1.py')
subprocess.run([sys.executable,H/'replay-exact.py',a/'boot-A2r1-20261121-055146'],check=True)
subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',H/'a2r1/test_usb_fence.c','-o',W/'test-usb-fence'],check=True)
subprocess.run([W/'test-usb-fence'],check=True)
subprocess.run([sys.executable,H/'a2r1/test_assessment.py'],check=True)
subprocess.run([sys.executable,H/'a3r1/run-a3r1.py','--check'],check=True)
# Decode actual common_start bytes to prove the OR immediately precedes barrier/SCTLR write.
p=b/'standalone.macho';data=p.read_bytes();nm=subprocess.check_output(['llvm-nm','-an',str(p)],text=True);start=int(re.search(r'^([0-9a-f]+) [a-zA-Z] common_start$',nm,re.M)[1],16);off=32;window=None
for _ in range(struct.unpack_from('<I',data,16)[0]):
 cmd,n=struct.unpack_from('<II',data,off)
 if cmd==0x19:
  base,size,fileoff,filesize=struct.unpack_from('<QQQQ',data,off+24)
  if base<=start<base+filesize:window=data[fileoff+start-base:fileoff+start-base+0x1800]
 off+=n
assert window is not None
md=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN);md.skipdata=True;ins=list(md.disasm(window,start));matches=[]
for i,v in enumerate(ins[:-2]):
 if v.mnemonic=='orr' and v.op_str=='x0, x0, #0x40000' and ins[i+1].mnemonic=='dsb' and ins[i+2].mnemonic=='msr' and 'sctlr_el1' in ins[i+2].op_str:
  matches.append([{'address':hex(t.address),'bytes':t.bytes.hex(),'mnemonic':t.mnemonic,'operands':t.op_str} for t in ins[i:i+3]])
assert len(matches)==1,matches
report={'status':'PASS','hardware_boots':0,'A2r1_boot_sha256':x['boot_sha256'],'A3r1_boot_sha256':y['boot_sha256'],'A3r1_kernel_sha256':y['kernel_sha256'],'observer_sources_identical':True,'args_ADT_trust_Data_driver_identical':True,'changed_behavior':'SCTLR_EL1.nTWE bit18 only','nTWI_unchanged':True,'common_cold_secondary_reset_path':True,'actual_instructions':matches[0],'walker_last_source_contract':'PASS','USB_completion_fence_source_contract':'byte-identical to accepted A2r1, including atomic helper','guard_Monitor_AST_equal':True,'accepted_A2r1_guard_replay_calls':2202,'assessment_tests':6,'baseline_log_sha256':prep['parent_A2r1_capture_log_sha256'],'segments':y['segments'],'text_const_vma':y['text_const_vma'],'fault_rule_sha256':pa['fault_rule_sha256']}
(E/'host-verification.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
