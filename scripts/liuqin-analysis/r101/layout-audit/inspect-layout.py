#!/usr/bin/env python3
"""Read-only A7 placement/header audit. No image emission or candidate build."""
from pathlib import Path
import hashlib,json,struct,sys
R=Path(__file__).resolve().parents[4];E=R/'out/liuqin-r101-layout-audit/evidence';A=R/'out/liuqin-r101-a7-work/evidence/a'
sys.path.insert(0,str(R/'kits/XnuPrelink'))
from kc_image import Image
from fileset_layout import Layout
K=Path('/media/disk_4/unixnu_workspace/ramdisk_dir/unixnu/ipsw/26C5035r/kernelcache.decompressed')
raw=K.read_bytes();assert hashlib.sha256(raw).hexdigest()=='d1003b5143ffd88439b4d45b6017f587171cfe6855660bed05370a2ea5db9fe9'
cache=Image(raw);native=Image((A/'standalone.macho').read_bytes());final=Image((A/'kernel.macho').read_bytes());entry=Image(final.data,final.entries['com.apple.kernel'][1])
closure=json.loads((A/'kernel.json').read_text())['closure'];layout=Layout(cache,native,set(closure));slide=native.base-cache.base
occupied=[]
for name,(_,at) in cache.entries.items():
    if name=='com.apple.kernel' or name not in closure:continue
    for s in Image(raw,at).segments:
        if s['size'] and s['name']!='__LINKEDIT':occupied.append({'owner':name,**s})
def seg(image,name):return next(s for s in image.segments if s['name']==name)
regions={}
for name,cap,rootname in [('__TEXT',0x1d8000,'__PRELINK_TEXT'),('__DATA',0x284000,'__DATA')]:
    start=layout.placements[name];end=start+seg(native,name)['size'];root=seg(cache,rootname)
    nxt=min((s for s in occupied if end<=s['va']<root['va']+root['size']),key=lambda s:s['va'])
    assert (start+slide)&((1<<64)-1)==seg(entry,name)['va']
    regions[name]={'policy_cap':hex(cap),'native_size':hex(seg(native,name)['size']),'policy_headroom_bytes':cap-seg(native,name)['size'],'emitted_start':hex(seg(entry,name)['va']),'emitted_end':hex(seg(entry,name)['va']+seg(entry,name)['size']),'next_retained':{'owner':nxt['owner'],'segment':nxt['name'],'emitted_start':hex(nxt['va']+slide)},'space_until_next_retained':hex(nxt['va']-start),'physical_slack_after_native_bytes':nxt['va']-end,'policy_matches_entire_gap':cap==nxt['va']-start}
def header(image):
    first=[]
    for cmd,at,length in image.commands:
        if cmd!=0x19:continue
        for i in range(struct.unpack_from('<I',image.data,at+64)[0]):
            s=at+72+i*80;size,off=struct.unpack_from('<QI',image.data,s+40)
            if size and off:first.append(off)
    ncmd,size=struct.unpack_from('<II',image.data,image.at+16)
    payload=min(first);return {'at':hex(image.at),'ncmds':ncmd,'sizeofcmds':hex(size),'header_end_fileoff':hex(image.at+32+size),'first_backed_section_fileoff':hex(payload),'actual_gap_bytes':payload-(image.at+32+size)}
headers={'standalone':header(native),'emitted_native':header(entry),'root':{'ncmds':len(final.commands),'sizeofcmds':hex(struct.unpack_from('<I',final.data,20)[0]),'mapping_filesize':hex(seg(final,'__TEXT')['filesize']),'command_end_fileoff':hex(32+struct.unpack_from('<I',final.data,20)[0]),'slack_to_mapping_end_bytes':seg(final,'__TEXT')['filesize']-32-struct.unpack_from('<I',final.data,20)[0]}}
const=next(s for s in native.sections if s['segment']=='__TEXT' and s['name']=='__const')
report={'scope':'host inspection only; Layout object constructed without image emission','original_cache_sha256':hashlib.sha256(raw).hexdigest(),'standalone_sha256':hashlib.sha256(native.data).hexdigest(),'emitted_kernel_sha256':hashlib.sha256(final.data).hexdigest(),'closure_entries':len(closure),'placement_windows':regions,'headers':headers,'const_gate':{'native_base':hex(native.base),'policy_floor':hex(0xfffffff007005900),'first_const_vma':hex(const['va']),'policy_margin_bytes':const['va']-0xfffffff007005900,'floor_offset_from_base':hex(0xfffffff007005900-native.base),'const_offset_from_base':hex(const['va']-native.base),'legacy_extra_section_bytes':80,'legacy_path_active':False},'read_only_native_layout':layout.describe()}
assert headers['standalone']['actual_gap_bytes']>=0 and headers['emitted_native']['actual_gap_bytes']>=0
(E/'placement-and-headers.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:report[k] for k in ['placement_windows','headers','const_gate']},indent=2))
