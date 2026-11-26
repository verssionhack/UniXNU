#!/usr/bin/env python3
"""Read-only pinned SkyLight text scan; save exact direct-branch/global-page refs."""
from pathlib import Path
import bisect,hashlib,json,mmap,re,struct
R=Path(__file__).resolve().parents[4];W=R/'out/liuqin-r101-skylight-audit';E=W/'evidence'
C=Path('/media/disk_4/unixnu_workspace/ramdisk_dir/liuqin-r101-host-cache')
manifest=json.loads((R/'out/liuqin-r101-work/evidence/review-A1/host-cache-manifest.json').read_text())
class Reader:
    def __init__(self):
        self.maps=[];self.verified={};self.open={};self.entries={}
        for e in manifest:
            p=C/Path(e['path']).name;self.entries[p]=e
            with p.open('rb') as f:
                h=f.read(104);assert h.startswith(b'dyld_v1') and h[88:104].hex()==e['uuid']
                off,n=struct.unpack_from('<II',h,16);assert n<1024;f.seek(off)
                for a,s,o,_,prot in struct.iter_unpack('<QQQII',f.read(n*32)):self.maps.append((a,s,o,p,prot))
    def read(self,a,n):
        matches=[m for m in self.maps if m[0]<=a and a+n<=m[0]+m[1]];assert len(matches)==1,(hex(a),n)
        base,_,off,p,_=matches[0]
        if p not in self.open:
            with p.open('rb') as f:
                digest=hashlib.file_digest(f,'sha256').hexdigest();assert digest==self.entries[p]['sha256'],p
                self.open[p]=mmap.mmap(f.fileno(),0,access=mmap.ACCESS_READ)
            self.verified[str(p)]={'sha256':digest,'uuid':self.entries[p]['uuid']}
        return self.open[p][off+a-base:off+a-base+n]
def signed(v,n):return v-(1<<n) if v>>(n-1) else v
reader=Reader();header=0x1826af000;h=reader.read(header,32);_,_,_,_,n,sz,_,_=struct.unpack('<8I',h)
commands=reader.read(header+32,sz);sections={};uuid=None;at=0
for _ in range(n):
    cmd,size=struct.unpack_from('<II',commands,at)
    if cmd==0x1b:uuid=commands[at+8:at+24].hex()
    if cmd==0x19:
        for i in range(struct.unpack_from('<I',commands,at+64)[0]):
            s=at+72+i*80;name=commands[s:s+16].split(b'\0')[0].decode();seg=commands[s+16:s+32].split(b'\0')[0].decode()
            a,size2=struct.unpack_from('<QQ',commands,s+32);sections[seg+','+name]=[a,size2]
    at+=size
assert uuid=='331822b11c9f367badd2310ddeeff7c9'
symbols={}
for line in (E/'SkyLight-symbols.txt').read_text().splitlines():
    m=re.match(r'0x([0-9a-f]+):.*\t([^\t]+)\s*$',line)
    if m:symbols[int(m[1],16)]=m[2].strip()
addrs=sorted(symbols)
def owner(a):
    i=bisect.bisect_right(addrs,a)-1;return {'start':hex(addrs[i]),'symbol':symbols[addrs[i]]} if i>=0 else None
targets={0x182836840:'WSCompositorSetDebugOptions',0x182837070:'WSCompositorActivateDefault',0x1828d407c:'CGXInitializeGL',0x182a8d14c:'WSInitialize',0x1828382b0:'activate_default_block',0x1828dfd58:'Metal_check_block'}
start,length=sections['__TEXT,__text'];code=reader.read(start,length);branches=[];pages=[]
for i,(word,) in enumerate(struct.iter_unpack('<I',code)):
    pc=start+i*4
    if word&0x7c000000==0x14000000:
        dest=pc+signed(word&0x3ffffff,26)*4
        if dest in targets:branches.append({'pc':hex(pc),'target':hex(dest),'target_symbol':targets[dest],'kind':'BL' if word>>31 else 'B','owner':owner(pc)})
    if word&0x9f000000==0x90000000:
        dest=(pc&~4095)+(signed(((word>>5)&0x7ffff)<<2|((word>>29)&3),21)<<12)
        if dest in [0x1eb1b6000,0x1eb1b7000]:pages.append({'pc':hex(pc),'page':hex(dest),'register':word&31,'owner':owner(pc)})
(E/'direct-branches.json').write_text(json.dumps(branches,indent=2)+'\n');(E/'global-page-references.json').write_text(json.dumps(pages,indent=2)+'\n')
(E/'inputs.json').write_text(json.dumps({'scope':'host-only; no candidate build or device action','SkyLight_UUID':uuid,'shared_cache_UUID':'8b1e17c672d6301791a4916022e3612e','sections':sections,'text_sha256':hashlib.sha256(code).hexdigest(),'cache_files_verified':reader.verified,'scan_limits':'All aligned direct B/BL in SkyLight __text; excludes other images/indirect calls. Global-page candidates are not resolved data-flow or a proof of all writers.'},indent=2)+'\n')
print(json.dumps(branches,indent=2));print('global page references',len(pages))
