#!/usr/bin/env python3
"""A6 snapshot-scoped publication evidence; missing/wrong-type values stay explicit."""
from pathlib import Path
import importlib.util,re
H=Path(__file__).resolve().parent
s=importlib.util.spec_from_file_location('coverage_a6',H.parent/'a2/coverage.py');coverage=importlib.util.module_from_spec(s);s.loader.exec_module(coverage)
CLASSES=['IOTimeSyncClockManager','IOTimeSyncDaemonService','IOTimeSyncTranslationMach'];KEYS=['TimeSyncTimeClockID','TimeSyncTimeCoreAudioClockDomain']
def fields(line):return dict(re.findall(r'(\w+)=([^ ]+)',line))
def snapshot(raw,target,clock_state=None):
 lines=raw.decode('utf8',errors='strict').splitlines();snaps=[s for s in coverage.snapshot_coverage(lines) if s['target_s']==target]
 if len(snaps)!=1 or not snaps[0]['complete']:raise ValueError('require unique complete checksum-verified snapshot')
 s=snaps[0];chunk=lines[s['begin_line']:s['end_line']-1];pubs=[fields(l) for l in chunk if l.startswith('LQ102 PUBLICATION:')];props=[fields(l) for l in chunk if l.startswith('LQ102 CLOCK_PROPERTY:')]
 return classify(target,pubs,props,clock_state)
def classify(target,pubs,props,clock_state=None):
 r={'target_s':target,'outcome':'unknown','protocol_complete':False,'positive_control':False,'publications':pubs,'properties':props,'reasons':[],'state_racy':True}
 def fail(reason):r['reasons'].append(reason);return r
 indexed={}
 for c in CLASSES:
  rows=[p for p in pubs if p.get('cls')==c]
  if len(rows)!=1:return fail('missing/ambiguous public state for '+c)
  row=rows[0]
  try:
   state=int(row['state'],16);rid=int(row['rid'],16)
   if not rid or row['registered']!=str(int(bool(state&2))) or row['matched']!=str(int(bool(state&4))) or row['inactive']!=str(int(bool(state&1))) or row['source']!='IOService':return fail('public bit/ID/source disagreement for '+c)
  except (KeyError,ValueError):return fail('malformed public state for '+c)
  indexed[c]=row
 if len({p['rid'] for p in indexed.values()})!=3:return fail('registry IDs alias across controls')
 clock=indexed[CLASSES[0]];ps={}
 for key in KEYS:
  matches=[p for p in props if p.get('rid')==clock['rid'] and p.get('key')==key]
  if len(matches)!=1:return fail('missing/ambiguous property '+key)
  p=matches[0]
  if p.get('present') not in ['0','1'] or p.get('decoded') not in ['0','1']:return fail('invalid property presence/decode flags')
  if p['present']=='0' and (p.get('type')!='none' or p['decoded']!='0'):return fail('absent property decoded as value')
  if p['decoded']=='1':
   try:
    if p['present']!='1' or int(p['bits']) not in [32,64] or not 0<=int(p['value'],16)<1<<int(p['bits']):return fail('invalid number geometry')
   except (KeyError,ValueError):return fail('invalid numeric property')
  ps[key]=p
 r['protocol_complete']=True;daemon=indexed[CLASSES[1]];translation=indexed[CLASSES[2]]
 r['positive_control']=daemon['registered']=='1' and daemon['matched']=='1' and daemon['inactive']=='0';r['translation_control']={'registered':translation['registered'],'matched':translation['matched'],'inactive':translation['inactive']}
 if not r['positive_control']:return fail('daemon public-state positive control did not pass')
 if clock['inactive']!='0':return fail('clock manager inactive')
 if clock['registered']=='0' and all(p['present']=='0' for p in ps.values()):r['outcome']='attached_unregistered_no_clock_ID'
 elif clock['registered']=='1' and clock['matched']=='1' and clock_state=='clock_pending':r['outcome']='registered_matched_but_userspace_clock_pending'
 else:r['reasons'].append('partial/contradictory publication state; inspect typed property values and notifier state')
 return r
