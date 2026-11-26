#!/usr/bin/env python3
"""Preserved A2/A1 boundary audit, raw exports and ESR decoding; no device calls."""
from pathlib import Path
import bisect,collections,difflib,hashlib,json,re
R=Path(__file__).resolve().parents[4];W=R/'out/liuqin-r101-a2-offline-audit';W.mkdir(exist_ok=True)
A=R/'out/liuqin-r101-work/evidence/a';B=R/'out/liuqin-r101-a2-work/evidence/a';logs={'A1':A/'boot-A1-20261120-175501/usb.log','A2':B/'boot-A2-20261120-231726/usb.log'}
pattern=re.compile(rb'TRAP ([0-9a-f]+) esr ([0-9a-f]+) far ([0-9a-f]+) pc ([0-9a-f]+) rec ([01]) lr ([0-9a-f]+)')
report={}
for tag,log in logs.items():
 raw=log.read_bytes();nm=(A if tag=='A1' else B)/'nm.txt';symbols=[]
 for l in nm.read_text(errors='replace').splitlines():
  m=re.match(r'([0-9a-f]+)\s+\w\s+(.+)',l)
  if m:symbols.append((int(m[1],16),m[2]))
 symbols.sort();addrs=[s[0] for s in symbols]
 def symbol(addr):
  if addr>=1<<64:return 'unresolved-invalid-width'
  i=bisect.bisect_right(addrs,addr)-1
  if i<0:return None
  base,name=symbols[i];return name+'+'+hex(addr-base) if addr-base<0x10000 else 'unresolved-no-nearby-symbol'
 rows=[]
 for m in pattern.finditer(raw):
  seq,esr,far,pc,rec,lr=[int(x,16) for x in m.groups()];ec=esr>>26&63;dfsc=esr&63
  rows.append({'byte_offset':m.start(),'line':raw.count(b'\n',0,m.start())+1,'raw':m[0].decode(),'sequence_hex':hex(seq),'ESR':hex(esr),'FAR':hex(far),'PC':hex(pc),'LR':hex(lr),'copyio_recovery_entry':bool(rec),'CPU':'not encoded','LR_width_valid':lr<1<<64,'LR_ambiguity':'trailing b0 beacon may be concatenated; no truncation applied' if lr>=1<<64 else None,'EC':hex(ec),'EL':'current EL data abort (EL1 hook)' if ec==0x25 else 'other','DFSC':hex(dfsc),'fault_class':{4:'translation',8:'access-flag',12:'permission'}.get(dfsc&~3,'other'),'level':dfsc&3,'access':'write' if esr&64 else 'read','pc_symbol':symbol(pc),'lr_symbol':symbol(lr)})
 unique=list({r['raw']:r for r in rows}.values());counts=collections.Counter((r['ESR'],r['pc_symbol'],r['lr_symbol']) for r in rows)
 if tag=='A2':
  tail=b''.join(raw.splitlines(keepends=True)[-50:]);(W/'A2-last-50-lines.verbatim.txt').write_bytes(tail);start=len(raw)-len(tail);tailrows=[r for r in rows if r['byte_offset']>=start]
  (W/'A2-terminal-traps.json').write_text(json.dumps(tailrows,indent=2)+'\n')
 report[tag]={'log_path':str(log.relative_to(R)),'sha256':hashlib.sha256(raw).hexdigest(),'TRAP_occurrences':len(rows),'distinct_raw_records':len(unique),'emission_caveat':'force_note plus ring replay can duplicate records; counters/order across CPUs are not timestamps','rows':rows,'classes':[{'ESR':k[0],'PC':k[1],'LR':k[2],'occurrences':n} for k,n in counts.most_common()]}
# A1-relative runtime USB source diff: A1 keeps the frozen baseline USB file.
old=R/'out/liuqin-r101-work/frozen-r100b-source/bsd/dev/liuqin_usb_debug.c';new=B/'sources/bsd/dev/liuqin_usb_debug.c'
(W/'A1-to-A2-USB.patch').write_text(''.join(difflib.unified_diff(old.read_text().splitlines(True),new.read_text().splitlines(True),fromfile='A1/bsd/dev/liuqin_usb_debug.c',tofile='A2/bsd/dev/liuqin_usb_debug.c')))
(W/'trap-comparison.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps({tag:{k:report[tag][k] for k in ['TRAP_occurrences','distinct_raw_records']} for tag in report},indent=2))
for tag in report:
 print(tag,'memmove/cs_validate_hash',sum('memmove' in r['pc_symbol'] and 'cs_validate_hash' in r['lr_symbol'] for r in report[tag]['rows']))
