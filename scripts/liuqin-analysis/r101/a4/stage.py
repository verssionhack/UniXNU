#!/usr/bin/env python3
"""Stage observer-only TimeSync capture from accepted A3r1. No hardware actions."""
from pathlib import Path
import difflib,hashlib,json,shutil
R=Path(__file__).resolve().parents[4];A=R/'out/liuqin-r101-a3r1-work';W=R/'out/liuqin-r101-a4-work'
assert not W.exists(), 'Preserve existing staging'
W.mkdir();E=W/'evidence';E.mkdir()
for v in ['a','b']:shutil.copytree(A/f'device-{v}',W/f'device-{v}',symlinks=True)
(W/'frozen-r100b-source').symlink_to(A/'frozen-r100b-source',target_is_directory=True)
shutil.copy2(A/'frozen-r100b-source-sha256.json',W/'frozen-r100b-source-sha256.json')
p=json.loads((A/'preparation.json').read_text());texts={r:(A/'evidence/a/sources'/r).read_text() for r in p['changed_kernel_files']}
r='bsd/dev/liuqin_r101.inc';s=texts[r].replace('int32_t ws_pid;','int32_t ws_pid, clocksyncd_pid;')
s=s.replace('if(!r101 || !r101_ws(p))return;','if(r101 && p && !strcmp(p->p_comm,"clocksyncd"))\n        __atomic_store_n(&r101->clocksyncd_pid,proc_pid(p),__ATOMIC_RELAXED);\n    if(!r101 || !r101_ws(p))return;',1)
s=s.replace('extern void liuqin_r101_task_waits(task_t,uint64_t);','extern void liuqin_r101_task_waits(task_t,uint64_t,unsigned);\nextern void liuqin_r104_timesync_dump(void);')
s=s.replace('extern void liuqin_r102_task_walk(task_t);','extern void liuqin_r102_task_walk(task_t,unsigned);')
s=s.replace('if(task)liuqin_r101_task_waits(task,r101_ms());','''liuqin_r101_emit(1,"LQ102 TARGET_BEGIN: name=WindowServer phase=waits pid=%d",pid);
    if(task)liuqin_r101_task_waits(task,r101_ms(),0);
    liuqin_r101_emit(1,"LQ102 TARGET_END: name=WindowServer phase=waits");
    int cpid=__atomic_load_n(&r101->clocksyncd_pid,__ATOMIC_RELAXED);p=cpid?proc_find(cpid):NULL;task_t clocktask=TASK_NULL;
    if(p){if(!strcmp(p->p_comm,"clocksyncd")){clocktask=proc_task(p);if(clocktask)task_reference(clocktask);}proc_rele(p);}
    liuqin_r101_emit(1,"LQ102 TARGET_BEGIN: name=clocksyncd phase=waits pid=%d present=%u",cpid,clocktask!=TASK_NULL);
    if(clocktask)liuqin_r101_task_waits(clocktask,r101_ms(),1);
    liuqin_r101_emit(1,"LQ102 TARGET_END: name=clocksyncd phase=waits");''')
s=s.replace('liuqin_r101_storage_dump();r102_regs_dump();r101_coverage();','liuqin_r101_storage_dump();r102_regs_dump();liuqin_r104_timesync_dump();r101_coverage();')
s=s.replace('if(task && liuqin_r102_usb_completed()>=fence)liuqin_r102_task_walk(task);','''if(liuqin_r102_usb_completed()>=fence){
        liuqin_r101_emit(1,"LQ102 TARGET_BEGIN: name=WindowServer phase=walk");
        if(task)liuqin_r102_task_walk(task,0);
        liuqin_r101_emit(1,"LQ102 TARGET_END: name=WindowServer phase=walk");
        liuqin_r101_emit(1,"LQ102 TARGET_BEGIN: name=clocksyncd phase=walk");
        if(clocktask)liuqin_r102_task_walk(clocktask,1);
        liuqin_r101_emit(1,"LQ102 TARGET_END: name=clocksyncd phase=walk");
    }''')
s=s.replace('if(task)task_deallocate(task);','if(task)task_deallocate(task);\n    if(clocktask)task_deallocate(clocktask);')
texts[r]=s
r='osfmk/kern/liuqin_r101_waits.inc';s=texts[r]
s=s.replace('r102_walk_saved[64]','r102_walk_saved[2][64]').replace('static unsigned r102_walk_count;','static unsigned r102_walk_count[2];\nstatic uint64_t r104_main_base[2];')
s=s.replace('task_t task,uint64_t ms)','task_t task,uint64_t ms,unsigned slot)')
s=s.replace('r102_walk_count=0;', 'if(slot>=2)return;\n    r102_walk_count[slot]=0;')
s=s.replace('slide=task->task_shared_region_slide;', 'r104_main_base[slot]=task->mach_header_vm_address;\n    slide=task->task_shared_region_slide;')
s=s.replace('char id[33];','liuqin_r101_emit(1,"LQ102 MAIN_BASE: address=%llx source=task_exec_header",(unsigned long long)r104_main_base[slot]);\n    char id[33];')
s=s.replace('r102_walk_count++','r102_walk_count[slot]++').replace('r102_walk_saved[j]','r102_walk_saved[slot][j]')
s=s.replace('task_walk(task_t task)','task_walk(task_t task,unsigned slot)')
s=s.replace('r101_walk_remaining=64;', 'if(slot>=2)return;\n    r104_main_uuid(task,r104_main_base[slot]);\n    r101_walk_remaining=64; /* Per-target, 128 candidates max per snapshot. */')
s=s.replace('i<r102_walk_count','i<r102_walk_count[slot]').replace('r102_walk_saved[i]','r102_walk_saved[slot][i]')
texts[r]=s
r='osfmk/kern/liuqin_r101_walk.inc';s=texts[r]
s+='''
/* Bounded nonfaulting main-image identity, executed only behind prefix fence.
 * No shared-cache slide is used for this image. Read failures are coverage gaps. */
static void r104_main_uuid(task_t task,uint64_t base) {
    vm_map_t map;task_lock(task);map=task->map;vm_map_reference(map);task_unlock(task);
    struct r101_reader reader={.map=map};uint64_t pair[2];uint32_t h[8];
    int invalid_rc=r101_read_user_frame(&reader,0,pair);
    const char *status="invalid-probe-failed";unsigned found=0,commands=0;uint32_t subtype=0;char uuid[33]="unknown";
    if(!invalid_rc)goto done;
    status="header-range";
    if(base<vm_map_min(map) || base>vm_map_max(map)-32 || (base&3))goto done;
    status="header-unavailable";
    for(unsigned i=0;i<2;i++){if(r101_read_user_frame(&reader,base+i*16,pair))goto done;memcpy(h+i*4,pair,16);}
    status="header-invalid";subtype=h[2];
    if(h[0]!=0xfeedfacf || h[1]!=0x100000c || h[3]!=2 || !h[4] || h[4]>128 || h[5]>32768 || h[5]<8 || base>vm_map_max(map)-32-h[5])goto done;
    uint64_t cursor=base+32,end=cursor+h[5];status="uuid-absent";
    for(unsigned i=0;i<h[4];i++){
        if(cursor>end || end-cursor<8){status="command-range";break;}
        if(r101_read_user_frame(&reader,cursor,pair)){status="command-unavailable";break;}
        uint32_t cmd=(uint32_t)pair[0],size=(uint32_t)(pair[0]>>32);commands++;
        if(size<8 || (size&7) || size>end-cursor){status="command-invalid";break;}
        if(cmd==0x1b){
            if(size!=24){status="uuid-size";break;}
            if(r101_read_user_frame(&reader,cursor+8,pair)){status="uuid-unavailable";break;}
            unsigned char *bytes=(unsigned char *)pair;
            for(unsigned j=0;j<16;j++){snprintf(uuid+2*j,3,"%02x",bytes[j]);}
            uuid[32]=0;
            status="ok";found=1;break;
        }
        cursor+=size;
    }
done:
    liuqin_r101_emit(1,"LQ102 MAIN_IMAGE: base=%llx subtype=%x uuid=%s status=%s found=%u commands=%u",
        (unsigned long long)base,subtype,uuid,status,found,commands);
    liuqin_r101_emit(1,"LQ102 MAIN_READS: invalid_rc=%d attempts=%u unavailable=%u reader_validated=0",invalid_rc,reader.attempts,reader.unavailable);
    vm_map_deallocate(map);
}
'''
texts[r]=s
r='iokit/Kernel/IOUserClient.cpp';s=texts[r]
s+='''
/* Read-only IOService-plane traversal. No matching registration, kext load,
 * service publication or property mutation. Bounds include explicit truncation. */
static bool r104_contains(const char *text,const char *word) {
    for(;*text;text++)if(!strncmp(text,word,strlen(word)))return true;
    return false;
}
extern "C" void liuqin_r104_timesync_dump(void) {
    IORegistryIterator *it=IORegistryIterator::iterateOver(gIOServicePlane,kIORegistryIterateRecursively);
    if(!it){liuqin_r101_emit(1,"LQ102 TIMESYNC_COVERAGE: status=iterator-unavailable");return;}
    unsigned visited=0,hits=0,exact=0,printed=0;IORegistryEntry *node;
    while(visited<4096 && (node=it->getNextObject())){
        visited++;const char *cls=node->getMetaClass()->getClassName(),*name=node->getName();
        bool daemon=node->metaCast("IOTimeSyncDaemonService")!=nullptr;
        if(daemon)exact++;
        if(!daemon && !r104_contains(cls,"TimeSync") && !r104_contains(name,"TimeSync") && !r104_contains(cls,"gPTP") && !r104_contains(name,"gPTP") && !r104_contains(cls,"Clock") && !r104_contains(name,"Clock"))continue;
        hits++;if(printed>=64)continue;printed++;
        IORegistryEntry *parent=node->getParentEntry(gIOServicePlane);
        liuqin_r101_emit(1,"LQ102 TIMESYNC_SERVICE: cls=%.60s name=%.60s parent=%.60s daemon=%u",cls,name,parent?parent->getMetaClass()->getClassName():"none",daemon);
    }
    liuqin_r101_emit(1,"LQ102 TIMESYNC_COVERAGE: visited=%u hits=%u printed=%u exact_daemon=%u visit_truncated=%u hit_truncated=%u valid=%u",
        visited,hits,printed,exact,visited==4096,hits-printed,it->isValid());
    it->release();
}
'''
texts[r]=s
patch='';delta=''
for rel,new in texts.items():
 oldpath=W/'frozen-r100b-source'/rel;old=oldpath.read_text() if oldpath.exists() else ''
 patch+=''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/'+rel if old else '/dev/null',tofile='b/'+rel))
 before=(A/'evidence/a/sources'/rel).read_text();delta+=''.join(difflib.unified_diff(before.splitlines(True),new.splitlines(True),fromfile='a/'+rel,tofile='b/'+rel))
 dest=W/'staged-sources'/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_text(new)
(W/'observer.patch').write_text(patch);(E/'A3r1-to-A4.patch').write_text(delta)
for v in ['a','b']:
 paths=list((W/f'device-{v}/patches/xnu').glob('*liuqin-r101.patch'));assert len(paths)==1;paths[0].write_text(patch)
p.update(observer_revision='A4',parent_A3r1_boot_sha256='85e02fede9faad5527010843d073ab50c208fa45f3423437780835f9e0d13be9',behavior_changes=[],observer_patch_sha256=hashlib.sha256(patch.encode()).hexdigest())
(W/'preparation.json').write_text(json.dumps(p,indent=2)+'\n')
for n in ['analysis-rule.json','analysis-rule-frozen.py.txt']:shutil.copy2(A/'evidence'/n,E/n)
print(W)
