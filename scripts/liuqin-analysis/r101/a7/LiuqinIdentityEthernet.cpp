// A7 experiment: native Ethernet identity, no transport or simulated carrier.
#include <IOKit/IOLib.h>
#include <IOKit/IOPlatformExpert.h>
#include <libkern/c++/OSMetaClass.h>
#include <libkern/c++/OSData.h>
#include <libkern/c++/OSBoolean.h>
#include <libkern/c++/OSString.h>
#include <libkern/c++/OSSymbol.h>
#include <libkern/OSKextLib.h>
#include <kern/thread.h>
#define __PRIVATE_SPI__
#include <IOKit/network/IOEthernetController.h>
#include <IOKit/network/IOEthernetInterface.h>
#include <IOKit/network/IOOutputQueue.h>

extern kmod_info_t g_kernel_kmod_info;
extern "C" void liuqin_identity_static_init(void) __asm__("__GLOBAL__sub_I_LiuqinIdentityEthernet.cpp");
static constexpr UInt8 address[6]={0x02,0x4c,0x51,0x10,0x00,0x01};
class LiuqinIdentityEthernet : public IOEthernetController {
    OSDeclareDefaultStructors(LiuqinIdentityEthernet)
    IOEthernetInterface *interface=nullptr;
public:
    bool start(IOService *provider) override {
        if(!IOEthernetController::start(provider))return false;
        OSDictionary *dict=OSDictionary::withCapacity(1);
        IONetworkMedium *medium=IONetworkMedium::medium(kIOMediumEthernetAuto,0);
        bool ok=dict && medium && IONetworkMedium::addMedium(dict,medium) && publishMediumDictionary(dict);
        OSSafeReleaseNULL(medium);OSSafeReleaseNULL(dict);
        if(ok)ok=setProperty("IOBuiltin",kOSBooleanTrue);
        if(ok){setLinkStatus(kIONetworkLinkValid,nullptr);ok=attachInterface(reinterpret_cast<IONetworkInterface **>(&interface),true);}
        if(!ok){if(interface){detachInterface(interface);OSSafeReleaseNULL(interface);}IOEthernetController::stop(provider);}
        return ok;
    }
    void stop(IOService *provider) override {
        if(interface){detachInterface(interface);OSSafeReleaseNULL(interface);}
        IOEthernetController::stop(provider);
    }
    bool configureInterface(IONetworkInterface *netif) override {
        if(!IOEthernetController::configureInterface(netif))return false;
        OSData *mac=OSData::withBytes(address,sizeof address);
        bool ok=mac && netif->setProperty("IOBuiltin",kOSBooleanTrue) && netif->setProperty("IOMACAddress",mac);
        OSSafeReleaseNULL(mac);return ok;
    }
    UInt32 getFeatures() const override{return kIONetworkFeatureNoBSDWait;}
    IOReturn getHardwareAddress(IOEthernetAddress *out) override {
        if(!out)return kIOReturnBadArgument;
        memcpy(out->bytes,address,sizeof address);return kIOReturnSuccess;
    }
    IOReturn enable(IONetworkInterface *) override {setLinkStatus(kIONetworkLinkValid,nullptr);return kIOReturnSuccess;}
    IOReturn disable(IONetworkInterface *) override {setLinkStatus(kIONetworkLinkValid,nullptr);return kIOReturnSuccess;}
    UInt32 outputPacket(mbuf_t packet,void *) override {
        if(packet)freePacket(packet);
        return kIOReturnOutputDropped;
    }
    // No receiver exists; accepting a filter setting cannot deliver traffic.
    IOReturn setPromiscuousMode(bool) override{return kIOReturnSuccess;}
    IOReturn setMulticastMode(bool) override{return kIOReturnSuccess;}
    IOReturn setMulticastList(IOEthernetAddress *list,UInt32 count) override {
        return count && !list?kIOReturnBadArgument:kIOReturnSuccess;
    }
    IOEthernetInterface *getIdentityInterface() const{return interface;}
};
OSDefineMetaClassAndStructors(LiuqinIdentityEthernet,IOEthernetController)
static_assert(sizeof(IOEthernetController)==0x118,"Pinned parent extent");

namespace {
// The boot hook only spawns this worker. No service/matching/command-gate lock
// is held across a wait. TimeSync's separate thread call waits for quiet before
// taking its own +0xf8 mutex; interfaceMatched releases that mutex after enqueue.
LiuqinIdentityEthernet *liveController;
void worker(void *,wait_result_t) {
    const char *stage="bsd";IOReturn status=kIOReturnError;
    LiuqinIdentityEthernet *controller=nullptr;IOService *parent=nullptr;
    bool attached=false,started=false;
    mach_timespec_t timeout={30,0};
    IOService *bsd=IOService::waitForService(IOService::resourceMatching("IOBSD"),&timeout);
    if(!bsd)goto done;
    {
        stage="family";
        OSReturn loaded=OSKextLoadKextWithIdentifier("com.apple.iokit.IONetworkingFamily");
        const OSSymbol *symbol=OSSymbol::withCString("IOEthernetController");
        const OSMetaClass *mc=symbol?OSMetaClass::getMetaClassWithName(symbol):nullptr;
        OSSafeReleaseNULL(symbol);
        IOLog("LQ107 ETHERNET: stage=family rc=%x parent_bytes=%u\n",loaded,mc?mc->getClassSize():0);
        if((loaded!=kOSReturnSuccess && loaded!=kOSKextReturnStartStopError) || !mc || mc->getClassSize()!=0x118)goto done;
        stage="prequiet";IOService *platform=IOService::getPlatform();
        status=platform?platform->waitQuiet(30ULL*1000000000):kIOReturnNotReady;
        IOLog("LQ107 ETHERNET: stage=prequiet rc=%x\n",status);
        if(status!=kIOReturnSuccess)goto done;
        stage="constructors";void *handle=OSMetaClass::preModLoad(g_kernel_kmod_info.name);
        if(!handle)goto done;
        liuqin_identity_static_init();status=OSMetaClass::postModLoad(handle);
        if(status!=kOSReturnSuccess)goto done;
        stage="init";controller=OSTypeAlloc(LiuqinIdentityEthernet);parent=IOService::getResourceService();
        if(!controller || !parent || !controller->init(nullptr))goto done;
        stage="attach";attached=controller->attach(parent);if(!attached)goto done;
        stage="start";started=controller->start(parent);if(!started)goto done;
        controller->registerService();
        stage="native-name";IOEthernetInterface *netif=controller->getIdentityInterface();
        // Native stack owns BSD name, unit reservation, ifnet and re-registration.
        // Poll without service locks, and never write its name/state by hand.
        bool ready=false;
        for(unsigned i=0;netif && i<300;++i){
            OSObject *name=netif->copyProperty("BSD Name");
            ready=OSDynamicCast(OSString,name) && netif->getIfnet()!=nullptr &&
                (netif->getInterfaceState() & kIONetworkInterfaceRegisteredState)!=0;
            OSSafeReleaseNULL(name);if(ready)break;IOSleep(100);
        }
        if(!ready)goto done;
        stage="postquiet";status=platform->waitQuiet(30ULL*1000000000);
        IOLog("LQ107 ETHERNET: stage=postquiet rc=%x\n",status);
        if(status!=kIOReturnSuccess)goto done;
        OSObject *name=netif->copyProperty("BSD Name");
        OSData *mac=OSDynamicCast(OSData,netif->getProperty("IOMACAddress"));
        IOLog("LQ107 ETHERNET: stage=ready cls=%s bsd=%s unit=%u builtin=%u mac_bytes=%u carrier=0\n",
            netif->getMetaClass()->getClassName(),OSDynamicCast(OSString,name)?static_cast<OSString *>(name)->getCStringNoCopy():"unknown",
            netif->getUnitNumber(),netif->getProperty("IOBuiltin")==kOSBooleanTrue,mac?mac->getLength():0);
        OSSafeReleaseNULL(name);
        liveController=controller;controller=nullptr;stage="complete";status=kIOReturnSuccess;
    }
done:
    if(!liveController && status==kIOReturnSuccess)status=kIOReturnError;
    if(controller){if(started)controller->stop(parent);if(attached)controller->detach(parent);controller->release();}
    IOLog("LQ107 ETHERNET: stage=%s rc=%x retained=%u\n",stage,status,liveController!=nullptr);
    thread_terminate(current_thread());
}
}
extern "C" void liuqin_identity_ethernet_start(void) {
    thread_t thread=nullptr;kern_return_t rc=kernel_thread_start(worker,nullptr,&thread);
    if(rc==KERN_SUCCESS)thread_deallocate(thread);
    else IOLog("LQ107 ETHERNET: stage=spawn rc=%x\n",rc);
}
