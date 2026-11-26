/* Observer delivery evidence only. No endpoint, IRQ or recovery policy. */
#ifndef LIUQIN_R103_USB_FENCE_H
#define LIUQIN_R103_USB_FENCE_H
struct r103_usb_fence { uint64_t pending,completed;unsigned lost; };
static inline void r103_fence_lost(struct r103_usb_fence *s) {
    __atomic_store_n(&s->lost,1,__ATOMIC_RELEASE);
}
static inline void r103_fence_ring(struct r103_usb_fence *s,uint64_t cursor) {
    __atomic_store_n(&s->pending,cursor,__ATOMIC_RELEASE);
}
static inline void r103_fence_note(struct r103_usb_fence *s,int takeover) {
    if(takeover)r103_fence_lost(s);
    __atomic_store_n(&s->pending,0,__ATOMIC_RELEASE);
}
static inline void r103_fence_complete(struct r103_usb_fence *s,unsigned left,unsigned bus_error) {
    uint64_t cursor=__atomic_exchange_n(&s->pending,0,__ATOMIC_ACQ_REL);
    if(bus_error || (cursor && left))r103_fence_lost(s);
    else if(cursor)__atomic_store_n(&s->completed,cursor,__ATOMIC_RELEASE);
}
static inline void r103_fence_copy(struct r103_usb_fence *s,uint64_t before,uint64_t after,unsigned copied) {
    if(after-before!=copied)r103_fence_lost(s);
}
static inline uint64_t r103_fence_value(struct r103_usb_fence *s) {
    if(__atomic_load_n(&s->lost,__ATOMIC_ACQUIRE))return 0;
    uint64_t cursor=__atomic_load_n(&s->completed,__ATOMIC_ACQUIRE);
    return __atomic_load_n(&s->lost,__ATOMIC_ACQUIRE)?0:cursor;
}
#endif
