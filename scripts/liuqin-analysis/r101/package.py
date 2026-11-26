#!/usr/bin/env python3
"""Package a frozen r101 variant; preserve r100 inputs and require strict layout/hash gates."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,shutil,subprocess,sys,tomllib
R=Path(__file__).resolve().parents[3];W=R/'out/liuqin-r101-work';OLD=R/'out/liuqin-r100-work/evidence'
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def run(args):return subprocess.run([str(x) for x in args],check=True,capture_output=True).stdout
def mod(name,p):
    s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--variant',choices=['a','b'],default='a');a=p.parse_args();e=W/'evidence'/a.variant;d=W/f'device-{a.variant}'
    layout=mod('layout',R/'scripts/liuqin-analysis/r100/package.py');segments,sections=layout.parse_macho_segments(e/'standalone.macho')
    assert segments['__TEXT']['vmsize']<=layout.TEXT_CAP
    assert segments['__DATA']['vmsize']<=layout.DATA_CAP
    assert sections['__TEXT,__const']>=layout.MIN_TEXT_CONST_VMA
    gate=e/'aes-fileset-gate.json'
    nm=e/'nm.txt'
    with nm.open('wb') as out:subprocess.run(['llvm-nm','-n',str(e/'kernel.macho')],check=True,stdout=out)
    run(['python3',R/'scripts/liuqin-analysis/aes_fileset_gate.py','--kernel',e/'kernel.macho','--standalone',e/'standalone.macho','--nm',nm,'--bindings',OLD/'original-bindings.S','--report',gate])
    # One private working FAT image per variant. Refuse overwrites of validated images.
    if (e/'validation-summary.json').exists():raise RuntimeError('Variant already packaged; preserve it and choose a new artifact directory')
    fat=e/'payload.img';reference=R/'out/liuqin/macos-27.3-26C5035r/liuqin/payload/payload.img'
    parent=json.loads((OLD/'candidate/payload.json').read_text());assert sha(reference)==parent['payload_sha256']
    if not fat.exists():shutil.copyfile(reference,fat)
    adt_parser=mod('adt',R/'scripts/liuqin-analysis/r100/package-r100b.py')
    if a.variant=='a':
        baseline=json.loads((OLD/'r100b/validation-summary-r100b.json').read_text());args=baseline['kernel_args'];raw=(OLD/'r100b/kernel.macho.adt').read_bytes();parent_boot=baseline['boot_sha256']
    else:
        old=R/'out/liuqin-r98-work/evidence';baseline=json.loads((old/'validation-summary.json').read_text());args=json.loads((old/'candidate/payload.json').read_text())['kernel_args'];raw=(old/'candidate/kernel.macho.adt').read_bytes();parent_boot='1a477a1d2dfc30e1aac6bdbe48259044e357632eaad63318894396b6ed142b6e'
    sys.path.insert(0,str(R/'scripts'));from unixnu.payload import check_args
    check_args(args.split());adt,end=adt_parser.parse(raw);assert end==len(raw) and adt_parser.pack(adt)==raw
    config=run(['mtype','-i',fat,'::/EFI/UniXNU/unixnu.toml']).decode();current=tomllib.loads(config)['entry'][0]['args'];config=config.replace(current,args)
    (e/'unixnu.toml').write_text(config);(e/'kernel.macho.adt').write_bytes(raw)
    for src,dest in [(e/'kernel.macho','::/EFI/UniXNU/Payloads/kernel.macho'),(e/'kernel.macho.adt','::/EFI/UniXNU/Payloads/kernel.macho.adt'),(e/'unixnu.toml','::/EFI/UniXNU/unixnu.toml')]:
        run(['mcopy','-o','-i',fat,src,dest]);assert hashlib.sha256(run(['mtype','-i',fat,dest])).hexdigest()==sha(src)
    trust_sha=hashlib.sha256(run(['mtype','-i',fat,'::/EFI/UniXNU/Payloads/kernel.macho.trustcache'])).hexdigest();assert trust_sha==parent['trust_cache_sha256']
    # No key access and no signing: retain the existing authenticated sidecars and trust cache.
    run(['python3',d/'scripts/wrap-payload-mbr.py',fat,e/'payload-mbr.img'])
    from unixnu import cli,feeds
    feeds.update_submodules=lambda ctx:None
    cli.main(['bootimg','-D',str(d),'--out',str(W/'package-out'),'--uefi','/home/kurumin/Codes/Github/uefi-sheng','--fd',str(OLD/'SILICIUM_UEFI.fd'),'--dtb',str(d/'dts/liuqin-cape.dtb'),'--ramdisk',str(e/'payload-mbr.img'),'--output',str(e/'boot.img')])
    candidate_mode=json.loads((W/'preparation.json').read_text())['walker_candidates']
    kj=json.loads((e/'kernel.json').read_text());assert sha(e/'kernel.macho')==kj['candidate_sha256']
    info={'status':'PASS','variant':a.variant,'hardware_tested':False,'walker_candidates':candidate_mode,'boot_sha256':sha(e/'boot.img'),'kernel_sha256':sha(e/'kernel.macho'),'parent_boot_sha256':parent_boot,'kernel_args':args,'kernel_args_len':len(args),'adt_sha256':sha(e/'kernel.macho.adt'),'trust_cache_sha256':trust_sha,'payload_sha256':sha(fat),'segments':{k:hex(segments[k]['vmsize']) for k in ['__TEXT','__DATA','__TEXT_EXEC']},'text_const_vma':hex(sections['__TEXT,__const']),'observer_patch_sha256':sha(W/'observer.patch'),'coverage_limits':['XPC/bootstrap payloads are explicitly undecoded; bounded raw prefixes recorded',('Raw candidate mode selected; frames untrusted pending host validation' if candidate_mode else 'A1 user frame walk remains gated; A2 raw-candidate mode and host validation route are wired, not hardware validated'),'Control uses common diagnostic retirement and relocation; hardware acceptance not established']}
    (e/'validation-summary.json').write_text(json.dumps(info,indent=2)+'\n');print(json.dumps(info,indent=2))
if __name__=='__main__':main()
