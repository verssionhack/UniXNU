#!/usr/bin/env python3
"""Apply A7's predeclared branches without changing the frozen capture assessor."""
from pathlib import Path
import argparse,csv,json,re
p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder',type=Path);args=p.parse_args();F=args.folder.resolve()
raw=(F/'usb.log').read_bytes();lines=raw.decode(errors='replace').splitlines();capture=json.loads((F/'boot-record.json').read_text())
assessment=json.loads((F/'capture-assessment.json').read_text());a=assessment.get('analysis',{})
def fields(s):return dict(re.findall(r'(\w+)=([^ ]+)',s))
driver=[{'line':i,'raw':s,**fields(s)} for i,s in enumerate(lines,1) if s.startswith('LQ107 ETHERNET:')]
ready=[r for r in driver if r.get('stage')=='ready'];complete=[r for r in driver if r.get('stage')=='complete' and r.get('rc')=='0' and r.get('retained')=='1']
quiet={phase:[r for r in driver if r.get('stage')==phase] for phase in ['prequiet','postquiet']}
activation=bool(len(ready)==1 and len(complete)==1 and ready[0].get('cls')=='IOEthernetInterface' and ready[0].get('builtin')=='1' and ready[0].get('mac_bytes')=='6' and ready[0].get('carrier')=='0' and all(len(rows)==1 and rows[0].get('rc')=='0' for rows in quiet.values()))
states=assessment.get('state_outcomes',[]);outcomes=[]
for pub in assessment.get('publication_outcomes',[]):
    when=pub['target_s'];state=next((s for s in states if s['target_s']==when),{})
    clock=next((r for r in pub.get('publications',[]) if r.get('cls')=='IOTimeSyncClockManager'),{})
    props={r.get('key'):r for r in pub.get('properties',[]) if r.get('rid')==clock.get('rid')}
    cid=props.get('TimeSyncTimeClockID',{});domain=props.get('TimeSyncTimeCoreAudioClockDomain',{})
    try:
        typed=cid.get('present')=='1' and cid.get('decoded')=='1' and cid.get('type')=='OSNumber' and cid.get('bits')=='64' and domain.get('present')=='1' and domain.get('decoded')=='1' and domain.get('type')=='OSNumber' and domain.get('bits')=='32' and int(domain['value'],16)==0x63690000
    except (KeyError,ValueError):typed=False
    published=pub.get('protocol_complete',False) and clock.get('registered')=='1' and clock.get('matched')=='1' and clock.get('inactive')=='0' and typed
    outcome='publication_not_confirmed'
    if not activation:outcome='adapter_activation_failure'
    elif published:
        outcome={'gptp_pending':'clock_published_gptp_pending','created_resumed_server_init':'clock_published_server_allocated','clock_pending':'clock_published_userspace_still_pending'}.get(state.get('outcome'),'clock_published_userspace_state_unknown')
    outcomes.append({'target_s':when,'outcome':outcome,'clock_published_with_typed_ID':published,'clock':clock,'properties':props,'daemon_control':pub.get('positive_control'),'translation_control':pub.get('translation_control'),'state_outcome':state.get('outcome'),'notifiers':state.get('notifiers'),'server_pointer':state.get('server_pointer'),'listener_pointer':state.get('listener_pointer'),'server_allocation_does_not_prove_live_reply':True})
frames=[]
for name in ['WindowServer','clocksyncd']:
    for t in [60,120,300]:
        f=F/f'frames-{name}-{t}-validation.json'
        if f.exists():frames.append(json.loads(f.read_text()))
born=re.search(rb'^LQ101 INIT: t_ms=(\d+)',raw,re.M);born=int(born[1]) if born else None
spaces=[{**r,'relative_ms':r['t_ms']-born,'capacity_MiB':r['blocks']*r['bsize']/1048576,'free_MiB':r['free']*r['bsize']/1048576} for r in a.get('spaces',[]) if 'free' in r and born is not None]
memory=a.get('a2_memory',[]);minimum=min(memory,key=lambda r:int(r['free'])) if memory else None
for n,rows in [('Data-space-series.csv',spaces),('memory-series.csv',memory)]:
    if rows:
        with (F/n).open('w') as f:w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
tagged=[l for l in raw.splitlines(keepends=True) if l.startswith((b'LQ101 ',b'LQ102 ',b'LIUQIN TASK_CPU'))]
embedded=[{'line':i,'raw':s} for i,s in enumerate(lines,1) if any(m.start()!=0 for m in re.finditer(r'LQ10[127] ',s))]
words={}
for r in a.get('a2_undefined_words',[]):words[(r['comm'],int(r['word'],16))]=int(r['total'])
faults=a.get('faults_versus_r100b',[])
raw_wfe=[r for r in faults if r.get('stage')=='ux_sig' and r.get('exc')==2 and r.get('sig')==4 and r.get('code')=='0x1' and r.get('sub')=='0xd503205f']
capture_ok=capture.get('capture_status')=='complete-observer-capture' and capture.get('assessment_exit_code')==0 and capture.get('returned_to_fastboot') and not capture.get('abort_reason') and not capture.get('fatal')
loss=a.get('loss',[]);hook_lossless=bool(loss) and all(not r.get('ring_drop',0) for r in loss)
checks={'frozen_capture_complete':bool(capture_ok),'adapter_ready':activation,'three_typed_clock_publications':len(outcomes)==3 and all(r['clock_published_with_typed_ID'] for r in outcomes),'daemon_controls':len(outcomes)==3 and all(r['daemon_control'] for r in outcomes),'all8_nTWE1_nTWI0':{int(r['cpu']) for r in a.get('a2_sctlr',[])}==set(range(8)) and all(r['nTWE']=='1' and r['nTWI']=='0' for r in a.get('a2_sctlr',[])),'no_embedded_prefix':not embedded,'observer_budget':sum(map(len,tagged))<=524288 and max(map(len,tagged),default=0)<255,'hook_history_lossless':hook_lossless}
result={'status':('complete-capture-activation-failed' if not activation else 'complete-capture-see-publication-branches') if capture_ok else 'capture-incomplete-preserve-frozen-exit','checks':checks,'capture':capture,'driver_lifecycle':driver,'outcomes':outcomes,'state_outcomes':states,'publication_outcomes_frozen_decoder':assessment.get('publication_outcomes',[]),'frames':frames,'snapshot_completeness':a.get('snapshot_completeness'),'registry_coverage':assessment.get('registry_coverage'),'registry_services':[s for s in lines if s.startswith('LQ102 TIMESYNC_SERVICE:')],'exact_guard_replay':a.get('exact_guard_replay'),'scale':a.get('scale'),'Data_samples':len(spaces),'early_Data_samples':sum(r['relative_ms']<=60000 for r in spaces),'Data_last':spaces[-1] if spaces else None,'memory_min':minimum,'memory_min_free_MiB':int(minimum['free'])/256 if minimum else None,'ENOSPC_last':a.get('a2_enospc_totals',[])[-1:] ,'undefined_last':a.get('a2_undefined_totals',[])[-1:],'sampled_WFE':sum(n for (comm,w),n in words.items() if w==0xd503205f),'raw_WFE':raw_wfe,'fault_details':faults,'fault_summary_last':a.get('el0_fault_summary',[])[-1:],'jetsam_last':a.get('jetsam_last'),'vnodes_last':a.get('vnodes_last'),'observer_bytes':sum(map(len,tagged)),'driver_bytes':sum(len((r['raw']+'\n').encode()) for r in driver),'max_observer_line_with_LF':max(map(len,tagged),default=0),'embedded_observer_prefixes':embedded,'output_last':a.get('output',[])[-1:],'loss_last':a.get('loss',[])[-1:],'native_reader_validated':False,'limits':['Frozen A6 publication classifier is retained verbatim; its unknown successful-publication branch is interpreted separately here using the predeclared typed-property criteria.','Ready log proves OSData cast/length and builtin property, not a raw MAC-byte dump; the fixed MAC value is pinned host source provenance.','Server pointer alone is allocation evidence, not live listener/reply proof.','User frames remain bounded raw candidates with host callsite checks, not a validated native unwinder.','EL0 TRAP=0 does not mean zero faults.']}
supplement=F/'notifier-supplement.json'
if supplement.exists():result['qualified_notifier_supplement']=json.loads(supplement.read_text())
result['history_loss_boundary']='Frozen complete-observer-capture checks snapshot/output protocol; no_reported_output_loss checks OUTPUT suppression/truncation/summary failure, not LOSS.ring_drop. Hook histories are lossy when hook_history_lossless is false.'
(F/'analysis-a7.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:result[k] for k in ['status','checks','driver_lifecycle','outcomes','Data_last','memory_min_free_MiB']},indent=2))
