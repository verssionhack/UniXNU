#!/usr/bin/env python3
"""Freeze final A2r1 measured summary/series; retain sampled-versus-tail limits."""
from pathlib import Path
import argparse,collections,csv,json,re
p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder',type=Path);args=p.parse_args();f=args.folder.resolve();a=json.loads((f/'analysis-a2r1.json').read_text());b=json.loads((f/'boot-record.json').read_text());raw=(f/'usb.log').read_bytes();ls=raw.decode(errors='replace').splitlines();born=int(re.search(rb'^LQ101 INIT: t_ms=(\d+)',raw,re.M)[1]);trace=[json.loads(l) for l in (f/'guard-trace.jsonl').read_text().splitlines()];data=[e for e in trace if e['event']=='monitor' and e['length']]
def fields(l):return dict(re.findall(r'(\w+)=([^ ]+)',l))
def csvout(name,rows):
 rows=list(rows)
 if rows:
  with (f/name).open('w') as fp:
   w=csv.DictWriter(fp,fieldnames=list(rows[0]),extrasaction='ignore');w.writeheader();w.writerows(rows)
spaces=[{'relative_ms':r['t_ms']-born,'t_ms':r['t_ms'],'free_MiB':r['free']*r['bsize']/1048576,'blocks':r['blocks'],'free_blocks':r['free'],'block_bytes':r['bsize']} for r in a['spaces'] if 'free' in r];csvout('Data-space-series.csv',spaces)
cross=next(i for i,r in enumerate(spaces) if r['free_MiB']<16);bracket=spaces[max(0,cross-1):cross+1];early=[r for r in spaces if r['relative_ms']<=60000]
csvout('memory-series.csv',({**{k:r[k] for k in ['relative_ms','t_ms','free','active','inactive','speculative','wired']},'free_MiB':int(r['free'])/256} for r in a['a2_memory']))
blocks=[];earlywriters=collections.defaultdict(lambda:[0,0]);byname=collections.defaultdict(lambda:[0,0])
for win in a['a2_block_windows']:
 for r in win['rows']:
  row={'relative_ms':win['t_ms']-born,'dt_ms':int(win['header']['dt_ms']),'initial':int(win['header']['initial']),**{k:r[k] for k in ['pid','comm','bytes','writes','legacy_bytes','legacy_writes']}};blocks.append(row)
  if win['t_ms']-born<=bracket[-1]['relative_ms']:
   x=earlywriters[(int(r['pid']),r['comm'])];x[0]+=int(r['bytes']);x[1]+=int(r['writes'])
  x=byname[r['comm']];x[0]+=int(r['bytes']);x[1]+=int(r['writes'])
csvout('block-writer-windows.csv',blocks)
cpu_times={};last_time=None
for no,line in enumerate(ls,1):
 if line.startswith('LQ101 CPU_TIME:'):
  z=fields(line);last_time=int(z['ticks'])*1000//int(z['frq'])
 if line.startswith('LIUQIN TASK_CPU_HDR:'):cpu_times[no]=last_time
coarse=[]
for w in a['cpu_windows']:
 for comm,r in w['rows'].items():coarse.append({'window_line':w['line'],'t_ms':cpu_times[w['line']],'relative_ms':cpu_times[w['line']]-born,'dt_ms':w['header']['dt_ms'],**r})
csvout('TASK_CPU-all-windows.csv',coarse)
csvout('fine-CPU-rows.csv',({k:r[k] for k in ['t_ms','comm','win_ms','cum_ms','exits','alive','initial']} for r in a['a2_cpu_comms']))
csvout('ENOSPC-counts.csv',({k:r[k] for k in ['t_ms','pid','comm','total','delta']} for r in a['enospc_counts']))
last_coarse=a['cpu_windows'][-1];minmem=min(a['a2_memory'],key=lambda r:int(r['free']));lastmem=a['a2_memory'][-1]
wfe=[r for r in a['faults_versus_r100b'] if r['stage']=='ux_sig' and r['exc']==2 and r['sub']=='0xd503205f'];lastwordtime=int(a['a2_undefined_totals'][-1]['t_ms']);wfelate=[]
for r in wfe:
 end=sum(len(x) for x in raw.splitlines(keepends=True)[:r['line']]);host=next((e['elapsed'] for e in data if e['offset']<end<=e['offset']+e['length']),None)
 wfelate.append({'comm':r['comm'],'pid':r['pid'],'line':r['line'],'host_delivery_s':host,'after_last_histogram_line':r['line']>a['a2_undefined_totals'][-1]['line']})
ws=[r for r in coarse if r['comm']=='WindowServer'];crash=[r for r in coarse if r['comm'].startswith('ReportCrash')]
validations=[json.loads((f/f'frames-{t}-validation.json').read_text()) for t in [60,120,300]]
summary={'status':b['capture_status'],'runner_exit_code':b['assessment_exit_code'],'hardware_boots':1,'A3_boots':0,'capture':b,'first_last_data_host_s':[data[0]['elapsed'],data[-1]['elapsed']],'serial_disconnects':[e for e in trace if e['event']=='serial_disconnect'],'snapshot_completeness':a['snapshot_completeness'],'snapshot_raw_frame_checks':[{'target_s':v['target_s'],'frames':v['raw_frame_count'],'callsites_plausible':v['plausible_frames'],'callsite_validation_passed':v['callsite_validation_passed'],'native_reader_independently_validated':v['native_reader_validated']} for v in validations],'SCTLR_cpus_by_snapshot':{},'readback_rows':a['a2_sctlr'],'all_observed_nTWE_zero':all(r['nTWE']=='0' for r in a['a2_sctlr']),'all_observed_nTWI_zero':all(r['nTWI']=='0' for r in a['a2_sctlr']),'WFE_histogram_last':a['a2_undefined_totals'][-1],'WFE_histogram_rows':a['a2_undefined_words'],'WFE_detail_records':wfelate,'WFE_count_limit':'Histogram sampled through last stated timestamp (not final live counter); a late logd WFE detail follows the final dump. Hook events are not unique crashes.','Data_samples':len(spaces),'early_Data_samples':len(early),'crossing_below16_bracket':bracket,'observer_effect_timing_screen_flag':not(bracket[-1]['relative_ms']>9292 and bracket[0]['relative_ms']<21328),'Data_last':spaces[-1],'Data_min_MiB':min(s['free_MiB'] for s in spaces),'memory_min_sample':minmem,'memory_min_free_MiB':int(minmem['free'])/256,'memory_last_sample':lastmem,'memory_last_free_MiB':int(lastmem['free'])/256,'first20_block_submitters':[{'pid':p,'comm':c,'bytes':n[0],'MiB':n[0]/1048576,'writes':n[1]} for (p,c),n in sorted(earlywriters.items(),key=lambda x:x[1][0],reverse=True)],'full_block_submitters':[{'comm':c,'bytes':n[0],'MiB':n[0]/1048576,'writes':n[1]} for c,n in sorted(byname.items(),key=lambda x:x[1][0],reverse=True)],'first20_block_caveat':'Includes initial pre-observer window; copied/submitted bytes include repeats, not unique APFS allocation or original asynchronous writer. No context overflow in received windows.','ENOSPC_last_sample':a['a2_enospc_totals'][-1],'WindowServer_CPU_rows':ws,'ReportCrash_CPU_rows':crash,'last_coarse_window':last_coarse['header'],'last_jetsam':a['jetsam_last'],'last_vnodes':a['vnodes_last'],'fault_summary_last_sample':a['el0_fault_summary'][-1],'fault_detail_count':a['el0_fault_details'],'fault_signature_rule_sha256':a['fault_rule_sha256'],'new_observer_bytes':a['new_observer_log_bytes'],'max_observer_line_bytes':max(len(l) for l in raw.splitlines(keepends=True) if l.startswith((b'LQ101 ',b'LQ102 ',b'LIUQIN TASK_CPU'))),'last_output':a['output'][-1],'last_loss':a['loss'][-1],'exact_guard_replay':a['exact_guard_replay'],'A3_held':True,'new_boot_authorized':False,'interpretation':'A2 early disappearance did not reproduce here; repairs and one run do not attribute the prior failure or establish variance. Raw WindowServer frames support synchronous TimeSync XPC wait; host service default is com.apple.timesync.expositor, live server port ownership/reply cause not observed.'}
# Preserve per-snapshot CPU coverage without associating INIT rows with a later snapshot.
current='INIT';reg={current:[]}
for l in ls:
 if l.startswith('LQ101 SNAPSHOT_BEGIN:'):current=fields(l)['target_s'];reg[current]=[]
 if l.startswith('LQ102 SCTLR:'):reg[current].append(int(fields(l)['cpu']))
 if l.startswith('LQ101 SNAPSHOT_END:'):current='outside'
summary['SCTLR_cpus_by_snapshot']={k:sorted(set(v)) for k,v in reg.items()}
(f/'result-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps({k:summary[k] for k in ['early_Data_samples','crossing_below16_bracket','Data_last','memory_min_free_MiB','memory_last_free_MiB','first20_block_submitters','ENOSPC_last_sample','WFE_detail_records']},indent=2))
