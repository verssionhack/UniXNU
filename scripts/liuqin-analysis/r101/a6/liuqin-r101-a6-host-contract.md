# A6 host audit: complete clock-ID selection and publication contract

**Host-verified, no target behavior change.** Original kernelcache SHA256 `d1003b5143ffd88439b4d45b6017f587171cfe6855660bed05370a2ea5db9fe9`; fileset `com.apple.iokit.IOTimeSyncFamily`. Full methods, condensed reviews, authenticated virtual-slot resolutions and input hash are in `out/liuqin-r101-a6-work/evidence/host-branches/`. Addresses below are original unslid KC addresses, not live addresses or new read tables.

The audit covers the entire `findTimeSyncTimeClockID` function (`0xfffffe000b104f44` through `0xfffffe000b105e44`), its **functional** `.cold.1` outline (`0xfffffe000b122790`), `_orderedInsert` (`0xfffffe000b106dac`), initial publication, notification wrapper/body, delayed retry and initialization. `.cold.1` is not a fatal/error stub: it implements the final TSN fallback enumeration. The other cold exits correspond to allocation/no-candidate logging; their callers return without setting readiness.

## Candidate passes, in actual priority order

A candidate OSArray is created first. Within a priority group Ethernet and TSN candidates are combined and ordered. Only if the group is empty does the next group execute:

| Priority / addresses | IOEthernetInterface path | TSNInterface path |
| --- | --- | --- |
| 1: `b104f88..b10536c` | Must cast to real IOEthernetInterface metaclass. Exclude IO80211Interface; exclude controllers metaCasting to AppleThunderboltIPPort or AppleUSBNCMData. Require interface `IOBuiltin` property castable to **OSBoolean** and true. | Must cast to TSNInterface. Require `isBuiltin()`. Accept numeric `interfaceType()` **1 or 2**. |
| 2: `b105370..b1056a4` | Require IO80211Interface metaCast and interface `IOBuiltin` OSBoolean true. | Require builtin and numeric type **3**. |
| 3: `b1056a8..b1058f8`, outline `b122790` | No builtin requirement. Exclude controller AppleThunderboltIPPort. For AppleUSBNCMData controllers, walk interface `getProvider()` ancestry and exclude if any ancestor metaCasts to **IOBufferCopyController**. Otherwise insert. | No builtin requirement. The outline skips numeric types **0,4,5,6**, accepts **1,2,3** and values **>6**. It uses comparison plus mask `0x71`, not an assumed named enum. |

These numeric TSN types are reported as verified numbers; assigning their semantic enum names would require an additional definition source. This is unnecessary for the simpler genuine IOEthernetInterface path.

The virtual calls were resolved against authenticated original vtables: interface `+0x8a0` is **getController**, `+0x8d0` **getNamePrefix**, `+0x908` **getUnitNumber**, `+0x6b0` **getProvider**, `+0x2d8` **getProperty(char const*)**; OSBoolean `+0x148` is **getValue**; OSData `+0x160/+0x198` are **getLength/getBytesNoCopy**. The matching iterator is an **OSIterator**, not an OSArray; its iterator virtual slots are kept distinct in the inventory.

`_orderedInsert` compares each existing candidate's prefix to the new prefix with **strncmp(existing,new,strlen(existing))**. A negative result inserts the new candidate before that entry; equal prefixes compare unit numbers and insert the smaller new unit first. The first resulting array element is selected (`b105940`). Do not simplify the prefix-length comparator to an unrelated sort. There is **no literal en0 requirement**: one otherwise eligible interface with a valid prefix/unit can be selected; competing candidates can change the choice.

## Selected candidate to clock ID

For Ethernet (`b10595c..b105b90`), get `IOMACAddress` from the **interface**, require OSData; if that cast fails, try the **controller's** property with the same name/type. If neither is OSData, return without setting readiness. For TSN (`b105cf0..b105e04`), `getMACAddress` must return success **0**; nonzero returns without readiness.

The Ethernet code logs when the OSData length is <=2 but still copies `min(length,6)` bytes into an initially zeroed six-byte buffer. Thus the implementation does not strictly reject every short MAC. That permissive path is **not** an acceptable experiment contract: supply a genuine six-byte, valid, stable address rather than depend on an error/log path. No unicast/nonzero check is visible in this function; that does not make an invented malformed address a sound interface implementation.

The successful common path packs the first three MAC bytes as a 24-bit OUI, combines them with 24 random bits and low 16 zero bits, stores the resulting 64-bit clock ID at manager+`0xa0`, publishes **TimeSyncTimeClockID** as a 64-bit OSNumber and **TimeSyncTimeCoreAudioClockDomain** as a 32-bit OSNumber, then sets manager+`0xbb` at `b105cac`. Init sets the CoreAudio domain field at +`0xa8` to **`0x63690000`**; no selected-interface property is read for that domain in this routine. This ID construction is not the full six-byte MAC copied verbatim and is not stable merely because the MAC is stable.

The candidate array empty path (`b10591c -> b105e30`), unavailable matching dictionaries/array allocations, uncastable selected object, missing usable OSData, or TSN MAC error all return without that property/ready sequence. PAC/authentication failure traps are architectural failure exits, not an interface fallback.

## Initial and asynchronous publication

`start` calls the ID finder, then creates its translation service. It invokes **IOService::registerService(unsigned int)** only when the ready byte captured after the finder is set. The original IOTimeSyncClockManager and IOService vtables both decode virtual **+`0x5e0`** to export **`0xfffffe000c325634`** (previous authenticated slot proof preserved in A5r1, reproduced by this audit's virtual-slot inventory). Translation-child presence therefore does not prove parent publication.

If no ID is ready, start registers matching notifications for **IOEthernetInterface and TSNInterface**. Wrapper `interfaceMatchedNotification` (`b1060fc`) checks nonnull context, calls `interfaceMatched` (`b1064e0`) and returns true. The body verifies the notifier is one of its stored notifier pointers and the service casts to the corresponding interface class:

- Ethernet notification additionally requires a **non-null `BSD Name` property** and rejects a controller metaCasting to AppleThunderboltIPPort. Presence is checked here; no literal BSD name string or exact unit is compared.
- TSN notification requires the TSN cast. Full candidate filters still run in the later finder.
- Under the manager mutex, callbacks skip scheduling if the ready byte is already set or lookup-pending byte +`0xc8` is set. Otherwise the manager is retained and its thread call is scheduled at current absolute time plus **1,000,000,000 ns**; +`0xc8` becomes 1.

`delayedClockIDLookup` (`b104780`) gets the **platform service via IOService::getPlatform()**; when nonnull, its flagged path uses **IOSleep(5000)**, while the other calls **platform->waitQuiet(UINT64_MAX)**. This is a platform-quiet wait, not a verified BSD/network-ready service. Under the mutex it reruns the complete ID finder if still not ready. On success it unlocks, updates the translation child and calls the verified registerService slot. On failure it clears +`0xc8` so a later valid notification can schedule another attempt. It releases its retained manager reference at exit. No MAC-only property mutation bypass or dummy clock-manager registration is implied by this flow.

## Minimum meaningful interface contract for a later, separately authorized experiment

A *single* real IOEthernetInterface implementation must be visible to IOService matching, have a valid controller object and working native getters for controller/name prefix/unit, and avoid the excluded controller/ancestry classes. To use priority 1, it must be non-Wi-Fi with **IOBuiltin as OSBoolean true**; that property is optional only if relying on the lower fallback group. Supply **six-byte OSData IOMACAddress** on the interface or controller. For arrival after clock-manager startup, the interface must have its **BSD Name already present when matching notification is delivered** and participate in proper publication/lifecycle so the notification reaches the manager. The subsequent ID finder still decides eligibility and precedence.

This is a verified *kext-side prerequisite contract*, not a completed network driver design, not proof any previous en0 fixture obeys it, and not authorization to create one. Attaching a plain IOService named IOEthernetInterface or adding only an en0 string does not establish the metaclass/virtual/lifecycle contract. No network, dummy service, display or Data-size behavior change is included in A6.

A6 will distinguish the live attached/unregistered/no-ID case from registered/matched without userspace delivery, using the daemon and translation service as in-run controls. A positive publication diagnosis plus the contract above can ground a later single-variable proposal; it does not authorize that proposal's execution in this round.
