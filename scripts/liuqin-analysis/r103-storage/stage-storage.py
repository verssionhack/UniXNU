#!/usr/bin/env python3
"""Stage opt-in UFS Data transport without modifying frozen A7 inputs."""
from pathlib import Path
import argparse
import difflib
import hashlib
import re
import shutil
import plistlib
import struct

ROOT=Path(__file__).resolve().parents[3]
HERE=Path(__file__).resolve().parent
A7=ROOT/'out/liuqin-r101-a7-work'

def replace(text,old,new):
    if text.count(old)!=1:
        raise RuntimeError('Expected one occurrence: '+old[:110])
    return text.replace(old,new)

def transport_source(original):
    if 'LQDATA03' in original:
        raise RuntimeError('Stage from a tree without the persistent Data patch')
    text=original
    text=replace(text,'#define UTRD_HDR_NODATA        0x10','#define UTRD_HDR_NODATA        0x10\n#define UTRD_HDR_WRITE         0x12\nstatic bool liuqin_ufs_io_failed;')
    text=replace(text,'ufs_utrd_run(vm_offset_t ufs, vm_offset_t dma, uint64_t pa, bool read)\n{',
                      'ufs_utrd_run(vm_offset_t ufs, vm_offset_t dma, uint64_t pa, unsigned direction)\n{\n\tbool read = direction != 0;\n\tif (liuqin_ufs_io_failed) return 2;')
    start=text.index('ufs_utrd_run(')
    end=text.index('ufs_scsi_cmd_impl(',start)
    scoped=text[start:end]
    scoped=replace(scoped,'for (n = 0; n < 1000; n++) {','for (n = 0; n < (direction == 2 ? 200000u : 1000u); n++) {')
    scoped=replace(scoped,'if (n == 1000) {\n\t\treturn 2;',
                      'if (n == (direction == 2 ? 200000u : 1000u)) {\n\t\tif (direction == 2) liuqin_ufs_io_failed = true;\n\t\treturn 2;')
    text=text[:start]+scoped+text[end:]
    signature='const uint8_t *cdb, unsigned cdb_len, unsigned len, bool read)\n{'
    if text.count(signature)!=2:
        raise RuntimeError('Expected the SCSI implementation and its perf wrapper')
    text=text.replace(signature,'const uint8_t *cdb, unsigned cdb_len, unsigned len, unsigned direction)\n{\n\tbool read = direction == 1;',2)
    text=replace(text,'bool read = direction == 1;\n\tuint64_t ucd',
                      'bool read = direction == 1, write = direction == 2;\n\tif (liuqin_ufs_io_failed || cdb_len > 16 || len > LQ_BUF_SIZE) return 2;\n\tuint64_t ucd')
    text=replace(text,'ufs_scsi_cmd_impl(ufs, dma, pa, lun, cdb, cdb_len, len, read);',
                      'ufs_scsi_cmd_impl(ufs, dma, pa, lun, cdb, cdb_len, len, direction);')
    text=replace(text,'read ? UTRD_HDR_READ : UTRD_HDR_NODATA','read ? UTRD_HDR_READ : write ? UTRD_HDR_WRITE : UTRD_HDR_NODATA')
    text=replace(text,'(read ? 1u : 0u) | (256u << 16)','((read || write) ? 1u : 0u) | (256u << 16)')
    text=replace(text,'read ? 0x40 : 0x00','read ? 0x40 : write ? 0x20 : 0x00')
    # The request's PRDT and the DMA buffer must be prepared for either direction.
    text=replace(text,'\tif (read) {\n\t\tdma_wr(dma, LQ_UCD_OFF + 1024,',
                      '\tif (read || write) {\n\t\tdma_wr(dma, LQ_UCD_OFF + 1024,')
    text=replace(text,'return ufs_utrd_run(ufs, dma, pa, read);','return ufs_utrd_run(ufs, dma, pa, direction);')
    text+='\n'+(HERE/'LiuqinDataTransport.inc').read_text()
    return text

def mount_probe_source(original):
    text=replace(original,'mount_t data=vnode_mount(data_vp);',
                 'bool reused=false;mount_t data=vnode_mount(data_vp);')
    needle=' if(!error)error=vnode_open(LQ_USER_PROBE,O_CREAT|O_EXCL|FWRITE|O_NOFOLLOW,0700,0,&file,ctx);'
    text=replace(text,needle,needle+'\n if(error==EEXIST&&liuqin_data_persistent()){error=0;reused=true;}\n if(!reused){')
    needle=' if(!error)error=vnode_open(LQ_USER_PROBE,FREAD|O_NOFOLLOW,0,0,&file,ctx);'
    text=replace(text,needle,' }\n'+needle+'\n if(!error&&(vnode_mount(file)!=data||vnode_vtype(file)!=VREG))error=EXDEV;')
    return text

def stage(dev, addon_header=None):
    # This file is not changed by r102's observer patch. Read its fully staged
    # version from the frozen source recipe, then append one last patch.
    path=A7/'frozen-r100b-source/bsd/dev/liuqin_ufs.c'
    original=path.read_text()
    text=transport_source(original)
    patch=''.join(difflib.unified_diff(original.splitlines(True),text.splitlines(True),fromfile='a/bsd/dev/liuqin_ufs.c',tofile='b/bsd/dev/liuqin_ufs.c'))
    directory=dev/'drivers/LiuqinSourceStorage'
    p=directory/'LiuqinScratchDisk.cpp'
    before=(A7/'device-a/drivers/LiuqinSourceStorage/LiuqinScratchDisk.cpp').read_text();s=before
    seed_text=(directory/'ScratchSeed.inc').read_text().split('{',1)[1].rsplit('}',1)[0]
    seed=bytes(map(int,re.findall(r'\d+',seed_text)))
    logical,count=struct.unpack_from('<QQ',seed,16)
    digest=hashlib.sha256()
    cursor=32+count*16
    previous=0
    zero=bytes(1<<20)
    def zeros(n):
        while n:
            chunk=min(n,len(zero));digest.update(zero[:chunk]);n-=chunk
    for i in range(count):
        offset,length=struct.unpack_from('<QQ',seed,32+i*16)
        zeros(offset-previous)
        digest.update(seed[cursor:cursor+length])
        cursor+=length;previous=offset+length
    zeros(logical-previous)
    declarations='''#include <libkern/crypto/sha2.h>
extern "C" {
int liuqin_data_open(const uint8_t *,uint64_t *,int *);
int liuqin_data_io(uint64_t,void *,unsigned,int);
int liuqin_data_sync(void);
int liuqin_data_finish(void);
}
'''
    declarations+='static const uint8_t lq_persistent_seed_sha[32]={'+','.join(str(b) for b in hashlib.sha256(seed).digest())+'};\n'
    declarations+='static const uint8_t lq_persistent_logical_sha[32]={'+','.join(str(b) for b in digest.digest())+'};\n'
    s=replace(s,'class LiuqinScratchDisk;',declarations+'\nclass LiuqinScratchDisk;')
    s=replace(s,'static constexpr uint64_t capacity = 512ULL << 20;','static constexpr uint64_t seedCapacity = 512ULL << 20;\n uint64_t capacity=seedCapacity;')
    s=replace(s,'static_assert(capacity == (512ULL << 20), "scratch capacity changed");','#include "PersistentData.inc"')
    s=replace(s,'  disk.bytes=capacity;', '''  unsigned persist=0;
  PE_parse_boot_argn("liuqin-data",&persist,sizeof(persist));
  if(persist>3)return false;
  if(persist && !initializePersistent())return false;
  disk.bytes=seedCapacity;''')
    s=replace(s,'  disk.pages=static_cast<uint8_t **>(IOMallocZero((capacity/4096)*sizeof(uint8_t *)));',
                  '  if(!persistent)disk.pages=static_cast<uint8_t **>(IOMallocZero((seedCapacity/4096)*sizeof(uint8_t *)));')
    s=replace(s,'  if(!disk.pages || !ramSparseImport(disk,scratch_seed,sizeof(scratch_seed),ops) || disk.resident>limit)return false;',
                  '  if(!persistent && (!disk.pages || !ramSparseImport(disk,scratch_seed,sizeof(scratch_seed),ops) || disk.resident>limit))return false;')
    s=replace(s,'  if (features) {','  if (features && !persistent) {')
    # Release the feature dictionary even when persistent Data does not support UNMAP.
    s=replace(s,'   features->release();\n  }','  }\n  OSSafeReleaseNULL(features);')
    s=replace(s,'  if(gate){IOLockFree(gate);gate=nullptr;}IOBlockStorageDevice::free();',
                  '  if(persistentBounce)IOFreeData(persistentBounce,65536);\n  if(gate){IOLockFree(gate);gate=nullptr;}IOBlockStorageDevice::free();')
    s=replace(s,' char *getProductString() override {return const_cast<char *>("ScratchAPFS");}',
                  ' char *getProductString() override {return const_cast<char *>(persistent?"PersistentData":"ScratchAPFS");}\n bool isPersistent() const {return persistent;}')
    s=s.replace('"RAM only, bounded qualification fixture"','persistent?"UFS-backed Data":"RAM only, bounded qualification fixture"')
    s=s.replace('// Diagnostic RAM-only transport. There are no UFS or persistent callbacks.',
                '// RAM fixture or guarded persistent UFS Data, selected by liuqin-data.')
    s=replace(s,'IOReturn getWriteCacheState(bool *v) override {*v=false;return kIOReturnSuccess;}',
                  'IOReturn getWriteCacheState(bool *v) override {*v=persistent;return kIOReturnSuccess;}')
    s=replace(s,'resident=%llu cap=%llu volatile=1\\n",r,w,f,e,u,ue,uf,n,c);',
                  'resident=%llu cap=%llu volatile=%u\\n",r,w,f,e,u,ue,uf,n,c,persistent?0:1);')
    s=replace(s,'unmap=1 ssd=1 volatile=1\\n",capacity,disk.resident,limit);',
                  'unmap=%u ssd=1 volatile=%u\\n",capacity,disk.resident,limit,persistent?0:1,persistent?0:1);')
    s=replace(s,'IOReturn r=online?kIOReturnSuccess:kIOReturnNotReady;',
                  'IOReturn r=!online?kIOReturnNotReady:persistent&&liuqin_data_sync()?kIOReturnIOError:kIOReturnSuccess;')
    s=replace(s,'  (void)options;','  (void)options;\n  if(persistent)return kIOReturnUnsupported;')
    s=replace(s,'  if(online){\n   if(direction==kIODirectionIn)',
                  '  if(online&&persistent){\n   done=persistentIO(b,block*512,count*512,direction==kIODirectionOut);\n   status=done==count*512?kIOReturnSuccess:kIOReturnIOError;\n   if(direction==kIODirectionIn)reads++;else writes++;\n  }else if(online){\n   if(direction==kIODirectionIn)')
    s+='\nextern "C" int liuqin_data_persistent(){return activeScratch&&activeScratch->isPersistent();}\n'
    p.write_text(s)
    shutil.copy2(HERE/'PersistentData.inc',directory/'PersistentData.inc')
    # Reuse populated Data on later boots instead of recreating its template
    # and overwriting the account and desktop preferences every time.
    population=(A7/'frozen-r100b-source/bsd/kern/liuqin_data_populate.h').read_text()
    seeded=r'''
extern int liuqin_data_persistent(void);
static bool lq_data_seeded(void) {
 if(!liuqin_data_persistent())return false;
 static const char marker[]="LQDATA03 seeded\n";
 vfs_context_t ctx=vfs_context_kernel();vnode_t vp=NULLVP;
 int err=vnode_open(LQ_DATA "/private/var/db/.liuqin-seeded",FREAD|O_NOFOLLOW,0,0,&vp,ctx);
 if(err)return false;
 char buf[sizeof(marker)]={};off_t size=0;int resid=0;
 err=vnode_size(vp,&size,ctx);
 if(!err&&(vnode_vtype(vp)!=VREG||size!=sizeof(marker)-1))err=EINVAL;
 if(!err)err=vn_rdwr(UIO_READ,vp,buf,sizeof(marker)-1,0,UIO_SYSSPACE,0,vfs_context_ucred(ctx),&resid,vfs_context_proc(ctx));
 vnode_close(vp,FREAD,ctx);
 return !err&&!resid&&!memcmp(buf,marker,sizeof(marker)-1);
}
'''
    needle='static int\nliuqin_data_populate(proc_t p,user_addr_t scratch)\n{'
    new_population=replace(population,needle,seeded+'\n'+needle+'\n if(lq_data_seeded())return 0;')
    patch+=''.join(difflib.unified_diff(population.splitlines(True),new_population.splitlines(True),fromfile='a/bsd/kern/liuqin_data_populate.h',tofile='b/bsd/kern/liuqin_data_populate.h'))
    probe=(A7/'frozen-r100b-source/bsd/kern/liuqin_mount_probe.h').read_text()
    new_probe=mount_probe_source(probe)
    patch+=''.join(difflib.unified_diff(probe.splitlines(True),new_probe.splitlines(True),fromfile='a/bsd/kern/liuqin_mount_probe.h',tofile='b/bsd/kern/liuqin_mount_probe.h'))
    if addon_header is None:
        addon_patch=next((dev/'patches/xnu').glob('*-liuqin-r102-gpu-addon.patch')).read_text()
        addition=addon_patch.split('+++ b/bsd/kern/liuqin_gpu_addon.h\n',1)[1].split('--- a/',1)[0]
        addon_header=''.join(line[1:] for line in addition.splitlines(True) if line.startswith('+'))
    grow_plist=plistlib.dumps({'Label':'local.unixnu.liuqin.data-grow',
        'ProgramArguments':['/bin/sh','/private/var/liuqin/grow-data.sh'],
        'RunAtLoad':True,'StartInterval':60,
        'StandardOutPath':'/private/var/log/liuqin-data-grow.log',
        'StandardErrorPath':'/private/var/log/liuqin-data-grow.log'},fmt=plistlib.FMT_XML)
    def array(name,data):
        return 'static const uint8_t '+name+'[] __attribute__((section("__BOOTDATA,__data")))={'+','.join(str(b) for b in data)+'};\n'
    extra=array('lq_grow_script',(HERE/'grow-data.sh').read_bytes())+array('lq_grow_plist',grow_plist)
    needle='static void liuqin_desktop_seed_install(proc_t p, user_addr_t scratch) {\n'
    reuse_update=(
        '\tif(lq_data_seeded()) {\n'
        '\t\t(void)lq_write_owned(p, scratch, "/private/var/ngpu/tu_debug", lq_seed_tu_debug, lq_seed_tu_debug_len, 0644, 0, 0);\n'
        '\t\t(void)lq_write_owned(p, scratch, "/private/var/db/com.apple.xpc.launchd/disabled.plist", lq_seed_disabled_plist, lq_seed_disabled_plist_len, 0644, 0, 0);\n'
        '\t\t(void)lq_write_owned(p, scratch, "/private/var/db/com.apple.xpc.launchd/disabled.501.plist", lq_seed_disabled_user_plist, lq_seed_disabled_user_plist_len, 0644, 0, 0);\n'
        '\t\treturn;\n'
        '\t}\n'
    )
    new_addon=replace(addon_header,needle,extra+needle+reuse_update)
    needle='\tprintf("LQ102GPU DESKTOP_SEED ok=%d fail=%d err=%d\\n", ok, fail, last_err);'
    install=r'''
    if(!fail && liuqin_data_persistent()) {
        int ge=lq_write_owned(p,scratch,"/private/var/liuqin/grow-data.sh",lq_grow_script,sizeof(lq_grow_script),0755,0,0);
        if(!ge)ge=lq_write_owned(p,scratch,"/Library/LaunchDaemons/local.unixnu.liuqin.data-grow.plist",lq_grow_plist,sizeof(lq_grow_plist),0644,0,0);
        static const uint8_t marker[]="LQDATA03 seeded\n";
        if(!ge)ge=lq_write_owned(p,scratch,"/private/var/db/.liuqin-seeded",marker,sizeof(marker)-1,0600,0,0);
        if(ge){fail++;last_err=ge;}
    }
'''
    new_addon=replace(new_addon,needle,install+needle)
    patch+=''.join(difflib.unified_diff(addon_header.splitlines(True),new_addon.splitlines(True),fromfile='a/bsd/kern/liuqin_gpu_addon.h',tofile='b/bsd/kern/liuqin_gpu_addon.h'))
    patch_name='zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz-liuqin-r103-data.patch'
    (dev/'patches/xnu'/patch_name).write_text(patch)
    series=dev/'patches/xnu/series'
    series_text=series.read_text()
    if patch_name not in series_text:
        series.write_text(series_text.rstrip()+'\n'+patch_name+'\n')
    return patch

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('device',type=Path)
    stage(parser.parse_args().device)
