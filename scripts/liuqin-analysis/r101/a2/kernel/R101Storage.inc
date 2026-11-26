/* Included by LiuqinScratchDisk.cpp. It does not modify registry properties. */
extern "C" void liuqin_r101_emit(int,const char *,...) __attribute__((format(printf,2,3)));
extern "C" void liuqin_r101_storage_dump(void) {
    OSDictionary *matching=IOService::serviceMatching("IOMedia");
    OSDictionary *props=OSDictionary::withCapacity(1);
    OSString *uuid=OSString::withCString("C7D5AD67-0CE2-4AAB-BC37-BCE0F85F6720");
    bool ok=matching && props && uuid && props->setObject("UUID",uuid) && matching->setObject("IOPropertyMatch",props);
    OSSafeReleaseNULL(props);OSSafeReleaseNULL(uuid);
    OSIterator *it=ok?IOService::getMatchingServices(matching):nullptr;OSSafeReleaseNULL(matching);
    if(!it){liuqin_r101_emit(1,"LQ101 MEDIA: error=matching-unavailable");return;}
    unsigned matches=0;
    while(OSObject *obj=it->getNextObject()){
        IOService *service=OSDynamicCast(IOService,obj);if(!service)continue;matches++;
        OSString *bsd=OSDynamicCast(OSString,service->getProperty(kIOBSDNameKey));
        liuqin_r101_emit(1,"LQ101 MEDIA: uuid=C7D5AD67-0CE2-4AAB-BC37-BCE0F85F6720 bsd=%s",bsd?bsd->getCStringNoCopy():"<missing>");
        IORegistryEntry *node=service;node->retain();unsigned depth=0;
        for(;node && depth<24;depth++){
            OSDictionary *protocol=OSDynamicCast(OSDictionary,node->getProperty(kIOPropertyProtocolCharacteristicsKey));
            OSString *location=protocol?OSDynamicCast(OSString,protocol->getObject(kIOPropertyPhysicalInterconnectLocationKey)):nullptr;
            liuqin_r101_emit(1,"LQ101 ANCESTOR: depth=%u cls=%.60s name=%.60s protocol=%u location=%.40s",
                depth,node->getMetaClass()->getClassName(),node->getName(),protocol!=nullptr,location?location->getCStringNoCopy():"<missing-or-wrong-type>");
            IORegistryEntry *next=node->getParentEntry(gIOServicePlane);if(next)next->retain();node->release();node=next;
        }
        if(node){node->release();liuqin_r101_emit(1,"LQ101 MEDIA: ancestry_truncated=1");}
    }
    it->release();liuqin_r101_emit(1,"LQ101 MEDIA: matches=%u",matches);
}
