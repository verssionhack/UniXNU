#!/usr/bin/env python3
"""Exercise the generated signed-helper installer with a simulated vnode API."""
from pathlib import Path
import importlib.util
import subprocess
import tempfile

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('stage', HERE / 'stage-storage.py')
stage = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stage)
source = stage.mount_probe_source(
    (stage.A7 / 'frozen-r100b-source/bsd/kern/liuqin_mount_probe.h').read_text()
).replace('#include "liuqin_mount_payload.h"', '')
harness = r'''
#include <openssl/sha.h>
#include <cassert>
#include <cerrno>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fcntl.h>
#include <sys/types.h>
using proc_t=int; using user_addr_t=uintptr_t; using vfs_context_t=int;
using mount_t=int;
struct node { int mount=1, type=1; } dir, helper;
using vnode_t=node*;
#define NULLVP nullptr
#define LQ_DATA "/Data"
#define MNT_RDONLY 1
#define MNT_WAIT 0
#define VREG 1
#define FREAD 0x100000
#define FWRITE 0x200000
#define UIO_WRITE 1
#define UIO_READ 0
#define UIO_SYSSPACE 0
#define IO_UNIT 0
#define Z_WAITOK 0
#define VNODE_LOOKUP_NOFOLLOW_ANY 0
struct vnode_attr { unsigned va_uid=0,va_gid=0,va_mode=0755; size_t va_data_size=0; } attrs;
#define VATTR_INIT(a) (*(a)=vnode_attr{})
#define VATTR_SET(a,k,v) ((a)->k=(v))
#define VATTR_WANTED(a,k) ((void)0)
#define VATTR_NOT_RETURNED(a,k) false
struct mkdir_args { user_addr_t path; int mode; };
static const unsigned char lq_probe_bytes[]={1,2,3,4,5};
static unsigned char lq_probe_sha[32], content[64];
static size_t length; static bool exists,persistent=true; static int writes;
int liuqin_data_persistent(){return persistent;}
int vfs_context_current(){return 0;}
int vfs_context_ucred(int){return 0;}
int vnode_lookup(const char* p,int,vnode_t* v,int){*v=strcmp(p,LQ_DATA)?&helper:&dir;return 0;}
int vnode_mount(vnode_t v){return v->mount;}
int vnode_vtype(vnode_t v){return v->type;}
int vfs_flags(int){return 0;}
void vnode_put(vnode_t){}
int copyout(const void*,uintptr_t,size_t){return 0;}
int mkdir(int,mkdir_args*,int32_t*){return EEXIST;}
int lq_layout_bind(const char*,const char*,int,int){return 0;}
int vnode_open(const char*,int flags,int,int,vnode_t* v,int){
 if(flags&O_CREAT){if(exists)return EEXIST;exists=true;}
 *v=&helper;return 0;
}
int vnode_close(vnode_t,int,int){return 0;}
int vn_rdwr(int op,vnode_t,char* b,unsigned n,unsigned off,int,int,int,int*,int){
 if(op==UIO_WRITE){memcpy(content+off,b,n);length=off+n;writes++;}
 else memcpy(b,content+off,n);return 0;
}
int vnode_setattr(vnode_t,vnode_attr* a,int){attrs=*a;length=a->va_data_size;return 0;}
int vnode_getattr(vnode_t,vnode_attr* a,int){*a=attrs;return 0;}
int VNOP_FSYNC(vnode_t,int,int){return 0;}
int vnode_size(vnode_t,off_t* s,int){*s=length;return 0;}
uint8_t* kalloc_data(size_t n,int){return static_cast<uint8_t*>(malloc(n));}
void kfree_data(void* p,size_t){free(p);}
'''
test = r'''
int main(){
 SHA256(lq_probe_bytes,sizeof(lq_probe_bytes),lq_probe_sha);
 assert(!liuqin_mount_probe_prepare(0,0)&&writes==1);
 assert(!liuqin_mount_probe_prepare(0,0)&&writes==1);
 content[0]^=1;assert(liuqin_mount_probe_prepare(0,0)==EIO&&writes==1);content[0]^=1;
 length--;assert(liuqin_mount_probe_prepare(0,0)==EIO);length++;
 attrs.va_uid=1;assert(liuqin_mount_probe_prepare(0,0)==EINVAL);attrs.va_uid=0;
 attrs.va_mode=0777;assert(liuqin_mount_probe_prepare(0,0)==EINVAL);attrs.va_mode=0755;
 helper.mount=2;assert(liuqin_mount_probe_prepare(0,0)==EXDEV);helper.mount=1;
 helper.type=2;assert(liuqin_mount_probe_prepare(0,0)==EXDEV);helper.type=1;
 persistent=false;assert(liuqin_mount_probe_prepare(0,0)==EEXIST&&writes==1);
 puts("PASS: create, verified reuse without writes, hash/size/owner/mode/mount/type rejection, volatile EEXIST");
}
'''
with tempfile.TemporaryDirectory(prefix='liuqin-probe-test-') as tmp:
    path = Path(tmp) / 'probe.cpp'
    path.write_text(harness + source + test)
    executable = Path(tmp) / 'probe'
    subprocess.run(['c++', '-std=c++20', '-Wno-deprecated-declarations',
                    '-fsanitize=address,undefined', '-g', str(path), '-lcrypto',
                    '-o', str(executable)], check=True)
    subprocess.run([str(executable)], check=True)
