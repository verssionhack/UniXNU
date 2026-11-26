#!/usr/bin/env python3
"""Classify all visible detailed faults; retain unknowns and per-run slide assumptions."""
from pathlib import Path
import hashlib,json,re,subprocess
R=Path(__file__).resolve().parents[3];E=R/'out/liuqin-r101-a2-work/evidence/review';E.mkdir(exist_ok=True)
C=Path('/media/disk_4/unixnu_workspace/ramdisk_dir/liuqin-r101-host-cache/dyld_shared_cache_arm64e');T=C.parent.parent/'tools/ipsw';S=R/'out/liuqin-r101-work/evidence/review-A1/cache-symbols.a2s'
logs={'r99p':R/'out/liuqin-r98-work/evidence/boot-r99p-20261119-122428/usb.log','r100b':R/'out/liuqin-r100-work/evidence/r100b/boot-r100b-20261120-155900/usb-combined.log','A1':R/'out/liuqin-r101-work/evidence/a/boot-A1-20261120-175501/usb.log'}
cache={};runs={}
def classify(addr,slide):
 if addr==0:return {'status':'none'}
 if addr>=1<<39:return {'status':'outside-native-39-bit-user-VA','raw':hex(addr)}
 if addr<0x180000000+slide:return {'status':'outside-host-shared-cache','raw':hex(addr)}
 u=addr-slide
 if u not in cache:
  p=subprocess.run([str(T),'dyld','a2s','--image','--mapping','--cache',str(S),str(C),hex(u)],capture_output=True,text=True)
  out=p.stdout+p.stderr;cache[u]={'unslid':hex(u),'status':'host-cache-mapped' if 'IMAGE' in out else 'unresolved','symbolication':out,'TPRO_CONST':'__TPRO_CONST' in out};(E/f'address-{u:x}.txt').write_text(out)
 return cache[u]
for name,path in logs.items():
 text=path.read_text(errors='replace');slide=int(re.search(r'LIUQIN SR_SLIDE:.*? slide=0x([0-9a-f]+)',text)[1],16);rows=[]
 for no,line in enumerate(text.splitlines(),1):
  if not line.startswith('LIUQIN EL0_FAULT:'):continue
  f=dict(re.findall(r'(\w+)=([^ ]+)',line));pc=int(f['pc'],16);sub=int(f['sub'],16);exc=int(f['exc']);code=int(f['code'],16)
  row={'line':no,**f,'PC_classification':classify(pc,slide),'slide_assumption':'run shared region; fault-task private region not excluded'}
  if exc==1:row['fault_address_classification']=classify(sub,slide)
  elif exc==2:row['subcode_kind']='instruction word, not fault address'
  elif exc==10:row['crash_code_decode']={'terminating_signal':code>>24&255,'original_exception':code>>20&15,'original_code_low20':code&0xfffff,'namespace':'not encoded'}
  rows.append(row)
 registry=[l for l in text.splitlines() if l.startswith('LIUQIN IOREG')]
 runs[name]={'log_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'shared_slide':hex(slide),'rows':rows,'detailed_records':len(rows),'TPRO_PC_records':sum(x['PC_classification'].get('TPRO_CONST',False) for x in rows),'TPRO_fault_address_records':sum(x.get('fault_address_classification',{}).get('TPRO_CONST',False) for x in rows),'registry_evidence':[l for l in registry if any(s in l for s in ['IOHIDSystem','AppleDisplayManager','DISP_SUM'])]}
result={'cache_UUID':'8b1e17c672d6301791a4916022e3612e','runs':runs,'scope':'Every visible detailed record; per-name detail cap hides additional faults. No private-region VM maps captured. PC/subcode are classified separately; EXC_CRASH sub=0 is not a fault address.'}
(E/'offline-review.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:{n:v[n] for n in ['shared_slide','detailed_records','TPRO_PC_records','TPRO_fault_address_records','registry_evidence']} for k,v in runs.items()},indent=2))
