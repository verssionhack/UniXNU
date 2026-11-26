#!/usr/bin/env python3
"""Read-only pinned host disassembly; must precede A5 target-read implementation."""
from pathlib import Path
import subprocess
R=Path(__file__).resolve().parents[4];E=R/'out/liuqin-r101-a5-audit';E.mkdir(exist_ok=True)
tool='/media/disk_4/unixnu_workspace/ramdisk_dir/tools/ipsw';cache='/media/disk_4/unixnu_workspace/ramdisk_dir/liuqin-r101-host-cache/dyld_shared_cache_arm64e'
for name,address in [('matcher-count','0x23b0c1d00'),('notifier-init','0x23b0c1e9c'),('notifier-match','0x23b0c1f48'),('notifier-notify','0x23b0c2298'),('notifier-notify-block','0x23b0c2358'),('matcher-start','0x23b0c179c'),('matcher-matched','0x23b0c1d08')]:
 with (E/(name+'.asm.txt')).open('w') as f:subprocess.run([tool,'dyld','disass',cache,'--vaddr',address,'--cache',str(R/'out/liuqin-r101-work/evidence/review-A1/cache-symbols.a2s')],stdout=f,stderr=subprocess.STDOUT,check=True)
with (E/'framework-ivar-cells.txt').open('w') as f:subprocess.run([tool,'dyld','dump',cache,'0x2728f5438','--size','24'],stdout=f,stderr=subprocess.STDOUT,check=True)
