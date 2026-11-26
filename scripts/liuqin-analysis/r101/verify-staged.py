#!/usr/bin/env python3
"""Verify staged A/B identities and invariants without opening USB or booting."""
from pathlib import Path
import hashlib,importlib.util,json,subprocess,sys
R=Path(__file__).resolve().parents[3];W=R/'out/liuqin-r101-work';H=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('runner',H/'run-r101.py');runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
checks={}
for variant in ['a','b']:
    e,j=runner.validate(variant);assert j['hardware_tested'] is False
    assert j['trust_cache_sha256']=='daf5a74e200f7390c86981cfe8fe84ddbb0d490d07610895bd5b48806678a5e5'
    assert not json.loads((W/'preparation.json').read_text())['walker_candidates']
    assert '#define R101_CAPTURE_CANDIDATES 0' in (e/'sources/osfmk/kern/liuqin_r101_walk.inc').read_text()
    assert j['observer_patch_sha256']==runner.sha(W/'observer.patch')
    assert j['kernel_args_len']==len(j['kernel_args'])<=1000
    names=dict(x.split('=',1) for x in j['kernel_args'].split() if '=' in x)
    assert all(names.get(k)==v for k,v in {'smp':'1','armcpu-self-ipi':'1','epss_step':'4','liuqin-scratch-probe':'1','liuqin-parkd-prepare':'1','lq_cs4k':'1','aks':'1'}.items())
    for key in ['liuqin_r101_emit','liuqin_r101_task_waits','liuqin_r101_scale','liuqin_r101_storage_dump','liuqin_r101_validate_walk_fixture','liuqin_r101_debug_line']:
        assert ('_'+key) in (e/'nm.txt').read_text(),key
    nm=(e/'nm.txt').read_text()
    assert ('_native_legacy_display_probe' in nm)==(variant=='a')
    if variant=='a':assert names['offline-legacy-phase']=='4' and 'ml-timeout-lock-panic-scale' not in names
    else:assert names['ml-timeout-lock-panic-scale']=='40' and 'offline-legacy-phase' not in names
    checks[variant]={'status':'PASS','boot_sha256':j['boot_sha256'],'kernel_sha256':j['kernel_sha256'],'kernel_args_len':j['kernel_args_len'],'segments':j['segments'],'package_hardware_tested_at_creation':j['hardware_tested']}
comparison=json.loads((W/'evidence/source-comparison.json').read_text());assert comparison['common_source_compare']['kernel_source_equal'] is True
for rel,digest in comparison['common_source_compare']['files'].items():
    for v in ['a','b']:assert runner.sha(W/'evidence'/v/'sources'/rel)==digest
for rel,digest in json.loads((W/'frozen-r100b-source-sha256.json').read_text()).items():assert runner.sha(W/'frozen-r100b-source'/rel)==digest
subprocess.run([sys.executable,H/'test_runner.py'],check=True)
subprocess.run([sys.executable,H/'check-candidates.py'],check=True)
subprocess.run([sys.executable,H/'test_fault_classes.py'],check=True)
subprocess.run([sys.executable,H/'test_coverage.py'],check=True)
subprocess.run([sys.executable,H/'test_user_frames.py'],check=True)
subprocess.run([sys.executable,H/'check-panic-path.py'],check=True,stdout=subprocess.DEVNULL)
subprocess.run([sys.executable,H/'check-idle-extraction.py'],check=True,stdout=subprocess.DEVNULL)
subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',H/'test_framewalk.c','-o',W/'test-framewalk'],check=True)
subprocess.run([W/'test-framewalk'],check=True)
trials=[]
for path in sorted((W/'evidence').glob('[ab]/boot-*/boot-record.json')):
    trial=json.loads(path.read_text());trials.append({'record':str(path.relative_to(R)),'tag':trial['tag'],'returned_to_fastboot':trial['returned_to_fastboot'],'elapsed_seconds':trial['elapsed_seconds']})
report={'status':'PASS','variants':checks,'same_observer_kernel_sources':True,'frozen_baseline_unchanged':True,'runner_tests':9,'snapshot_coverage_tests':8,'host_callsite_tests':11,'fault_signature_and_field_tests':5,'frame_walk_tests':'host fixtures PASS; native reader/user-stack fixture not hardware validated','hardware_boots_by_this_check':0,'captured_trials':trials,'coverage_limits':['No verified bootstrap/XPC name decoder; unsupported layouts counted, not absence','A1 walker is gated; dormant A2 raw-candidate reader compiles and host callsite/export tests pass; native/target-cache validation remains pending'],'device_action':'none'}
(W/'evidence/host-verification.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
