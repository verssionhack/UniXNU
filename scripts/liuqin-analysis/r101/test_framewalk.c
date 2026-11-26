#include "kernel/r101_framewalk.h"
#include <assert.h>
#include <stdio.h>
struct fixture { unsigned mode, reads; };
static int read_frame(void *ctx,uint64_t fp,uint64_t pair[2]) {
    struct fixture *f=ctx;f->reads++;
    if(f->mode==1)return 1;
    pair[0]=f->mode==2?fp:fp>=0x1100?0:fp+16;
    pair[1]=0x100000000ULL+fp;
    return 0;
}
int main(void){
 struct fixture f={0};struct r101_frame frames[16];enum r101_walk_stop stop;
 unsigned n=r101_walk_frames(0x1000,0x1000,0x1000,0x2000,read_frame,&f,frames,&stop);
 assert(n==16 && stop==R101_WALK_LIMIT && f.reads==16 && frames[0].lr==0x100001000ULL);
 f=(struct fixture){0};n=r101_walk_frames(0x10f0,0x1000,0x1000,0x2000,read_frame,&f,frames,&stop);
 assert(n==2 && stop==R101_WALK_END);
 f=(struct fixture){.mode=1};n=r101_walk_frames(0x1000,0x1000,0x1000,0x2000,read_frame,&f,frames,&stop);assert(n==0 && stop==R101_WALK_READ);
 f=(struct fixture){.mode=2};n=r101_walk_frames(0x1000,0x1000,0x1000,0x2000,read_frame,&f,frames,&stop);assert(n==1 && stop==R101_WALK_ORDER);
 f=(struct fixture){0};n=r101_walk_frames(0x1001,0x1000,0x1000,0x2000,read_frame,&f,frames,&stop);assert(n==0 && stop==R101_WALK_ALIGNMENT && f.reads==0);
 n=r101_walk_frames(0xffff000000001000ULL,0x1000,0x1000,0x2000,read_frame,&f,frames,&stop);assert(n==0 && stop==R101_WALK_RANGE && f.reads==0);
 n=r101_walk_frames(0xff0,0x1000,0,0x2000,read_frame,&f,frames,&stop);assert(n==0 && stop==R101_WALK_RANGE);
 puts("Frame walker host fixtures PASS; live target-map reader validation still required.");
 return 0;
}
