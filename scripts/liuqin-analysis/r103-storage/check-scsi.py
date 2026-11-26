#!/usr/bin/env python3
"""Run the actual staged UPIU constructor with a simulated descriptor buffer."""
from pathlib import Path
import importlib.util
import subprocess
import tempfile

HERE=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('storage_stage',HERE/'stage-storage.py')
stage=importlib.util.module_from_spec(spec);spec.loader.exec_module(stage)
source=stage.transport_source((stage.A7/'frozen-r100b-source/bsd/dev/liuqin_ufs.c').read_text())
start=source.index('static int\nufs_scsi_cmd_impl(')
end=source.index('static int\nufs_scsi_cmd(',start)
function=source[start:end]
harness=r'''
#include <stdint.h>
#include <stdbool.h>
#include <string.h>
#include <assert.h>
#include <stdio.h>
typedef uintptr_t vm_offset_t;
#define LQ_UCD_OFF 0
#define LQ_UTRL_OFF 2048
#define LQ_BUF_OFF 4096
#define LQ_BUF_SIZE 65536
#define OCS_INVALID 15
#define UTRD_HDR_READ 0x14
#define UTRD_HDR_WRITE 0x12
#define UTRD_HDR_NODATA 0x10
static bool liuqin_ufs_io_failed;
static unsigned issued,last_direction;
static void dma_wr(vm_offset_t p,unsigned off,uint32_t v){memcpy((void *)(p+off),&v,4);}
static int ufs_utrd_run(vm_offset_t u,vm_offset_t d,uint64_t pa,unsigned direction){(void)u;(void)d;(void)pa;issued++;last_direction=direction;return 0;}
'''
test=r'''
static uint32_t u32(const uint8_t *p){uint32_t v;memcpy(&v,p,4);return v;}
int main(void){
 uint8_t dma[4096+65536]={};uint8_t cdb[16]={0x28};
 assert(!ufs_scsi_cmd_impl(0,(uintptr_t)dma,0x12345678000ULL,2,cdb,10,4096,1));
 assert(last_direction==1&&dma[LQ_UTRL_OFF+3]==0x14&&dma[1]==0x40&&dma[2]==2);
 assert((u32(dma+LQ_UTRL_OFF+28)&65535)==1&&u32(dma+1036)==4095);
 assert(!memcmp(dma+16,cdb,10)&&dma[14]==16&&dma[15]==0);
 cdb[0]=0x2a;assert(!ufs_scsi_cmd_impl(0,(uintptr_t)dma,0x12345678000ULL,2,cdb,10,65536,2));
 assert(last_direction==2&&dma[LQ_UTRL_OFF+3]==0x12&&dma[1]==0x20);
 assert((u32(dma+LQ_UTRL_OFF+28)&65535)==1&&u32(dma+1036)==65535);
 assert(u32(dma+1024)==0x45679000&&u32(dma+1028)==0x123);
 cdb[0]=0x35;assert(!ufs_scsi_cmd_impl(0,(uintptr_t)dma,0,2,cdb,10,0,0));
 assert(last_direction==0&&dma[LQ_UTRL_OFF+3]==0x10&&!dma[1]);
 assert(!(u32(dma+LQ_UTRL_OFF+28)&65535));
 unsigned before=issued;assert(ufs_scsi_cmd_impl(0,(uintptr_t)dma,0,2,cdb,17,0,0));
 assert(ufs_scsi_cmd_impl(0,(uintptr_t)dma,0,2,cdb,10,65537,1));
 liuqin_ufs_io_failed=true;assert(ufs_scsi_cmd_impl(0,(uintptr_t)dma,0,2,cdb,10,0,0)&&issued==before);
 puts("PASS: actual READ/WRITE/SYNC UPIU flags, UTRD direction, PRDT length/address, CDB limits and failed-transport guard");
}
'''
with tempfile.TemporaryDirectory(prefix='liuqin-scsi-test-') as tmp:
    root=Path(tmp);path=root/'scsi.c';path.write_text(harness+function+test)
    executable=root/'scsi'
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-fsanitize=address,undefined','-g',str(path),'-o',str(executable)],check=True)
    subprocess.run([str(executable)],check=True)
