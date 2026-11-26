# A5r1 corrective audit: select clocksyncd's local implementation

**Audit error corrected:** A5 verified the `_TSF_` framework implementation's layouts but did not verify that clocksyncd calls that implementation. The pinned executable defines its own `TSDClockManager`, `TSDgPTPManager`, `TSDKextNotifier`, and matcher classes. A5's requested framework globals can legitimately be unavailable; their EFAULT results are neither nil nor evidence about the active local notifier. A5's own daemon read remains useful and its raw capture/inputs are preserved. No behavior fix follows from the unavailable framework globals.

Before coding A5r1, the local implementation was disassembled and its **actual class references** verified from chained fixups:

| Actual reference in executable | Rebase target / source |
| --- | --- |
| GOT `0x100063448` (`TSDClockManager`) | **`0x10006d918`**; used by TSDDaemon.start and +[TSDClockManager initialize] |
| GOT `0x100063498` (`TSDgPTPManager`) | **`0x10006d8c8`**; used by the local clock callback |
| class reference `0x100062c80` (`TSDKextNotifier`) | **`0x10006ce28`**; local clock/gPTP initialize allocate that same class literal |

These are rebases into the **main executable**, not binds to `_TSF_` framework classes. Therefore active notifier/singleton globals must use **clocksyncd's own executable relocation**, not the shared-cache slide.

| Local global | Main unslid address | Verification |
| --- | --- | --- |
| Clock notifier / singleton | `0x10006e1a0` / `0x10006e1a8` | +initialize `0x10002d5d8`; +notify `0x10002d684`; +shared `0x10002d860` |
| Clock singleton queue / once | `0x10006e1b0` / `0x10006e1b8` | +sharedClockManager loads |
| gPTP notifier / singleton | `0x10006e180` / `0x10006e188` | +initialize `0x10002c038`; +notify `0x10002c0d0`; +shared `0x10002c230` |
| gPTP singleton queue / once | `0x10006e190` / `0x10006e198` | +sharedgPTPManager loads |
| Shared matcher notification queue | `0x10006e0d8` | -[TSDKextNotifier notifyWhenServiceIsAvailable:] at `0x100004210`, load at `0x10000423c` |
| Daemon global | `0x10006e0a0` | Unchanged and correctly captured in A5 |

The local notifier/matcher layout is independently verified by its own direct loads/stores: match/terminate notifications +8/+16; matched registry-ID set +24; identifier +32; availability/unavailability callback arrays +40/+48. `getMatchedCount` at `0x100003c78` sends count to +24. The local availability block at **`0x1000042d0`** checks count and either invokes the callback or copies it into the +40 array; local serviceMatched at **`0x100003ec0`** invokes and clears that array. This confirms semantics on the active implementation, not by name similarity to the framework copy.

Local daemon/server layouts, class objects and initialization/resume ordering are unchanged from the valid portion of the A5 audit. Libobjc ISA constants and CoreFoundation array/set classes/storage/count layouts remain in the shared cache, correctly qualified with this task's own shared slide. A5r1 removes the unrelated framework notifier ivar-cell reads: local field offsets are literal instructions in the UUID/SHA-pinned main executable. No guessed offsets or masks are substituted.

Preserved new raw evidence: `out/liuqin-r101-a5-audit/local-daemon/` (copied into A5r1 evidence). The old A5 preboot audit and frozen inputs are **not edited**. This revision changes only observer addresses/relocation qualification and decoder version, retains nonfaulting read bounds/fence, and requires new host verification/layout checks before a separate volatile run under existing session authorization.
