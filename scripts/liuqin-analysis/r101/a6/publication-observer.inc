/* A6: public read-only state/property observation, same retained iterator entry. */
static void r106_publication(IOService *s) {
    if(!s)return;
    static_assert(kIOServiceRegisteredState==2 && kIOServiceMatchedState==4,"A6 public IOService bit contract");
    IOOptionBits state=s->getState();uint64_t rid=s->getRegistryEntryID();
    liuqin_r101_emit(1,"LQ102 PUBLICATION: cls=%.48s rid=%llx state=%x registered=%u matched=%u inactive=%u source=IOService",
        s->getMetaClass()->getClassName(),(unsigned long long)rid,(unsigned)state,!!(state&kIOServiceRegisteredState),!!(state&kIOServiceMatchedState),!!(state&kIOServiceInactiveState));
    if(!s->metaCast("IOTimeSyncClockManager"))return;
    const char *keys[]={"TimeSyncTimeClockID","TimeSyncTimeCoreAudioClockDomain"};
    for(unsigned i=0;i<2;i++){
        OSObject *object=s->copyProperty(keys[i]);OSNumber *n=OSDynamicCast(OSNumber,object);
        liuqin_r101_emit(1,"LQ102 CLOCK_PROPERTY: rid=%llx key=%s present=%u type=%.40s decoded=%u bits=%u value=%llx",
            (unsigned long long)rid,keys[i],object!=nullptr,object?object->getMetaClass()->getClassName():"none",n!=nullptr,n?n->numberOfBits():0,(unsigned long long)(n?n->unsigned64BitValue():0));
        if(object)object->release();
    }
}
