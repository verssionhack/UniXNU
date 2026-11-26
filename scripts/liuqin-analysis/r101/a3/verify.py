#!/usr/bin/env python3
"""Verify one-instruction A3 behavior delta and identical observer inputs."""
from pathlib import Path
import hashlib,json,re,struct,subprocess
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
R=Path(__file__).resolve().parents[4];A=R/'out/liuqin-r101-a2-work';W=R/'out/liuqin-r101-a3-work';E=W/'evidence';a=A/'evidence/a';b=E/'a'
def sha(p):
 with p.open('rb') as s:return hashlib.file_digest(s,'sha256').hexdigest()
x=json.loads((a/'validation-summary.json').read_text());y=json.loads((b/'validation-summary.json').read_text())
for key in ['kernel_args','kernel_args_len','adt_sha256','trust_cache_sha256','segments','text_const_vma']:assert x[key]==y[key],key
prep=json.loads((W/'preparation.json').read_text());pa=json.loads((A/'preparation.json').read_text())
assert prep['changed_kernel_files']==pa['changed_kernel_files']+['osfmk/arm64/start.s']
for rel in pa['changed_kernel_files']:assert sha(a/'sources'/rel)==sha(b/'sources'/rel),rel
old=(A/'frozen-r100b-source/osfmk/arm64/start.s').read_text();new=(b/'sources/osfmk/arm64/start.s').read_text();line='\torr x0, x0, #0x40000\t// A3: EL0 WFE enabled; preserve nTWI\n';assert new.count(line)==1 and new.replace(line,'')==old
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
s=(b/'sources/bsd/dev/liuqin_usb_debug.c').read_text();assert 'if(!left && r102_pending_cursor)__atomic_store_n(&r102_completed_cursor' in s
assert 'if(left && r102_pending_cursor)__atomic_store_n(&r102_transport_gap,1' in s
assert 'if(u.cursor-r102_before_copy!=n)__atomic_store_n(&r102_transport_gap,1' in s
assert s.count('__atomic_store_n(&r102_transport_gap,')==2
assert 'r102_transport_gap,__ATOMIC_ACQUIRE)?0:' in s
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
report={'status':'PASS','hardware_boots':0,'A2_boot_sha256':x['boot_sha256'],'A3_boot_sha256':y['boot_sha256'],'A3_kernel_sha256':y['kernel_sha256'],'observer_sources_identical':True,'args_ADT_trust_Data_driver_identical':True,'changed_behavior':'SCTLR_EL1.nTWE bit18 only','nTWI_unchanged':True,'common_cold_secondary_reset_path':True,'actual_instructions':matches[0],'walker_last_source_contract':'PASS','USB_completion_fence_source_contract':'PASS; native execution untested','segments':y['segments'],'text_const_vma':y['text_const_vma'],'fault_rule_sha256':pa['fault_rule_sha256']}
(E/'host-verification-a3.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
