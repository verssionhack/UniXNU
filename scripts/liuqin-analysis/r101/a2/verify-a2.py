#!/usr/bin/env python3
"""Host acceptance of isolated A2; no USB opens or boots."""
from pathlib import Path
import ast,hashlib,importlib.util,json,shutil,subprocess,sys
H=Path(__file__).resolve().parent;R=H.parents[3];W=R/'out/liuqin-r101-a2-work';BASE=R/'out/liuqin-r101-work';E=W/'evidence';A=E/'a'
def sha(p):
 with p.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def load(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
runner=load('a2runner',H/'run-a2.py');folder,j=runner.validate('a');old=json.loads((BASE/'evidence/a/validation-summary.json').read_text());prep=json.loads((W/'preparation.json').read_text())
assert j['status']=='PASS' and j['hardware_tested'] is False and j['walker_candidates'] is True
for key in ['kernel_args','kernel_args_len','adt_sha256','trust_cache_sha256']:assert j[key]==old[key],key
assert j['kernel_args_len']==999
assert j['observer_patch_sha256']==sha(W/'observer.patch')==prep['observer_patch_sha256']
assert prep['data_bytes']==536870912 and prep['behavior_changes']==[]
assert int(j['segments']['__TEXT'],16)<=0x1d8000 and int(j['segments']['__DATA'],16)<=0x284000 and int(j['text_const_vma'],16)>=0xfffffff007005900
assert '#define R101_CAPTURE_CANDIDATES 1' in (A/'sources/osfmk/kern/liuqin_r101_walk.inc').read_text()
assert '#define R101_WRITERS 256u' in (A/'sources/bsd/dev/liuqin_r101.inc').read_text()
nm=(A/'nm.txt').read_text()
assert '_liuqin_r101_validate_walk_fixture' not in nm
for name in ['liuqin_r102_cpu_readback','liuqin_r102_block_window','liuqin_r101_task_waits','liuqin_r102_undefined']:assert '_'+name in nm,name
critical=['osfmk/arm64/start.s','osfmk/arm/caches.c','bsd/kern/kern_exec.c','bsd/kern/kern_proc.c','osfmk/mach/arm/vm_param.h','osfmk/arm64/proc_reg.h']
source=R/'out/liuqin/macos-27.3-26C5035r/liuqin/tree/.cache/xnu-work'
for rel in critical:assert sha(source/rel)==sha(BASE/'frozen-r100b-source'/rel),rel
for rel in prep['changed_kernel_files']:assert sha(source/rel)==sha(A/'sources'/rel),rel
old_driver=BASE/'device-a/drivers/LiuqinSourceStorage';new_driver=W/'device-a/drivers/LiuqinSourceStorage'
for name in ['SparseDisk.h','ScratchSeed.inc','R101Variant.h']:assert sha(new_driver/name)==sha(old_driver/name),name
before=(old_driver/'LiuqinScratchDisk.cpp').read_text();after=(new_driver/'LiuqinScratchDisk.cpp').read_text()
assert 'static constexpr uint64_t capacity = 512ULL << 20;' in after
start=' IOReturn doAsyncReadWrite';end='OSDefineMetaClassAndStructors'
assert before[before.index(start):before.index(end)]==after[after.index(start):after.index(end)]
frozen=json.loads((E/'analysis-rule.json').read_text());assert frozen['sha256']==sha(H.parent/'analyze.py')==sha(E/'analysis-rule-frozen.py.txt')
for rel,digest in json.loads((BASE/'frozen-r100b-source-sha256.json').read_text()).items():assert sha(BASE/'frozen-r100b-source'/rel)==digest
# Both monitor implementations have precisely the same control/guard AST.
def monitor_ast(path):
 return ast.dump(next(n for n in ast.parse(path.read_text()).body if isinstance(n,ast.ClassDef) and n.name=='Monitor'),include_attributes=False)
assert monitor_ast(H/'run-a2.py')==monitor_ast(H.parent/'run-r101.py')
subprocess.run([sys.executable,H/'test_a2.py'],check=True)
subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror',H/'test_block_windows.cpp','-o',W/'test-block-windows'],check=True)
subprocess.run([W/'test-block-windows'],check=True)
subprocess.run(['c++','-std=c++17','-Wall','-Wextra','-Werror',H/'test_undefined.cpp','-o',W/'test-undefined'],check=True)
subprocess.run([W/'test-undefined'],check=True)
assert sha(A/'sources/osfmk/kern/r101_framewalk.h')==sha(H.parent/'kernel/r101_framewalk.h')
subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',H.parent/'test_framewalk.c','-o',W/'test-framewalk'],check=True)
subprocess.run([W/'test-framewalk'],check=True)
subprocess.run([sys.executable,H.parent/'test_user_frames.py'],check=True)
subprocess.run([sys.executable,H.parent/'test_fault_classes.py'],check=True)
subprocess.run([sys.executable,H.parent/'replay-exact.py',BASE/'evidence/a/boot-A1-20261120-175501'],check=True)
subprocess.run([sys.executable,H/'run-a2.py','--variant','a','--check'],check=True)
# Freeze complete storage observer sources next to the linked native source.
for path in [new_driver/'LiuqinScratchDisk.cpp',new_driver/'R102Block.inc',new_driver/'R101Storage.inc']:
 target=A/'sources-device/drivers/LiuqinSourceStorage'/path.name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
report={'status':'PASS','hardware_boots':0,'boot_sha256':j['boot_sha256'],'kernel_sha256':j['kernel_sha256'],'kernel_args_len':999,'trust_and_adt_equal_A1':True,'data_bytes':536870912,'sctlr_write_path_unchanged':True,'storage_read_write_transport_path_unchanged':True,'USB_observer_instrumentation':'completion cursor; short transfer or cursor gap permanently disables native walker fence','frozen_original_files':6143,'fault_rule_sha256':frozen['sha256'],'a2_tests':12,'native_block_window_tests':'PASS: conservation, legacy overflow, PID separation and recycling','native_undefined_counter_tests':'PASS: 100 events beyond detail cap, WFE/WFI separation, primary-stage filtering, delta and overflow','host_callsite_tests':11,'fault_and_hex_field_tests':5,'A1_guard_replay_calls':2130,'guard_monitor_AST_equal':True,'segments':j['segments'],'text_const_vma':j['text_const_vma'],'text_const_headroom_bytes':int(j['text_const_vma'],16)-0xfffffff007005900,'observer_only':True,'raw_walker_native_validation':'pending hardware; saved-register host callsite profile passed; raw stacks require host validation','log_budget_bytes':524288,'snapshot_reserve_bytes_each':98304,'writer_slots':256,'block_slots_each_window':256}
(E/'host-verification-a2.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
