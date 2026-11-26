#!/usr/bin/env python3
"""Compile and exercise the actual native A5 reader with sparse nonfault mocks."""
from pathlib import Path
import subprocess
R=Path(__file__).resolve().parents[4];H=Path(__file__).resolve().parent;W=R/'out/liuqin-r101-a5r1-work'
prefix=r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
#include <assert.h>
struct fake_map { uint64_t min,max; };typedef struct fake_map *vm_map_t;
struct fake_task { uint64_t task_shared_region_slide;unsigned char task_shared_region_uuid[16];vm_map_t map; };typedef struct fake_task *task_t;
struct r101_reader { vm_map_t map;unsigned attempts,unavailable; };
#define task_lock(t) ((void)(t))
#define task_unlock(t) ((void)(t))
#define vm_map_reference(m) ((void)(m))
#define vm_map_deallocate(m) ((void)(m))
#define vm_map_min(m) ((m)->min)
#define vm_map_max(m) ((m)->max)
static char logtext[32768];static unsigned reads,read_zero,read_outside;static int probe_success,fail_reads,bad_pointer;
static int r101_read_user_frame(void *ctx,uint64_t a,uint64_t p[2]) {
 struct r101_reader *r=ctx;r->attempts++;reads++;p[0]=p[1]=0;
 if(!a){read_zero++;return probe_success?0:14;}
 if(a<0x1000 || a>(1ULL<<39)-16)read_outside++;
 if(fail_reads){r->unavailable++;return 14;}
 if(a==0x10006e0a0ULL)p[0]=bad_pointer?0xffffffffffff0000ULL:0x10000;
 if(a==0x10006e1a0ULL)p[0]=0x20000;
 if(a==0x10006e180ULL)p[0]=0x30000;
 if(a==0x20010 || a==0x30010)p[1]=0x40000;
 if(a==0x20020 || a==0x30020)p[1]=0x50000;
 return 0;
}
static void liuqin_r101_emit(int summary,const char *fmt,...) {
 (void)summary;va_list ap;va_start(ap,fmt);size_t n=strlen(logtext);vsnprintf(logtext+n,sizeof(logtext)-n,fmt,ap);va_end(ap);strcat(logtext,"\n");
}
'''
main=r'''
static struct fake_map m={0x1000,1ULL<<39};static struct fake_task t;
static void reset(void){memset(&t,0,sizeof(t));unsigned char id[16]={0x8b,0x1e,0x17,0xc6,0x72,0xd6,0x30,0x17,0x91,0xa4,0x91,0x60,0x22,0xe3,0x61,0x2e};memcpy(t.task_shared_region_uuid,id,16);t.task_shared_region_slide=0x1000;t.map=&m;reads=read_zero=read_outside=0;probe_success=fail_reads=bad_pointer=0;logtext[0]=0;}
int main(void){
 reset();r105_state(&t,0x100000000);assert(strstr(logtext,"STATE_END: status=recorded"));assert(r105_requests<=64 && reads<=65 && !read_outside && read_zero==1);assert(strstr(logtext,"key=CNA2"));assert(strstr(logtext,"key=GNS1"));
 reset();probe_success=1;r105_state(&t,0x100000000);assert(reads==1 && !strstr(logtext,"STATE_WORD:"));
 reset();t.task_shared_region_uuid[0]^=1;r105_state(&t,0x100000000);assert(!reads && strstr(logtext,"cache-identity-mismatch"));
 reset();fail_reads=1;r105_state(&t,0x100000000);assert(strstr(logtext,"key=DAEMON addr=10006e0a0 rc=14"));assert(!strstr(logtext,"key=D0"));
 reset();bad_pointer=1;r105_state(&t,0x100000000);assert(strstr(logtext,"key=D0 addr=ffffffffffff0000 rc=22"));assert(!read_outside);
 puts("PASS: native state budget, invalid probe, cache identity, unavailable and unmasked bad pointer");
}
'''
p=W/'test-state-reader.c';p.write_text(prefix+(H/'state-reader.inc').read_text()+main)
subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-Wno-misleading-indentation',str(p),'-o',str(W/'test-state-reader')],check=True);subprocess.run([str(W/'test-state-reader')],check=True)
