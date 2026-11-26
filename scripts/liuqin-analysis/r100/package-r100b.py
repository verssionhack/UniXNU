#!/usr/bin/env python3
"""Repair r100a's omitted RAM Data/parkd preparation; reuse its exact kernel and trust bundle."""
from pathlib import Path
import hashlib, json, struct, subprocess, sys, tomllib
R=Path(__file__).resolve().parents[3]
E=R/'out/liuqin-r100-work/evidence'
B=E/'r100b'
W=R/'out/liuqin/macos-27.3-26C5035r/liuqin'
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def run(args):return subprocess.run([str(a) for a in args],check=True,capture_output=True).stdout

def parse(b,off=0):
    np,nc=struct.unpack_from('<II',b,off);off+=8;props=[];kids=[]
    for _ in range(np):
        key,size=struct.unpack_from('<32sI',b,off);off+=36
        props.append((key.rstrip(b'\0'),b[off:off+size]));off+=size+(-size%4)
    for _ in range(nc):
        kid,off=parse(b,off);kids.append(kid)
    return (props,kids),off

def pack(node):
    props,kids=node
    out=struct.pack('<II',len(props),len(kids))
    for k,v in props:out+=struct.pack('<32sI',k,len(v))+v+b'\0'*(-len(v)%4)
    return out+b''.join(pack(k) for k in kids)

def main():
    B.mkdir(exist_ok=True)
    v=json.loads((E/'validation-summary-r100a.json').read_text())
    old=json.loads((E/'candidate/payload.json').read_text())
    assert sha(E/'candidate/boot.img')==v['boot_sha256']
    assert sha(E/'kernel.macho')==v['kernel_sha256']==old['kernel_sha256']
    image=W/'payload/payload.img'
    # Operate on a separate FAT image; preserve the original payload and candidate.
    target=B/'payload.img'
    if target.exists():raise RuntimeError('r100b payload already exists; refusing overwrite')
    assert sha(image)==old['payload_sha256']
    import shutil
    shutil.copyfile(image,target)
    cfg=run(['mtype','-i',target,'::/EFI/UniXNU/unixnu.toml']).decode()
    before=tomllib.loads(cfg)['entry'][0]['args']
    assert before==v['kernel_args']
    after=before.replace('ml-timeout-lock-panic-scale=40 ','').replace('exec-stand-in=/private/var/liuqin/parkd','exec-stand-in=/var/liuqin/parkd')+' liuqin-scratch-probe=1 liuqin-parkd-prepare=1'
    sys.path.insert(0,str(R/'scripts'))
    from unixnu.payload import check_args
    check_args(after.split())
    assert len(after)<=1000
    conf=B/'unixnu.toml';conf.write_text(cfg.replace(before,after))
    raw=(E/'candidate/kernel.macho.adt').read_bytes()
    node,end=parse(raw);assert end==len(raw) and pack(node)==raw
    chosen=next(k for k in node[1] if dict(k[0]).get(b'name')==b'chosen\0')
    assert not any(dict(k[0]).get(b'name')==b'machine-timeouts\0' for k in chosen[1])
    chosen[1].append(([(b'name',b'machine-timeouts\0'),(b'lock-panic-scale',struct.pack('<I',40))],[]))
    adt=B/'kernel.macho.adt';adt.write_bytes(pack(node))
    # Removing precisely the new node must reconstruct every original byte.
    check,end=parse(adt.read_bytes());assert end==adt.stat().st_size
    c=next(k for k in check[1] if dict(k[0]).get(b'name')==b'chosen\0')
    assert c[1].pop()==chosen[1][-1] and pack(check)==raw
    for p,dest in [(conf,'::/EFI/UniXNU/unixnu.toml'),(adt,'::/EFI/UniXNU/Payloads/kernel.macho.adt')]:
        run(['mcopy','-o','-i',target,p,dest]);assert run(['mtype','-i',target,dest])==p.read_bytes()
    # Read back the embedded kernel/trust, rather than relying on host metadata.
    for name,key in [('kernel.macho','kernel_sha256'),('kernel.macho.trustcache','trust_cache_sha256')]:
        assert hashlib.sha256(run(['mtype','-i',target,'::/EFI/UniXNU/Payloads/'+name])).hexdigest()==old[key]
    run(['python3',R/'out/liuqin-r100-work/device/scripts/wrap-payload-mbr.py',target,B/'payload-mbr.img'])
    from unixnu import cli,feeds
    feeds.update_submodules=lambda ctx:None
    cli.main(['bootimg','-D',str(R/'out/liuqin-r100-work/device'),'--uefi','/home/kurumin/Codes/Github/uefi-sheng','--fd',str(E/'SILICIUM_UEFI.fd'),'--dtb',str(R/'out/liuqin-r100-work/device/dts/liuqin-cape.dtb'),'--ramdisk',str(B/'payload-mbr.img'),'--output',str(B/'boot.img')])
    report=dict(status='PASS',experiment='r100b',parent_boot_sha256=v['boot_sha256'],kernel_sha256=v['kernel_sha256'],boot_sha256=sha(B/'boot.img'),kernel_args=after,kernel_args_len=len(after),adt_sha256=sha(adt),payload_sha256=sha(target),trust_cache_sha256=old['trust_cache_sha256'],changes=['Restore RAM Data setup gate liuqin-scratch-probe=1','Restore signed parkd installation gate liuqin-parkd-prepare=1','Move lock-panic timeout scale 40 from command line to /chosen/machine-timeouts/lock-panic-scale','Use equivalent /var/liuqin/parkd stand-in path'],hardware_tested=False)
    (B/'validation-summary-r100b.json').write_text(json.dumps(report,indent=2)+'\n')
    # Runner and validation stay bound to this variant's image, with the same abort guards.
    s=(R/'scripts/liuqin-analysis/r100/run-r100.py').read_text().replace("image = D / 'candidate' / 'boot.img'","image = D / 'boot.img'").replace("D / 'candidate' / 'boot.json'","D / 'boot.json'").replace('validation-summary-r100a.json','validation-summary-r100b.json').replace("!= 'r100a'","!= 'r100b'").replace("default='r100a'","default='r100b'").replace("D / 'kernel.macho'","D.parent / 'kernel.macho'")
    (B/'run-r100b.py').write_text(s)
    shutil.copy2(E/'device_runner.py',B/'device_runner.py')
    print(json.dumps(report,indent=2))
if __name__=='__main__':main()
