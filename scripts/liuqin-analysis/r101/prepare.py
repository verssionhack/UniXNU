#!/usr/bin/env python3
"""Stage common r101 observers on preserved r100b sources; never boots a device."""
from pathlib import Path
import argparse,difflib,hashlib,json,shutil
R=Path(__file__).resolve().parents[3];HERE=Path(__file__).resolve().parent
W=R/'out/liuqin-r101-work';F=W/'frozen-r100b-source'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--walker-candidates',action='store_true',help='A2 preparation only: raw nonfault frames, host validation required; no trusted backtrace')
    args=parser.parse_args()
    if not F.is_dir():raise SystemExit('Freeze r100b source before preparation')
    changed={};original={}
    def get(rel):
        if rel not in changed:
            original[rel]=(F/rel).read_text() if (F/rel).exists() else '';changed[rel]=original[rel]
        return changed[rel]
    def put(rel,text):get(rel);changed[rel]=text
    def sub(rel,old,new,count=1):
        s=get(rel)
        if s.count(old)!=count:raise RuntimeError(f'{rel}: expected {count} matches of {old[:80]!r}, got {s.count(old)}')
        put(rel,s.replace(old,new))
    for name in ['liuqin_r101.h','liuqin_r101.inc']:
        put('bsd/dev/'+name,(HERE/'kernel'/name).read_text())
    for name in ['liuqin_r101_waits.inc','liuqin_r101_walk.inc','r101_framewalk.h']:
        text=(HERE/'kernel'/name).read_text()
        if name=='liuqin_r101_walk.inc' and args.walker_candidates:text=text.replace('#define R101_CAPTURE_CANDIDATES 0','#define R101_CAPTURE_CANDIDATES 1')
        put('osfmk/kern/'+name,text)
    perf='bsd/dev/liuqin_perf.c'
    sub(perf,'/* r63: bounded observation only; preserve operation results and policies. */',
        '/* r63: bounded observation only; preserve operation results and policies. */\n#include <dev/liuqin_r101.h>')
    sub(perf,'static void lq_sc_enter(struct proc *p, unsigned code, struct liuqin_perf_call *call, const uint64_t *args);',
        'static void r101_start(void);\nstatic void r101_sys_begin(struct proc *, unsigned, struct liuqin_perf_call *);\nstatic void r101_sys_end(struct proc *, struct liuqin_perf_call *, int, uint64_t);\nstatic void lq_sc_enter(struct proc *p, unsigned code, struct liuqin_perf_call *call, const uint64_t *args);')
    sub(perf,'    lq_sc_enter(p, code, call, args);','    lq_sc_enter(p, code, call, args);\n    r101_sys_begin(p, code, call);')
    sub(perf,'    lq_sc_exit(p, call, error);','    r101_sys_end(p, call, error, result);\n    lq_sc_exit(p, call, error);')
    sub(perf,'if (LQ_WR_IS_ENOSPC_CAND(code) && __atomic_load_n(&lq_enospc_logs, __ATOMIC_RELAXED) < 20u)', 'if (LQ_WR_IS_ENOSPC_CAND(code))')
    sub(perf,'    __atomic_store_n(&lq_hist_ready, 1u, __ATOMIC_RELEASE);','    __atomic_store_n(&lq_hist_ready, 1u, __ATOMIC_RELEASE);\n    r101_start();')
    sub(perf,'        if (i >= 10 && !lq_ui_tag_for(agg[i].comm)) continue;', '        if (i >= 15 && !lq_ui_tag_for(agg[i].comm)) continue;')
    sub(perf,'    liuqin_log_line("LIUQIN TASK_CPU_HDR:', '    liuqin_r101_emit(1, "LQ101 CPU_TIME: ticks=%llu frq=%llu", LQ_U64(now), LQ_U64(frq));\n    liuqin_log_line("LIUQIN TASK_CPU_HDR:')
    sub(perf,'liuqin_log_line("LIUQIN TASK_CPU_HDR:', 'liuqin_r101_emit(1, "LIUQIN TASK_CPU_HDR:')
    sub(perf,'liuqin_log_line("LIUQIN TASK_CPU:', 'liuqin_r101_emit(0, "LIUQIN TASK_CPU:')
    put(perf,get(perf)+'\n#include "liuqin_r101.inc"\n')
    sub('bsd/dev/liuqin_perf.h','    uint64_t sc_start;','    uint64_t sc_start;\n    uint64_t r101_id;')
    debug='bsd/dev/liuqin_debug.c'
    # Retire 8 KiB of old panic-tail diagnostics, preserving the full USB panic log.
    sub(debug,'static char lq_panic_tail[1u << 14];','static char lq_panic_tail[1u << 13];')
    # Reliable worker-only append: retry contention with interrupts restored.
    sub(debug,'static void\nlq_debug_append_impl(', 'static int\nlq_debug_append_impl(')
    sub(debug,'if (!data || size <= 0 || liuqin_debug_mute) {\n\t\treturn;', 'if (!data || size <= 0 || liuqin_debug_mute) {\n\t\treturn 0;')
    sub(debug,'\t\tml_set_interrupts_enabled(intr);\n\t\t\treturn;', '\t\tml_set_interrupts_enabled(intr);\n\t\t\treturn 0;')
    sub(debug,'\tml_set_interrupts_enabled(intr);\n}\n\nint\nliuqin_debug_at_line_start', '\tml_set_interrupts_enabled(intr);\n\treturn 1;\n}\n\nint\nliuqin_debug_at_line_start')
    put(debug,get(debug)+'''
extern void IOSleep(unsigned int);
int liuqin_r101_debug_line(const char *, int);
int liuqin_r101_debug_line(const char *line,int size) {
    while(!liuqin_panic_active){
        if(lq_debug_append_impl(line,size,1))return 1;
        IOSleep(1);
    }
    return 0;
}
''')
    thread='osfmk/kern/thread.c';put(thread,get(thread)+'\n#include "liuqin_r101_waits.inc"\n')
    sleh='osfmk/arm64/sleh.c';put(sleh,get(sleh)+'''
void liuqin_r101_user_regs(thread_t thr,uint64_t *pc,uint64_t *lr,uint64_t *sp,uint64_t *fp);
void liuqin_r101_user_regs(thread_t thr,uint64_t *pc,uint64_t *lr,uint64_t *sp,uint64_t *fp) {
    arm_saved_state_t *st=thr?find_user_regs(thr):NULL;
    *pc=st?get_saved_state_pc(st):0;*lr=st?get_saved_state_lr(st):0;
    *sp=st?get_saved_state_sp(st):0;*fp=st?get_saved_state_fp(st):0;
}
''')
    machine='osfmk/kern/machine.c'
    sub(machine,'\tos_atomic_store_wide((uint64_t*)spec->ptr, timeout, relaxed);', '''\tos_atomic_store_wide((uint64_t*)spec->ptr, timeout, relaxed);
    if (!strcmp(spec->name, "lock-panic") && suffix[0] == 0) {
        extern void liuqin_r101_scale(unsigned,unsigned,uint32_t,unsigned,uint64_t,uint64_t,uint64_t);
        const uint32_t *r101_dt=NULL;unsigned r101_len=0;uint64_t r101_arg=0;
        unsigned r101_ok=chosen && SecureDTGetProperty(chosen,scale_name,(const void **)&r101_dt,&r101_len)==kSuccess;
        unsigned r101_arg_ok=PE_parse_boot_argn(boot_arg_scale_name,&r101_arg,sizeof(r101_arg));
        liuqin_r101_scale(r101_ok,r101_len,(r101_ok && r101_len==4)?*r101_dt:0,r101_arg_ok,scale,global_scale_set?global_scale:1,timeout);
    }''')
    ipc='osfmk/ipc/ipc_kmsg.c'
    sub(ipc,'\t\tliuqin_perf_record_kmsg(task_pid(current_task()), -10, (uint32_t)hdr->msgh_id);','''        extern void liuqin_r101_ipc(int,int,uint32_t,uint32_t,uint64_t,uint64_t,const void *,unsigned,unsigned);
        unsigned r101_complex=!!(hdr->msgh_bits & MACH_MSGH_BITS_COMPLEX);
        unsigned r101_len=(!r101_complex && hdr->msgh_size>sizeof(*hdr))?hdr->msgh_size-sizeof(*hdr):0;
        liuqin_r101_ipc(task_pid(current_task()),0,hdr->msgh_id,hdr->msgh_size,(uintptr_t)port,(uintptr_t)hdr->msgh_local_port,
            r101_len?ikm_udata_from_header(kmsg):NULL,r101_len,r101_complex);
\t\tliuqin_perf_record_kmsg(task_pid(current_task()), -10, (uint32_t)hdr->msgh_id);''')
    sub(ipc,'\t\t\tliuqin_perf_record_kmsg(task_pid(current_task()), lq_rpid, (uint32_t)hdr->msgh_id);','''            extern void liuqin_r101_ipc(int,int,uint32_t,uint32_t,uint64_t,uint64_t,const void *,unsigned,unsigned);
            unsigned r101_complex=!!(hdr->msgh_bits & MACH_MSGH_BITS_COMPLEX);
            unsigned r101_len=(!r101_complex && hdr->msgh_size>sizeof(*hdr))?hdr->msgh_size-sizeof(*hdr):0;
            liuqin_r101_ipc(kernel_reply?0:task_pid(current_task()),lq_rpid,hdr->msgh_id,hdr->msgh_size,(uintptr_t)port,(uintptr_t)hdr->msgh_local_port,
                r101_len?ikm_udata_from_header(kmsg):NULL,r101_len,r101_complex | (kernel_reply?2:0));
\t\t\tliuqin_perf_record_kmsg(task_pid(current_task()), lq_rpid, (uint32_t)hdr->msgh_id);''')
    io='iokit/Kernel/IOUserClient.cpp'
    sub(io,'#include <IOKit/IOService.h>','#include <IOKit/IOService.h>\n#include "../../bsd/dev/liuqin_r101.h"\nstatic void r101_matching_record(OSDictionary *, const char *);')
    # These are the three shared internals handling string, binary and OOL wrappers.
    # More generic compatibility matching call sites are recorded too, never silently excluded.
    needle='IOTaskRegistryCompatibilityMatching(current_task(), dict);'
    n=get(io).count(needle)
    sub(io,needle,needle+'\n        r101_matching_record(dict, "matching-request");',n)
    put(io,get(io)+'''
static void r101_matching_record(OSDictionary *dict,const char *op) {
    if(!dict)return;
    const char *keys[]={"IOProviderClass","IOClass","IONameMatch","IOBSDName"};
    bool found=false;
    for(unsigned i=0;i<4;i++){
        OSObject *o=dict->getObject(keys[i]);if(!o)continue;
        OSString *s=OSDynamicCast(OSString,o);
        char text[128];snprintf(text,sizeof(text),"%s=%s",keys[i],s?s->getCStringNoCopy():"<non-string>");
        liuqin_r101_iokit(op,text,s?0:1);found=true;
    }
    if(!found)liuqin_r101_iokit(op,nullptr,1);
}
''')
    patch=''.join(''.join(difflib.unified_diff(original[p].splitlines(True),changed[p].splitlines(True),fromfile='a/'+p,tofile='b/'+p)) for p in changed)
    name='zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz-liuqin-r101.patch'
    (W/'observer.patch').write_text(patch)
    for variant in ['a','b']:
        d=W/f'device-{variant}'
        if not d.is_dir():raise RuntimeError('Missing staged device')
        (d/'patches/xnu'/name).write_text(patch)
        series=d/'patches/xnu/series';s=series.read_text()
        if name not in s:s+='\n'+name+'\n'
        series.write_text(s)
        driver=d/'drivers/LiuqinSourceStorage/LiuqinScratchDisk.cpp'
        src=(R/'out/liuqin-r100-work/device/drivers/LiuqinSourceStorage/LiuqinScratchDisk.cpp').read_text()
        start=src.index('  OSDictionary *proto = OSDictionary::withCapacity(1);')
        end=src.index('  OSSafeReleaseNULL(proto);',start)+len('  OSSafeReleaseNULL(proto);')
        src=src[:start]+'#if !LQ101_CONTROL\n'+src[start:end]+'\n#endif'+src[end:]
        src='#include "R101Variant.h"\n'+src+'\n#include "R101Storage.inc"\n'
        driver.write_text(src)
        (driver.parent/'R101Variant.h').write_text('#pragma once\n#define LQ101_CONTROL '+('1' if variant=='b' else '0')+'\n')
        shutil.copy2(HERE/'kernel/R101Storage.inc',driver.parent/'R101Storage.inc')
        cfg=d/'configs/liuqin_defconfig';s=cfg.read_text().replace('CONFIG_XNU_NATIVE_LEGACY_DISPLAY=y','CONFIG_XNU_NATIVE_LEGACY_DISPLAY='+('n' if variant=='b' else 'y'));cfg.write_text(s)
    (W/'preparation.json').write_text(json.dumps({'observer_patch_sha256':sha(W/'observer.patch'),'changed_kernel_files':list(changed),'retired':{'panic_tail_r100b_bytes':16384,'panic_tail_r101_bytes':8192,'static_data_saved':8192},'normalization':'Both staged variants share r100 device sources; control disables GopFramebuffer and Internal property by configuration. Control uses common seed BOOTDATA relocation and reduced diagnostic tail; acceptance requires hardware contrast validation.','deferred':['verified bootstrap/XPC name decoder; wire capture + explicit undecoded counters implemented','A1 native walking gated; opt-in A2 raw-candidate mode uses invalid-address nonfault test and host callsite/export validation; native/target-cache validation pending'],'walker_candidates':args.walker_candidates,'hardware_booted':False},indent=2)+'\n')
    print('Prepared common observer patch',sha(W/'observer.patch'),'and A/B snapshots')
if __name__=='__main__':main()
