#!/usr/bin/env python3
"""Exercise the actual adapter class with fault-injectable host lifecycle stubs.

This checks owned code only, not native IOKit ABI/notification behavior.
"""
from pathlib import Path
import subprocess,tempfile
H=Path(__file__).resolve().parent
text=(H/'LiuqinIdentityEthernet.cpp').read_text()
owned=text[text.index('static constexpr UInt8 address'):text.index('OSDefineMetaClassAndStructors')]
stub=r'''
#include <cassert>
#include <cstring>
#include <cstdint>
#include <cstdio>
using UInt8=uint8_t;using UInt32=uint32_t;using IOReturn=int;using mbuf_t=void *;
constexpr int kIOReturnSuccess=0,kIOReturnBadArgument=1,kIOReturnOutputDropped=2;
constexpr unsigned kIONetworkFeatureNoBSDWait=1,kIONetworkLinkValid=1,kIOMediumEthernetAuto=1;
static int stops,detaches,freed,linkFlags;static bool baseConfig=true,makeMac=true,attachOk=true,propOk=true,mediumOk=true;
static void *const kOSBooleanTrue=(void *)0x1234;
#define OSDeclareDefaultStructors(c)
#define OSSafeReleaseNULL(p) do{if(p)(p)->release();(p)=nullptr;}while(0)
struct IOService{virtual ~IOService()=default;};
struct OSData{uint8_t bytes[6];static OSData *withBytes(const void *p,unsigned n){assert(n==6);if(!makeMac)return nullptr;auto d=new OSData;memcpy(d->bytes,p,6);return d;}void release(){delete this;}};
struct OSDictionary{static OSDictionary *withCapacity(unsigned){return new OSDictionary;}void release(){delete this;}};
struct IONetworkMedium{static IONetworkMedium *medium(unsigned,unsigned){return new IONetworkMedium;}static bool addMedium(OSDictionary *,IONetworkMedium *){return mediumOk;}void release(){delete this;}};
struct IONetworkInterface:IOService{bool builtin=false;uint8_t mac[6]={};bool setProperty(const char *key,void *p){builtin=p==kOSBooleanTrue;return propOk;}bool setProperty(const char *key,OSData *p){memcpy(mac,p->bytes,6);return propOk;}void release(){delete this;}};
struct IOEthernetInterface:IONetworkInterface{};
struct IOEthernetAddress{uint8_t bytes[6];};
struct IOEthernetController:IOService{
 virtual bool start(IOService *){return true;}virtual void stop(IOService *){++stops;}
 virtual bool configureInterface(IONetworkInterface *){return baseConfig;}
 virtual UInt32 getFeatures()const{return 0;}
 virtual IOReturn getHardwareAddress(IOEthernetAddress *)=0;
 virtual IOReturn enable(IONetworkInterface *){return 0;}virtual IOReturn disable(IONetworkInterface *){return 0;}
 virtual UInt32 outputPacket(mbuf_t,void *){return 0;}
 virtual IOReturn setPromiscuousMode(bool){return 0;}virtual IOReturn setMulticastMode(bool){return 0;}
 virtual IOReturn setMulticastList(IOEthernetAddress *,UInt32){return 0;}
 bool publishMediumDictionary(OSDictionary *){return true;}bool setProperty(const char *,void *){return propOk;}
 void setLinkStatus(unsigned flags,void *){linkFlags=flags;}
 bool attachInterface(IONetworkInterface **out,bool){if(!attachOk)return false;auto p=new IOEthernetInterface;if(!configureInterface(p)){delete p;return false;}*out=p;return true;}
 void detachInterface(IONetworkInterface *){++detaches;}void freePacket(mbuf_t p){assert(p==(void *)0x42);++freed;}
};
'''
tests=r'''
int main(){
 LiuqinIdentityEthernet c;IOService p;IOEthernetAddress a{};
 assert(c.getHardwareAddress(nullptr)==kIOReturnBadArgument);
 assert(c.getHardwareAddress(&a)==0 && memcmp(a.bytes,address,6)==0 && (a.bytes[0]&3)==2);
 assert(c.getFeatures()==kIONetworkFeatureNoBSDWait);
 assert(c.outputPacket((void *)0x42,nullptr)==kIOReturnOutputDropped && freed==1);
 assert(c.outputPacket(nullptr,nullptr)==kIOReturnOutputDropped && freed==1);
 assert(c.setMulticastList(nullptr,1)==kIOReturnBadArgument);
 assert(c.setMulticastList(nullptr,0)==0);
 IONetworkInterface n;baseConfig=false;assert(!c.configureInterface(&n));baseConfig=true;
 makeMac=false;assert(!c.configureInterface(&n));makeMac=true;
 propOk=false;assert(!c.configureInterface(&n));propOk=true;
 assert(c.configureInterface(&n) && n.builtin && memcmp(n.mac,address,6)==0);
 mediumOk=false;assert(!c.start(&p) && stops==1 && !c.getIdentityInterface());mediumOk=true;
 attachOk=false;assert(!c.start(&p) && stops==2 && !c.getIdentityInterface());attachOk=true;
 assert(c.start(&p));assert(c.getIdentityInterface()->builtin && linkFlags==kIONetworkLinkValid);
 c.enable(nullptr);assert(linkFlags==kIONetworkLinkValid);c.disable(nullptr);assert(linkFlags==kIONetworkLinkValid);
 c.stop(&p);assert(stops==3 && detaches==1 && !c.getIdentityInterface());
 puts("PASS: actual class MAC/type/configuration failures, partial-start cleanup, inactive carrier, exact packet ownership");
}
'''
with tempfile.TemporaryDirectory(prefix='liuqin-a7-test-') as d:
    p=Path(d);(p/'test.cpp').write_text(stub+owned+tests)
    subprocess.run(['c++','-std=c++17','-Wall','-Werror','-Wno-unused-parameter',p/'test.cpp','-o',p/'test'],check=True)
    subprocess.run([p/'test'],check=True)
