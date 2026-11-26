#!/usr/bin/env python3
"""Stage A2r1 fence correctness repair from immutable executed A2; never boot."""
from pathlib import Path
import difflib,hashlib,json,shutil
R=Path(__file__).resolve().parents[4];H=Path(__file__).resolve().parent;A=R/'out/liuqin-r101-a2-work';W=R/'out/liuqin-r101-a2r1-work'
assert not (W/'preparation.json').exists(),'Do not overwrite an existing revision'
W.mkdir(exist_ok=True)
for v in ['a','b']:shutil.copytree(A/f'device-{v}',W/f'device-{v}',symlinks=True)
F=A/'frozen-r100b-source';(W/'frozen-r100b-source').symlink_to(F,target_is_directory=True);shutil.copy2(A/'frozen-r100b-source-sha256.json',W/'frozen-r100b-source-sha256.json')
p=json.loads((A/'preparation.json').read_text());texts={rel:(A/'evidence/a/sources'/rel).read_text() for rel in p['changed_kernel_files']}
rel='bsd/dev/liuqin_usb_debug.c';s=texts[rel]
old='''static uint64_t r102_pending_cursor,r102_completed_cursor;
static unsigned r102_transport_gap;
uint64_t liuqin_r102_usb_completed(void);
uint64_t liuqin_r102_usb_completed(void) { return __atomic_load_n(&r102_transport_gap,__ATOMIC_ACQUIRE)?0:__atomic_load_n(&r102_completed_cursor,__ATOMIC_ACQUIRE); }'''
assert s.count(old)==1;s=s.replace(old,'''#include "liuqin_r103_usb_fence.h"
static struct r103_usb_fence r103_fence;
uint64_t liuqin_r102_usb_completed(void);
uint64_t liuqin_r102_usb_completed(void) { return r103_fence_value(&r103_fence); }''')
s=s.replace('complete(unsigned ep)','complete(unsigned ep,unsigned event_status)').replace('complete(ep);','complete(ep,status);')
old='''        if(left && r102_pending_cursor)__atomic_store_n(&r102_transport_gap,1,__ATOMIC_RELEASE);
        if(!left && r102_pending_cursor)__atomic_store_n(&r102_completed_cursor,r102_pending_cursor,__ATOMIC_RELEASE);
        r102_pending_cursor=0;''';assert s.count(old)==1;s=s.replace(old,'        r103_fence_complete(&r103_fence,left,event_status&1);')
s=s.replace('    if(u.cursor-r102_before_copy!=n)__atomic_store_n(&r102_transport_gap,1,__ATOMIC_RELEASE);','    r103_fence_copy(&r103_fence,r102_before_copy,u.cursor,n);').replace('        r102_pending_cursor=u.cursor;','        r103_fence_ring(&r103_fence,u.cursor);')
needle='fail(const char *why)\n{';assert s.count(needle)==1;s=s.replace(needle,needle+'\n    r103_fence_lost(&r103_fence);')
needle='\t\t\t\tep3_drop();\n\t\t\t\towned = ep3_take();';assert s.count(needle)==1;s=s.replace(needle,'                r103_fence_note(&r103_fence,1);\n'+needle)
needle='\tchar *dst = (char *)(u.dma + TX);';assert s.count(needle)==1;s=s.replace(needle,'    r103_fence_note(&r103_fence,0);\n'+needle)
assert 'r102_pending_cursor' not in s and 'r102_transport_gap' not in s;texts[rel]=s
header='bsd/dev/liuqin_r103_usb_fence.h';texts[header]=(H/'kernel/liuqin_r103_usb_fence.h').read_text();p['changed_kernel_files'].append(header)
patch=''
for rel in p['changed_kernel_files']:
 old=(F/rel).read_text() if (F/rel).exists() else ''
 patch+=''.join(difflib.unified_diff(old.splitlines(True),texts[rel].splitlines(True),fromfile='a/'+rel,tofile='b/'+rel))
(W/'observer.patch').write_text(patch)
for v in ['a','b']:
 targets=list((W/f'device-{v}/patches/xnu').glob('*liuqin-r101.patch'));assert len(targets)==1;targets[0].write_text(patch)
p['observer_revision']='A2r1';p['observer_patch_sha256']=hashlib.sha256(patch.encode()).hexdigest();p['parent_A2_boot_sha256']=json.loads((A/'evidence/a/validation-summary.json').read_text())['boot_sha256'];p['behavior_changes']=[];(W/'preparation.json').write_text(json.dumps(p,indent=2)+'\n')
e=W/'evidence';e.mkdir(exist_ok=True)
for n in ['analysis-rule.json','analysis-rule-frozen.py.txt']:shutil.copy2(A/'evidence'/n,e/n)
(e/'A2-to-A2r1-USB.patch').write_text(''.join(difflib.unified_diff((A/'evidence/a/sources/bsd/dev/liuqin_usb_debug.c').read_text().splitlines(True),s.splitlines(True),fromfile='A2/bsd/dev/liuqin_usb_debug.c',tofile='A2r1/bsd/dev/liuqin_usb_debug.c')))
print(W)
