# A5r1 clock-manager publication — host follow-up

This is read-only disassembly of the original pinned `com.apple.iokit.IOTimeSyncFamily` fileset, performed during A5r1 capture. Raw methods, input SHA256 and the independently decoded vtable slot are under `out/liuqin-r101-a5r1-work/evidence/kernel-followup/`. No device behavior, interface or property was changed.

The live observer finds a local clock notifier with **matched count 0 and one retained availability callback**, despite an `IOTimeSyncClockManager` object in the IOService registry. That distinguishes a registry object from one whose first-match publication reached userspace. The next question is publication/notification state, not gPTP readiness.

Host `IOTimeSyncClockManager::start` (`0xfffffe000b104aac`) has a specific branch:

1. Calls `findTimeSyncTimeClockID` at `0xfffffe000b104b2c` and copies an internal byte at object+`0xbb` into w22.
2. Creates the translation service, explaining how `IOTimeSyncTranslationMach` can already be present.
3. If the copied byte is set, updates the translation service and invokes virtual slot **+`0x5e0`** at `0xfffffe000b104bc4`.
4. If it is clear, branches at `0xfffffe000b104b4c` to `0xfffffe000b104d30`, constructs matching for literal **IOEthernetInterface**, and registers `interfaceMatchedNotification`; it also sets up **TSNInterface** matching. This path does not invoke the registerService call above.

Virtual slot +`0x5e0` was **verified**, not guessed from its position: existing tested `kc_image.Image.fixups` decodes both IOTimeSyncClockManager and IOService vtable entries (symbol+16-byte vptr header+`0x5e0`) to **`0xfffffe000c325634`, IOService::registerService(unsigned int)**. The authenticated chained words and decoded targets are preserved in `registerService-slot.json`.

Host `findTimeSyncTimeClockID` (`0xfffffe000b104f44`) scans Ethernet/TSN candidates, includes filters such as IO80211Interface / IOBuiltin, reads **IOMACAddress**, and on its successful path publishes **TimeSyncTimeClockID** and **TimeSyncTimeCoreAudioClockDomain**, then sets object+`0xbb` at `0xfffffe000b105cac`. The full function is long and has several candidate/fallback paths: this does **not** establish that any arbitrary Ethernet stand-in, or specifically the BSD name en0, satisfies it. The literal class/property requirements now have source evidence; the exact selected interface/ID remains unmeasured on this device.

**Inference:** clock-ID discovery may be why the existing manager is attached but unpublished, leaving clocksyncd before its clock-ready callback. This is consistent with A5r1 state but is not a measured internal flag or registration state. A broken matching/notification delivery path is still an alternative.

The next small observer should report the manager's public `getState()` bits (`kIOServiceRegisteredState=0x2`, `kIOServiceMatchedState=0x4`, verified in pinned XNU IOService.h), registry ID, and presence/type/value of the two TimeSync ID properties. Distinguish attached/unregistered, registered but not matched, and registered/matched without userspace delivery before choosing an interface or notification behavior change. This follow-up is a host diagnosis proposal only; no such observer or behavior boot is included in A5r1.
