/* r101 observation only. This file is included once by liuqin_perf.c. */
#include <dev/liuqin_r101.h>
#include <kern/clock.h>
#include <kern/thread.h>
extern kern_return_t thread_terminate(thread_t);
#include <stdarg.h>
#define R101_RING 256u
#define R101_LAST 50u
#define R101_WRITERS 256u
#define R101_BUDGET (512u * 1024u)
#define R101_DETAIL (448u * 1024u)
#define R101_SNAPSHOT_RESERVE (96u * 1024u)
#define R101_SUMMARY_RESERVE (16u * 1024u)
enum { R101_OPEN_IN=1, R101_OPEN_OUT, R101_IPC, R101_ENOSPC, R101_IOKIT };
struct r101_event {
    uint64_t seq, ticks, tid, object, reply, request;
    int32_t pid, peer, code, error;
    uint32_t kind, size, flags;
    char comm[20], text[128];
};
_Static_assert(sizeof(struct r101_event) * R101_RING <= 65536, "r101 event ring budget");
struct r101_writer { int32_t pid; char comm[20]; uint64_t count, previous; };
struct r102_undefined { char comm[20];int32_t pid;uint64_t word,count,previous; };
struct r101_state {
    struct r101_event ring[R101_RING], opens[R101_LAST], ipc[R101_LAST];
    struct r101_writer writers[R101_WRITERS], writer_copy[R101_WRITERS];
    uint64_t ws_enospc;unsigned space_started;
    struct r102_undefined undefined[64],undefined_copy[64];
    uint64_t undefined_total,undefined_overflow;
    uint64_t head, tail, serial, drop, overwrite, trunc, suppressed, line_trunc;
    uint64_t observed, candidate, endpoint_unknown, attempted, decoded, undecoded;
    uint64_t enospc, writer_overflow, saturated, bytes, detail_bytes, summary_failed;
    uint64_t open_head, ipc_head, born, last_space, last_summary;
    uint64_t open_revision,dumped_open_revision,dumped_ipc_head;
    unsigned last_open_dump,last_ipc_dump;
    uint64_t path_epoch; unsigned paths_this_epoch, snapshots;
    int32_t ws_pid;
    thread_t snapshot_thread;
    uint64_t snapshot_lines, snapshot_hash, snapshot_failures;
    unsigned snapshots_done;
};
static struct r101_state *r101;
static lck_spin_t r101_lock;
static lck_mtx_t r101_output_lock;
static struct { unsigned seen, dt_ok, dt_len, arg; uint32_t dt_value; uint64_t scale, global, ticks; } r101_scale;
static void r101_start(void);
static void r102_regs_dump(void);
static void r101_sys_begin(proc_t, unsigned, struct liuqin_perf_call *);
static void r101_sys_end(proc_t, struct liuqin_perf_call *, int, uint64_t);

static uint64_t r101_ms(void) {
    uint64_t ns=0; absolutetime_to_nanoseconds(mach_absolute_time(), &ns); return ns/1000000ULL;
}
static void r101_inc(uint64_t *v) { if (*v==UINT64_MAX) r101->saturated=1; else ++*v; }
static int r101_ws(proc_t p) { return p && !strcmp(p->p_comm,"WindowServer"); }

extern int liuqin_r101_debug_line(const char *, int);
void liuqin_r101_emit(int summary, const char *fmt, ...) {
    if (!r101) return;
    char line[253]; va_list ap; va_start(ap,fmt); int n=vsnprintf(line,sizeof(line),fmt,ap); va_end(ap);
    if (n<0) return;
    lck_mtx_lock(&r101_output_lock);
    int snapshot=__atomic_load_n(&r101->snapshot_thread,__ATOMIC_ACQUIRE)==current_thread();
    if ((unsigned)n>=sizeof(line)) { if(snapshot)r101->snapshot_failures++; r101->line_trunc++; lck_mtx_unlock(&r101_output_lock); return; }
    uint64_t amount=(unsigned)n+1;
    uint64_t reserve=(3u-__atomic_load_n(&r101->snapshots_done,__ATOMIC_RELAXED))*R101_SNAPSHOT_RESERVE+R101_SUMMARY_RESERVE;
    /* Worker snapshots bypass the hook ring. Reserve their budget before live
     * details; no waiting, formatting or output locking occurs in hook locks. */
    if (r101->bytes+amount>R101_BUDGET ||
        (!snapshot && summary!=2 && r101->bytes+amount+reserve-R101_SUMMARY_RESERVE>R101_BUDGET) ||
        (!snapshot && !summary && (r101->bytes+amount+reserve>R101_BUDGET || r101->detail_bytes+amount>R101_DETAIL))) {
        if(snapshot)r101->snapshot_failures++;
        r101->suppressed++; if(summary)r101->summary_failed=1; lck_mtx_unlock(&r101_output_lock); return;
    }
    r101->bytes+=amount; if(!summary)r101->detail_bytes+=amount;
    /* %s formatting through the existing serial logger; <=253 bytes including newline. */
    if(snapshot || summary==2){
        line[n]='\n';
        /* This is the observer worker, after releasing task/thread/IPC locks.
         * Retry logger contention with sleep; hook-originated ring events may
         * drop, but worker evidence is never drop-new. Panic breaks the wait. */
        if(!liuqin_r101_debug_line(line,(int)amount))r101->snapshot_failures++;
        if(snapshot)for(unsigned i=0;i<amount;i++){r101->snapshot_hash^=(unsigned char)line[i];r101->snapshot_hash*=1099511628211ULL;}
        if(snapshot)r101->snapshot_lines++;
    }else liuqin_log_line("%s",line);
    lck_mtx_unlock(&r101_output_lock);
}
static void r101_clean(char *p, unsigned cap) {
    for(unsigned i=0;i<cap && p[i];i++) if((unsigned char)p[i]<32 || (unsigned char)p[i]>126)p[i]='?';
}
static void r101_push(struct r101_event *e) {
    struct r101_state *s=__atomic_load_n(&r101,__ATOMIC_ACQUIRE); if(!s)return;
    e->ticks=r101_ms();e->tid=thread_tid(current_thread());
    lck_spin_lock(&r101_lock);
    e->seq=++s->serial;
    if(s->head-s->tail==R101_RING){r101_inc(&s->drop);lck_spin_unlock(&r101_lock);return;}
    s->ring[s->head++%R101_RING]=*e;
    lck_spin_unlock(&r101_lock);
}
void liuqin_r101_scale(unsigned ok,unsigned len,uint32_t value,unsigned arg,uint64_t scale,uint64_t global,uint64_t ticks) {
    r101_scale.dt_ok=ok;r101_scale.dt_len=len;r101_scale.dt_value=value;r101_scale.arg=arg;
    r101_scale.scale=scale;r101_scale.global=global;r101_scale.ticks=ticks;__atomic_store_n(&r101_scale.seen,1,__ATOMIC_RELEASE);
}
static void r101_sys_begin(proc_t p,unsigned code,struct liuqin_perf_call *call) {
    call->r101_id=0;
    if(!r101 || !r101_ws(p))return;
    __atomic_store_n(&r101->ws_pid,proc_pid(p),__ATOMIC_RELAXED);
    if(code!=5 && code!=398 && code!=441 && code!=463 && code!=464)return;
    struct r101_event e={.kind=R101_OPEN_IN,.pid=proc_pid(p),.code=(int)code};
    e.request=(thread_tid(current_thread())<<32) ^ mach_absolute_time();call->r101_id=e.request;
    strlcpy(e.text,call->path,sizeof(e.text));e.flags=strlen(call->path)>=sizeof(e.text)-1 || call->path[0]=='<';
    r101_push(&e);
}
static void r101_sys_end(proc_t p,struct liuqin_perf_call *call,int error,uint64_t result) {
    if(!r101 || !p)return;
    if(call->r101_id){
        struct r101_event e={.kind=R101_OPEN_OUT,.pid=proc_pid(p),.code=(int)call->code,.error=error,.request=call->r101_id,.object=result};r101_push(&e);
    }
    if(error!=28)return;
    int pid=proc_pid(p);int detail=0;
    lck_spin_lock(&r101_lock);r101_inc(&r101->enospc);
    if(r101_ws(p))r101_inc(&r101->ws_enospc);
    unsigned i;for(i=0;i<R101_WRITERS;i++){
        struct r101_writer *w=&r101->writers[i];
        if(!w->count || (w->pid==pid&&!strncmp(w->comm,p->p_comm,sizeof(w->comm)))){
            w->pid=pid;strlcpy(w->comm,p->p_comm,sizeof(w->comm));r101_inc(&w->count);break;
        }
    }
    if(i==R101_WRITERS)r101_inc(&r101->writer_overflow);
    uint64_t now=mach_absolute_time(),epoch=now/(__builtin_arm_rsr64("CNTFRQ_EL0")*10);
    if(epoch!=r101->path_epoch){r101->path_epoch=epoch;r101->paths_this_epoch=0;}
    if(r101->paths_this_epoch<8){r101->paths_this_epoch++;detail=1;}
    lck_spin_unlock(&r101_lock);
    if(!detail)return;
    struct r101_event e={.kind=R101_ENOSPC,.pid=pid,.code=(int)call->code,.error=28,.peer=call->wr_code?call->wr_fd:-1};
    strlcpy(e.comm,p->p_comm,sizeof(e.comm));strlcpy(e.text,"<not-a-write-fd>",sizeof(e.text));
    if(call->wr_code){
        struct fileproc *fp=NULL;vnode_t vp=NULLVP;
        if(fp_getfvp(p,call->wr_fd,&fp,&vp)==0){
            int len=sizeof(e.text);int rc=ENOENT;
            if(vp && vnode_getwithref(vp)==0){rc=vn_getpath(vp,e.text,&len);vnode_put(vp);}
            if(rc){strlcpy(e.text,"<path-unavailable-or-truncated>",sizeof(e.text));e.flags=1;}
            fp_drop(p,call->wr_fd,fp,0);
        }else{strlcpy(e.text,"<fd-unavailable>",sizeof(e.text));e.flags=1;}
    }
    r101_push(&e);
}
void liuqin_r101_ipc(int spid,int peer,uint32_t id,uint32_t size,uint64_t object,uint64_t reply,const void *body,unsigned body_len,unsigned flags) {
    if(!r101)return;
    int ws=__atomic_load_n(&r101->ws_pid,__ATOMIC_RELAXED);
    if(!ws){proc_t p=current_proc();if(r101_ws(p)){ws=proc_pid(p);__atomic_store_n(&r101->ws_pid,ws,__ATOMIC_RELAXED);}}
    if(!ws || (spid!=ws && peer!=ws))return;
    struct r101_event e={.kind=R101_IPC,.pid=spid,.peer=peer,.code=(int32_t)id,.size=size,.object=object,.reply=reply,.flags=flags};
    unsigned n=body_len<sizeof(e.text)?body_len:sizeof(e.text);
    if(body && n)memcpy(e.text,body,n);
    e.error=(int)n;
    lck_spin_lock(&r101_lock);r101_inc(&r101->observed);
    if(peer==1 || spid==1)r101_inc(&r101->candidate);
    if(peer<0)r101_inc(&r101->endpoint_unknown);
    /* All unknown/complex layouts remain explicitly undecoded. Never scan arbitrary strings as names. */
    r101_inc(&r101->attempted);r101_inc(&r101->undecoded);
    if(body_len>sizeof(e.text)||flags)r101_inc(&r101->trunc);
    lck_spin_unlock(&r101_lock);r101_push(&e);
}
void liuqin_r101_iokit(const char *op,const char *predicate,unsigned status) {
    if(!r101 || !r101_ws(current_proc()))return;
    struct r101_event e={.kind=R101_IOKIT,.pid=proc_pid(current_proc()),.error=(int)status};
    strlcpy(e.comm,op,sizeof(e.comm));strlcpy(e.text,predicate?predicate:"<predicate-unavailable>",sizeof(e.text));
    e.flags=!predicate || strlen(predicate)>=sizeof(e.text);r101_push(&e);
}
static void r101_event_out(const struct r101_event *e,const char *scope) {
    if(e->kind==R101_IPC){
        liuqin_r101_emit(0,"LQ101 IPC: scope=%s seq=%llu t_ms=%llu tid=%llu src=%d dst=%d id=%x size=%u obj=%llx reply=%llx decode=unsupported flags=%u",
            scope,LQ_U64(e->seq),LQ_U64(e->ticks),LQ_U64(e->tid),e->pid,e->peer,(unsigned)e->code,e->size,LQ_U64(e->object),LQ_U64(e->reply),e->flags);
    }else{
        char text[sizeof(e->text)];memcpy(text,e->text,sizeof(text));text[sizeof(text)-1]=0;r101_clean(text,sizeof(text));
        liuqin_r101_emit(0,"LQ101 EVENT: scope=%s seq=%llu t_ms=%llu tid=%llu pid=%d peer=%d kind=%u code=%d err=%d req=%llx flags=%u",
            scope,LQ_U64(e->seq),LQ_U64(e->ticks),LQ_U64(e->tid),e->pid,e->peer,e->kind,e->code,e->error,LQ_U64(e->request),e->flags);
        liuqin_r101_emit(0,"LQ101 TEXT: seq=%llu comm=%s value=%s",LQ_U64(e->seq),e->comm,text);
    }
}
static void r101_drain(void) {
    for(unsigned n=0;n<R101_RING;n++){
        struct r101_event e;
        lck_spin_lock(&r101_lock);
        if(r101->tail==r101->head){lck_spin_unlock(&r101_lock);return;}
        e=r101->ring[r101->tail++%R101_RING];lck_spin_unlock(&r101_lock);
        if(e.kind==R101_OPEN_IN){r101->open_revision++;if(r101->open_head>=R101_LAST)r101->overwrite++;r101->opens[r101->open_head++%R101_LAST]=e;}
        else if(e.kind==R101_OPEN_OUT){
            int found=0;for(unsigned j=0;j<R101_LAST;j++)if(r101->opens[j].request==e.request){r101->opens[j].error=e.error;r101->opens[j].flags|=2;r101->open_revision++;found=1;break;}
            if(!found){lck_spin_lock(&r101_lock);r101_inc(&r101->overwrite);lck_spin_unlock(&r101_lock);}
        }else if(e.kind==R101_IPC){if(r101->ipc_head>=R101_LAST)r101->overwrite++;r101->ipc[r101->ipc_head++%R101_LAST]=e;}
        if(e.kind==R101_ENOSPC || e.kind==R101_IOKIT)r101_event_out(&e,"live");
    }
}
static void r101_coverage(void) {
    uint64_t obs,cand,unk,attempt,dec,undec,drop,ovw,trunc,sat,enospc,wo;
    lck_spin_lock(&r101_lock);obs=r101->observed;cand=r101->candidate;unk=r101->endpoint_unknown;attempt=r101->attempted;dec=r101->decoded;undec=r101->undecoded;drop=r101->drop;ovw=r101->overwrite;trunc=r101->trunc;sat=r101->saturated;enospc=r101->enospc;wo=r101->writer_overflow;lck_spin_unlock(&r101_lock);
    liuqin_r101_emit(1,"LQ101 COVERAGE: t_ms=%llu observed=%llu candidate=%llu endpoint_unknown=%llu attempted=%llu decoded=%llu undecoded=%llu outstanding=unknown",
        LQ_U64(r101_ms()),LQ_U64(obs),LQ_U64(cand),LQ_U64(unk),LQ_U64(attempt),LQ_U64(dec),LQ_U64(undec));
    liuqin_r101_emit(1,"LQ101 LOSS: ring_drop=%llu history_overwrite=%llu payload_trunc=%llu saturated=%llu enospc=%llu writer_overflow=%llu",
        LQ_U64(drop),LQ_U64(ovw),LQ_U64(trunc),LQ_U64(sat),LQ_U64(enospc),LQ_U64(wo));
    liuqin_r101_emit(1,"LQ101 OUTPUT: bytes=%llu detail=%llu suppressed=%llu line_trunc=%llu summary_failed=%llu budget=%u line_max=253",
        LQ_U64(r101->bytes),LQ_U64(r101->detail_bytes),LQ_U64(r101->suppressed),LQ_U64(r101->line_trunc),LQ_U64(r101->summary_failed),R101_BUDGET);
}
extern void liuqin_r101_task_waits(task_t,uint64_t);
extern void liuqin_r102_task_walk(task_t);
extern uint64_t liuqin_debug_total(void);
extern uint64_t liuqin_r102_usb_completed(void);
static void r101_snapshot(unsigned when) {
    uint64_t suppressed=r101->suppressed,trunc=r101->line_trunc;
    liuqin_r101_emit(2,"LQ101 SNAPSHOT_BEGIN: target_s=%u t_ms=%llu",when,LQ_U64(r101_ms()));
    r101->snapshot_lines=0;r101->snapshot_hash=14695981039346656037ULL;r101->snapshot_failures=0;
    __atomic_store_n(&r101->snapshot_thread,current_thread(),__ATOMIC_RELEASE);
    int pid=__atomic_load_n(&r101->ws_pid,__ATOMIC_RELAXED);proc_t p=pid?proc_find(pid):NULL;task_t task=TASK_NULL;
    if(p){if(r101_ws(p)){task=proc_task(p);if(task)task_reference(task);}proc_rele(p);}
    liuqin_r101_emit(1,"LQ101 SNAPSHOT: target_s=%u t_ms=%llu pid=%d present=%u boot_origin=hist_init",when,LQ_U64(r101_ms()),pid,task!=TASK_NULL);
    liuqin_r101_emit(1,"LQ101 SNAPSHOT_STAGE: target_s=%u stage=waits",when);
    if(task)liuqin_r101_task_waits(task,r101_ms());
    liuqin_r101_emit(1,"LQ101 SNAPSHOT_STAGE: target_s=%u stage=histories",when);
    unsigned reuse_open=(r101->last_open_dump && r101->open_revision==r101->dumped_open_revision)?r101->last_open_dump:0;
    liuqin_r101_emit(1,"LQ102 HISTORY: kind=%s n=%llu rev=%llu reuse_s=%u","open",LQ_U64(r101->open_head),LQ_U64(r101->open_revision),reuse_open);
    if(!reuse_open){
        for(unsigned i=0;i<R101_LAST;i++)if(r101->opens[i].kind)r101_event_out(&r101->opens[i],"last50-open");
        r101->dumped_open_revision=r101->open_revision;r101->last_open_dump=when;
    }
    unsigned reuse_ipc=(r101->last_ipc_dump && r101->ipc_head==r101->dumped_ipc_head)?r101->last_ipc_dump:0;
    liuqin_r101_emit(1,"LQ102 HISTORY: kind=%s n=%llu rev=%llu reuse_s=%u","ipc",LQ_U64(r101->ipc_head),LQ_U64(r101->ipc_head),reuse_ipc);
    if(!reuse_ipc){
        for(unsigned i=0;i<R101_LAST;i++)if(r101->ipc[i].kind)r101_event_out(&r101->ipc[i],"last50-ipc");
        r101->dumped_ipc_head=r101->ipc_head;r101->last_ipc_dump=when;
    }
    liuqin_r101_emit(1,"LQ101 SNAPSHOT_STAGE: target_s=%u stage=storage",when);
    liuqin_r101_storage_dump();r102_regs_dump();r101_coverage();
    liuqin_r101_emit(1,"LQ101 SNAPSHOT_STAGE: target_s=%u stage=walker-begin prefix_flush=USB-completion-required",when);
    uint64_t fence=liuqin_debug_total();unsigned waited=0;
    while(liuqin_r102_usb_completed()<fence && waited<2000){IOSleep(1);waited++;}
    /* Timeout skips first-use map switching; never sacrifice the prefix. USB
     * completion proves transfer delivery, not host filesystem persistence. */
    if(task && liuqin_r102_usb_completed()>=fence)liuqin_r102_task_walk(task);
    liuqin_r101_emit(1,"LQ102 WALK_END: target_s=%u prefix_completed=%u wait_ms=%u task=%u",when,liuqin_r102_usb_completed()>=fence,waited,task!=TASK_NULL);
    if(task)task_deallocate(task);
    __atomic_store_n(&r101->snapshot_thread,THREAD_NULL,__ATOMIC_RELEASE);__atomic_add_fetch(&r101->snapshots_done,1,__ATOMIC_RELAXED);
    liuqin_r101_emit(2,"LQ101 SNAPSHOT_END: target_s=%u lines=%llu hash=%llx complete=%u suppressed_delta=%llu trunc_delta=%llu logger_failed=%llu",
        when,LQ_U64(r101->snapshot_lines),LQ_U64(r101->snapshot_hash),
        !r101->snapshot_failures,
        LQ_U64(r101->suppressed-suppressed),LQ_U64(r101->line_trunc-trunc),LQ_U64(r101->snapshot_failures));
}
static void r101_space(void) {
    if(!rootvnode){liuqin_r101_emit(1,"LQ101 SPACE: status=root-not-ready");return;}
    vnode_t vp=NULLVP;vfs_context_t ctx=vfs_context_kernel();
    int rc=vnode_lookup("/System/Volumes/Data",0,&vp,ctx);
    if(rc || !vp){liuqin_r101_emit(1,"LQ101 SPACE: t_ms=%llu rc=%d",LQ_U64(r101_ms()),rc);return;}
    mount_t mp=vnode_mount(vp);rc=vfs_update_vfsstat(mp,ctx,VFS_KERNEL_EVENT);
    struct vfsstatfs *fs=vfs_statfs(mp);vnode_t dev=vfs_devvp(mp);dev_t device=dev?vnode_specrdev(dev):NODEV;if(dev)vnode_put(dev);
    extern int liuqin_scratch_volume(dev_t *,char *,size_t);
    dev_t expected=NODEV;char selected[64];int selected_ok=liuqin_scratch_volume(&expected,selected,sizeof(selected));
    if(!selected_ok || device!=expected){vnode_put(vp);liuqin_r101_emit(1,"LQ101 SPACE: status=Data-identity-not-ready dev=%u selected=%u",(unsigned)device,selected_ok);return;}
    liuqin_r101_emit(1,"LQ101 SPACE_ID: dev=%u bsd=%s uuid=C7D5AD67-0CE2-4AAB-BC37-BCE0F85F6720",(unsigned)device,selected);
    if(fs)liuqin_r101_emit(1,"LQ101 SPACE: t_ms=%llu dev=%u rc=%d bsize=%u blocks=%llu free=%llu avail=%llu fs=%s",
        LQ_U64(r101_ms()),(unsigned)device,rc,fs->f_bsize,LQ_U64(fs->f_blocks),LQ_U64(fs->f_bfree),LQ_U64(fs->f_bavail),fs->f_fstypename);
    vnode_put(vp);
    struct r101_writer *copy=r101->writer_copy;
    lck_spin_lock(&r101_lock);memcpy(copy,r101->writers,sizeof(r101->writers));
    uint64_t total=r101->enospc,overflow=r101->writer_overflow,ws=r101->ws_enospc;
    for(unsigned i=0;i<R101_WRITERS;i++)r101->writers[i].previous=r101->writers[i].count;lck_spin_unlock(&r101_lock);
    liuqin_r101_emit(1,"LQ102 ENOSPC_TOTAL: t_ms=%llu total=%llu writer_overflow=%llu WindowServer=%llu slots=%u",
        LQ_U64(r101_ms()),LQ_U64(total),LQ_U64(overflow),LQ_U64(ws),R101_WRITERS);
    for(unsigned i=0;i<R101_WRITERS;i++)if(copy[i].count!=copy[i].previous)
        liuqin_r101_emit(1,"LQ101 ENOSPC_COUNT: t_ms=%llu pid=%d comm=%s total=%llu delta=%llu errno=28",
            LQ_U64(r101_ms()),copy[i].pid,copy[i].comm,LQ_U64(copy[i].count),LQ_U64(copy[i].count-copy[i].previous));
}
#include "liuqin_r102_undefined.inc"
#include "liuqin_r102_sample.inc"
static void r101_worker(void *arg,wait_result_t wr) {
    (void)arg;(void)wr;static const unsigned at[]={60,120,300};
    liuqin_r101_emit(1,"LQ101 INIT: t_ms=%llu state_bytes=%lu ring_bytes=%lu decoder=wire-capture-only walker=compiled-validation-gated temperature=unavailable",
        LQ_U64(r101_ms()),(unsigned long)sizeof(*r101),(unsigned long)sizeof(r101->ring));
    if(__atomic_load_n(&r101_scale.seen,__ATOMIC_ACQUIRE)){
        liuqin_r101_emit(1,"LQ101 SCALE: dt_ok=%u len=%u dt=%u arg=%u selected=%s scale=%llu global=%llu effective_ticks=%llu",
            r101_scale.dt_ok,r101_scale.dt_len,r101_scale.dt_value,r101_scale.arg,r101_scale.arg?"boot-arg":(r101_scale.dt_ok?"chosen-dt":"other"),
            LQ_U64(r101_scale.scale),LQ_U64(r101_scale.global),LQ_U64(r101_scale.ticks));
    }else liuqin_r101_emit(1,"LQ101 SCALE: readback=missing");
    r102_regs_dump();
    liuqin_r101_emit(1,"LQ102 INIT: data_first60_ms=1000 data_later_ms=10000 block_slots=256 writer_slots=256 legacy_overflow=per-writer-window CPU=independent-comm-cumulative walker=raw-host-validation-pending");
    for(;;){
        uint64_t now=r101_ms(),up=now-r101->born;r101_drain();
        if(up-r101->last_space>=(up<=60000?1000u:10000u) || !r101->space_started){r101->space_started=1;r101->last_space=up;r101_space();r102_sample(up);}
        if(r101->snapshots<3 && up>=at[r101->snapshots]*1000ULL)r101_snapshot(at[r101->snapshots++]);
        if(up-r101->last_summary>=30000){r101->last_summary=up;r101_coverage();}
        if(up>=600000){r101_coverage();thread_terminate(current_thread());return;}
        IOSleep(250);
    }
}
static void r101_start(void) {
    if(r101)return;
    struct r101_state *s=kalloc_data(sizeof(*s),Z_WAITOK|Z_ZERO);if(!s)return;
    lck_spin_init(&r101_lock,&lq_perf_lck_grp,NULL);lck_mtx_init(&r101_output_lock,&lq_perf_lck_grp,NULL);
    s->born=r101_ms();__atomic_store_n(&r101,s,__ATOMIC_RELEASE);
    thread_t t=THREAD_NULL;kern_return_t kr=kernel_thread_start(r101_worker,NULL,&t);
    if(kr==KERN_SUCCESS)thread_deallocate(t);else liuqin_r101_emit(1,"LQ101 INIT: worker_start_rc=%d",kr);
}
