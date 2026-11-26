#!/usr/bin/env python3
"""Freeze corrected readiness result; preserve A5 null and all original verdicts."""
from pathlib import Path
import hashlib,json,datetime
R=Path(__file__).resolve().parents[4];H=Path(__file__).resolve().parent;W=R/'out/liuqin-r101-a5r1-work';E=W/'evidence';F=E/'a/boot-A5r1-20261121-102912'
def sha(p):
 with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
assert not (E/'result-manifest.json').exists();checked=0
for p in [R/'out/liuqin-r101-a4-work/evidence/result-manifest.json',R/'out/liuqin-r101-a5-work/evidence/result-manifest.json',E/'review-manifest.json']:
 d=json.loads(p.read_text());files=d.get('files',d)
 for name,digest in files.items():assert sha(R/name)==digest,name;checked+=1
rec=json.loads((F/'boot-record.json').read_text());result=json.loads((F/'analysis-a5r1.json').read_text());assert rec['capture_status']=='complete-observer-capture' and rec['assessment_exit_code']==0 and rec['returned_to_fastboot'];assert all(result['checks'].values())
assert sha(F/'usb.log')==rec['log_sha256'] and sha(F/'guard-trace.jsonl')==rec['trace_sha256']
assert result['Data_last']['capacity_MiB']==512 and int(result['ENOSPC_last']['total'])==0 and result['Data_min_free_MiB']>190
for r in result['state_analysis']['outcomes']:
 assert r['outcome']=='clock_pending' and not r['failed_reads']
 assert r['notifiers']['CN']['matched_count']==0 and r['notifiers']['CN']['pending_count']==1 and r['notifiers']['GN']['status']=='nil_notifier'
 assert r['server_pointer']=='0x0' and r['diagnostics_pointer']=='0x0' and not r['native_reader_validated']
for r in result['frames']:
 assert not r['native_reader_validated']
 if r['name']=='clocksyncd':assert r['plausible_frames']==9 and r['raw_frame_count']==10 and [v['lr_raw'] for v in r['frames'] if v['status']!='callsite-plausible']==[0]
 else:assert r['callsite_validation_passed'] and r['plausible_frames']==17
source=json.loads((E/'full-baseline-source-audit.json').read_text());assert source['checked']==6132 and not source['different'] and not source['missing'];assert json.loads((E/'Data-seed-audit.json').read_text())['Data_seed_identical']
paths=[p for p in E.rglob('*') if p.is_file()]+[p for p in H.rglob('*') if p.is_file() and '__pycache__' not in p.parts]+[p for p in W.glob('*.log')]+[R/'kits/XnuPrelink/kc_image.py',R/'scripts/liuqin-analysis/r101/a4/validate-frames.py',R/'scripts/liuqin-analysis/r101/validate-user-frames.py']
r={'time':datetime.datetime.now().astimezone().isoformat(),'status':'clock-availability-pending; complete-observer-capture','boot_count_this_A5_session':2,'behavior_changes':0,'returned_to_fastboot':True,'image_sha256':rec['image_sha256'],'log_sha256':rec['log_sha256'],'prior_manifest_entries_rechecked':checked,'A5_framework_ownership_audit_error':'disclosed and corrected; original capture/null/inputs preserved','Data_usage_change':'unattributed; compiled seed bytes and behavior inputs unchanged; no ENOSPC in A5/A5r1','files':{str(p.relative_to(R)):sha(p) for p in sorted(set(paths))}}
(E/'result-manifest.json').write_text(json.dumps(r,indent=2)+'\n');print('Frozen',len(r['files']),'result files; SHA256',sha(E/'result-manifest.json'))
