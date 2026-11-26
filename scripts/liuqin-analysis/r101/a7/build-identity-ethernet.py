#!/usr/bin/env python3
"""Compile A7's isolated archive and qualify its full native-family ABI. Never boots."""
from pathlib import Path
import hashlib,json,os,struct,subprocess

def require(ok,message):
    if not ok:raise RuntimeError(message)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def object_info(raw):
    require(struct.unpack_from('<I',raw)[0]==0xfeedfacf,'Mach-O object')
    sections=[];st=None;at=32
    for _ in range(struct.unpack_from('<I',raw,16)[0]):
        cmd,size=struct.unpack_from('<II',raw,at)
        if cmd==2:st=at
        if cmd==0x19:
            for i in range(struct.unpack_from('<I',raw,at+64)[0]):
                s=at+72+i*80
                sections.append((s,*struct.unpack_from('<QQI',raw,s+32)))
        at+=size
    sy,count,strings,_=struct.unpack_from('<4I',raw,st+8)
    symbols=[]
    for i in range(count):
        ix,kind,_,_,va=struct.unpack_from('<IBBHQ',raw,sy+i*16)
        symbols.append((raw[strings+ix:raw.index(b'\0',strings+ix)].decode(),va,kind))
    reloc={}
    for s,va,size,off in sections:
        ro,rc=struct.unpack_from('<II',raw,s+56)
        for i in range(rc):
            delta,word=struct.unpack_from('<II',raw,ro+i*8)
            if word>>27&1 and word>>28==11:
                reloc[va+delta]=(symbols[word&0xffffff][0],struct.unpack_from('<Q',raw,off+delta)[0])
    return symbols,reloc

def main():
    tree=Path.cwd();device=Path(os.environ['UNIXNU_DEVICE']);out=tree/'build/liuqin-identity-ethernet';out.mkdir(parents=True,exist_ok=True)
    source=device/'drivers/LiuqinIdentityEthernet/LiuqinIdentityEthernet.cpp';fixture=device/'scripts/net-ether-26C5035r.json'
    abi=json.loads(fixture.read_text());slots=[(int(t,16),int(d,16)) for t,d in abi['slots']];slide=int(abi['collection_slide'],16)
    kc=Path('/media/disk_4/unixnu_workspace/ramdisk_dir/unixnu/ipsw/26C5035r/kernelcache.decompressed')
    require(sha(kc)==abi['kernelcache_sha256']=='d1003b5143ffd88439b4d45b6017f587171cfe6855660bed05370a2ea5db9fe9','pinned KC identity')
    record=json.loads((tree/'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/iokit/DEVELOPMENT/IOPlatformExpert.cpo.json').read_text().strip().rstrip(','))
    include=out/'include/IOKit';include.mkdir(parents=True,exist_ok=True)
    if not (include/'network').exists():(include/'network').symlink_to(device/'drivers/LiuqinIdentityEthernet/network',target_is_directory=True)
    obj=out/'LiuqinIdentityEthernet.o';cmd=[];args=record['arguments'];i=0
    while i<len(args):
        v=args[i]
        if v==record['file']:cmd.append(str(source))
        elif v=='-o':cmd+=['-o',str(obj)];i+=1
        elif v in ['-MF','-MT','-MJ']:i+=1
        elif v=='-Xclang' and args[i+1].startswith('-W'):i+=1
        elif not v.startswith('-W'):cmd.append(v)
        i+=1
    cmd+=['-I',str(out/'include'),'-I',str(tree/'.cache/xnu-work/osfmk'),'-Wall','-Wextra','-Werror','-Wno-unused-parameter','-Wno-unnecessary-virtual-specifier','-Wno-c99-designator','-Wno-reorder-init-list','-Wno-deprecated-enum-enum-conversion','-Wno-deprecated-anon-enum-enum-conversion','-Wno-overriding-option','-Wno-missing-designated-field-initializers','-Wno-unused-but-set-global','-Wno-deprecated-declarations']
    (out/'compile-command.json').write_text(json.dumps(cmd,indent=2)+'\n')
    result=subprocess.run(cmd,cwd=record['directory'],stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True)
    (out/'compile.log').write_text(result.stdout);require(result.returncode==0,result.stdout[-7000:])
    symbols,reloc=object_info(obj.read_bytes());cls='LiuqinIdentityEthernet';own=tuple(p+str(len(cls))+cls for p in ['__ZN','__ZNK'])
    # XNU's source header/compiler projects this inherited slot as reserved3;
    # the shipped collection uses Dispatch there. Its PAC diversity already
    # agrees with the pinned Dispatch slot. Bind the slot to native Dispatch,
    # never the source reserved3 panic implementation. Refuse any broader use.
    reserved='__ZN15OSMetaClassBase25_RESERVEDOSMetaClassBase3Ev';dispatch='__ZN15OSMetaClassBase8DispatchE5IORPC'
    original_obj_sha=sha(obj)
    projected=[a for a,(n,_) in reloc.items() if n==reserved]
    vstart=next(a for n,a,_ in symbols if n==f'__ZTV{len(cls)}{cls}')+16
    names=json.loads((device/'scripts/controller-slots.json').read_text())
    mv=next(a for n,a,_ in symbols if n==f'__ZTVN{len(cls)}{cls}9MetaClassE')+16
    meta=json.loads((device/'scripts/metaclass-Dispatch.json').read_text())
    require(set(projected)=={vstart+16*8,mv+16*8} and dispatch in names[16]['names'] and dispatch in meta['names'],'exact inherited Dispatch projections')
    require(all((reloc[a][1]>>32)&0xffff==slots[16][1] for a in projected),'Dispatch projection PAC diversity')
    subprocess.run(['llvm-objcopy','--redefine-sym',reserved+'='+dispatch,obj],check=True)
    symbols,reloc=object_info(obj.read_bytes())
    vt=next(a for n,a,_ in symbols if n==f'__ZTV{len(cls)}{cls}')+16
    entries=[reloc[vt+8*i] for i in range(len(slots))];require(vt+8*len(slots) not in reloc,'exact full parent vtable extent')
    bindings={n:int(a,16)+slide for n,a in abi['bindings'].items()};pure=int(abi['pure_target'],16)
    classes=['IONetworkController','IOEthernetController','IONetworkMedium','IONetworkInterface','IOEthernetInterface','IOOutputQueue']
    family=tuple(str(len(c))+c for c in classes);overrides={};report=[]
    for i,(n,w) in enumerate(entries):
        require(w>>63 and w>>48&1 and w>>49&3==0 and (w>>32)&0xffff==slots[i][1],f'slot {i}: PAC/auth/key/address-diversity mismatch')
        role='native'
        if n.startswith(own):
            role='override';prefix=own[0] if n.startswith(own[0]) else own[1];overrides[n[len(prefix):]]=i
        elif any(c in n for c in family):
            role='retained-family';require(slots[i][0]!=pure,f'pure slot {i} unimplemented')
            require(bindings.setdefault(n,slots[i][0]+slide)==slots[i][0]+slide,f'slot {i}: inherited native target mismatch')
        else:require(i<abi['base_slots'] and n in names[i]['names'],f'slot {i}: IOService inherited identity mismatch: {n}')
        require(slots[i][0]!=pure or role=='override',f'pure slot {i}')
        report.append({'slot':i,'name':n,'role':role,'target':hex(slots[i][0]),'diversity':hex(slots[i][1])})
    used={n for n,_,k in symbols if k==1 and any(c in n for c in family)}
    for n in used-set(bindings):
        prefix=next((p for p in ['__ZN20IOEthernetController','__ZNK20IOEthernetController'] if n.startswith(p)),None)
        suffix=n[len(prefix):] if prefix else None
        require(suffix in overrides,f'unresolved qualified family call {n}')
        bindings[n]=slots[overrides[suffix]][0]+slide
    used|={n for n,_ in entries if not n.startswith(own) and any(c in n for c in family)}
    asm='.text\n.p2align 2\n';addresses=''
    for n in sorted(used):
        a=bindings[n]
        if n.endswith('10gMetaClassE') or n.startswith('__ZTV'):addresses+=f'.globl {n}\n.set {n}, {a:#x}\n'
        else:
            addresses+=f'.globl {n}.original\n.set {n}.original, {a:#x}\n'
            asm+=f'.globl {n}\n{n}:\n bti c\n b {n}.original\n'
    for stem,text in [('original-bindings',asm),('original-addresses',addresses)]:
        s=out/(stem+'.S');s.write_text(text)
        subprocess.run([args[0],'-target','arm64e-apple-ios17.0','-c',s,'-o',out/(stem+'.o')],check=True)
    late=out/'LiuqinIdentityEthernet.late.o'
    subprocess.run(['llvm-objcopy','--remove-section=__DATA,__mod_init_func','--globalize-symbol=__GLOBAL__sub_I_LiuqinIdentityEthernet.cpp',obj,late],check=True)
    archive=out/'libLiuqinIdentityEthernet.a';archive.unlink(missing_ok=True)
    subprocess.run(['llvm-ar','rcsD',archive,late,out/'original-bindings.o',out/'original-addresses.o'],check=True)
    summary={'status':'PASS','vtable_slots':len(entries),'overrides':overrides,'pure_slots_implemented':[i for i,(t,_) in enumerate(slots) if t==pure],'inherited_Dispatch_projection':{'slot':16,'from':reserved,'to':dispatch,'unadjusted_object_sha256':original_obj_sha},'fixture_sha256':sha(fixture),'source_sha256':sha(source),'archive_sha256':sha(archive),'bindings':{n:hex(bindings[n]) for n in sorted(used)},'slots':report}
    (out/'build-report.json').write_text(json.dumps(summary,indent=2)+'\n');print('A7 archive ABI PASS:',len(entries),'slots;',len(used),'bindings')

if __name__=='__main__':main()
