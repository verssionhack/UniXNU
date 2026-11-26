#!/usr/bin/env python3
"""Evaluate the pre-frozen A3r1 nTWE comparison; no target operations."""
from pathlib import Path
import argparse,csv,json,re
H=Path(__file__).resolve().parent;R=H.parents[3]
p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder',type=Path);args=p.parse_args();f=args.folder.resolve();W=f.parents[2];spec=json.loads((W/'evidence/comparison-spec.json').read_text());record=json.loads((f/'boot-record.json').read_text());accepted=json.loads((f/'capture-assessment.json').read_text());a=accepted['analysis'];raw=(f/'usb.log').read_bytes();lines=raw.decode(errors='replace').splitlines();born_match=re.search(rb'^LQ101 INIT: t_ms=(\d+)',raw,re.M)
if not born_match:raise ValueError('No native observer origin; comparison cannot be evaluated')
born=int(born_match[1]);baseline=R/'out/liuqin-r101-a2r1-work/evidence/a/boot-A2r1-20261121-055146';ba=json.loads((baseline/'analysis-a2r1.json').read_text())
(f/'analysis-a3r1.json').write_text(json.dumps(a,indent=2)+'\n')
selected_candidates=[r for r in a['a2_undefined_totals'] if int(r['t_ms'])-born<=spec['histogram_comparison']['A3r1_select_latest_sample_at_or_before_ms']];selected=selected_candidates[-1] if selected_candidates else None;end=int(selected['t_ms']) if selected else -1
state={}
for r in a['a2_undefined_words']:
 if int(r['t_ms'])<=end:state[(r['comm'],int(r['word'],16))]=int(r['total'])
wfe=sum(n for (comm,word),n in state.items() if word==0xd503205f);valid_windows=[r for r in a['a2_undefined_windows'] if r['t_ms']<=end];word_coverage=bool(selected and valid_windows) and all(r['complete'] and r['unknown_events']==0 for r in valid_windows)
raw_wfe=[r for r in a['faults_versus_r100b'] if r['stage']=='ux_sig' and r['exc']==2 and r['sig']==4 and r['code']=='0x1' and r['sub']=='0xd503205f']
last_reg={int(r['cpu']):r for r in a['a2_sctlr']};base_reg={int(r['cpu']):r for r in ba['a2_sctlr']};reg_diffs=[]
for cpu,r in sorted(last_reg.items()):
 old=base_reg.get(cpu);before=int(old['sctlr'],16) if old else None;now=int(r['sctlr'],16)
 reg_diffs.append({'cpu':cpu,'MPIDR':r['mpidr'],'MIDR':r['midr'],'baseline_sctlr':hex(before) if before is not None else None,'A3r1_sctlr':hex(now),'xor':hex(now^before) if before is not None else None,'only_bit18_added':before is not None and now==(before|1<<18),'nTWE':r['nTWE'],'nTWI':r['nTWI']})
checks={'capture_complete':accepted['status']=='complete-observer-capture' and record['returned_to_fastboot'],'all_8_CPU_readbacks':set(last_reg)==set(range(8)),'all_nTWE_one':bool(last_reg) and all(r['nTWE']=='1' for r in a['a2_sctlr']),'nTWI_and_other_SCTLR_bits_unchanged':bool(reg_diffs) and all(r['only_bit18_added'] for r in reg_diffs),'selected_histogram_endpoint_at_least_420s':selected is not None and end-born>=420000,'sampled_words_accounted_without_overflow':word_coverage,'sampled_WFE_zero':word_coverage and wfe==0,'no_raw_WFE_detail_including_tail':not raw_wfe}

def csvout(name,rows):
 rows=list(rows)
 if rows:
  with (f/name).open('w') as stream:
   writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
spaces=[{'relative_ms':r['t_ms']-born,'t_ms':r['t_ms'],'free_MiB':r['free']*r['bsize']/1048576,'free_blocks':r['free'],'capacity_MiB':r['blocks']*r['bsize']/1048576} for r in a['spaces'] if 'free' in r];csvout('Data-space-series.csv',spaces)
csvout('memory-series.csv',({k:r[k] for k in ['relative_ms','t_ms','free','active','inactive','speculative','wired']} for r in a['a2_memory']))
ci=next((i for i,r in enumerate(spaces) if r['free_MiB']<16),None);crossing=spaces[max(0,ci-1):ci+1] if ci is not None else []
memmin=min(a['a2_memory'],key=lambda r:int(r['free'])) if a['a2_memory'] else None
last_hist=a['a2_undefined_totals'][-1] if a['a2_undefined_totals'] else None
report={'status':'observed-nTWE-correction' if all(checks.values()) else 'comparison-incomplete-or-correction-not-established','checks':checks,'protocol':spec,'capture':record,'register_comparison':reg_diffs,'selected_histogram':selected,'selected_relative_ms':end-born if selected else None,'sampled_WFE_count':wfe if word_coverage else None,'sampled_word_state':[{'comm':c,'word':hex(w),'count':n} for (c,w),n in sorted(state.items())],'raw_WFE_details':raw_wfe,'last_histogram':last_hist,'unsampled_tail_limit':'Counter readback ends at its stated timestamp. No received raw WFE detail is not an uncapped final live-counter zero; legacy detail caps remain.','all_fault_details':a['faults_versus_r100b'],'faults_versus_r99p':a['faults_versus_r99p'],'Data_sample_count':len(spaces),'early_Data_samples':len([s for s in spaces if s['relative_ms']<=60000]),'Data_crossing_below16':crossing,'Data_last':spaces[-1] if spaces else None,'memory_min_sample':memmin,'memory_min_free_MiB':int(memmin['free'])/256 if memmin else None,'ENOSPC_last_sample':a['a2_enospc_totals'][-1:] ,'snapshots':a['snapshot_completeness'],'new_observer_bytes':a['new_observer_log_bytes'],'last_output':a['output'][-1:],'last_loss':a['loss'][-1:],'jetsam_last':a['jetsam_last'],'vnodes_last':a['vnodes_last'],'exact_guard_replay':a['exact_guard_replay'],'quiescence_proxy':a['first_quiescent_sample'],'counter_semantics':'Primary undefined-instruction hook events; not unique crashes. EL0 TRAP=0 does not mean zero faults.','causal_limits':'One A2r1/A3r1 pair. Retain actual sample endpoints; no variance or crash/Data causality claim from counts alone.'}
(f/'comparison-a3r1.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({'status':report['status'],'checks':checks,'sampled_WFE_count':report['sampled_WFE_count'],'selected_relative_ms':report['selected_relative_ms'],'raw_WFE_details':len(raw_wfe),'Data_crossing_below16':crossing,'memory_min_free_MiB':report['memory_min_free_MiB']},indent=2))
