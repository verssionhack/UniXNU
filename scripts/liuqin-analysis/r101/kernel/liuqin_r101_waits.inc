/* Included by osfmk/kern/thread.c: native layout and lifetime rules, no target suspension.
 * Lock-order table (each row is an independent phase):
 * task_lock       -> retain threads/map; release before thread/IPC/output locks
 * splsched/thread -> copy state, io_reference only; release before port/waitq
 * port/waitq      -> inspect retained object; release before output
 * target-map read -> observer thread only, faults disabled, no above locks
 * output mutex    -> logger append/retry; no task/thread/IPC/spin locks held
 * hook spinlock   -> bounded copy/counters only; never output or sleep
 */
#include "../../bsd/dev/liuqin_r101.h"
#include <vm/vm_shared_region_xnu.h>
#include <ipc/ipc_pset.h>
#include <ipc/ipc_space.h>
#include "liuqin_r101_walk.inc"
extern void liuqin_r101_user_regs(thread_t,uint64_t *,uint64_t *,uint64_t *,uint64_t *);
void liuqin_r101_task_waits(task_t task,uint64_t ms);
void liuqin_r101_task_waits(task_t task,uint64_t ms) {
    enum { MAX_THREADS=64 };
    r101_walk_remaining=64; /* 16/depth, 64 raw candidate frames/snapshot total. */
    thread_t *list=kalloc_data(MAX_THREADS*sizeof(*list),Z_WAITOK|Z_ZERO);
    if(!list){liuqin_r101_emit(1,"LQ101 WAIT_COVERAGE: error=allocation");return;}
    unsigned n=0,total=0;thread_t th;uint64_t base=0,slide=0;unsigned char uuid[16];
    task_lock(task);
    slide=task->task_shared_region_slide;memcpy(uuid,task->task_shared_region_uuid,sizeof(uuid));
    if(task->shared_region)base=task->shared_region->sr_base_address;
    queue_iterate(&task->threads,th,thread_t,task_threads){
        total++;if(n<MAX_THREADS){thread_reference(th);list[n++]=th;}
    }
    task_unlock(task);
    _Static_assert(MACH_VM_MAX_ADDRESS==0x8000000000ULL,"r101 VA width requires native BCM2837 39-bit user range");
    vm_map_t map;task_lock(task);map=task->map;vm_map_reference(map);task_unlock(task);
    liuqin_r101_emit(1,"LQ101 USER_MAP: min=%llx max=%llx machine_max=%llx va_bits=39 source=BCM2837-native-4k-TTBR0 verify_machine_max=1",
        (unsigned long long)vm_map_min(map),(unsigned long long)vm_map_max(map),(unsigned long long)MACH_VM_MAX_ADDRESS);
    vm_map_deallocate(map);
    char id[33];for(unsigned i=0;i<16;i++)snprintf(id+2*i,3,"%02x",uuid[i]);id[32]=0;
    liuqin_r101_emit(1,"LQ101 SHARED_REGION: base=%llx slide=%llx uuid=%s pc_normalization=native_saved_state raw_mask=none",
        (unsigned long long)base,(unsigned long long)slide,id);
    for(unsigned i=0;i<n;i++){
        th=list[i];uint64_t tid,event,wq,deadline=0,pc=0,lr=0,sp=0,fp=0;
        unsigned state,hint,armed;mach_msg_option64_t option=0;mach_msg_return_t receive=0;ipc_object_t object=IPC_OBJECT_NULL;
        spl_t level=splsched();thread_lock(th);
        tid=thread_tid(th);state=th->state;hint=th->block_hint;event=th->wait_event;wq=(uint64_t)th->waitq.wq_q;
        armed=th->wait_timer_armed;
        if(armed && th->wait_timer)deadline=__atomic_load_n(&th->wait_timer->tc_soft_deadline,__ATOMIC_RELAXED);
        /* The receive continuation holds this object's reference. While TH_WAIT
         * and receive-state agree under thread_lock, retain it before unlocking.
         * Never take a port/waitq lock while holding thread_lock (reverse order).
         */
        if((state&TH_WAIT) && (hint==kThreadWaitPortReceive || hint==kThreadWaitPortSetReceive)){
            option=th->ith_option;receive=th->ith_state;
            if((receive==MACH_RCV_IN_PROGRESS || receive==MACH_RCV_IN_PROGRESS_TIMED) && th->ith_object!=IPC_OBJECT_NULL){
                object=th->ith_object;io_reference(object);
            }
        }
        if((state&TH_WAIT) && !(state&TH_RUN))liuqin_r101_user_regs(th,&pc,&lr,&sp,&fp);
        thread_unlock(th);splx(level);
        const char *mode=armed?(deadline?"timed":"unknown"):((object!=IPC_OBJECT_NULL && !(option&MACH_RCV_TIMEOUT))?"indefinite":"unknown");
        liuqin_r101_emit(0,"LQ101 WAIT: t_ms=%llu tid=%llu state=%x hint=%u event=%llx waitq=%llx receive=%x mode=%s",
            (unsigned long long)ms,(unsigned long long)tid,state,hint,(unsigned long long)event,(unsigned long long)wq,receive,mode);
        liuqin_r101_emit(0,"LQ101 DEADLINE: tid=%llu armed=%u deadline=%llu clock=mach_absolute snapshot=%llu best_effort=1",
            (unsigned long long)tid,armed,(unsigned long long)deadline,(unsigned long long)mach_absolute_time());
        int owner=-1;unsigned type=0;uint64_t name=0;int active=0;
        if(object!=IPC_OBJECT_NULL){
            if(io_lock_allow_invalid(object)){
                type=io_type(object);active=io_state_active(object->io_state);
                if(io_is_any_port(object)){
                    ipc_port_t port=(ipc_port_t)object;
                    if(ip_active(port) && ip_in_a_space(port) && !ip_in_space(port,ipc_space_kernel)){
                        ipc_space_t space=ip_get_receiver(port);if(space && is_active(space))owner=task_pid(space->is_task);
                        name=port->ip_receiver_name;
                    }else if(ip_in_space(port,ipc_space_kernel))owner=0;
                }
                io_unlock(object);
            }
            liuqin_r101_emit(0,"LQ101 WAIT_OBJECT: tid=%llu obj=%llx type=%u active=%d receiver_pid=%d receive_name=%llx set_ownership=unknown",
                (unsigned long long)tid,(unsigned long long)(uintptr_t)object,type,active,owner,(unsigned long long)name);
            io_release(object);
        }else liuqin_r101_emit(0,"LQ101 WAIT_OBJECT: tid=%llu object=unknown ownership=unknown",(unsigned long long)tid);
        liuqin_r101_emit(0,"LQ101 USER_STATE: tid=%llu pc=%llx lr=%llx sp=%llx fp=%llx frame_reader=native_nofault running=%u",
            (unsigned long long)tid,(unsigned long long)pc,(unsigned long long)lr,(unsigned long long)sp,(unsigned long long)fp,!!(state&TH_RUN));
        if(pc && sp)r101_walk_user(task,fp,sp,tid);
        else liuqin_r101_emit(0,"LQ101 WALK: tid=%llu status=user-state-unavailable",(unsigned long long)tid);
        thread_deallocate(th);
    }
    kfree_data(list,MAX_THREADS*sizeof(*list));
    liuqin_r101_emit(1,"LQ101 WAIT_COVERAGE: total=%u captured=%u truncated=%u stack_validation=pending no_lookup_inference=forbidden",total,n,total-n);
}
