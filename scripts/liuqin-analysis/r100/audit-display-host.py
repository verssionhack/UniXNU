#!/usr/bin/env python3
"""Bounded host inspection of the exact original display-family functions; no device mutation."""
from pathlib import Path
import sys,bisect,hashlib,json
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_ARM
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'kits/XnuPrelink'))
from kc_image import Image
p=Path('/media/disk_4/unixnu_workspace/ramdisk_dir/unixnu/ipsw/26C5035r/kernelcache.decompressed')
b=p.read_bytes();digest=hashlib.sha256(b).hexdigest();assert digest=='d1003b5143ffd88439b4d45b6017f587171cfe6855660bed05370a2ea5db9fe9'
kc=Image(b);result={'kernelcache_sha256':digest,'functions':[]}
for entry,needle in [('com.apple.iokit.IOMobileGraphicsFamily','s_map_display_type'),('com.apple.iokit.IOGraphicsFamily','__ZNK9IODisplay9MetaClass5allocEv')]:
    im=Image(b,kc.entries[entry][1]);symbols=im.symbols();keys=sorted(symbols)
    matches=[(a,n) for a,n in symbols.items() if any(needle in s for s in n)];assert len(matches)==1
    a,n=matches[0];i=bisect.bisect_right(keys,a);size=min(keys[i]-a if i<len(keys) else 1024,1200)
    ins=[{'pc':hex(x.address),'mnemonic':x.mnemonic,'operands':x.op_str} for x in Cs(CS_ARCH_ARM64,CS_MODE_ARM).disasm(im.read(a,size),a)]
    result['functions'].append({'entry':entry,'symbols':n,'original_pc':hex(a),'size':size,'instructions':ins})
out=R/'out/liuqin-r100-work/evidence/review/host-display-audit.json';out.write_text(json.dumps(result,indent=2)+'\n')
print('Original kernelcache hash verified; bounded display disassembly saved:',out)
