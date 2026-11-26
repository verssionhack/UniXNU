#!/usr/bin/env python3
"""Reproduce A1 writer/path evidence and ordinal-window r100b CPU comparison."""
from pathlib import Path
from collections import Counter,defaultdict
import argparse,json,re
R=Path(__file__).resolve().parents[3]
def main():
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder',type=Path);a=p.parse_args();f=a.folder
 j=json.loads((f/'analysis-r101.json').read_text());old=json.loads((R/'out/liuqin-r100-work/evidence/review/review-audit.json').read_text())['logs']['r100b']
 raw=(f/'usb.log').read_text();lines=raw.splitlines();born=int(re.search(r'^LQ101 INIT: t_ms=(\d+)',raw,re.M)[1])
 latest={}
 for row in j['enospc_counts']:latest[(row['pid'],row['comm'])]=row
 writers=sorted([{'pid':pid,'comm':comm,'count':v['total'],'sample_t_ms':v['t_ms'],'observer_relative_ms':v['t_ms']-born} for (pid,comm),v in latest.items()],key=lambda r:r['count'],reverse=True)
 events={};paths=defaultdict(list)
 for row in j['raw_event_lines']:
  line=row['text'];fields=dict(re.findall(r'(\w+)=([^ ]+)',line))
  if line.startswith('LQ101 EVENT:'):events[fields['seq']]=fields
  elif line.startswith('LQ101 TEXT:'):
   e=events.get(fields.get('seq'),{})
   if e.get('kind')=='4':
    path=line.split(' value=',1)[1];value={'pid':int(e['pid']),'syscall':int(e['code']),'path':path}
    if value not in paths[fields.get('comm','?')]:paths[fields.get('comm','?')].append(value)
 spaces=[{**r,'observer_relative_ms':r['t_ms']-born,'free_bytes':r['free']*r['bsize'],'capacity_bytes':r['blocks']*r['bsize']} for r in j['spaces'] if 'free' in r]
 comparisons=[]
 for index,(wa,wb) in enumerate(zip(j['cpu_windows'],old['windows'])):
  rows=[]
  for name in wa['rows'].keys()|wb['rows'].keys():
   va=wa['rows'].get(name);vb=wb['rows'].get(name)
   rows.append({'comm':name,'a1_ms':va['win_ms'] if va else None,'r100b_ms':vb['win_ms'] if vb else None,'delta_ms':va['win_ms']-vb['win_ms'] if va and vb else None,'a1_rank':va['rank'] if va else None})
  rows.sort(key=lambda r:(r['a1_rank'] is None,r['a1_rank'] if r['a1_rank'] is not None else 0,r['comm']))
  comparisons.append({'window':index,'a1_dt_ms':wa['header']['dt_ms'],'r100b_dt_ms':wb['header']['dt_ms'],'a1_total_ms':wa['header']['win_ms'],'r100b_total_ms':wb['header']['win_ms'],'rows':rows})
 def fieldlines(prefix):return [{'line':i,'text':line} for i,line in enumerate(lines,1) if line.startswith(prefix)]
 summary={'observer_init_t_ms':born,'writer_totals_are_latest_per_pid_lower_bounds_not_a_common_end_time':True,'writers':writers,'writer_path_examples':dict(paths),'spaces':spaces,'cpu_r100b_comparison':comparisons,'cpu_comparison_limits':'Ordinal windows at the same hist-init cadence; first row cumulative, next ~50s, then ~30s. Baseline only top10 plus pinned; omitted rows unknown, never zero. Single runs and observer changes prevent causal attribution. No B contrast booted.','fault_detail_classifications_r100b':dict(Counter(r['classification'] for r in j['faults_versus_r100b'])),'fault_summary':j['el0_fault_summary'][-1:],'fault_summary_semantics':'Observer invocation counter, incremented before duplicate-thread suppression; not a unique-fault count. Detail capped at three per process name.','jetsam_detail':j['jetsam_details'][-1:],'block_writer_lines':fieldlines('LIUQIN SCRATCH_BLK_WRITERS:')[-1:],'scratch_stats':fieldlines('LIUQIN SCRATCH STATS:')[-1:],'sampled_global_enospc':{**j['loss'][-1],'observer_relative_ms':j['coverage'][-1]['t_ms']-born},'no_display_network_metal_choice_permitted':True}
 (f/'evidence-summary.json').write_text(json.dumps(summary,indent=2)+'\n')
 md=['# A1 versus r100b task CPU windows','',summary['cpu_comparison_limits'],'','All CPU values are milliseconds; delta = A1 minus r100b. Full union is in evidence-summary.json. Tables retain A1 top15 plus pinned processes.','']
 for window in comparisons:
  md += [f"## Window {window['window']}: dt {window['a1_dt_ms']} / {window['r100b_dt_ms']} ms",'', '| Process | A1 | r100b | Delta |','| --- | ---: | ---: | ---: |']
  for row in window['rows']:
   if row['a1_rank'] is None:continue
   md.append('| '+' | '.join(str(row[k]) if row[k] is not None else 'unknown' for k in ['comm','a1_ms','r100b_ms','delta_ms'])+' |')
  md.append('')
 (f/'cpu-r100b-comparison.md').write_text('\n'.join(md)+'\n')
 print(json.dumps({'output':str(f/'evidence-summary.json'),'writer_entries':len(writers),'space_samples':len(spaces),'compared_cpu_windows':len(comparisons),'fault_classifications':summary['fault_detail_classifications_r100b']},indent=2))
if __name__=='__main__':main()
