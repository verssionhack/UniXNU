/* Exercise the actual class-member observer with host stubs, not a mirror. */
#include <cstdint>
#include <cstring>
#include <cstdarg>
#include <cstdio>
#include <cstdlib>
#include <cassert>
#include <string>
#include <vector>
static int32_t test_pid;
static int32_t proc_selfpid(){return test_pid;}
static void IOLockLock(void*){}
static void IOLockUnlock(void*){}
static std::vector<std::string> lines;
static void liuqin_r101_emit(int,const char *fmt,...){char line[512];va_list args;va_start(args,fmt);int n=std::vsnprintf(line,sizeof(line),fmt,args);va_end(args);assert(n>=0&&n<253);lines.emplace_back(line);}
struct Harness {
 void *gate=(void*)1;
#include "kernel/R102Block.inc"
public:
 Harness(){r102_window=(R102Blk*)std::calloc(256,sizeof(R102Blk));r102_copy=(R102Blk*)std::calloc(256,sizeof(R102Blk));}
 ~Harness(){std::free(r102_window);std::free(r102_copy);}
 void add(int pid,const char *name,uint64_t bytes,bool legacy=false){test_pid=pid;r102RecordLocked(bytes,name,legacy);}
};
int main(){
 Harness h;
 h.add(1,"same",100);h.add(2,"same",200,true);h.r102Window(1000);
 assert(lines.size()==3);assert(lines[0].find("bytes=300 writes=2 named=2")!=std::string::npos);
 assert(lines[0].find("legacy_bytes=200 legacy_writes=1")!=std::string::npos);
 assert(lines[2].find("pid=2 comm=same bytes=200 writes=1 legacy_bytes=200")!=std::string::npos);
 lines.clear();
 for(int pid=1;pid<=257;pid++)h.add(pid,"worker",4096,true);
 h.r102Window(2000);
 assert(lines.size()==257);assert(lines[0].find("dt_ms=1000")!=std::string::npos);
 assert(lines[0].find("bytes=1052672 writes=257 named=256 overflow_bytes=4096 overflow_writes=1")!=std::string::npos);
 assert(lines[0].find("legacy_bytes=1052672 legacy_writes=257")!=std::string::npos);
 lines.clear();h.add(257,"worker",8192,true);h.r102Window(3000);
 assert(lines.size()==2);assert(lines[0].find("bytes=8192 writes=1 named=1 overflow_bytes=0 overflow_writes=0")!=std::string::npos);
 assert(lines[1].find("pid=257")!=std::string::npos);
 lines.clear();h.r102Window(4000);assert(lines.size()==1);assert(lines[0].find("bytes=0 writes=0 named=0")!=std::string::npos);
 std::puts("PASS: PID separation, byte conservation, legacy overflow breakdown, 257th context overflow, window recycling, no cumulative carryover, line bound");
}
