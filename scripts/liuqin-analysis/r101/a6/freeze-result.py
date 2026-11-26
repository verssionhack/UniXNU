#!/usr/bin/env python3
"""Freeze A6 result and its completed host branch audit, preserving parent evidence."""
from pathlib import Path
import hashlib,json,datetime
R=Path(__file__).resolve().parents[4];H=Path(__file__).resolve().parent;W=R/'out/liuqin-r101-a6-work';E=W/'evidence';F=E/'a/boot-A6-20261121-150526'
def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
assert not (E/'result-manifest.json').exists();checked=0
for p in [R/'out/liuqin-r101-a5r1-work/evidence/result-manifest.json',E/'review-manifest.json']:
 m=json.loads(p.read_text());files=m.get('files',m)
 for name,digest in files.items():assert sha(R/name)==digest,name;checked+=1
r=json.loads((F/'analysis-a6.json').read_text());record=json.loads((F/'boot-record.json').read_text());assert all(r['checks'].values()) and r['status']=='attached-unregistered-clock-manager-confirmed';assert record['returned_to_fastboot'] and record['assessment_exit_code']==0
assert sha(F/'usb.log')==record['log_sha256'] and sha(F/'guard-trace.jsonl')==record['trace_sha256']
for p in r['publication_outcomes']:
 assert p['outcome']=='attached_unregistered_no_clock_ID' and p['positive_control']
 clock=next(v for v in p['publications'] if v['cls']=='IOTimeSyncClockManager');assert clock['state']=='0'
 assert all(v['present']=='0' and v['type']=='none' and v['decoded']=='0' for v in p['properties'])
 assert p['translation_control']=={'registered':'1','matched':'1','inactive':'0'}
for f in r['frames']:
 assert not f['native_reader_validated']
 if f['name']=='WindowServer':assert f['raw_frame_count']==f['plausible_frames']==16 and f['callsite_validation_passed']
 else:assert f['raw_frame_count']==10 and f['plausible_frames']==9 and [x['lr_raw'] for x in f['frames'] if x['status']!='callsite-plausible']==[0]
assert json.loads((E/'host-branches/inputs.json').read_text())['sha256']=='d1003b5143ffd88439b4d45b6017f587171cfe6855660bed05370a2ea5db9fe9'
paths=[p for p in E.rglob('*') if p.is_file()]+[p for p in H.rglob('*') if p.is_file() and '__pycache__' not in p.parts]+[p for p in W.glob('*.log')]+[R/'kits/XnuPrelink/kc_image.py',R/'scripts/liuqin-analysis/r101/a4/validate-frames.py',R/'scripts/liuqin-analysis/r101/a5r1/decode-state.py']
manifest={'time':datetime.datetime.now().astimezone().isoformat(),'status':r['status'],'capture_status':record['capture_status'],'volatile_boots':1,'behavior_changes':0,'returned_to_fastboot':True,'boot_sha256':record['image_sha256'],'raw_log_sha256':record['log_sha256'],'parent_and_preboot_entries_rechecked':checked,'host_contract':'complete candidate/fallback/MAC/publication/notification/delayed-retry audit; no interface experiment built or booted','files':{str(p.relative_to(R)):sha(p) for p in sorted(set(paths))}}
(E/'result-manifest.json').write_text(json.dumps(manifest,indent=2)+'\n');print('Frozen',len(manifest['files']),'files; SHA256',sha(E/'result-manifest.json'))
