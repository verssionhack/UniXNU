#!/usr/bin/env python3
"""Freeze A4 result without altering the preboot inputs or raw verdict."""
from pathlib import Path
import hashlib,json,datetime
R=Path(__file__).resolve().parents[4];H=Path(__file__).resolve().parent;W=R/'out/liuqin-r101-a4-work';E=W/'evidence';F=E/'a/boot-A4-20261121-094931'
def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
assert not (E/'result-manifest.json').exists()
checked=0
for p in [R/'out/liuqin-r101-a3r1-work/evidence/review-manifest.json',E/'review-manifest.json']:
 d=json.loads(p.read_text());files=d.get('files',d)
 for name,digest in files.items():assert sha(R/name)==digest,name;checked+=1
record=json.loads((F/'boot-record.json').read_text());assert record['returned_to_fastboot'] and record['capture_status']=='incomplete-observer-capture' and record['assessment_exit_code']==5
assessment=json.loads((F/'capture-assessment.json').read_text());assert all(assessment['target_contract'].values())
assert assessment['failed_contracts']==['block_windows_accounted','legacy_overflow_breakdown']
assert sha(F/'usb.log')==record['log_sha256'] and sha(F/'guard-trace.jsonl')==record['trace_sha256']
recover=json.loads((F/'block-framing-recovery.json').read_text());assert recover['raw_log_modified'] is False and recover['all_block_windows_accounted_after_exact_suffix_recovery']
assert len(recover['recoveries'])==1 and recover['recoveries'][0]['line']==3608
for t in [60,120,300]:
 ws=json.loads((F/f'frames-WindowServer-{t}-validation.json').read_text());clock=json.loads((F/f'frames-clocksyncd-{t}-validation.json').read_text())
 assert ws['callsite_validation_passed'] and ws['raw_frame_count']==ws['plausible_frames']==17
 assert clock['raw_frame_count']==10 and clock['plausible_frames']==9 and clock['callsite_validation_passed'] is False
 assert [r['lr_raw'] for r in clock['frames'] if r['status']!='callsite-plausible']==[0]
 assert not ws['native_reader_validated'] and not clock['native_reader_validated']
paths=[p for p in E.rglob('*') if p.is_file()]+[p for p in H.rglob('*') if p.is_file() and '__pycache__' not in p.parts]+[p for p in W.glob('*.log')]
manifest={'time':datetime.datetime.now().astimezone().isoformat(),'status':'raw-observer-contract-incomplete; targeted-TimeSync-evidence-complete; exact-storage-suffix-recovery','volatile_boots':1,'returned_to_fastboot':True,'no_behavior_fix_booted':True,'preboot_manifest_entries_rechecked':checked,'image_sha256':record['image_sha256'],'raw_log_sha256':record['log_sha256'],'files':{str(p.relative_to(R)):sha(p) for p in sorted(set(paths))}}
(E/'result-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print('Frozen result:',len(manifest['files']),'files; SHA256',sha(E/'result-manifest.json'))
