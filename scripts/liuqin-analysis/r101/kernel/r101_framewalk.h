#ifndef R101_FRAMEWALK_H
#define R101_FRAMEWALK_H
#include <stdint.h>
#include <stddef.h>
enum r101_walk_stop { R101_WALK_END, R101_WALK_LIMIT, R101_WALK_RANGE, R101_WALK_ALIGNMENT, R101_WALK_ORDER, R101_WALK_READ };
struct r101_frame { uint64_t fp, lr; };
typedef int (*r101_read_frame_fn)(void *,uint64_t,uint64_t [2]);
static unsigned r101_walk_frames(uint64_t fp,uint64_t sp,uint64_t low,uint64_t high,r101_read_frame_fn read,void *ctx,struct r101_frame frames[16],enum r101_walk_stop *stop) {
    unsigned n=0;*stop=R101_WALK_END;
    while(fp && n<16){
        if(high<16 || fp<low || fp>high-16 || fp<sp || fp-sp>(8ULL<<20)){*stop=R101_WALK_RANGE;break;}
        if(fp&15){*stop=R101_WALK_ALIGNMENT;break;}
        uint64_t pair[2];if(read(ctx,fp,pair)){*stop=R101_WALK_READ;break;}
        frames[n++]=(struct r101_frame){fp,pair[1]};
        if(!pair[0]){fp=0;break;}
        if(pair[0]<=fp){*stop=R101_WALK_ORDER;break;}
        fp=pair[0];
    }
    if(fp && n==16)*stop=R101_WALK_LIMIT;
    return n;
}
#endif
