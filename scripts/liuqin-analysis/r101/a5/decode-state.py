#!/usr/bin/env python3
"""Conservative A5 raw state decoding; unknown bytes/classes never become nil."""
from pathlib import Path
import importlib.util,json,re
H=Path(__file__).resolve().parent
s=importlib.util.spec_from_file_location('a4_target_export',H.parent/'a4/target-frames.py');target=importlib.util.module_from_spec(s);s.loader.exec_module(target)
MAIN_UUID='91f59f6a64c3321c88b00cc7a485ab1c';CACHE_UUID='8b1e17c672d6301791a4916022e3612e'
def fields(line):return dict(re.findall(r'(\w+)=([^ ]+)',line))
def snapshot(raw,when):
 record=target.export(raw,when,'clocksyncd');lines=raw.decode('utf8',errors='strict').splitlines();snap=next(s for s in target.coverage.snapshot_coverage(lines) if s['target_s']==when and s['complete']);chunk=lines[snap['begin_line']:snap['end_line']-1]
 begins=[fields(l) for l in chunk if l.startswith('LQ102 STATE_BEGIN:')];ends=[fields(l) for l in chunk if l.startswith('LQ102 STATE_END:')];items=[fields(l) for l in chunk if l.startswith('LQ102 STATE_WORD:')]
 return decode(record,begins,ends,items)
def decode(record,begins,ends,items):
 result={'target_s':record['target_s'],'pid':record['pid'],'outcome':'unknown','reasons':[],'raw_begin':begins,'raw_end':ends,'raw_words':items,'native_reader_validated':False,'snapshot_racy':True}
 def unknown(reason):result['reasons'].append(reason);return result
 if len(begins)!=1 or len(ends)!=1:return unknown('missing/ambiguous state markers')
 begin,end=begins[0],ends[0];image=record['main_image'];base=int(image['base'],16);slide=record['slide']
 if image['status']!='ok' or image['uuid']!=MAIN_UUID or image['subtype']!='80000002' or record['cache_uuid']!=CACHE_UUID:return unknown('target identity mismatch')
 if begin.get('version')!='5' or int(begin['main'],16)!=base or int(begin['shared_slide'],16)!=slide or begin.get('invalid_rc')!='14':return unknown('state identity/probe mismatch')
 if end.get('status')!='recorded' or len(items)>64 or int(end.get('requests','0'))!=len(items):return unknown('state read contract incomplete')
 if len({i['key'] for i in items})!=len(items):return unknown('duplicate keys')
 words={i['key']:i for i in items};result['failed_reads']=[i for i in items if i['rc']!='0'];result['probe_included_in_native_attempts_and_unavailable']=True
 def get(key,address=None):
  v=words.get(key)
  if v is None or v['rc']!='0':raise ValueError(key+' unavailable')
  if address is not None and int(v['addr'],16)!=address:raise ValueError(key+' address mismatch')
  return int(v['a'],16),int(v['b'],16)
 def object_isa(value):return value & 0x00007ffffffffff8 if value&1 else value
 def pointer(value):return record['map_min']<=value<record['map_max'] and not value&7
 def stable(key,endkey,address):
  a=get(key,address);b=get(endkey,address)
  if a!=b:raise ValueError(key+' changed during state read')
  return a
 try:
  daemon,_=stable('DAEMON','DAEMON_END',base+0x6e0a0);result['daemon_pointer']=hex(daemon)
  if daemon==0:result['outcome']='nil_daemon';return result
  if not pointer(daemon):raise ValueError('daemon pointer outside authoritative user map')
  isam=get('ISAM',slide+0x180447ba8);isav=get('ISAV',slide+0x180447bb8)
  if isam!=(0x00007ffffffffff8,1) or isav[0]!=1:raise ValueError('unqualified live ISA layout')
  d0=get('D0',daemon);d1=get('D1',daemon+8)
  if d0[1]!=d1[0] or d1!=get('D1_END',daemon+8):raise ValueError('daemon fields changed')
  if object_isa(d0[0])!=base+0x6d6e8:raise ValueError('daemon ISA mismatch')
  server=d1[1];result['diagnostics_pointer']=hex(d1[0]);result['server_pointer']=hex(server)
  if server:
   if not pointer(server):raise ValueError('server pointer outside authoritative user map')
   sv0=get('SV0',server);sv1=get('SV1',server+16)
   if object_isa(sv0[0])!=base+0x6d648:raise ValueError('server ISA mismatch')
   result['listener_pointer']=hex(sv1[0]);result['server_queue_pointer']=hex(sv0[1]);result['server_connections_pointer']=hex(sv1[1])
   if not sv1[0] or not pointer(sv1[0]):raise ValueError('stored server without qualified nonnil listener')
   result['outcome']='created_resumed_server_init';result['resume_boundary']='Host init invokes resume before returning the server later stored on daemon; current listener activity/replies unproven.';return result
  # Offset cells qualify exact pinned count fields. No guessed class-cluster count.
  iv0=get('IVAR0',slide+0x2728f5438);iv1=get('IVAR1',slide+0x2728f5448)
  if iv0!=(0x1000000008,0x2000000018) or iv1[0]!=0x3000000028:raise ValueError('notifier ivar layout mismatch')
  if (get('ARRIV',slide+0x1eb1deb78)[0]>>32)!=16 or (get('SETIV',slide+0x1eb1dee90)[0]>>32)!=16:raise ValueError('collection storage ivar mismatch')
  states={}
  for prefix,key,endkey,addr in [('CN','CLKY','CLKY_END',0x275739818),('GN','GPTY','GPTY_END',0x275739790)]:
   state={};states[prefix]=state
   try:
    notifier,singleton=stable(key,endkey,slide+addr);state.update(notifier=hex(notifier),singleton=hex(singleton))
    if not notifier:state['status']='nil_notifier';continue
    if not pointer(notifier):raise ValueError('notifier pointer outside user map')
    n0=get(prefix+'0',notifier);n1=get(prefix+'1',notifier+16);n2=get(prefix+'2',notifier+32);n3=get(prefix+'3',notifier+40)
    if object_isa(n0[0])!=slide+0x275737be8:raise ValueError('notifier ISA mismatch')
    if n2[1]!=n3[0]:raise ValueError('notifier callback-array pointer changed')
    matched,pending=n1[1],n2[1];state.update(match_notification=hex(n0[1]),terminate_notification=hex(n1[0]),matched_set=hex(matched),pending_array=hex(pending))
    ms0=get(prefix+'S0',matched);ms1=get(prefix+'S1',matched+16);pa0=get(prefix+'A0',pending);pa1=get(prefix+'A1',pending+16);pa2=get(prefix+'A2',pending+32)
    if object_isa(ms0[0])!=slide+0x1ed9533f8:raise ValueError('matched set has unsupported implementation ISA '+hex(object_isa(ms0[0])))
    if object_isa(pa0[0])!=slide+0x1ed954668:raise ValueError('pending array has unsupported implementation ISA '+hex(object_isa(pa0[0])))
    state.update(status='decoded',matched_count=(ms1[1]>>32)&0x3ffffff,pending_count=(pa2[0]>>32)&0xffffffff)
   except ValueError as error:state.update(status='unknown',reason=str(error))
  result['notifiers']=states
  clock,gptp=states['CN'],states['GN'];cp=clock.get('status')=='decoded' and clock['matched_count']==0 and clock['pending_count']>0;gp=gptp.get('status')=='decoded' and gptp['matched_count']==0 and gptp['pending_count']>0
  if cp and gp:raise ValueError('both readiness notifiers pending; no unique gate')
  if cp:result['outcome']='clock_pending'
  elif gp and clock.get('status')=='decoded' and clock['matched_count']>0 and int(clock['singleton'],16)!=0:result['outcome']='gptp_pending'
  elif gp:result['reasons'].append('gPTP notifier pending, but completed clock path not independently supported')
  else:result['reasons'].append('No retained unfulfilled availability callback proves a unique readiness gate')
  result['notification_limit']='Counts concern all retained callbacks in this process notifier, not identified block owners; a queued callback is not visible. Single racy reads are not atomic object snapshots.'
  return result
 except (ValueError,KeyError) as error:return unknown(str(error))
if __name__=='__main__':
 import argparse
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder',type=Path);a=p.parse_args();raw=(a.folder/'usb.log').read_bytes();records=[snapshot(raw,t) for t in [60,120,300]];report={'outcomes':records,'all_state_reads_identified':all(r['outcome']!='unknown' for r in records),'classification_is_inference':True,'native_reader_validated':False};(a.folder/'state-analysis-a5.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps([{k:r.get(k) for k in ['target_s','outcome','reasons','notifiers']} for r in records],indent=2))
