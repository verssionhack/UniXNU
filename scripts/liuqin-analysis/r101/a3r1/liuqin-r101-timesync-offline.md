# TimeSync / clocksyncd host follow-up — no kernel change

**Scope:** optional offline analysis alongside the A3r1 build. No device boot or new observer was added. A2r1's WindowServer frames remain bounded/racy and `native_reader_validated=false`. The analysis below names host implementation gates; it does not prove where the live clocksyncd process is blocked.

## Inputs and endpoint ownership

Read-only extraction used the existing APFS reader against pinned root image `/media/disk_4/unixnu_workspace/ramdisk_dir/unixnu/ipsw/26C5035r/141-22233-021.dmg`. It extracted only `usr/libexec/clocksyncd` (1467840 B) and `System/Library/LaunchDaemons/com.apple.clocksyncd.plist` (669 B). No filesystem was mounted or modified. Binary/plist hashes, source image metadata, listings, decoded metadata and disassembly are under `out/liuqin-r101-a3r1-work/evidence/timesync/` and the review manifest.

The plist declares:

```text
Label: com.apple.clocksyncd
Program: /usr/libexec/clocksyncd
MachServices:
  com.apple.timesync.expositor
  com.apple.timesync.manager
  com.apple.timesync.ptp.manager
```

This confirms which launchd job owns the default service name returned by `+[TSXDaemonServiceClient serviceName]` in the UUID-matched TimeSync cache. Launchd declaring a Mach service is different from its process completing initialization, resuming its NSXPC listener or replying. A2r1's alive pid 140 / 111 ms CPU therefore does not prove the service was ready.

## Startup gates before the expositor listener

The host executable is universal; the inspected **arm64e slice** has entry `0x1000010c8`. Main performs user-directory/sandbox setup, allocates `TSDDaemon` at `0x1000012c0`, then calls `CFRunLoopRun` at `0x1000012d8` after initialization returns.

The disassembled path is:

1. **`-[TSDDaemon init]` at 0x1000256ac** creates `DaemonServiceMatcher` and synchronously calls `waitForService` at 0x100025738, before calling `start`. The host string says “TSDDaemon waiting for daemon service to become available”.
2. **`-[DaemonServiceMatcher waitForService]` at 0x100025b34** constructs `IOKService serviceMatching:@"IOTimeSyncDaemonService"`, starts matching notifications, then calls `dispatch_semaphore_wait` at **0x100025b98** with deadline **-1 / forever**. Its `serviceMatched:` callback at 0x100025bd4 signals that semaphore. A missing/unmatched `IOTimeSyncDaemonService` is therefore a concrete pre-listener blocking hypothesis.
3. Once that wait succeeds, **`-[TSDDaemon start]` at 0x1000257bc** registers `notifyWhenClockManagerIsAvailable:` (0x100025868).
4. Its clock-manager callback at **0x10002587c** calls `sharedClockManager` and `addgPTPServicesWithError:`, then registers **`notifyWhengPTPManagerIsAvailable:` at 0x10002599c**.
5. Only in the gPTP-ready callback at **0x1000259bc** is **`TSDDaemonServiceServer` allocated at 0x100025a50** (after creating its diagnostics manager).
6. **`-[TSDDaemonServiceServer init]` at 0x100022938** creates an NSXPCListener with `initWithMachServiceName:` at 0x1000229fc, sets its delegate/queue, then **resumes it at 0x100022a60**. The surrounding host metadata identifies the expositor service.

Thus a daemon can be alive with little CPU while its expositor listener has not yet resumed. There are at least three specific readiness gates to distinguish: IOTimeSyncDaemonService matching, clock-manager availability and gPTP-manager availability. This is stronger evidence than a generic networking dependency, but it does **not** prove that adding en0 satisfies any of these gates.

## Once a request is accepted

`-[TSDDaemonServiceServerExported getSyncEntityManagerWithReply:]` at **0x100025228** obtains `TSDSyncEntityManager.sharedSyncEntityManager` at 0x10002524c before invoking the reply block at 0x10002526c. Its implementation supplies another possible post-listener failure boundary: initialization of that shared manager, or handling the request/returning its reply. No live daemon stack, instruction pointer, XPC-server port owner or callback state was captured to choose between these branches.

The stripped binary's method addresses were resolved through ipsw's host-generated symbol cache and decoded ObjC metadata; `read-symbol-cache.py` strictly reads its leading Gob uint64/string map. Selected methods are disassembled by address, with objc selector and imported-function annotations. Raw files are preserved; no remote decompiler or external model was used.

## Targeted later observation, not included in A3r1

After the nTWE experiment is reviewed, a dedicated observer revision could capture:

- clocksyncd's main and worker wait states, raw registers and bounded frame candidates, with **its own main-executable load base/UUID** as well as its recorded shared-region slide; the WindowServer slide must not be used to relocate a daemon executable;
- instances/matching state of **IOTimeSyncDaemonService** and the clock/gPTP readiness stages, plus whether the expositor listener is resumed or a worker entered `getSyncEntityManagerWithReply:`;
- whether the main thread is in the identified forever semaphore wait, a run loop awaiting readiness callbacks, or a worker inside shared-manager initialization.

Do not infer registry absence from the existing display-oriented sweep: its keyword filter does not cover these TimeSync classes. Do not publish services, change network interfaces, disable synchronization, resize Data or add these observers to A3r1. A3r1 retains **exactly A2r1 observers**.

**Boundary:** these are host-side control-flow facts from the pinned OS image. The live clocksyncd main-image UUID/base and stacks were not observed, and its current stage remains a hypothesis. User-space WFE behavior is addressed first in the separately gated A3r1 experiment.
