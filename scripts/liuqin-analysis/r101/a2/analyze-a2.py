#!/usr/bin/env python3
"""A2 analysis with the pre-frozen fault rule and expanded observer contracts."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,re
H=Path(__file__).resolve().parent;R=H.parents[3];W=R/'out/liuqin-r101-a2-work'
def load(name,path):
 s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
base=load('analysis',H.parent/'analyze.py');checks=load('a2_coverage',H/'coverage.py');blocks=load('blocks',H/'block-coverage.py');undefined=load('undefined',H/'undefined-coverage.py')
def analyze(folder):
 frozen=json.loads((W/'evidence/analysis-rule.json').read_text());rule=H.parent/'analyze.py'
 if hashlib.sha256(rule.read_bytes()).hexdigest()!=frozen['sha256']:raise ValueError('Fault rule changed after A2 freeze')
 base.coverage_checks.snapshot_coverage=checks.snapshot_coverage
 report=base.analyze(folder);raw=(folder/'usb.log').read_bytes();lines=raw.decode(errors='replace').splitlines()
 def rows(prefix):return [{'line':i,'raw':line,**dict(re.findall(r'(\w+)=([^ ]+)',line))} for i,line in enumerate(lines,1) if line.startswith(prefix)]
 report['a2_block_windows']=blocks.block_windows(lines)
 report['a2_history_references']=checks.history_references(lines)
 report['a2_undefined_windows']=undefined.undefined_windows(lines)
 report['a2_sctlr']=rows('LQ102 SCTLR:');report['a2_memory']=rows('LQ102 MEMORY:');report['a2_cpu_windows']=rows('LQ102 CPU_WINDOW:');report['a2_cpu_comms']=rows('LQ102 CPU_COMM:');report['a2_cpu_coverage']=rows('LQ102 CPU_COVERAGE:');report['a2_enospc_totals']=rows('LQ102 ENOSPC_TOTAL:');report['a2_thread_tags']=rows('LQ102 THREAD_TAG:');report['a2_undefined_totals']=rows('LQ102 UNDEFINED_TOTAL:');report['a2_undefined_words']=rows('LQ102 UNDEFINED:')
 tagged=[line for line in raw.splitlines(keepends=True) if line.startswith((b'LQ101 ',b'LQ102 ',b'LIUQIN TASK_CPU'))]
 report['new_observer_log_bytes']=sum(len(line) for line in tagged);report['overlong_observer_lines']=[len(line) for line in tagged if len(line)>=255];report['observer_budget_ok']=report['new_observer_log_bytes']<=512*1024
 born_match=re.search(rb'^LQ101 INIT: t_ms=(\d+)',raw,re.M)
 born=int(born_match[1]) if born_match else None
 early_spaces=[row for row in report['spaces'] if born is not None and 'free' in row and 0<=row['t_ms']-born<=60000]
 init_delivery=None
 if born_match:
  end=raw.find(b'\n',born_match.start())+1
  for text in (folder/'guard-trace.jsonl').read_text().splitlines():
   event=json.loads(text)
   if event['event']=='monitor' and event['offset']<end<=event['offset']+event['length']:
    init_delivery=event['elapsed'];break
 record=json.loads((folder/'boot-record.json').read_text())
 observed_lifetime_lower_ms=max(0,(record['elapsed_seconds']-init_delivery)*1000) if init_delivery is not None else None
 last_memory_relative=max((int(row['relative_ms']) for row in report['a2_memory']),default=-1)
 report['a2_sampling_coverage']={'early_Data_samples':len(early_spaces),'early_minimum':50,'last_memory_relative_ms':last_memory_relative,'init_host_delivery_s':init_delivery,'observer_lifetime_lower_ms':observed_lifetime_lower_ms,'tail_grace_ms':15000,'limits':'Delivery gives a lower bound, not an exact native/host clock alignment; initial replay may delay delivery.'}
 report['a2_contract']={'snapshot_complete':len(report['snapshot_completeness'])==3 and all(s['complete'] for s in report['snapshot_completeness']),
 'all_8_cpu_readbacks':{int(row['cpu']) for row in report['a2_sctlr']}==set(range(8)),
 'block_windows_accounted':bool(report['a2_block_windows']) and all(w['complete'] for w in report['a2_block_windows']),
 'no_block_context_overflow':all(w['unknown_context_writes']==0 for w in report['a2_block_windows']),
 'legacy_overflow_breakdown':all(w['legacy_breakdown_complete'] for w in report['a2_block_windows']),
 'sample_layers_present':len(report['a2_block_windows'])==len(report['a2_memory']),
 'cpu_sampling_present':bool(report['a2_cpu_windows']),'memory_sampling_present':bool(report['a2_memory']),
 'undefined_counter_present':bool(report['a2_undefined_totals']),'undefined_counts_accounted':bool(report['a2_undefined_windows']) and all(w['complete'] and not w['unknown_events'] for w in report['a2_undefined_windows']),'no_reported_output_loss':all(not (r.get('suppressed',0) or r.get('line_trunc',0) or r.get('summary_failed',0)) for r in report['output']),
 'history_references_valid':len(report['a2_history_references'])==6 and all(r['complete'] for r in report['a2_history_references']),
 'fine_Data_series_usable':len(early_spaces)>=50,'sampling_reaches_tail':observed_lifetime_lower_ms is not None and last_memory_relative>=observed_lifetime_lower_ms-15000,
 'fault_rule_frozen':True,'walker_host_validation':'required separately; raw candidates are not trusted backtraces'}
 report['fault_rule_sha256']=frozen['sha256']
 if not report['observer_budget_ok'] or report['overlong_observer_lines'] or not all(report['a2_contract'][k] for k in ['snapshot_complete','all_8_cpu_readbacks','block_windows_accounted','no_block_context_overflow','legacy_overflow_breakdown','sample_layers_present','cpu_sampling_present','memory_sampling_present','undefined_counter_present','undefined_counts_accounted','no_reported_output_loss','history_references_valid','fine_Data_series_usable','sampling_reaches_tail']):report['status']='A2-observer-contract-incomplete'
 return report
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder',type=Path);a=p.parse_args();j=analyze(a.folder);(a.folder/'analysis-a2.json').write_text(json.dumps(j,indent=2)+'\n');print(json.dumps({'status':j['status'],'contract':j['a2_contract']},indent=2))
