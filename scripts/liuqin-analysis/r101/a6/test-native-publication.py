#!/usr/bin/env python3
from pathlib import Path
import subprocess
R=Path(__file__).resolve().parents[4];H=Path(__file__).resolve().parent;W=R/'out/liuqin-r101-a6-work'
prefix=r'''
#include <stdint.h>
#include <stdio.h>
#include <stdarg.h>
#include <string.h>
#include <assert.h>
#include <string>
typedef unsigned IOOptionBits;enum {kIOServiceInactiveState=1,kIOServiceRegisteredState=2,kIOServiceMatchedState=4};
static unsigned releases,property_reads;static std::string output;
struct Meta { const char *name;const char *getClassName(){return name;} };
struct OSObject { Meta meta;virtual ~OSObject(){};explicit OSObject(const char *n):meta{n}{};Meta *getMetaClass(){return &meta;} void release(){releases++;} };
struct OSNumber:OSObject { uint64_t value;unsigned bits;OSNumber(uint64_t v,unsigned b):OSObject("OSNumber"),value(v),bits(b){} unsigned numberOfBits(){return bits;}uint64_t unsigned64BitValue(){return value;} };
struct IOService:OSObject { unsigned state;uint64_t rid;OSObject *properties[2];IOService(const char *n,unsigned s,uint64_t i):OSObject(n),state(s),rid(i),properties{nullptr,nullptr}{} IOOptionBits getState(){return state;}uint64_t getRegistryEntryID(){return rid;}bool metaCast(const char *n){return !strcmp(n,meta.name);}OSObject *copyProperty(const char *k){property_reads++;return properties[!strcmp(k,"TimeSyncTimeClockID")?0:1];} };
#define OSDynamicCast(T,o) dynamic_cast<T *>(o)
static void liuqin_r101_emit(int summary,const char *fmt,...) { (void)summary;char line[512];va_list ap;va_start(ap,fmt);int n=vsnprintf(line,sizeof(line),fmt,ap);va_end(ap);assert(n>0 && n+1<255);output+=line;output+='\n';}
'''
main=r'''
int main(){
 IOService daemon("IOTimeSyncDaemonService",6,0xffffffffffffffffULL);r106_publication(&daemon);assert(output.find("registered=1 matched=1 inactive=0")!=std::string::npos);assert(!property_reads);
 IOService manager("IOTimeSyncClockManager",0,2);OSNumber zero(0,64),full(0xffffffff,32);manager.properties[0]=&zero;manager.properties[1]=&full;output.clear();r106_publication(&manager);assert(output.find("present=1 type=OSNumber decoded=1 bits=64 value=0")!=std::string::npos);assert(releases==2);
 manager.properties[0]=nullptr;OSObject wrong("OSString");manager.properties[1]=&wrong;output.clear();r106_publication(&manager);assert(output.find("present=0 type=none decoded=0 bits=0 value=0")!=std::string::npos);assert(output.find("present=1 type=OSString decoded=0")!=std::string::npos);assert(releases==3);
 r106_publication(nullptr);puts("PASS: actual native public control bits, numeric zero, absent/wrong type, balanced retained-property release, line cap");
}
'''
p=W/'test-native-publication.cpp';p.write_text(prefix+(H/'publication-observer.inc').read_text()+main);subprocess.run(['c++','-std=c++14','-Wall','-Wextra','-Werror',str(p),'-o',str(W/'test-native-publication')],check=True);subprocess.run([str(W/'test-native-publication')],check=True)
