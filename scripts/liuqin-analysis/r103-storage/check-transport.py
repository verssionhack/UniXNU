#!/usr/bin/env python3
"""Exercise the production Data transport against a sparse simulated UFS LUN."""
from pathlib import Path
import subprocess
import tempfile

HERE=Path(__file__).resolve().parent
HARNESS=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <openssl/sha.h>
#define ROOT_LBA_BYTES 4096
#define LQ_BUF_SIZE 65536
#define LQ_UCD_OFF 0
#define LQ_UTRL_OFF 2048
#define LQ_BUF_OFF 4096
#define Z_WAITOK 0
#define Z_ZERO 1
static void *kalloc_data(size_t n,int flags){return flags&1?calloc(1,n):malloc(n);}
static void kfree_data(void *p,size_t n){(void)n;free(p);}
static void lck_mtx_lock(void *p){(void)p;}
static void lck_mtx_unlock(void *p){(void)p;}
static uint8_t dma[4096+LQ_BUF_SIZE];
static struct {int ready;unsigned block_size,lun;uint64_t block_count,dma_pa;uintptr_t dma,ufs;} ufs_state={1,4096,0,64000000,0,(uintptr_t)dma,0};
static void *ufs_lock=(void *)1;
static struct {uint64_t first_lba,last_lba,image_bytes;} root_state={10000,60000000,17466130432ULL};
static int mode=0, writes=0, syncs=0, bad=0;
static int PE_parse_boot_argn(const char *name,unsigned *v,unsigned n){assert(!strcmp(name,"liuqin-data")&&n==4);*v=mode;return 1;}
static int liuqin_ufs_root_ready(void){return 1;}
struct page{uint64_t lba;uint8_t data[4096];};
static struct page pages[64];static unsigned used;
static uint8_t *page(uint64_t lba){for(unsigned i=0;i<used;i++)if(pages[i].lba==lba)return pages[i].data;assert(used<64);pages[used].lba=lba;return pages[used++].data;}
static int liuqin_ufs_block_read(uint64_t lba,unsigned n,void *p){for(unsigned i=0;i<n;i++)memcpy((uint8_t *)p+4096*i,page(lba+i),4096);return 0;}
static int ufs_scsi_cmd(uintptr_t u,uintptr_t d,uint64_t pa,unsigned lun,const uint8_t *c,unsigned cdb_len,unsigned bytes,unsigned direction){
 (void)u;(void)d;(void)pa;(void)lun;assert(cdb_len==10);
 memset(dma+512,0,32);dma[512]=0x21;memset(dma+LQ_UTRL_OFF+8,0,4);
 if(bad){dma[519]=2;return 0;}
 if(c[0]==0x35){assert(!bytes&&!direction);syncs++;return 0;}
 assert(c[0]==0x2a&&direction==2);
 uint64_t lba=((uint32_t)c[2]<<24)|((uint32_t)c[3]<<16)|((uint32_t)c[4]<<8)|c[5];
 unsigned blocks=((unsigned)c[7]<<8)|c[8];assert(bytes==blocks*4096);
 // Reject every attempted write outside this test's metadata/data allocations.
 uint64_t meta=(((root_state.image_bytes+1048575)&~1048575ULL)+(128ULL<<20))/4096+root_state.first_lba;
 uint64_t first=meta+256;
 uint64_t end=root_state.last_lba+1-(64ULL<<20)/4096;
 assert((lba==meta&&blocks==1)||(lba>=first&&lba<end&&blocks<=end-lba));
 for(unsigned i=0;i<blocks;i++)memcpy(page(lba+i),dma+LQ_BUF_OFF+i*4096,4096);
 writes++;return 0;
}
'''
TEST=r'''
int main(void){
 uint8_t seed[32]={1};uint64_t bytes=0;int init=0;
 assert(liuqin_data_open(seed,&bytes,&init)!=0&&!writes); // no initialization permission
 memcpy(page(lq_data.meta_lba),"old HTML",8);
 mode=2;assert(liuqin_data_open(seed,&bytes,&init)!=0&&!writes); // conservative mode preserves foreign bytes
 mode=3;
 assert(!liuqin_data_open(seed,&bytes,&init)&&init&&writes==1); // explicit first format
 mode=2;assert(!liuqin_data_open(seed,&bytes,&init)&&init&&bytes==(root_state.last_lba+1-(64ULL<<20)/4096-lq_data.first_lba)*4096);
 assert(writes==1&&syncs==1); // only the allocation marker
 uint8_t a[8192],b[8192];memset(a,0xa5,sizeof(a));
 int before=writes;
 assert(liuqin_data_io(bytes-512,a,1024,1)!=0);
 assert(liuqin_data_io(UINT64_MAX-511,a,512,1)!=0);
 assert(liuqin_data_io(1,a,512,1)!=0);
 assert(liuqin_data_io(0,NULL,512,1)!=0&&writes==before);
 assert(!liuqin_data_io(512,a,512,1));
 assert(!liuqin_data_io(0,b,4096,0));
 for(unsigned i=0;i<4096;i++)assert(b[i]==(i>=512&&i<1024?0xa5:0));
 assert(!liuqin_data_io(4096,a,4608,1));
 assert(!liuqin_data_io(4096,b,4608,0)&&!memcmp(a,b,4608));
 assert(!liuqin_data_finish()&&!lq_data.initializing);
 mode=1;before=writes;
 assert(!liuqin_data_open(seed,&bytes,&init)&&!init&&writes==before); // reopen preserves data
 mode=3;assert(!liuqin_data_open(seed,&bytes,&init)&&!init&&writes==before); // format does not erase a completed store
 bad=1;assert(liuqin_data_io(0,a,4096,1)!=0);assert(liuqin_data_sync()!=0);bad=0;
 uint8_t other[32]={2};assert(liuqin_data_open(other,&bytes,&init)!=0&&writes==before);
 page(lq_data.meta_lba)[100]^=1;
 mode=3;
 assert(liuqin_data_open(seed,&bytes,&init)!=0&&writes==before); // corrupt marker never formats
 puts("PASS: allocation guards, sub-block RMW, multi-block I/O, cache flush, reopen, failures, seed identity and marker corruption");
}
'''
with tempfile.TemporaryDirectory(prefix='liuqin-data-test-') as tmp:
    root=Path(tmp)
    source=root/'transport.c'
    source.write_text(HARNESS+'\n'+(HERE/'LiuqinDataTransport.inc').read_text()+'\n'+TEST)
    executable=root/'transport'
    subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror','-Wno-deprecated-declarations','-fsanitize=address,undefined','-g',str(source),'-lcrypto','-o',str(executable)],check=True)
    subprocess.run([str(executable)],check=True)
