#!/usr/bin/env python3
"""Analyze r101 capture without treating missing/undecoded observations as absence."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,re
R=Path(__file__).resolve().parents[3]
def module(name,p):
    s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
coverage_checks=module('coverage_checks',Path(__file__).with_name('coverage.py'))
base=module('audit',R/'scripts/liuqin-analysis/r100/audit-review.py');exact=module('exact',Path(__file__).with_name('replay-exact.py'))
def observation_fields(line):
    row=base.fields(line)
    # Native observer %llx fields can contain only decimal-looking digits.
    # Preserve their hexadecimal radix explicitly; never guess from characters.
    kinds={
        'LQ101 WAIT:':('state','event','waitq','receive'),
        'LQ101 WAIT_OBJECT:':('obj','receive_name'),
        'LQ101 USER_STATE:':('pc','lr','sp','fp'),
        'LQ101 FRAME:':('fp_raw','lr_raw'),
        'LQ101 USER_MAP:':('min','max','machine_max'),
        'LQ101 SHARED_REGION:':('base','slide'),
    }
    for prefix,keys in kinds.items():
        if line.startswith(prefix):
            for key in keys:
                match=re.search(r'(?:^| )'+key+r'=([0-9a-fA-F]+)(?: |$)',line)
                if match:row[key]='0x'+match[1]
    if line.startswith('LQ101 SHARED_REGION:'):
        match=re.search(r' uuid=([^ ]+)',line)
        if match:row['uuid']=match[1]
    return row

def fault_classes(rows,baseline):
    keys=('comm','stage','exc','sig','code')
    signature=lambda r:tuple(str(r.get(k)) for k in keys)
    known={signature(r) for r in baseline}
    known_processes={r['comm'] for r in baseline}
    result=[]
    for r in rows:
        if signature(r)==('parkd','exc_crash','10','5','0x9000000'):label='expected-existing-denial-policy'
        elif signature(r) in known:label='pre-existing-unresolved'
        elif r['comm'] in known_processes:label='new-signature-in-compared-capture'
        else:label='new-process-in-compared-capture'
        result.append({**r,'classification':label,'match_confidence':'comm/stage/exc/sig/code signature; capped comparison; no guessed PC normalization','global_new_or_absent_claim':False})
    return result

def analyze(folder):
    path=folder/'usb.log';raw=path.read_bytes();lines=raw.decode(errors='replace').splitlines();data=base.load(path)
    reference=R/'out/liuqin-r100-work/evidence/review/review-audit.json';old=json.loads(reference.read_text())
    tagged=[(i,l) for i,l in enumerate(raw.splitlines(keepends=True),1) if l.startswith((b'LQ101 ',b'LIUQIN TASK_CPU'))]
    overlong=[{'line':i,'bytes':len(l)} for i,l in tagged if len(l)>=255]
    def values(prefix):return [{'line':i,'raw':l,**observation_fields(l)} for i,l in enumerate(lines,1) if l.startswith(prefix)]
    coverage=values('LQ101 COVERAGE:');loss=values('LQ101 LOSS:');output=values('LQ101 OUTPUT:')
    incomplete=not coverage or any(x.get('undecoded',0) or x.get('endpoint_unknown',0) for x in coverage)
    incomplete=incomplete or any(x.get('ring_drop',0) or x.get('payload_trunc',0) or x.get('saturated',0) for x in loss)
    report={'log_sha256':hashlib.sha256(raw).hexdigest(),'exact_guard_replay':exact.replay(folder),'first_quiescent_sample':data['first_quiescent_sample'],'registration_end_markers':raw.count(b'LIUQIN FILE: phase=end'),'el0_traps':raw.count(b'LIUQIN EL0 TRAP:'),'el0_fault_details':len(data['faults']),'faults_versus_r100b':fault_classes(data['faults'],old['logs']['r100b']['faults']),'faults_versus_r99p':fault_classes(data['faults'],old['logs']['r99p']['faults']),'fault_detail_caveat':'Detail records may be capped; EL0 TRAP=0 does not mean zero faults.','el0_fault_summary':values('LIUQIN EL0_FAULT_SUM:'),'jetsam_details':values('LIUQIN JETSAM_TOP:'),'jetsam_last':data['jetsam'][-1:] ,'vnodes_last':data['vnodes'][-1:],'spaces':values('LQ101 SPACE:'),'media':values('LQ101 MEDIA:'),'ancestors':values('LQ101 ANCESTOR:'),'snapshots':values('LQ101 SNAPSHOT:'),'waits':values('LQ101 WAIT:'),'wait_objects':values('LQ101 WAIT_OBJECT:'),'deadlines':values('LQ101 DEADLINE:'),'user_maps':values('LQ101 USER_MAP:'),'shared_regions':values('LQ101 SHARED_REGION:'),'user_state':values('LQ101 USER_STATE:'),'walk_validation':values('LQ101 WALK_VALIDATION:'),'walks':values('LQ101 WALK:'),'frames':values('LQ101 FRAME:'),'scale':values('LQ101 SCALE:'),'coverage':coverage,'loss':loss,'output':output,'enospc_counts':values('LQ101 ENOSPC_COUNT:'),'lookup_coverage':'incomplete' if incomplete else 'requires-manual-endpoint-and-startup-validation','no_lookup_claim_permitted':False,'new_observer_log_bytes':sum(len(l) for _,l in tagged),'overlong_observer_lines':overlong,'observer_budget_ok':sum(len(l) for _,l in tagged)<=512*1024,'cpu_windows':data['windows'],'raw_event_lines':[{'line':i,'text':l} for i,l in enumerate(lines,1) if l.startswith(('LQ101 EVENT:','LQ101 TEXT:','LQ101 IPC:','LQ101 IPC_WIRE:'))]}
    report['snapshot_completeness']=coverage_checks.snapshot_coverage(lines)
    report['apfs_enospc_coverage']=coverage_checks.apfs_coverage(lines)
    report['iokit_scope']='matching requests; outstanding notifications unknown'
    report['scale_effective_40_seen']=any(x.get('scale')==40 for x in report['scale'])
    required=['LQ101 INIT:','LQ101 SCALE:','LQ101 COVERAGE:','LQ101 LOSS:','LQ101 OUTPUT:','LQ101 SPACE:','LQ101 MEDIA:']
    report['missing_observers']=[prefix for prefix in required if not any(line.startswith(prefix) for line in lines)]
    observed_targets={x['target_s'] for x in report['snapshot_completeness'] if x['complete']}
    report['missing_snapshot_targets']=sorted({60,120,300}-observed_targets)
    report['a1_acceptance']={'snapshots_complete':not report['missing_snapshot_targets'] and all(x['complete'] for x in report['snapshot_completeness']),'scale_40':report['scale_effective_40_seen'],'data_ancestry_shown':bool(report['ancestors']),'syscall_writers_named':bool(report['enospc_counts']),'apfs_async_writers_named':False}
    report['status']='captured-observers; blocked-object attribution requires review'
    if report['missing_observers'] or report['missing_snapshot_targets'] or report['registration_end_markers']!=82 or not report['scale_effective_40_seen'] or not report['ancestors']:
        report['status']='boot-or-observer-contract-failed'
    if any(not x['complete'] for x in report['snapshot_completeness']) or overlong or not report['observer_budget_ok']:report['status']='observer-output-contract-failed'
    return report
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder',type=Path);a=p.parse_args();report=analyze(a.folder.resolve());dest=a.folder/'analysis-r101.json';dest.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'status':report['status'],'output':str(dest),'lookup_coverage':report['lookup_coverage'],'scale_effective_40_seen':report['scale_effective_40_seen']},indent=2))
