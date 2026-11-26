/* Class member observer; all counter writes use the existing storage gate. */
struct R102Blk { int32_t pid;char comm[20];uint64_t bytes,writes,legacy_overflow_bytes,legacy_overflow_writes; };
R102Blk *r102_window=nullptr,*r102_copy=nullptr;
uint64_t r102_bytes=0,r102_writes=0,r102_overflow_bytes=0,r102_overflow_writes=0,r102_previous_ms=0,r102_legacy_bytes=0,r102_legacy_writes=0;
void r102RecordLocked(uint64_t bytes,const char *name,bool legacyOverflow) {
 r102_bytes+=bytes;r102_writes++;
 if(legacyOverflow){r102_legacy_bytes+=bytes;r102_legacy_writes++;}
 int32_t pid=proc_selfpid();
 if(r102_window)for(unsigned i=0;i<256;i++){
  R102Blk *e=&r102_window[i];
  if(!e->writes || (e->pid==pid && !strncmp(e->comm,name,sizeof(e->comm)))){
   e->pid=pid;strlcpy(e->comm,name,sizeof(e->comm));e->bytes+=bytes;e->writes++;
   if(legacyOverflow){e->legacy_overflow_bytes+=bytes;e->legacy_overflow_writes++;}return;
  }
 }
 r102_overflow_bytes+=bytes;r102_overflow_writes++;
}
public:
void r102Window(uint64_t now) {
 if(!gate)return;
 IOLockLock(gate);
 uint64_t bytes=r102_bytes,writes=r102_writes,ob=r102_overflow_bytes,ow=r102_overflow_writes;
 uint64_t lb=r102_legacy_bytes,lw=r102_legacy_writes;
 bool ready=r102_window&&r102_copy;unsigned n=0;
 if(ready){memcpy(r102_copy,r102_window,256*sizeof(R102Blk));memset(r102_window,0,256*sizeof(R102Blk));}
 r102_bytes=r102_writes=r102_overflow_bytes=r102_overflow_writes=r102_legacy_bytes=r102_legacy_writes=0;
 IOLockUnlock(gate);
 if(ready)for(unsigned i=0;i<256;i++)if(r102_copy[i].writes)n++;
 liuqin_r101_emit(1,"LQ102 BLK_WINDOW: t_ms=%llu dt_ms=%llu initial=%u bytes=%llu writes=%llu named=%u overflow_bytes=%llu overflow_writes=%llu legacy_bytes=%llu legacy_writes=%llu slots=256 ready=%u",
  now,r102_previous_ms?now-r102_previous_ms:0,!r102_previous_ms,bytes,writes,n,ob,ow,lb,lw,ready);
 if(ready)for(unsigned i=0;i<256;i++)if(r102_copy[i].writes){R102Blk *e=&r102_copy[i];
  liuqin_r101_emit(0,"LQ102 BLK_WRITER: t_ms=%llu pid=%d comm=%s bytes=%llu writes=%llu legacy_bytes=%llu legacy_writes=%llu context=block-submitter path=unknown",now,e->pid,e->comm,e->bytes,e->writes,e->legacy_overflow_bytes,e->legacy_overflow_writes);
 }
 r102_previous_ms=now;
}
private:
