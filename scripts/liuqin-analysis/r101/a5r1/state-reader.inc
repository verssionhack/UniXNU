/* A5: fixed scalar reads only; no target calls/writes, faults or suspension.
 * Host-qualified offsets/semantics: liuqin-r101-a5-host-audit.md.
 * At most 64 attempts / 1024 bytes per snapshot; failed reads remain unknown.
 * Strong pointers are range/alignment checked unchanged, never trial-masked.
 */
static unsigned r105_requests;
static int r105_piece(struct r101_reader *r,const char *key,uint64_t address,uint64_t out[2]) {
    out[0]=out[1]=0;int rc=22;
    if(++r105_requests<=64 && address>=vm_map_min(r->map) && address<=vm_map_max(r->map)-16 && !(address&7))
        rc=r101_read_user_frame(r,address,out);
    liuqin_r101_emit(1,"LQ102 STATE_WORD: key=%s addr=%llx rc=%d a=%llx b=%llx",key,(unsigned long long)address,rc,(unsigned long long)out[0],(unsigned long long)out[1]);
    return rc;
}
static void r105_collection(struct r101_reader *r,const char *key,uint64_t p,unsigned pairs) {
    if(!p)return;
    for(unsigned i=0;i<pairs;i++){
        uint64_t v[2];char label[20];snprintf(label,sizeof(label),"%s%u",key,i);
        if(r105_piece(r,label,p+i*16,v))break;
    }
}
static void r105_notifier(struct r101_reader *r,const char *key,uint64_t p) {
    if(!p)return;
    uint64_t v[2],matched=0,pending=0;char label[20];
    for(unsigned i=0;i<4;i++){
        snprintf(label,sizeof(label),"%s%u",key,i);
        if(r105_piece(r,label,p+(i==3?40:i*16),v))return;
        if(i==1)matched=v[1];if(i==2)pending=v[1];
    }
    snprintf(label,sizeof(label),"%sS",key);r105_collection(r,label,matched,2);
    snprintf(label,sizeof(label),"%sA",key);r105_collection(r,label,pending,3);
}
static void r105_state(task_t task,uint64_t base) {
    uint64_t slide;unsigned char uuid[16];vm_map_t map;
    task_lock(task);slide=task->task_shared_region_slide;memcpy(uuid,task->task_shared_region_uuid,16);map=task->map;vm_map_reference(map);task_unlock(task);
    const unsigned char expected[16]={0x8b,0x1e,0x17,0xc6,0x72,0xd6,0x30,0x17,0x91,0xa4,0x91,0x60,0x22,0xe3,0x61,0x2e};
    if(memcmp(uuid,expected,16)){liuqin_r101_emit(1,"LQ102 STATE_END: status=cache-identity-mismatch");vm_map_deallocate(map);return;}
    struct r101_reader r={.map=map};r105_requests=0;uint64_t invalid[2];int probe=r101_read_user_frame(&r,0,invalid);
    liuqin_r101_emit(1,"LQ102 STATE_BEGIN: version=6 main=%llx shared_slide=%llx invalid_rc=%d cap=64 target_suspended=0",(unsigned long long)base,(unsigned long long)slide,probe);
    if(!probe){vm_map_deallocate(map);return;}
    uint64_t v[2],daemon=0,clock=0,gptp=0;
    if(!r105_piece(&r,"DAEMON",base+0x6e0a0,v))daemon=v[0];
    static const struct { const char *key;uint64_t address; } globals[]={
        {"GPTY",0x6e180},{"GPTQ",0x6e190},{"CLKY",0x6e1a0},{"CLKQ",0x6e1b0},
        {"NOTQ",0x6e0d8},{"ISAM",0x180447ba8},{"ISAV",0x180447bb8},
        {"ARRIV",0x1eb1deb78},{"SETIV",0x1eb1dee90}};
    for(unsigned i=0;i<sizeof(globals)/sizeof(globals[0]);i++){
        int rc=r105_piece(&r,globals[i].key,globals[i].address+(i<5?base:slide),v);
        if(!rc && i==0)gptp=v[0];if(!rc && i==2)clock=v[0];
    }
    if(daemon && !r105_piece(&r,"D0",daemon,v) && !r105_piece(&r,"D1",daemon+8,v)){
        uint64_t server=v[1];
        r105_collection(&r,"SV",server,2);
        r105_piece(&r,"D1_END",daemon+8,v);
    }
    r105_notifier(&r,"CN",clock);r105_notifier(&r,"GN",gptp);
    r105_piece(&r,"DAEMON_END",base+0x6e0a0,v);
    r105_piece(&r,"CLKY_END",base+0x6e1a0,v);r105_piece(&r,"GPTY_END",base+0x6e180,v);
    liuqin_r101_emit(1,"LQ102 STATE_END: status=recorded requests=%u attempts=%u unavailable=%u budget=64 snapshot_racy=1",r105_requests,r.attempts,r.unavailable);
    vm_map_deallocate(map);
}
