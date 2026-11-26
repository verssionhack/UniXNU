#!/usr/bin/env python3
"""Compile an unlinked interface witness to verify every header virtual slot."""
from pathlib import Path
import importlib.util,json,subprocess,sys
R=Path(__file__).resolve().parents[4];H=Path(__file__).resolve().parent;W=R/'out/liuqin-r101-a7-work';E=W/'evidence/host'
sys.path.insert(0,str(R/'kits/XnuPrelink'))
from kc_image import Image
s=importlib.util.spec_from_file_location('a7_builder',H/'build-identity-ethernet.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
k=Path('/media/disk_4/unixnu_workspace/ramdisk_dir/unixnu/ipsw/26C5035r/kernelcache.decompressed');raw=k.read_bytes();root=Image(raw);names={};table={}
for _,(_,at) in root.entries.items():
    for a,ns in Image(raw,at).symbols().items():
        names.setdefault(a,[]).extend(ns)
        for n in ns:table[n]=a
v=table['__ZTV19IOEthernetInterface']+16;fix=root.fixups();rows=[]
while (p:=fix.get(v+8*len(rows))) and p[1] and (not rows or v+8*len(rows) not in names):
    rows.append({'slot':len(rows),'names':names.get(p[0],[]),'target':hex(p[0]),'key':p[2],'diversity':hex(p[3]),'address_diversity':p[4]})
(E/'interface-slots.json').write_text(json.dumps(rows,indent=2)+'\n')
source=E/'InterfaceWitness.cpp';obj=E/'InterfaceWitness.o'
source.write_text('''#define __PRIVATE_SPI__
#include <IOKit/network/IOEthernetInterface.h>
class A7InterfaceWitness : public IOEthernetInterface {
 OSDeclareDefaultStructors(A7InterfaceWitness)
};
OSDefineMetaClassAndStructors(A7InterfaceWitness,IOEthernetInterface)
static_assert(sizeof(IOEthernetInterface)==0x148,"Pinned interface extent");
''')
build=R/'out/liuqin/macos-27.3-26C5035r/liuqin/tree/build/liuqin-identity-ethernet'
cmd=json.loads((build/'compile-command.json').read_text());i=cmd.index('-o');cmd[i+1]=str(obj)
old=next(i for i,x in enumerate(cmd) if x.endswith('/LiuqinIdentityEthernet.cpp'));cmd[old]=str(source)
record=json.loads((R/'out/liuqin/macos-27.3-26C5035r/liuqin/tree/build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/iokit/DEVELOPMENT/IOPlatformExpert.cpo.json').read_text().strip().rstrip(','))
subprocess.run(cmd,cwd=record['directory'],check=True)
symbols,reloc=m.object_info(obj.read_bytes());start=next(a for n,a,_ in symbols if n=='__ZTV18A7InterfaceWitness')+16
assert start+8*len(rows) not in reloc
for row in rows:
    n,w=reloc[start+row['slot']*8]
    assert w>>63 and w>>48&1 and w>>49&3==row['key'] and w>>32&0xffff==int(row['diversity'],16),row
    if row['slot']==16:
        assert n=='__ZN15OSMetaClassBase25_RESERVEDOSMetaClassBase3Ev' and '__ZN15OSMetaClassBase8DispatchE5IORPC' in row['names']
    elif 'A7InterfaceWitness' not in n:assert n in row['names'],(row,n)
    row['compiled_symbol']=n
report={'status':'PASS','interface_size':0x148,'slots':len(rows),'inherited_reserved_Dispatch_projection_slot':16,'witness_linked_into_candidate':False,'rows':rows}
(E/'interface-header-abi.json').write_text(json.dumps(report,indent=2)+'\n');print('PASS: native interface header ABI:',len(rows),'slots, instance 0x148; witness not linked')
