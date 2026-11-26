#include <stdint.h>
#include <assert.h>
#include <stdio.h>
#include "kernel/liuqin_r103_usb_fence.h"
int main(void) {
 struct r103_usb_fence s={0};
 r103_fence_ring(&s,100);assert(!r103_fence_value(&s));
 r103_fence_complete(&s,0,0);assert(r103_fence_value(&s)==100);
 r103_fence_ring(&s,200);r103_fence_complete(&s,0,1);assert(!r103_fence_value(&s));
 r103_fence_ring(&s,300);r103_fence_complete(&s,0,0);assert(!r103_fence_value(&s));
 s=(struct r103_usb_fence){0};r103_fence_ring(&s,100);r103_fence_complete(&s,1,0);assert(!r103_fence_value(&s));
 r103_fence_ring(&s,200);r103_fence_complete(&s,0,0);assert(!r103_fence_value(&s));
 s=(struct r103_usb_fence){0};r103_fence_ring(&s,100);r103_fence_note(&s,1);r103_fence_complete(&s,0,0);assert(!s.completed&&!r103_fence_value(&s));
 s=(struct r103_usb_fence){0};r103_fence_ring(&s,100);r103_fence_complete(&s,0,0);r103_fence_note(&s,0);r103_fence_complete(&s,0,0);assert(r103_fence_value(&s)==100);
 r103_fence_copy(&s,100,150,50);assert(r103_fence_value(&s)==100);
 r103_fence_copy(&s,150,150,0);assert(r103_fence_value(&s)==100);
 r103_fence_copy(&s,150,300,50);assert(!r103_fence_value(&s));
 s=(struct r103_usb_fence){0};r103_fence_lost(&s);r103_fence_ring(&s,100);r103_fence_complete(&s,0,0);assert(!r103_fence_value(&s));
 puts("PASS: full/short/error completion, sticky loss, takeover, ordinary notes, gap, copy contention, explicit failure");
}
