#!/usr/bin/env python3
"""Build and freeze one r101 variant using the shared generated tree; never boots."""
from pathlib import Path
import argparse,fcntl,hashlib,json,shutil,sys
R=Path(__file__).resolve().parents[3];W=R/'out/liuqin-r101-work'
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--variant',choices=['a','b'],default='a');a=p.parse_args()
lock=(W/'build.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
if not (W/'frozen-r100b-source-sha256.json').is_file():raise SystemExit('Missing frozen baseline')
sys.path.insert(0,str(R/'scripts'));from unixnu import cli,feeds
feeds.update_submodules=lambda ctx:None
d=W/f'device-{a.variant}'
cli.main(['defconfig','liuqin_defconfig','-D',str(d)])
cli.main(['build','kernel','-D',str(d),'--jobs','4','--kernelcache','/media/disk_4/unixnu_workspace/ramdisk_dir/unixnu/ipsw/26C5035r/kernelcache.decompressed'])
work=R/'out/liuqin/macos-27.3-26C5035r/liuqin';e=W/'evidence'/a.variant;e.mkdir(parents=True,exist_ok=True)
for name in ['kernel.macho','kernel.json','kernel.map.json']:shutil.copy2(work/'kernel'/name,e/name)
shutil.copy2(work/'tree/build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837.unstripped.noctf',e/'standalone.macho')
source=work/'tree/.cache/xnu-work';frozen=e/'sources';frozen.mkdir(exist_ok=True)
prep=json.loads((W/'preparation.json').read_text())
for rel in prep['changed_kernel_files']:
 dest=frozen/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source/rel,dest)
print('Frozen',a.variant,'build in',e)
