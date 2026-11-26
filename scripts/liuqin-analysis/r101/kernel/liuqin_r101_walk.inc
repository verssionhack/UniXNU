/* A1 stays gated. A later candidate-only build can collect raw frames for host
 * callsite validation without trusting/normalizing them in the kernel. */
#ifndef R101_CAPTURE_CANDIDATES
#define R101_CAPTURE_CANDIDATES 0
#endif
static unsigned r101_walk_remaining;
#include <vm/vm_fault_xnu.h>
#include "r101_framewalk.h"
static volatile unsigned r101_walk_validated;
struct r101_reader { vm_map_t map; unsigned attempts, unavailable; };
static int r101_read_user_frame(void *ctx,uint64_t address,uint64_t pair[2]) {
    struct r101_reader *reader=ctx;vm_map_t map=reader->map;reader->attempts++;
    if(vm_fault_get_disabled())return 1;
    vm_map_switch_context_t restore=vm_map_switch_to(map);
    vm_fault_disable();
    int error=copyin(address,pair,16);
    vm_fault_enable();
    vm_map_switch_back(restore);
    if(error)reader->unavailable++;
    return error;
}
/* No user-facing setter: a later verified existing-fixture hook must supply the
 * independently pinned expected LRs. Merely walking an arbitrary stack cannot
 * enable this gate. Never activate it from a boot argument or a guessed PC mask.
 */
int liuqin_r101_validate_walk_fixture(task_t,uint64_t,uint64_t,const uint64_t [2]);
int liuqin_r101_validate_walk_fixture(task_t task,uint64_t fp,uint64_t sp,const uint64_t expected[2]) {
    vm_map_t map;task_lock(task);map=task->map;vm_map_reference(map);task_unlock(task);
    struct r101_reader reader={.map=map};
    struct r101_frame frames[16];enum r101_walk_stop stop;
    unsigned n=r101_walk_frames(fp,sp,vm_map_min(map),vm_map_max(map),r101_read_user_frame,&reader,frames,&stop);
    uint64_t invalid[2];int invalid_rc=r101_read_user_frame(&reader,0,invalid);
    int ok=n>=2 && frames[0].lr==expected[0] && frames[1].lr==expected[1] && invalid_rc!=0;
    vm_map_deallocate(map);
    if(ok)__atomic_store_n(&r101_walk_validated,1,__ATOMIC_RELEASE);
    liuqin_r101_emit(1,"LQ101 WALK_VALIDATION: frames=%u stop=%u expected_match=%d invalid_rc=%d enabled=%d",n,stop,ok,invalid_rc,ok);
    return ok;
}
static void r101_walk_user(task_t task,uint64_t fp,uint64_t sp,uint64_t tid) {
    if(!R101_CAPTURE_CANDIDATES && !__atomic_load_n(&r101_walk_validated,__ATOMIC_ACQUIRE)){
        liuqin_r101_emit(0,"LQ101 WALK: tid=%llu status=deferred-known-user-fixture-validation",(unsigned long long)tid);return;
    }
    if(!r101_walk_remaining){liuqin_r101_emit(0,"LQ101 WALK: tid=%llu status=snapshot-frame-budget",(unsigned long long)tid);return;}
    vm_map_t map;task_lock(task);map=task->map;vm_map_reference(map);task_unlock(task);
    struct r101_reader reader={.map=map};uint64_t invalid[2];
    int invalid_rc=r101_read_user_frame(&reader,0,invalid);
    liuqin_r101_emit(0,"LQ101 WALK_VALIDATION: tid=%llu mode=raw-host-callsite-pending invalid_rc=%d enabled=0",(unsigned long long)tid,invalid_rc);
    if(!invalid_rc){vm_map_deallocate(map);return;}
    reader.attempts=reader.unavailable=0;
    struct r101_frame frames[16];enum r101_walk_stop stop;
    unsigned n=r101_walk_frames(fp,sp,vm_map_min(map),vm_map_max(map),r101_read_user_frame,&reader,frames,&stop);
    if(n>r101_walk_remaining)n=r101_walk_remaining;r101_walk_remaining-=n;
    vm_map_deallocate(map);
    for(unsigned i=0;i<n;i++)liuqin_r101_emit(0,"LQ101 FRAME: tid=%llu depth=%u fp_raw=%llx lr_raw=%llx normalized=unknown",(unsigned long long)tid,i,(unsigned long long)frames[i].fp,(unsigned long long)frames[i].lr);
    liuqin_r101_emit(0,"LQ101 WALK_READS: tid=%llu attempts=%u unavailable=%u cause=nonresident-or-unmapped target_error=0",
        (unsigned long long)tid,reader.attempts,reader.unavailable);
    liuqin_r101_emit(0,"LQ101 WALK: tid=%llu frames=%u stop=%u target_suspended=0 snapshot_racy=1",(unsigned long long)tid,n,stop);
}
