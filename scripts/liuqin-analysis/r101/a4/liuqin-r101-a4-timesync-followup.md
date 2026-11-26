# A4 TimeSync host interpretation

This is offline analysis of the pinned host executable/cache, alongside the observer capture. It adds no target behavior change. Host disassembly is under `out/liuqin-r101-a4-work/evidence/timesync-followup/`.

The TimeSync framework exposes `_TSF_TSDClockManager` and `_TSF_TSDgPTPManager` implementation classes. Its pinned symbol listing gives:

| Host implementation | Unslid address | Observed control flow |
| --- | --- | --- |
| Clock manager initialize | `0x23b0d934c` | Allocates `_TSF_TSDKextNotifier`; matches literal `IOTimeSyncClockManager` at `0x23b0d93a4`; starts notifications at `0x23b0d93bc`. |
| Clock availability subscription | `0x23b0d93f8` | Uses `_kextNotifier` global `0x275739818`; calls `notifyWhenServiceIsAvailable:`. |
| gPTP manager initialize | `0x23b0b38e8` | Allocates its notifier; matches literal `IOTimeSyncgPTPManager` at `0x23b0b3940`; starts notifications at `0x23b0b3958`. |
| gPTP availability subscription | `0x23b0b3980` | Uses separate notifier global `0x275739790`; calls `notifyWhenServiceIsAvailable:`. |
| Clock singleton | `0x23b0d95d4` | Once token at `0x275739830`, queue at `0x275739828`, singleton at `0x275739820`. |

A4's registry sweep matches all three literal class names, not only display keywords. Presence of `IOTimeSyncClockManager` and absence of `IOTimeSyncgPTPManager` therefore distinguish actual service availability; they do not prove that user-mode notification subscription/delivery completed successfully.

**Important null branch:** clocksyncd's captured main thread is in `CFRunLoopRun`, called at main `0x1000012d8` (return `0x1000012dc`). This rules out being synchronously stuck in `DaemonServiceMatcher.waitForService` at the snapshots. It does **not** prove successful daemon initialization. Main stores the result of `objc_alloc_init(TSDDaemon)` at main-image global `0x10006e0a0`, then calls CFRunLoopRun without checking it. `-[TSDDaemon init]` can return nil if matcher setup/wait reports failure (`0x1000257ac` path). A valid event-loop stack therefore also permits failed initialization, as well as an outstanding clock/gPTP callback or a resumed idle listener.

The captured main/workqueue stacks and service registry alone cannot distinguish those asynchronous cases or prove expositor listener readiness. Do not convert the absent gPTP service into a measured causal explanation, or add en0/dummy services from this result.

If further observation is needed, use a bounded, nonfaulting identity-qualified read of the daemon global at **own main-image base + `0x6e0a0`**, followed by host-verified notifier/singleton and daemon/server field state. The globals in the framework use **this task's recorded shared-region slide**, not the main-image relocation. First verify the notifier's exact ivar layout and availability/notification semantics on the host. A nil daemon, clock subscription pending, gPTP subscription pending, and created/resumed server must have separate explicit outcomes. Unavailable pages remain null evidence. This is a proposed observer, not built or booted in A4.
