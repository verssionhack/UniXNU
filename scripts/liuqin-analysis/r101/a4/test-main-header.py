#!/usr/bin/env python3
"""Exercise the exact staged native identity parser with bounded mock reads."""
from pathlib import Path
import subprocess
R=Path(__file__).resolve().parents[4];W=R/'out/liuqin-r101-a4-work'
s=(W/'staged-sources/osfmk/kern/liuqin_r101_walk.inc').read_text();fn=s[s.index('static void r104_main_uuid('):]
prefix=r'''
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdarg.h>
#include <assert.h>
typedef struct fake_map { uint64_t min,max; } *vm_map_t;
struct fake_task { vm_map_t map; };typedef struct fake_task *task_t;
struct r101_reader { vm_map_t map;unsigned attempts,unavailable; };
static unsigned char memory[65536];static int fail_read,fail_probe;static uint64_t requested_max;static char output[1024];
#define task_lock(t) ((void)(t))
#define task_unlock(t) ((void)(t))
#define vm_map_reference(m) ((void)(m))
#define vm_map_deallocate(m) ((void)(m))
#define vm_map_min(m) ((m)->min)
#define vm_map_max(m) ((m)->max)
static int r101_read_user_frame(void *ctx,uint64_t address,uint64_t pair[2]) {
 struct r101_reader *r=ctx;r->attempts++;
 if(!address && fail_probe){memset(pair,0,16);return 0;}
 if(address+16>requested_max)requested_max=address+16;
 if(!address || fail_read || address<0x1000 || address+16>sizeof(memory)){r->unavailable++;return 14;}
 memcpy(pair,memory+address,16);return 0;
}
static void liuqin_r101_emit(int summary,const char *format,...) {
 (void)summary;va_list ap;va_start(ap,format);vsnprintf(output+strlen(output),sizeof(output)-strlen(output),format,ap);va_end(ap);
}
'''
main=r'''
static struct fake_map m={0x1000,sizeof(memory)};static struct fake_task task={&m};
static void reset(void){memset(memory,0,sizeof(memory));output[0]=0;fail_read=fail_probe=0;requested_max=0;uint32_t h[]={0xfeedfacf,0x100000c,0x80000002,2,1,24,0,0};memcpy(memory+0x1000,h,32);uint32_t c[]={0x1b,24};memcpy(memory+0x1020,c,8);for(unsigned i=0;i<16;i++)memory[0x1028+i]=i;}
int main(void){
 reset();r104_main_uuid(&task,0x1000);assert(strstr(output,"uuid=000102030405060708090a0b0c0d0e0f status=ok found=1"));
 reset();fail_read=1;r104_main_uuid(&task,0x1000);assert(strstr(output,"status=header-unavailable"));
 reset();fail_probe=1;r104_main_uuid(&task,0x1000);assert(strstr(output,"status=invalid-probe-failed"));assert(!requested_max);
 reset();r104_main_uuid(&task,UINT64_MAX-8);assert(strstr(output,"status=header-range"));
 reset();((uint32_t *)(memory+0x1000))[4]=129;r104_main_uuid(&task,0x1000);assert(strstr(output,"status=header-invalid"));assert(requested_max<=0x1020);
 reset();((uint32_t *)(memory+0x1020))[1]=32768;r104_main_uuid(&task,0x1000);assert(strstr(output,"status=command-invalid"));
 reset();((uint32_t *)(memory+0x1020))[1]=16;r104_main_uuid(&task,0x1000);assert(strstr(output,"status=uuid-size"));
 reset();((uint32_t *)(memory+0x1000))[5]=65536;r104_main_uuid(&task,0x1000);assert(strstr(output,"status=header-invalid"));
 puts("PASS: 8 native main-header parser cases");
}
'''
p=W/'test-main-header.c';p.write_text(prefix+fn+main)
subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-Wno-misleading-indentation',str(p),'-o',str(W/'test-main-header')],check=True)
subprocess.run([str(W/'test-main-header')],check=True)
