// SPDX-License-Identifier: BSD-2-Clause-Patent
// Included in LiuqinScratchDisk's private fields/methods.
 bool persistent=false;
 uint8_t *persistentBounce=nullptr;
 bool initializePersistent() {
  int initialize=0;
  int rc=liuqin_data_open(lq_persistent_seed_sha,&capacity,&initialize);
  if(rc){printf("LQ103 DATA open failed rc=%d\n",rc);return false;}
  persistent=true;limit=capacity;
  persistentBounce=static_cast<uint8_t *>(IOMallocData(65536));
  if(!persistentBounce)return false;
  if(!initialize)return true;
  uint64_t logical=0;
  if(!ramPackedLayout(scratch_seed,sizeof(scratch_seed),&logical)||logical!=seedCapacity)return false;
  // Clear the seed's whole logical extent, then materialize its packed runs.
  // The state=1 marker makes an interrupted initialization explicit and retryable.
  memset(persistentBounce,0,65536);
  for(uint64_t offset=0;offset<seedCapacity;offset+=65536)
   if(liuqin_data_io(offset,persistentBounce,65536,1))return false;
  const uint64_t count=ramU64(scratch_seed+24);
  uint64_t cursor=32+count*16;
  for(uint64_t i=0;i<count;i++){
   uint64_t at=ramU64(scratch_seed+32+i*16),left=ramU64(scratch_seed+40+i*16);
   while(left){
    unsigned n=left>65536?65536:static_cast<unsigned>(left);
    memcpy(persistentBounce,scratch_seed+cursor,n);
    if(liuqin_data_io(at,persistentBounce,n,1))return false;
    at+=n;cursor+=n;left-=n;
   }
  }
  if(liuqin_data_sync())return false;
  SHA256_CTX sha;SHA256_Init(&sha);
  for(uint64_t offset=0;offset<seedCapacity;offset+=65536){
   if(liuqin_data_io(offset,persistentBounce,65536,0))return false;
   SHA256_Update(&sha,persistentBounce,65536);
  }
  uint8_t digest[32];SHA256_Final(digest,&sha);
  if(memcmp(digest,lq_persistent_logical_sha,32))return false;
  return liuqin_data_finish()==0;
 }
 uint64_t persistentIO(IOMemoryDescriptor *b,uint64_t offset,uint64_t bytes,bool write) {
  uint64_t done=0;
  while(done<bytes){
   unsigned n=bytes-done>65536?65536:static_cast<unsigned>(bytes-done);
   if(write&&b->readBytes(done,persistentBounce,n)!=n)break;
   if(liuqin_data_io(offset+done,persistentBounce,n,write))break;
   if(!write&&b->writeBytes(done,persistentBounce,n)!=n)break;
   done+=n;
  }
  return done;
 }
