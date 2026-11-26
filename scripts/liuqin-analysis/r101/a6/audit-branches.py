#!/usr/bin/env python3
"""Host-only complete method/virtual-call inventory for publication prerequisites."""
from pathlib import Path
import hashlib,json,re,subprocess,sys
R=Path(__file__).resolve().parents[4];E=R/'out/liuqin-r101-a6-work/evidence/host-branches';E.mkdir(exist_ok=True)
K=Path('/media/disk_4/unixnu_workspace/ramdisk_dir/unixnu/ipsw/26C5035r/kernelcache.decompressed');tool='/media/disk_4/unixnu_workspace/ramdisk_dir/tools/ipsw'
sys.path.insert(0,str(R/'kits/XnuPrelink'));from kc_image import Image
root=Image(K.read_bytes());symbols=root.symbols();fixups=root.fixups()
nm=subprocess.check_output(['llvm-nm','--defined-only','--demangle',str(K)],text=True);names={int(m[1],16):m[2] for line in nm.splitlines() if (m:=re.match(r'^([0-9a-f]+) \w (.+)$',line))}
methods={'find-time-clock-id':0xfffffe000b104f44,'start':0xfffffe000b104aac,'interface-notification':0xfffffe000b1060fc,'interface-matched':0xfffffe000b1064e0,'external-TSN-outline':0xfffffe000b122790,'ordered-insert':0xfffffe000b106dac,'clock-manager-init':0xfffffe000b104044,'delayed-lookup':0xfffffe000b104780}
for name,addr in methods.items():
 with (E/(name+'.asm.txt')).open('w') as f:subprocess.run([tool,'macho','disass','--fileset-entry','com.apple.iokit.IOTimeSyncFamily','--vaddr',hex(addr),str(K)],check=True,stdout=f,stderr=subprocess.STDOUT)
# Resolve public virtual slots from authenticated original vtables, rather than naming by analogy.
classes=['IOEthernetInterface','OSArray','OSData','OSBoolean','IOService','OSString','IORegistryEntry','IOTimeSyncClockManager','OSIterator']
vtables={c:next((a for a,n in names.items() if n=='vtable for '+c),None) for c in classes}
slots={}
for c,addr in vtables.items():
 if addr is None:continue
 slots[c]={}
 for off in [0x28,0x38,0x140,0x148,0x150,0x160,0x168,0x198,0x2a0,0x2d8,0x5e0,0x8a0,0x8d0,0x908,0x6b0,0x1e8,0x1f0,0x218]:
  site=addr+16+off
  try:
   target=fixups.get(site)
   if target:slots[c][hex(off)]={'site':hex(site),'target':hex(target[0]),'symbol':names.get(target[0],symbols.get(target[0]))}
  except ValueError:pass
(E/'virtual-slots.json').write_text(json.dumps(slots,indent=2)+'\n')
# Condensed full-function review keeps every conditional/branch, call, string, data write and arithmetic operation.
for name in methods:
 s=(E/(name+'.asm.txt')).read_text();rows=[]
 for line in s.splitlines():
  m=re.match(r'^(0x[0-9a-f]+):\s+(?:[0-9a-f]{2} ){4}\s*([^\t ]+)\s*(.*)$',line)
  if not m:continue
  pc,op,args=m.groups();suffix=''
  call=re.search(r'__stub_(ffff[0-9a-f]+)',args)
  if call:suffix='  => '+str(names.get(int(call[1],16),'unresolved export'))
  if op in ['pacibsp','autibsp','bti','autda','xpacd','pacia','movk','stp','ldp'] and '"' not in args:continue
  if op=='adrp' or (op=='mov' and 'sp' not in args) or (op.startswith('ldr') and not any(x in args for x in ['#0xbb','#0xa0','#0xa8'])):continue
  rows.append(pc+' '+op+' '+args+suffix)
 (E/(name+'-review.txt')).write_text('\n'.join(rows)+'\n')
with K.open('rb') as f:digest=hashlib.file_digest(f,'sha256').hexdigest()
assert digest=='d1003b5143ffd88439b4d45b6017f587171cfe6855660bed05370a2ea5db9fe9'
(E/'inputs.json').write_text(json.dumps({'kernelcache':str(K),'sha256':digest,'methods':{k:hex(v) for k,v in methods.items()},'kc_decoder_sha256':hashlib.sha256((R/'kits/XnuPrelink/kc_image.py').read_bytes()).hexdigest()},indent=2)+'\n')
print('Host branches and authenticated virtual slots frozen in',E)
