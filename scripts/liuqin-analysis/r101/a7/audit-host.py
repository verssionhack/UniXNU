#!/usr/bin/env python3
"""Generate A7's ABI evidence directly from the pinned KC; never builds or boots."""
from pathlib import Path
import hashlib,json,struct,subprocess,sys
R=Path(__file__).resolve().parents[4]; W=R/'out/liuqin-r101-a7-work'; E=W/'evidence/host'; E.mkdir(parents=True,exist_ok=True)
K=Path('/media/disk_4/unixnu_workspace/ramdisk_dir/unixnu/ipsw/26C5035r/kernelcache.decompressed')
sys.path.insert(0,str(R/'kits/XnuPrelink'))
from kc_image import Image
raw=K.read_bytes(); digest=hashlib.sha256(raw).hexdigest()
assert digest=='d1003b5143ffd88439b4d45b6017f587171cfe6855660bed05370a2ea5db9fe9'
root=Image(raw); fix=root.fixups(); names={}; tables={}
for entry,(_,at) in root.entries.items():
 table={}
 for addr,ns in Image(raw,at).symbols().items():
  names.setdefault(addr,[]).extend(ns)
  for n in ns:table[n]=addr
 tables[entry]=table
def vt(entry,cls):
 start=tables[entry][f'__ZTV{len(cls)}{cls}']+16; slots=[]
 while (p:=fix.get(start+8*len(slots))) and p[1] and (not slots or start+8*len(slots) not in names):slots.append(p)
 return start,slots
entry='com.apple.iokit.IONetworkingFamily'; cls='IOEthernetController'; base,slots=vt(entry,cls)
image=Image(raw,root.entries[entry][1]); ctor=tables[entry]['__ZN20IOEthernetController9MetaClassC2Ev']; code=image.read(ctor,128)
sizes=[(w>>5)&0xffff for (w,) in struct.iter_unpack('<I',code) if w&0xffe0001f==0x52800003]
assert sizes==[0x118],sizes
classes=['IONetworkController','IOEthernetController','IONetworkMedium','IONetworkInterface','IOEthernetInterface','IOOutputQueue']
prefixes=tuple(p+str(len(c))+c for c in classes for p in ['__ZN','__ZNK'])
bindings={n:hex(a) for n,a in tables[entry].items() if n.startswith(prefixes) and not any(s in n for s in ['_os_log','kalloc_type_view','.cold'])}
bindings['__ZTV20IOEthernetController']=hex(base-16)
pure=tables['com.apple.kernel']['___cxa_pure_virtual']
assert len(slots)==400
assert all(p[1]==1 and p[2]==0 and p[4]==1 for p in slots)
fixture={'kernelcache_sha256':digest,'collection_slide':hex(0xfffffff007004000-root.base),'vtable':hex(base),'instance_size':hex(sizes[0]),'base_slots':len(vt('com.apple.kernel','IOService')[1]),'pure_target':hex(pure),'slots':[[hex(p[0]),hex(p[3])] for p in slots],'bindings':bindings}
(E/'net-ether-26C5035r.json').write_text(json.dumps(fixture,indent=2)+'\n')
inventory=[{'slot':i,'offset':hex(i*8),'site':hex(base+i*8),'target':hex(p[0]),'names':names.get(p[0],[]),'auth':p[1],'key':p[2],'diversity':hex(p[3]),'address_diversity':p[4],'pure':p[0]==pure} for i,p in enumerate(slots)]
(E/'controller-slots.json').write_text(json.dumps(inventory,indent=2)+'\n')
meta=tables[entry]['__ZTVN20IOEthernetController9MetaClassE']+16
mp=fix[meta+16*8]
assert mp==fix[base+16*8]
(E/'metaclass-Dispatch.json').write_text(json.dumps({'site':hex(meta+16*8),'pointer':list(mp),'names':names[mp[0]]},indent=2)+'\n')
_,isv=vt('com.apple.kernel','IOService')
assert 'isInactive' in ' '.join(names[0xfffffe000c334808])
# Exact called export in BSD attach and virtual registerService slot.
assert isv[0x5e0//8][0]==0xfffffe000c325634
ipsw='/media/disk_4/unixnu_workspace/ramdisk_dir/tools/ipsw'
jobs={
 'com.apple.iokit.IONetworkingFamily':{'bsd-attach':0xfffffe000acad124,'parent-meta-constructor':ctor,'controller-start':0xfffffe000aca0760,'attach-interface':0xfffffe000aca0cd0,'configure-interface':0xfffffe000aca211c},
 'com.apple.iokit.IOTimeSyncFamily':{'clock-init':0xfffffe000b104044,'interface-matched':0xfffffe000b1064e0,'delayed-lookup':0xfffffe000b104780}}
for ent,methods in jobs.items():
 for n,a in methods.items():
  with (E/(n+'.asm.txt')).open('w') as f:subprocess.run([ipsw,'macho','disass','--fileset-entry',ent,'--vaddr',hex(a),str(K)],stdout=f,stderr=subprocess.STDOUT,check=True)
# Keep unfiltered instructions alongside names for every stub call.
exports={hex(a):ns for a,ns in names.items() if any(s in ' '.join(ns) for s in ['thread_call_allocate','thread_call_enter_delayed','isInactive','IOService9waitQuiet'])}
(E/'ownership-exports.json').write_text(json.dumps(exports,indent=2)+'\n')
capture=R/'out/liuqin-r101-a6-work/evidence/a/boot-A6-20261121-150526'; log=(capture/'usb.log').read_bytes()
landmarks={}
for label,needle in [('root_quiet',b'IOKit busy 0:'),('first_userspace_exec',b'LIUQIN PROC +'),('observer_INIT',b'LQ102 INIT:')]:
 pos=log.find(needle)
 if pos<0:landmarks[label]={'found':False};continue
 rows=[json.loads(x) for x in (capture/'guard-trace.jsonl').read_text().splitlines()]
 row=next(x for x in rows if x.get('event')=='monitor' and x.get('length',0)>0 and x['offset']<=pos<x['offset']+x['length'])
 landmarks[label]={'offset':pos,'line':log[:pos].count(b'\n')+1,'host_elapsed_upper_s':row['elapsed'],'line_text':log[pos:log.find(b'\n',pos)].decode(errors='replace')}
(E/'A6-landmarks.json').write_text(json.dumps(landmarks,indent=2)+'\n')
print(json.dumps({'KC':digest,'slots':len(slots),'pure_slots':[x['slot'] for x in inventory if x['pure']],'instance_size':sizes[0],'isInactive_export':names[0xfffffe000c334808],'landmarks':landmarks},indent=2))
