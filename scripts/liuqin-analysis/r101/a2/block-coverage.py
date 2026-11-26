"""Verify per-window block counters without summing asynchronous and syscall layers."""
import re

def block_windows(lines):
 windows={};duplicates=[];orphans=[]
 for no,line in enumerate(lines,1):
  f=dict(re.findall(r'(\w+)=([^ ]+)',line))
  if line.startswith('LQ102 BLK_WINDOW:'):
   timestamp=int(f['t_ms'])
   if timestamp in windows:duplicates.append(timestamp)
   windows[timestamp]={'header':f,'line':no,'rows':[]}
  elif line.startswith('LQ102 BLK_WRITER:'):
   timestamp=int(f['t_ms'])
   if timestamp in windows:windows[timestamp]['rows'].append(f)
   else:orphans.append({'header':{},'rows':[f],'t_ms':timestamp,'line':no,'complete':False,'legacy_breakdown_complete':False,'unknown_context_writes':0,'reason':'writer without window header'})
 result=[]
 for timestamp,w in windows.items():
  h=w['header'];rows=w['rows'];named_bytes=sum(int(r['bytes']) for r in rows);named_writes=sum(int(r['writes']) for r in rows)
  complete=len(rows)==int(h['named']) and named_bytes+int(h['overflow_bytes'])==int(h['bytes']) and named_writes+int(h['overflow_writes'])==int(h['writes']) and timestamp not in duplicates
  legacy_bytes=sum(int(r['legacy_bytes']) for r in rows);legacy_writes=sum(int(r['legacy_writes']) for r in rows)
  legacy_complete=complete and int(h['overflow_writes'])==0 and legacy_bytes==int(h['legacy_bytes']) and legacy_writes==int(h['legacy_writes'])
  result.append({**w,'t_ms':timestamp,'complete':complete,'legacy_breakdown_complete':legacy_complete,'unknown_context_writes':int(h['overflow_writes']),'layer':'block-submission context; no syscall/origin/path identity claim'})
 return result+orphans
