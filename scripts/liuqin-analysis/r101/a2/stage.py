#!/usr/bin/env python3
"""Stage A2 observers in a separate work directory; no boot or key access."""
from pathlib import Path
import difflib,hashlib,importlib.util,json,shutil,subprocess,sys,tempfile
R=Path(__file__).resolve().parents[4];HERE=Path(__file__).resolve().parent;BASE=R/'out/liuqin-r101-work';W=R/'out/liuqin-r101-a2-work'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 W.mkdir(exist_ok=True)
 for variant in ['a','b']:
  target=W/f'device-{variant}'
  if not target.exists():shutil.copytree(BASE/f'device-{variant}',target,symlinks=True)
 f=W/'frozen-r100b-source'
 if not f.exists():f.symlink_to(BASE/'frozen-r100b-source',target_is_directory=True)
 if not (W/'frozen-r100b-source-sha256.json').exists():shutil.copy2(BASE/'frozen-r100b-source-sha256.json',W/'frozen-r100b-source-sha256.json')
 spec=importlib.util.spec_from_file_location('prepare',HERE.parent/'prepare.py');p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)
 p.W=W;p.F=f;p.HERE=HERE
 sys.argv=[str(HERE/'stage.py'),'--walker-candidates'];p.main()
 extras={name:(HERE/'kernel'/Path(name).name).read_text() for name in ['bsd/dev/liuqin_r102_sample.inc','bsd/dev/liuqin_r102_undefined.inc']}
 rel='osfmk/arm64/cpu.c';old=(f/rel).read_text();needle='\tcdp->cpu_running = TRUE;';assert old.count(needle)==1
 extras[rel]=old.replace(needle,needle+'''
    /* A2: sample this CPU's own register; store only, never write SCTLR. */
    extern void liuqin_r102_cpu_readback(unsigned,uint64_t,uint64_t,uint64_t);
    liuqin_r102_cpu_readback(cdp->cpu_number,__builtin_arm_rsr64("SCTLR_EL1"),
        __builtin_arm_rsr64("MIDR_EL1"),__builtin_arm_rsr64("MPIDR_EL1"));''')
 prep=json.loads((W/'preparation.json').read_text());names=prep['changed_kernel_files']+list(extras)
 with tempfile.TemporaryDirectory(dir=W) as tmp:
  overlay=Path(tmp)
  for rel in prep['changed_kernel_files']:
   if (f/rel).exists():
    target=overlay/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(f/rel,target)
  subprocess.run(['git','-C',str(overlay),'apply',str(W/'observer.patch')],check=True)
  for rel,text in extras.items():
   target=overlay/rel;target.parent.mkdir(parents=True,exist_ok=True);target.write_text(text)
  perf=overlay/'bsd/dev/liuqin_perf.c';text=perf.read_text()
  needle='#include <dev/liuqin_r101.h>';assert text.count(needle)==1
  text=text.replace(needle,needle+'\nvoid liuqin_r102_undefined(const char *,int,const char *,int,int,uint64_t,uint64_t);')
  needle='    int do_print = 0; uint64_t n_seen = 0;';assert text.count(needle)==1
  text=text.replace(needle,'    liuqin_r102_undefined(stage,pid,nm,exc,sig,code,subcode);\n'+needle);perf.write_text(text)
  # Worker-only evidence fence: acknowledge only a complete successful bulk-IN
  # transfer. No USB endpoint or transport policy changes.
  rel='bsd/dev/liuqin_usb_debug.c';names.append(rel)
  usb=(f/rel).read_text().replace('static volatile int ep3_owner;', 'static volatile int ep3_owner;\nstatic uint64_t r102_pending_cursor,r102_completed_cursor;\nstatic unsigned r102_transport_gap;\nuint64_t liuqin_r102_usb_completed(void);\nuint64_t liuqin_r102_usb_completed(void) { return __atomic_load_n(&r102_transport_gap,__ATOMIC_ACQUIRE)?0:__atomic_load_n(&r102_completed_cursor,__ATOMIC_ACQUIRE); }')
  needle='\tif (ep == 3) {\n\t\tep3_drop();'
  assert usb.count(needle)==1
  usb=usb.replace(needle,'\tif (ep == 3) {\n        if(left && r102_pending_cursor)__atomic_store_n(&r102_transport_gap,1,__ATOMIC_RELEASE);\n        if(!left && r102_pending_cursor)__atomic_store_n(&r102_completed_cursor,r102_pending_cursor,__ATOMIC_RELEASE);\n        r102_pending_cursor=0;\n\t\tep3_drop();')
  needle='\tunsigned n = liuqin_debug_copy(&u.cursor, (char *)(u.dma + TX), TX_SIZE);'
  assert usb.count(needle)==1
  usb=usb.replace(needle,'\tuint64_t r102_before_copy=u.cursor;\n'+needle+'\n    if(u.cursor-r102_before_copy!=n)__atomic_store_n(&r102_transport_gap,1,__ATOMIC_RELEASE);')
  needle='\tif (n) {\n\t\tlq_tx_last_nl'
  assert usb.count(needle)==1
  usb=usb.replace(needle,'\tif (n) {\n        r102_pending_cursor=u.cursor;\n\t\tlq_tx_last_nl')
  (overlay/rel).write_text(usb)
  patch=''
  for rel in names:
   original=(f/rel).read_text() if (f/rel).exists() else ''
   patch+=''.join(difflib.unified_diff(original.splitlines(True),(overlay/rel).read_text().splitlines(True),fromfile='a/'+rel,tofile='b/'+rel))
 (W/'observer.patch').write_text(patch)
 prep['changed_kernel_files']=names;prep['observer_patch_sha256']=sha(W/'observer.patch');prep['observer_revision']='A2';prep['behavior_changes']=[];prep['writer_slots']=256;prep['data_bytes']=536870912;prep['fault_rule_sha256']=sha(HERE.parent/'analyze.py')
 (W/'preparation.json').write_text(json.dumps(prep,indent=2)+'\n')
 for variant in ['a','b']:
  d=W/f'device-{variant}';patches=list((d/'patches/xnu').glob('*liuqin-r101.patch'));assert len(patches)==1;patches[0].write_text(patch)
  path=d/'drivers/LiuqinSourceStorage/LiuqinScratchDisk.cpp';s=path.read_text()
  s='#include <sys/proc.h>\nextern "C" void liuqin_r101_emit(int,const char *,...) __attribute__((format(printf,2,3)));\n'+s
  needle=' struct BlkWriter { char comm[16]; uint64_t bytes; uint64_t writes; };';assert s.count(needle)==1;s=s.replace(needle,needle+'\n#include "R102Block.inc"')
  needle='    blkWriters[i].writes++;';assert s.count(needle)==1;s=s.replace(needle,needle+'\n    r102RecordLocked(nbytes,name,false);')
  needle='  blkWriters[31].writes++;';assert s.count(needle)==1;s=s.replace(needle,needle+'\n  r102RecordLocked(nbytes,name,true);')
  needle='  gate=IOLockAlloc(); if(!gate)return false;';assert s.count(needle)==1;s=s.replace(needle,needle+'\n  r102_window=static_cast<R102Blk *>(IOMallocZero(256*sizeof(R102Blk)));\n  r102_copy=static_cast<R102Blk *>(IOMallocZero(256*sizeof(R102Blk)));')
  needle='  if(gate){IOLockFree(gate);gate=nullptr;}';assert s.count(needle)==1;s=s.replace(needle,'  if(r102_window)IOFree(r102_window,256*sizeof(R102Blk));\n  if(r102_copy)IOFree(r102_copy,256*sizeof(R102Blk));\n'+needle)
  s+='\nextern "C" void liuqin_r102_block_window(uint64_t now) { if(activeScratch)activeScratch->r102Window(now); }\n'
  path.write_text(s);shutil.copy2(HERE/'kernel/R102Block.inc',path.parent/'R102Block.inc')
 # Freeze the exact host classification rule before the next capture.
 evidence=W/'evidence';evidence.mkdir(exist_ok=True)
 (evidence/'analysis-rule-frozen.py.txt').write_bytes((HERE.parent/'analyze.py').read_bytes())
 (evidence/'analysis-rule.json').write_text(json.dumps({'sha256':prep['fault_rule_sha256'],'keys':['comm','stage','exc','sig','code'],'pc_normalization':'none','global_new_or_absent_claim':False,'freeze':'before A2 build/capture'},indent=2)+'\n')
 print(json.dumps({'work':str(W),'observer_patch_sha256':prep['observer_patch_sha256'],'walker_candidates':True,'hardware_boots':0}))
if __name__=='__main__':main()
