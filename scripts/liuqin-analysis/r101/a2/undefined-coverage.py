"""Reconstruct sampled instruction-word totals without trusting capped fault details."""
import re

def undefined_windows(lines):
 groups={};orphans=[]
 for no,line in enumerate(lines,1):
  fields=dict(re.findall(r'(\w+)=([^ ]+)',line))
  if line.startswith('LQ102 UNDEFINED_TOTAL:'):
   groups[int(fields['t_ms'])]={'header':fields,'rows':[],'line':no}
  elif line.startswith('LQ102 UNDEFINED:'):
   timestamp=int(fields['t_ms'])
   if timestamp in groups:groups[timestamp]['rows'].append(fields)
   else:orphans.append({'t_ms':timestamp,'complete':False,'unknown_events':0,'reason':'word row without sampled total'})
 previous={};result=[];last_total=0;last_overflow=0
 for timestamp,group in groups.items():
  valid=True;header=group['header'];total=int(header['events']);overflow=int(header['overflow'])
  for row in group['rows']:
   key=(row['comm'],int(row['word'],16));count=int(row['total']);old=previous.get(key,0)
   valid=valid and count>=old and count-old==int(row['delta']);previous[key]=count
  valid=valid and total>=last_total and overflow>=last_overflow and sum(previous.values())+overflow==total
  last_total=total;last_overflow=overflow
  result.append({**group,'t_ms':timestamp,'complete':valid,'unknown_events':overflow,'event_semantics':'primary ux_sig EXC_BAD_INSTRUCTION/SIGILL/EXC_ARM_UNDEFINED hook events, not unique crashes'})
 return result+orphans
