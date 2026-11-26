/* A2 read-only counters. Never alter SCTLR, target execution or legacy CPU cadence. */
struct r102_reg { uint64_t sctlr,midr,mpidr;unsigned samples,seen; };
static struct r102_reg r102_regs[8];
void liuqin_r102_cpu_readback(unsigned,uint64_t,uint64_t,uint64_t);
void liuqin_r102_cpu_readback(unsigned cpu,uint64_t sctlr,uint64_t midr,uint64_t mpidr) {
    if(cpu>=8)return;
    r102_regs[cpu].sctlr=sctlr;r102_regs[cpu].midr=midr;r102_regs[cpu].mpidr=mpidr;
    __atomic_add_fetch(&r102_regs[cpu].samples,1,__ATOMIC_RELAXED);
    __atomic_store_n(&r102_regs[cpu].seen,1,__ATOMIC_RELEASE);
}
static void r102_regs_dump(void) {
    unsigned seen=0;
    for(unsigned i=0;i<8;i++)if(__atomic_load_n(&r102_regs[i].seen,__ATOMIC_ACQUIRE)){
        seen++;struct r102_reg *r=&r102_regs[i];
        liuqin_r101_emit(1,"LQ102 SCTLR: cpu=%u mpidr=%llx midr=%llx sctlr=%llx nTWE=%u nTWI=%u samples=%u origin=cpu_init no_write=1",
            i,LQ_U64(r->mpidr),LQ_U64(r->midr),LQ_U64(r->sctlr),(unsigned)((r->sctlr>>18)&1),(unsigned)((r->sctlr>>16)&1),r->samples);
    }
    liuqin_r101_emit(1,"LQ102 SCTLR_COVERAGE: seen=%u expected=8",seen);
}
struct r102_cpu_prev { char comm[20];uint64_t total; };
struct r102_cpu_state {
    struct lq_task_snap tasks[LQ_CPU_SNAP_MAX];
    struct lq_cpu_comm work[LQ_CPU_COMM_SLOTS];
    struct r102_cpu_prev previous[LQ_CPU_COMM_SLOTS];
    uint64_t previous_ms;
};
static struct r102_cpu_state *r102_cpu;
static uint64_t r102_exit_sum_locked(void) {
    uint64_t sum=0;
    if(lq_cpu_ex_tab)for(unsigned i=0;i<LQ_CPU_COMM_SLOTS;i++)sum+=lq_cpu_ex_tab[i].exits;
    return sum;
}
static int r102_cpu_pin(const char *name) {
    return !strcmp(name,"WindowServer") || !strncmp(name,"ReportCrashServ",15) ||
        !strcmp(name,"logd_helper") || !strncmp(name,"coresymbolicatio",15);
}
static void r102_cpu_sample(uint64_t now) {
    extern unsigned liuqin_proc_cpu_snapshot(struct lq_task_snap *,unsigned);
    if(!r102_cpu)r102_cpu=kalloc_data(sizeof(*r102_cpu),Z_WAITOK|Z_ZERO);
    if(!r102_cpu){liuqin_r101_emit(1,"LQ102 CPU_COVERAGE: status=allocation-failed");return;}
    struct r102_cpu_state *s=r102_cpu;memset(s->work,0,sizeof(s->work));
    /* Independent copy only. No mutation of lq_cpu_prev_t, prev_tot, filter
     * banks or legacy 30/50s accounting. Never nest process locks with cpu_mtx. */
    lck_mtx_lock(&lq_cpu_mtx);uint64_t before=r102_exit_sum_locked(),overflow=lq_cpu_ovf;
    if(lq_cpu_ex_tab)memcpy(s->work,lq_cpu_ex_tab,sizeof(s->work));lck_mtx_unlock(&lq_cpu_mtx);
    unsigned live=liuqin_proc_cpu_snapshot(s->tasks,LQ_CPU_SNAP_MAX);
    lck_mtx_lock(&lq_cpu_mtx);uint64_t after=r102_exit_sum_locked();lck_mtx_unlock(&lq_cpu_mtx);
    if(before!=after){liuqin_r101_emit(1,"LQ102 CPU_COVERAGE: t_ms=%llu exit_race=1 skipped=1 previous_retained=1",LQ_U64(now));return;}
    for(unsigned i=0;i<LQ_CPU_COMM_SLOTS;i++)s->work[i].cur_user=s->work[i].cur_sys=s->work[i].alive=0;
    unsigned missing=0;
    for(unsigned n=0;n<live;n++){
        unsigned i;for(i=0;i<LQ_CPU_COMM_SLOTS;i++)if(!s->work[i].comm[0] || !strncmp(s->work[i].comm,s->tasks[n].comm,20))break;
        if(i==LQ_CPU_COMM_SLOTS){missing++;continue;}
        struct lq_cpu_comm *e=&s->work[i];if(!e->comm[0])strlcpy(e->comm,s->tasks[n].comm,20);
        e->cur_user+=s->tasks[n].user_ticks;e->cur_sys+=s->tasks[n].sys_ticks;e->alive++;
    }
    uint64_t sum=0;unsigned n=0;int initial=!s->previous_ms;
    for(unsigned i=0;i<LQ_CPU_COMM_SLOTS;i++){
        struct lq_cpu_comm *e=&s->work[i];if(!e->comm[0])continue;
        uint64_t total=e->ex_user+e->ex_sys+e->cur_user+e->cur_sys;
        unsigned p;for(p=0;p<LQ_CPU_COMM_SLOTS;p++)if(!s->previous[p].comm[0] || !strncmp(s->previous[p].comm,e->comm,20))break;
        if(p==LQ_CPU_COMM_SLOTS){missing++;continue;}
        uint64_t old=s->previous[p].total;e->win_ticks=(!initial && total>=old)?total-old:0;
        strlcpy(s->previous[p].comm,e->comm,20);s->previous[p].total=total;sum+=e->win_ticks;
        if(n!=i)s->work[n]=*e;n++;
    }
    for(unsigned i=0;i<n;i++)for(unsigned k=i+1;k<n;k++)if(s->work[k].win_ticks>s->work[i].win_ticks){struct lq_cpu_comm t=s->work[i];s->work[i]=s->work[k];s->work[k]=t;}
    uint64_t frq=__builtin_arm_rsr64("CNTFRQ_EL0"),dt=initial?0:now-s->previous_ms;
    liuqin_r101_emit(1,"LQ102 CPU_WINDOW: t_ms=%llu dt_ms=%llu initial=%u live=%u comms=%u missing=%u exit_overflow=%llu total_ms=%llu live_limit=%u",
        LQ_U64(now),LQ_U64(dt),initial,live,n,missing,LQ_U64(overflow),LQ_U64(frq?sum*1000/frq:0),LQ_CPU_SNAP_MAX);
    for(unsigned i=0;i<n;i++)if(i<4 || r102_cpu_pin(s->work[i].comm)){
        struct lq_cpu_comm *e=&s->work[i];
        liuqin_r101_emit(0,"LQ102 CPU_COMM: t_ms=%llu comm=%s win_ms=%llu cum_ms=%llu exits=%llu alive=%u initial=%u",
            LQ_U64(now),e->comm,LQ_U64(frq?e->win_ticks*1000/frq:0),LQ_U64(frq?(e->ex_user+e->ex_sys+e->cur_user+e->cur_sys)*1000/frq:0),LQ_U64(e->exits),e->alive,initial);
    }
    s->previous_ms=now;
}
extern void liuqin_r102_block_window(uint64_t);
static void r102_sample(uint64_t up) {
    uint64_t now=r101_ms();
    liuqin_r101_emit(1,"LQ102 MEMORY: t_ms=%llu relative_ms=%llu page_bytes=%u free=%u active=%u inactive=%u speculative=%u wired=%u coherent=0",
        LQ_U64(now),LQ_U64(up),(unsigned)PAGE_SIZE,vm_page_free_count,vm_page_active_count,vm_page_inactive_count,vm_page_speculative_count,vm_page_wire_count);
    liuqin_r102_block_window(now);
    r102_undefined_dump(now);
    if(up<=60000)r102_cpu_sample(now);
}
