/* Exercise actual instruction-word counters independently of the detail cap. */
#include <cstdint>
#include <cstring>
#include <cstdio>
#include <cstdarg>
#include <cassert>
#include <string>
#include <vector>
#define LQ_U64(v) ((unsigned long long)(v))
struct r102_undefined { char comm[20];int32_t pid;uint64_t word,count,previous; };
struct State { r102_undefined undefined[64],undefined_copy[64];uint64_t undefined_total,undefined_overflow; };
static State state{};static State *r101=&state;static int r101_lock;
static void lck_spin_lock(void*){}static void lck_spin_unlock(void*){}
static void r101_inc(uint64_t *v){++*v;}
static std::vector<std::string> lines;
static void liuqin_r101_emit(int,const char *fmt,...){char text[512];va_list ap;va_start(ap,fmt);int n=std::vsnprintf(text,sizeof(text),fmt,ap);va_end(ap);assert(n>=0&&n<253);lines.emplace_back(text);}
#include "kernel/liuqin_r102_undefined.inc"
int main(){
 for(int i=0;i<100;i++)liuqin_r102_undefined("ux_sig",275,"ReportCrashServ",2,4,1,0xd503205f);
 liuqin_r102_undefined("exc_crash",275,"ReportCrashServ",2,4,1,0xd503205f);
 liuqin_r102_undefined("ux_sig",275,"ReportCrashServ",2,5,1,0xd503205f);
 liuqin_r102_undefined("ux_sig",275,"ReportCrashServ",2,4,1,0xd503207f);
 assert(state.undefined_total==101&&state.undefined[0].count==100&&state.undefined[1].count==1);
 r102_undefined_dump(1000);assert(lines.size()==3);assert(lines[1].find("word=d503205f total=100 delta=100")!=std::string::npos);
 lines.clear();r102_undefined_dump(2000);assert(lines.size()==1);
 liuqin_r102_undefined("ux_sig",300,"ReportCrashServ",2,4,1,0xd503205f);lines.clear();r102_undefined_dump(3000);
 assert(lines.size()==2);assert(lines[1].find("last_pid=300 word=d503205f total=101 delta=1")!=std::string::npos);
 std::memset(&state,0,sizeof(state));lines.clear();
 for(int i=0;i<65;i++){char comm[20];std::snprintf(comm,sizeof(comm),"process%d",i);liuqin_r102_undefined("ux_sig",i,comm,2,4,1,0xd503205f);}
 assert(state.undefined_total==65&&state.undefined_overflow==1);r102_undefined_dump(4000);assert(lines.size()==65);
 std::puts("PASS: 100 events beyond detail cap, stage/signal filtering, WFE/WFI separation, delta sampling, last PID, bounded overflow and line cap");
}
