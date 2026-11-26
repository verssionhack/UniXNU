#!/usr/bin/env python3
"""Extract review evidence from the immutable A1 capture without device access."""
from pathlib import Path
import csv,hashlib,json,re
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
R=Path(__file__).resolve().parents[3];F=R/'out/liuqin-r101-work/evidence/a/boot-A1-20261120-175501';E=R/'out/liuqin-r101-work/evidence/review-A1';E.mkdir(exist_ok=True)
raw=(F/'usb.log').read_bytes();lines=raw.decode().splitlines();summary=json.loads((F/'evidence-summary.json').read_text());analysis=json.loads((F/'analysis-r101.json').read_text());born=summary['observer_init_t_ms']
def fields(line):return dict(re.findall(r'(\w+)=([^ ]*)',line))
opens=[];matching=[];events={};current=None;counts20=[];ws_events=[]
for no,line in enumerate(lines,1):
 f=fields(line)
 if line.startswith('LQ101 SNAPSHOT_BEGIN:'):current=int(f['target_s'])
 if line.startswith('LQ101 SNAPSHOT_END:'):current=None
 if line.startswith('LQ101 EVENT:'):events[f['seq']]={**f,'line':no}
 if line.startswith('LQ101 TEXT:'):
  e=events.get(f.get('seq'),{})
  if e.get('kind')=='1' and e.get('scope')=='last50-open':opens.append({'snapshot_s':current,'seq':int(e['seq']),'t_ms':int(e['t_ms']),'tid':int(e['tid']),'syscall':int(e['code']),'errno':int(e['err']),'exit_seen':bool(int(e['flags'])&2),'path_incomplete':bool(int(e['flags'])&1),'path':line.split(' value=',1)[1]})
  if e.get('kind')=='5':matching.append({'seq':int(e['seq']),'pid':int(e['pid']),'tid':int(e['tid']),'t_ms':int(e['t_ms']),'predicate':line.split(' value=',1)[1],'truncated':bool(int(e['flags']))})
  if e.get('kind')=='4' and e.get('pid')=='111':ws_events.append({'event':e,'text':line})
 if line.startswith('LQ101 ENOSPC_COUNT:') and 20000<=int(f['t_ms'])-born<21000:counts20.append({k:int(v) if k in ['pid','total','delta','t_ms'] else v for k,v in f.items()})
opens.sort(key=lambda x:(x['snapshot_s'],x['seq']))
with (E/'windowserver-open-history.csv').open('w') as stream:
 writer=csv.DictWriter(stream,fieldnames=list(opens[0]));writer.writeheader();writer.writerows(opens)
spaces=summary['spaces']
with (E/'data-space-45-samples.csv').open('w') as stream:
 keys=['observer_relative_ms','t_ms','bsize','blocks','free','avail','free_bytes','capacity_bytes'];writer=csv.DictWriter(stream,fieldnames=keys,extrasaction='ignore');writer.writeheader();writer.writerows(spaces)
vm=[];regs=[]
for no,line in enumerate(lines,1):
 if line.startswith('LIUQIN VM:'):vm.append({'line':no,**{k:int(v) for k,v in fields(line).items()},'raw':line})
 if line.startswith('LIUQIN CACHE:'):
  f=fields(line);value=int(f['sctlr'],16);entry={'sctlr':f['sctlr'],'midr':f['midr'],'tcr':f['tcr'],'T0SZ':int(f['tcr'],16)&63,'user_va_bits':64-(int(f['tcr'],16)&63),'nTWE':(value>>18)&1,'nTWI':(value>>16)&1}
  if entry not in regs:regs.append(entry)
word=0xd503205f;instruction=next(Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN).disasm(word.to_bytes(4,'little'),0)).mnemonic
proof=next(({'summary_t_ms':c['t_ms'],'relative_ms':c['t_ms']-born,'writer_overflow':loss['writer_overflow']} for c,loss in zip(analysis['coverage'],analysis['loss']) if c['t_ms']>=born+20328),None)
assert proof and proof['writer_overflow']==0
prior_wfe={}
for name,path in [('r97a',R/'out/liuqin-r97-work/evidence/boot-r97a-20261118-195157/usb.log'),('r99p',R/'out/liuqin-r98-work/evidence/boot-r99p-20261119-122428/usb.log'),('r100b',R/'out/liuqin-r100-work/evidence/r100b/boot-r100b-20261120-155900/usb-combined.log')]:
 text=path.read_text(errors='replace');prior_wfe[name]={'log_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'WFE_details':[l for l in text.splitlines() if l.startswith('LIUQIN EL0_FAULT:') and 'sub=0xd503205f' in l],'sctlr_values':sorted(set(re.findall(r'^LIUQIN CACHE: sctlr=([^ ]+)',text,re.M)))}
report={'enospc20_coverage_proof':proof,'prior_wfe':prior_wfe,'log_sha256':hashlib.sha256(raw).hexdigest(),'iokit_matching_requests':matching,'open_history_records':len(opens),'unique_opens':len({x['seq'] for x in opens}),'opens_per_snapshot':{str(t):sum(x['snapshot_s']==t for x in opens) for t in [60,120,300]},'opens':opens,
 'windowserver_thread_count':2,'thread_count_raw':[l for l in lines if l.startswith('LQ101 WAIT_COVERAGE:')],'raw_register_threads':[x['tid'] for x in analysis['user_state'][:2]],'thread676_main_thread':'not recorded; older TID/first queue entry suggests initial thread, not proven by A1',
 'enospc_at_20s':counts20,'enospc_at_20s_sample_observer_ms':20328,'windowserver_at_20s':{'count':0,'reason':'no writer-table overflow before this sample; entry would have been emitted if count>0'},'locationd_at_20s':{'count':0,'reason':'no entry before this sample, while table has capacity'},'windowserver_path_events':ws_events,'windowserver_late_errno28':'no attributed entry; 22 unlabelled overflow events cannot be excluded retrospectively',
 'memory_last':{**vm[-1],'page_bytes':4096,'free_MiB':vm[-1]['free']/256},'memory_min_sampled_free':{**min(vm,key=lambda r:r['free']),'page_bytes':4096,'free_MiB':min(x['free'] for x in vm)/256},'memory_physical_bytes':1<<32,
 'sctlr_samples':regs,'wfe_instruction':{'word':hex(word),'capstone_mnemonic':instruction},'locationd_mapping_at_fault':'not captured in A1; no surviving per-fault VM map or vnode association; full-disk SIGBUS hypothesis not established',
 'cpu_windowserver_ms':278,'r100b_reported_306s_windowserver_ms':202,'difference_ms':76,'no_performance_cause_claim':True}
(E/'offline-extractions.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({k:report[k] for k in ['iokit_matching_requests','opens_per_snapshot','enospc_at_20s','memory_last','memory_min_sampled_free','sctlr_samples']},indent=2))
