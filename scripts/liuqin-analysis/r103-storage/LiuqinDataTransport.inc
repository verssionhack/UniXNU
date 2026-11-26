/* SPDX-License-Identifier: BSD-2-Clause-Patent
 * Included after liuqin_ufs.c's root parser. Only the allocated Data extent
 * and its metadata block are writable; OS, SystemOS, App and GPT stay read-only.
 */
int liuqin_data_sync(void);
int liuqin_data_open(const uint8_t [32], uint64_t *, int *);
int liuqin_data_io(uint64_t, void *, unsigned, int);
int liuqin_data_finish(void);
static struct {
 uint64_t meta_lba, first_lba, bytes;
 uint8_t seed_sha[32];
 bool online, initializing;
} lq_data;

static int
lq_data_scsi_write(uint64_t lba, unsigned blocks, const void *src)
{
 if (!ufs_state.ready || !ufs_lock || !blocks || lba >= ufs_state.block_count ||
     blocks > ufs_state.block_count-lba || lba > UINT32_MAX || blocks-1 > UINT32_MAX-lba) return -1;
 unsigned per=LQ_BUF_SIZE/ROOT_LBA_BYTES;
 const uint8_t *p=src;
 int rc=0;
 lck_mtx_lock(ufs_lock);
 while (blocks) {
  unsigned n=blocks>per?per:blocks;
  uint8_t cdb[10]={0x2a,0,0,0,0,0,0,0,0,0};
  cdb[2]=lba>>24;cdb[3]=lba>>16;cdb[4]=lba>>8;cdb[5]=lba;
  cdb[7]=n>>8;cdb[8]=n;
  memcpy((void *)(ufs_state.dma+LQ_BUF_OFF),p,n*ROOT_LBA_BYTES);
  rc=ufs_scsi_cmd(ufs_state.ufs,ufs_state.dma,ufs_state.dma_pa,ufs_state.lun,cdb,10,n*ROOT_LBA_BYTES,2);
  uint8_t *rsp=(uint8_t *)(ufs_state.dma+LQ_UCD_OFF+512);
  unsigned ocs=*(volatile uint32_t *)(ufs_state.dma+LQ_UTRL_OFF+8)&255;
  if (rc || ocs || rsp[0]!=0x21 || rsp[6] || rsp[7] || (rsp[1]&0x60)) {
   printf("LQ103 DATA WRITE fail lba=%llu n=%u rc=%d ocs=%u rsp=%02x/%02x/%02x/%02x\n",
       (unsigned long long)lba,n,rc,ocs,rsp[0],rsp[1],rsp[6],rsp[7]);
   rc=-2;break;
  }
  p+=n*ROOT_LBA_BYTES;lba+=n;blocks-=n;
 }
 lck_mtx_unlock(ufs_lock);
 return rc;
}

int
liuqin_data_sync(void)
{
 if (!lq_data.online || !ufs_state.ready || !ufs_lock) return -1;
 const uint8_t cdb[10]={0x35,0,0,0,0,0,0,0,0,0};
 lck_mtx_lock(ufs_lock);
 int rc=ufs_scsi_cmd(ufs_state.ufs,ufs_state.dma,ufs_state.dma_pa,ufs_state.lun,cdb,10,0,false);
 uint8_t *rsp=(uint8_t *)(ufs_state.dma+LQ_UCD_OFF+512);
 unsigned ocs=*(volatile uint32_t *)(ufs_state.dma+LQ_UTRL_OFF+8)&255;
 if (rc || ocs || rsp[0]!=0x21 || rsp[6] || rsp[7]) {
  printf("LQ103 DATA SYNC fail rc=%d ocs=%u rsp=%02x/%02x/%02x\n",rc,ocs,rsp[0],rsp[6],rsp[7]);
  rc=-2;
 }
 lck_mtx_unlock(ufs_lock);
 return rc;
}

static int
lq_data_header(unsigned state)
{
 uint8_t *header=kalloc_data(ROOT_LBA_BYTES,Z_WAITOK|Z_ZERO);
 if (!header) return -1;
 memcpy(header,"LQDATA03",8);
 uint64_t fields[4]={state,lq_data.first_lba,lq_data.bytes,root_state.image_bytes};
 memcpy(header+8,fields,sizeof(fields));memcpy(header+40,lq_data.seed_sha,32);
 SHA256_CTX ctx;SHA256_Init(&ctx);SHA256_Update(&ctx,header,4064);SHA256_Final(header+4064,&ctx);
 int rc=lq_data_scsi_write(lq_data.meta_lba,1,header);
 kfree_data(header,ROOT_LBA_BYTES);
 return rc?rc:liuqin_data_sync();
}

int
liuqin_data_open(const uint8_t seed_sha[32], uint64_t *bytes, int *initialize)
{
 lq_data.online=false;
 if (!seed_sha || !bytes || !initialize || !liuqin_ufs_root_ready() || ufs_state.block_size!=4096) return -1;
 const uint64_t mib=1ULL<<20;
 /* Preserve an additional 128 MiB after the manifest image. The first
  * candidate at image_bytes contained pre-existing JSON on this tablet. */
 uint64_t meta=((root_state.image_bytes+mib-1)&~(mib-1))+(128ULL<<20);
 uint64_t offset=meta+mib;
 uint64_t partition=(root_state.last_lba-root_state.first_lba+1)*4096ULL;
 if (partition<(64ULL<<20) || offset>partition-(64ULL<<20) ||
     partition-(64ULL<<20)-offset<(1ULL<<30)) return -2;
 uint64_t capacity=partition-(64ULL<<20)-offset;
 lq_data.meta_lba=root_state.first_lba+meta/4096;
 lq_data.first_lba=root_state.first_lba+offset/4096;
 lq_data.bytes=capacity;memcpy(lq_data.seed_sha,seed_sha,32);
 uint8_t *header=kalloc_data(4096,Z_WAITOK|Z_ZERO);
 if (!header) return -3;
 int rc=liuqin_ufs_block_read(lq_data.meta_lba,1,header);
 unsigned init=0;PE_parse_boot_argn("liuqin-data",&init,sizeof(init));
 bool blank=true;for (unsigned i=0;i<4096;i++) if(header[i]){blank=false;break;}
 bool existing=false;uint64_t state=0;
 bool owned=!memcmp(header,"LQDATA03",8);
 if (!rc && !blank && owned) {
  uint8_t digest[32];SHA256_CTX ctx;SHA256_Init(&ctx);SHA256_Update(&ctx,header,4064);SHA256_Final(digest,&ctx);
  uint64_t fields[4];memcpy(fields,header+8,sizeof(fields));state=fields[0];
  existing=!memcmp(digest,header+4064,32) && fields[1]==lq_data.first_lba && fields[2]==capacity &&
      fields[3]==root_state.image_bytes && !memcmp(header+40,seed_sha,32) && (state==1 || state==2);
 }
 printf("LQ103 DATA OPEN meta=%llu rc=%d blank=%u existing=%u state=%llu mode=%u magic=%02x%02x%02x%02x%02x%02x%02x%02x\n",
     (unsigned long long)lq_data.meta_lba,rc,blank,existing,(unsigned long long)state,init,
     header[0],header[1],header[2],header[3],header[4],header[5],header[6],header[7]);
 bool fresh=blank || (!owned && !existing && init==3);
 kfree_data(header,4096);
 if (rc || (!fresh && !existing) || ((fresh || state==1) && init!=2 && init!=3)) return -4;
 lq_data.online=true;lq_data.initializing=fresh || state==1;
 if (fresh && lq_data_header(1)) {lq_data.online=false;return -5;}
 *bytes=capacity;*initialize=lq_data.initializing;
 printf("LQ103 DATA region=%llu+%llu state=%s\n",(unsigned long long)offset,(unsigned long long)capacity,lq_data.initializing?"initialize":"reuse");
 return 0;
}

/* The caller serializes sub-block read/modify/write with its IOStorage gate.
 * Root-window readers use the same UFS mutex but never change this extent. */
int
liuqin_data_io(uint64_t offset, void *buffer, unsigned bytes, int write)
{
 if (!lq_data.online || !buffer || !bytes || ((offset|bytes)&511) ||
     offset>=lq_data.bytes || bytes>lq_data.bytes-offset) return -1;
 uint8_t *bounce=kalloc_data(4096,Z_WAITOK);
 if (!bounce) return -2;
 uint8_t *p=buffer;int rc=0;
 while (bytes) {
  uint64_t lba=lq_data.first_lba+offset/4096;
  unsigned within=offset&4095,n=4096-within;if(n>bytes)n=bytes;
  if (!within && bytes>=4096) {
   n=bytes&~4095u;if(n>LQ_BUF_SIZE)n=LQ_BUF_SIZE;
   rc=write?lq_data_scsi_write(lba,n/4096,p):liuqin_ufs_block_read(lba,n/4096,p);
   if(rc)break;
   p+=n;offset+=n;bytes-=n;continue;
  }
  if (!write || within || n!=4096) {rc=liuqin_ufs_block_read(lba,1,bounce);if(rc)break;}
  if(write){memcpy(bounce+within,p,n);rc=lq_data_scsi_write(lba,1,bounce);}
  else memcpy(p,bounce+within,n);
  if(rc)break;
  p+=n;offset+=n;bytes-=n;
 }
 kfree_data(bounce,4096);return rc;
}

int
liuqin_data_finish(void)
{
 if (!lq_data.online || !lq_data.initializing) return -1;
 int rc=liuqin_data_sync();
 if (!rc) rc=lq_data_header(2);
 if (!rc) lq_data.initializing=false;
 return rc;
}
