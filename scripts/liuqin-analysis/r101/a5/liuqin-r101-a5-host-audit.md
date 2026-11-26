# A5 host layout and notification audit — before target implementation

Pinned source: macOS 27.3 / 26C5035r, clocksyncd arm64e UUID `91f59f6a64c3321c88b00cc7a485ab1c` (slice SHA256 `f2d989cdb9018859dae8f84de5f297d21afefbc5729bd9fce1c06be1e18bfddd`), shared-cache UUID `8b1e17c672d6301791a4916022e3612e`. Read-only output lives in `out/liuqin-r101-a5-audit/`; preceding daemon disassembly and framework symbol listing remain pinned in the A3r1/A4 evidence. No target code was added before this audit.

## Exact layouts verified

`TSDDaemon` inherits NSObject. The pinned ObjC declaration names `_diagnosticsManager`, `_daemonServiceServer`. The gPTP-ready callback at `0x1000259bc` directly stores diagnostics at **+8**, tests/stores server at **+16**; `objc_alloc_init(TSDDaemonServiceServer)` returns before the server pointer is stored. Main stores the daemon at **`0x10006e0a0`**. Expected local class objects are TSDDaemon **`0x10006d6e8`**, TSDDaemonServiceServer **`0x10006d648`**, relocated by the executable's own load base minus `0x100000000`.

`TSDDaemonServiceServer.init` directly accesses queue **+8**, NSXPCListener **+16**, client connections **+24**. It sends listener `resume` at **`0x100022a60`**, then returns; only afterwards does the caller store the server on the daemon. A stable, correctly typed nonnil stored server with a nonnil listener therefore supports **created/server-init-returned-after-resume-invocation**. It does not prove an NSXPC request/reply succeeded or that the listener remains active. No unverified NSXPCListener private flag will be decoded.

`_TSF_TSDKextNotifier` inherits `_TSF_TSDIOKServiceMatcher`. ObjC ivar cells at **`0x2728f5438`** contain little-endian offsets **8,16,24,32,40,48**, confirmed independently by direct field loads:

| Offset | Field |
| --- | --- |
| +8 | match notification |
| +16 | terminate notification |
| +24 | NSMutableSet of matched registry IDs |
| +32 | identifier string |
| +40 | NSMutableArray of pending availability callbacks |
| +48 | NSMutableArray of pending unavailability callbacks |

Notifier class object: **`0x275737be8`**. Framework globals: gPTP notifier/singleton/queue/once **`0x275739790/798/7a0/7a8`**; clock equivalents **`0x275739818/820/828/830`**; shared matcher notification queue **`0x2757397d0`**. All framework addresses use this task's own recorded shared slide.

## Availability semantics verified

`getMatchedCount` (`0x23b0c1d00`) sends `count` to the matched-ID set at +24. `notifyWhenServiceIsAvailable:` (`0x23b0c2298`) asynchronously queues a block onto the shared matcher notification queue. Its block (`0x23b0c2358`) checks matched count: **>=1 invokes the callback; zero appends a copied callback to the +40 array**. `serviceMatched:` (`0x23b0c1f48`) invokes saved availability blocks and then removes all objects from that array. Matching/termination update the +24 set. Empty callback arrays alone do not prove a subscription was ever registered; these reads remain racy and cannot inspect an in-flight block on the queue.

Clock initialization matches literal **IOTimeSyncClockManager**; gPTP initialization matches **IOTimeSyncgPTPManager**. An initialized clock singleton alone is weaker than a completed clock callback; classify using daemon/server fields, matched counts and retained callback counts together. A nil global notifier can mean the class was never initialized or its allocation failed.

## Collection layouts and ISA qualification

The pinned libobjc constants at **`0x180447ba8`** are class mask **`0x00007ffffffffff8`**, magic mask **1**, magic value **1** (next word). A5 must capture these live, reject mismatches, and use them only for ISA decoding, not as an arbitrary user-pointer/PAC mask. Strong object pointers must lie in the task's authoritative user map; raw pointers/ISA remain recorded.

CoreFoundation implementation classes verified by symbol and count-method disassembly:

- **`__NSArrayM`**, class **`0x1ed954668`**: `count` (`0x18473b9d0`) loads the storage ivar offset from **`0x1eb1deb7c`**, host value **16**, then reads **u32 at storage+20**, i.e. **object+36**.
- **`__NSSetM`**, class **`0x1ed9533f8`**: `count` (`0x184761248`) loads storage offset from **`0x1eb1dee94`**, host value **16**, then reads **u32 at storage+12**, i.e. **object+28**, masked with **`0x03ffffff`**.

Read those offset cells live and validate them before decoding. Decode counts only for the exact matching live ISA class. Other class-cluster implementations remain explicit unknowns; do not search for a count that looks plausible. No collection method, target code, pointer authentication instruction or target-memory write is executed by the observer.

## Fixed state outcomes and nulls

- Identity-qualified daemon global is zero, stable on reread: **nil daemon**, consistent with init failure; allocation/matcher reason remains unknown.
- Typed nonnil daemon, no stored server, typed clock notifier has matched=0 and retained availability callbacks>0: **clock pending** (even if IORegistry currently publishes the class; notifier delivery may be missing).
- Typed nonnil daemon, no stored server, typed gPTP notifier has matched=0 and retained availability callbacks>0: **gPTP pending**. Report clock evidence alongside it; contradictory simultaneous states remain ambiguous.
- Typed nonnil stored server, typed daemon, nonnil listener, stable pointers: **created/resumed server initialization**, with the resume-invocation boundary above; request/reply readiness is still separate.
- Identity mismatch, unavailable pages, unknown collection class, changed pointers/count words, failed notification setup, or no uniquely supported branch: **unknown**, with raw evidence and exact reason. Never treat read failure as nil.

Every read must be bounded and nonfaulting, last behind the existing fail-closed USB prefix fence. Host analysis assigns the outcome; the kernel records raw words and read status. Do not suspend tasks or introduce en0, dummy services, display changes, larger Data, flash or key operations.
