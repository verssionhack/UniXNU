#!/usr/bin/env python3
"""Summarize target evidence with explicit gate and coverage boundaries."""
from pathlib import Path
import argparse,json,re,hashlib
H=Path(__file__).resolve().parent;R=H.parents[3]
p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder',type=Path);args=p.parse_args();f=args.folder.resolve();raw=(f/'usb.log').read_bytes();lines=raw.decode(errors='replace').splitlines();capture=json.loads((f/'boot-record.json').read_text());assessment=json.loads((f/'capture-assessment.json').read_text());a=assessment.get('analysis',{})
def fields(line):return dict(re.findall(r'(\w+)=([^ ]+)',line))
rows=lambda prefix:[fields(l) for l in lines if l.startswith(prefix)]
born=int(rows('LQ101 INIT:')[0]['t_ms']);spaces=[{'relative_ms':r['t_ms']-born,'free_MiB':r['free']*r['bsize']/1048576,'capacity_MiB':r['blocks']*r['bsize']/1048576} for r in a.get('spaces',[]) if 'free' in r]
i=next((i for i,r in enumerate(spaces) if r['free_MiB']<16),None);memory=a.get('a2_memory',[]);minimum=min(memory,key=lambda r:int(r['free'])) if memory else None
validations=[]
for t in [60,120,300]:
 for name in ['WindowServer','clocksyncd']:
  q=f/f'frames-{name}-{t}-validation.json'
  if q.is_file():validations.append(json.loads(q.read_text()))
reg=rows('LQ102 TIMESYNC_COVERAGE:');daemon=[v for v in validations if v['name']=='clocksyncd'];gate1=bool(len(daemon)==3 and len(reg)==3 and all(v['callsite_validation_passed'] and any(r['return_unslid']=='0x100025b9c' and r['image']=='clocksyncd' for r in v['frames']) for v in daemon) and all(r.get('exact_daemon')=='0' and r.get('valid')=='1' and r.get('visit_truncated')=='0' and r.get('hit_truncated')=='0' for r in reg))
words={}
for row in a.get('a2_undefined_words',[]):words[(row['comm'],int(row['word'],16))]=int(row['total'])
report={'status':assessment['status'],'capture':capture,'inherited_observer_contract':a.get('a2_contract'),'target_contract':assessment.get('target_contract'),'snapshots':a.get('snapshot_completeness'),'registry_coverage':reg,'registry_services':rows('LQ102 TIMESYNC_SERVICE:'),'target_records':assessment.get('target_records'),'frame_validation':validations,'gate1_supported_inference':gate1,'gate1_interpretation':'Daemon main is inside the host-verified forever wait for IOTimeSyncDaemonService, before TSDDaemon.start and listener creation; absence from complete registry sweeps supports an unmet service match.' if gate1 else 'Null or different gate: inspect actual stacks, identity, registry validity and truncation. Do not select a behavior change from this boolean alone.','native_reader_validated':False,'Data_crossing_below16':spaces[max(0,i-1):i+1] if i is not None else [],'Data_last':spaces[-1:] ,'early_Data_samples':len([r for r in spaces if r['relative_ms']<=60000]),'memory_min_sample':minimum,'memory_min_free_MiB':int(minimum['free'])/256 if minimum else None,'SCTLR':a.get('a2_sctlr'),'undefined_last_sample':a.get('a2_undefined_totals',[])[-1:],'sampled_WFE_count':sum(n for (comm,w),n in words.items() if w==0xd503205f),'raw_WFE_details':[r for r in a.get('faults_versus_r100b',[]) if r['stage']=='ux_sig' and r['exc']==2 and r['sig']==4 and r['code']=='0x1' and r['sub']=='0xd503205f'],'fault_details':a.get('faults_versus_r100b'),'ENOSPC_last':a.get('a2_enospc_totals',[])[-1:],'new_observer_log_bytes':a.get('new_observer_log_bytes'),'output':a.get('output',[])[-1:],'loss':a.get('loss',[])[-1:],'exact_guard_replay':a.get('exact_guard_replay'),'jetsam_last':a.get('jetsam_last'),'vnodes_last':a.get('vnodes_last'),'counter_semantics':'EL0 TRAP=0 does not mean zero faults. WFE histogram ends at stated native sample; raw tail remains detail-capped.','no_behavior_fix_booted':True}
recovery_path=f/'block-framing-recovery.json'
if recovery_path.is_file():
 recovery=json.loads(recovery_path.read_text());report['block_framing_recovery']=recovery
 report['new_observer_log_bytes_including_exact_embedded_suffix']=report['new_observer_log_bytes']+sum(r['recovered_observer_record_bytes_with_LF'] for r in recovery['recoveries'])
 report['raw_contract_status_preserved']=True
(f/'analysis-a4.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:report[k] for k in ['status','target_contract','gate1_supported_inference','Data_crossing_below16','memory_min_free_MiB','sampled_WFE_count','new_observer_log_bytes']},indent=2))
