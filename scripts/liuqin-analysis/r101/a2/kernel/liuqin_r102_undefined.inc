/* Count primary Unix SIGILL delivery, avoiding the later exc_crash duplicate.
 * No instruction reads, target-map locks, formatting or policy change in hook. */
void liuqin_r102_undefined(const char *,int,const char *,int,int,uint64_t,uint64_t);
void liuqin_r102_undefined(const char *stage,int pid,const char *comm,int exc,int sig,uint64_t code,uint64_t word) {
    if(!r101 || exc!=2 || sig!=4 || code!=1 || strcmp(stage,"ux_sig"))return;
    lck_spin_lock(&r101_lock);r101_inc(&r101->undefined_total);
    unsigned i;for(i=0;i<64;i++){
        struct r102_undefined *e=&r101->undefined[i];
        if(!e->count || (e->word==word && !strncmp(e->comm,comm,sizeof(e->comm)))){
            strlcpy(e->comm,comm,sizeof(e->comm));e->pid=pid;e->word=word;r101_inc(&e->count);break;
        }
    }
    if(i==64)r101_inc(&r101->undefined_overflow);
    lck_spin_unlock(&r101_lock);
}
static void r102_undefined_dump(uint64_t now) {
    struct r102_undefined *copy=r101->undefined_copy;
    lck_spin_lock(&r101_lock);memcpy(copy,r101->undefined,sizeof(r101->undefined));
    uint64_t total=r101->undefined_total,overflow=r101->undefined_overflow;
    for(unsigned i=0;i<64;i++)r101->undefined[i].previous=r101->undefined[i].count;
    lck_spin_unlock(&r101_lock);
    liuqin_r101_emit(1,"LQ102 UNDEFINED_TOTAL: t_ms=%llu events=%llu overflow=%llu stage=ux_sig exc=2 sig=4 code=1",LQ_U64(now),LQ_U64(total),LQ_U64(overflow));
    for(unsigned i=0;i<64;i++)if(copy[i].count!=copy[i].previous)
        liuqin_r101_emit(1,"LQ102 UNDEFINED: t_ms=%llu comm=%s last_pid=%d word=%llx total=%llu delta=%llu",
            LQ_U64(now),copy[i].comm,copy[i].pid,LQ_U64(copy[i].word),LQ_U64(copy[i].count),LQ_U64(copy[i].count-copy[i].previous));
}
