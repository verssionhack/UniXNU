#!/usr/bin/env python3
"""Freeze the single A7 capture, retaining frozen status and explicit hook loss."""
from pathlib import Path
import datetime,hashlib,json
R=Path(__file__).resolve().parents[4];H=Path(__file__).resolve().parent;W=R/'out/liuqin-r101-a7-work';E=W/'evidence';F=E/'a/boot-A7-20261121-164915'
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
dest=E/'result-manifest.json';assert not dest.exists()
checked={}
for p in [E/'host-manifest.json',R/'out/liuqin-r101-a6-work/evidence/result-manifest.json']:
    m=json.loads(p.read_text())
    for name,digest in m['files'].items():assert sha(R/name)==digest,name
    checked[str(p.relative_to(R))]=len(m['files'])
record=json.loads((F/'boot-record.json').read_text());r=json.loads((F/'analysis-a7.json').read_text());assessment=json.loads((F/'capture-assessment.json').read_text())
assert record['image_sha256']=='ffdec111a73bdfafd5be42574dbf71d0542c0c78daffb8d98fde8942a91a3d5a'
assert record['capture_status']=='complete-observer-capture' and record['assessment_exit_code']==0 and record['returned_to_fastboot']
assert sha(F/'usb.log')==record['log_sha256'] and sha(F/'guard-trace.jsonl')==record['trace_sha256']
assert len(list((E/'a').glob('boot-A7-*')))==1
assert all(v for k,v in r['checks'].items() if k!='hook_history_lossless')
assert not r['checks']['hook_history_lossless'] and r['loss_last'][0]['ring_drop']==68558
assert all(s['complete'] for s in r['snapshot_completeness'])
assert r['exact_guard_replay']['status']=='PASS' and r['exact_guard_replay']['steps']==2223
assert all(s['outcome']=='created_resumed_server_init' and not s['failed_reads'] for s in r['state_outcomes'])
supp=json.loads((F/'notifier-supplement.json').read_text())
assert len(supp['outcomes'])==3 and all(s['status']=='qualified-counts' and all(n['matched_count']==1 and n['pending_count']==0 for n in s['notifiers'].values()) for s in supp['outcomes'])
for t in [60,120,300]:
    ws=json.loads((F/f'frames-WindowServer-{t}-validation.json').read_text());cs=json.loads((F/f'frames-clocksyncd-{t}-validation.json').read_text())
    assert (ws['raw_frame_count'],ws['plausible_frames'])==(64,62)
    assert (cs['raw_frame_count'],cs['plausible_frames'])==(11,10)
    assert not ws['native_reader_validated'] and not cs['native_reader_validated']
    assert any('WSSystemCanCompositeWithMetal' in f.get('symbolication','') and f['status']=='callsite-plausible' for f in ws['frames'])
paths=[p for p in F.rglob('*') if p.is_file()]+[p for p in H.iterdir() if p.is_file()]+[E/n for n in ['launch-authorization.json','effective-A6-runner.py.txt','host-manifest.json']]+[W/n for n in ['run-A7.log','analysis.log']]
manifest={'time':datetime.datetime.now().astimezone().isoformat(),'status':'primary-publication-experiment-succeeded; WindowServer-Metal-wait-and-SIGABRT; hook-histories-lossy','capture_status':record['capture_status'],'runner_exit':0,'volatile_boots':1,'returned_to_fastboot':True,'boot_sha256':record['image_sha256'],'raw_log_sha256':record['log_sha256'],'trace_sha256':record['trace_sha256'],'prior_entries_verified':checked,'snapshot_checksums_verified':3,'exact_guard_calls_verified':2223,'hook_history_lossless':False,'last_sampled_ring_drop':68558,'EXC_CRASH_correction':'high byte is termination signal; 0x06=SIGABRT, not DYLD namespace','no_flash_or_private_key_operation':True,'native_reader_validated':False,'files':{str(p.relative_to(R)):sha(p) for p in sorted(set(paths))}}
dest.write_text(json.dumps(manifest,indent=2)+'\n');print('Frozen',len(manifest['files']),'files. Manifest SHA256:',sha(dest))
