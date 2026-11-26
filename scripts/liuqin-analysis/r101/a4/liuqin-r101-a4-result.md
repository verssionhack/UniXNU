# Liuqin r101 A4 — targeted TimeSync observer result

**Verdict:** the full 480 s volatile capture and targeted evidence succeeded, with automatic return to verified fastboot. **The frozen runner's overall verdict remains `incomplete-observer-capture`, exit 5**, because one early block-writer record was concatenated onto a TRAP prefix. Exact offline suffix recovery reconciles every storage window; it does not change the original verdict. No retry or behavior fix was booted.

**Measured:** `IOTimeSyncDaemonService` exists. clocksyncd is in its main CFRunLoop, not synchronously parked in `DaemonServiceMatcher.waitForService`. `IOTimeSyncClockManager` also exists; `IOTimeSyncgPTPManager` is absent from all three complete registry sweeps. **Inference:** this eliminates the proposed *current* forever-semaphore wait, but does not yet identify which asynchronous initialization/listener gate failed. **Hypothesis:** absent gPTP readiness prevents listener creation. Do not add en0 or a dummy service from this evidence alone.

## Scope and artifact identity

A4 contains only observer changes on accepted A3r1 behavior: nTWE=1, nTWI unchanged, 512 MiB Data, identical 999-byte arguments, ADT, trust bundle, device drivers and USB transport/fence. No partition writes, flashing, signing or owner-key access. The user withdrew the separate-go rule; session authorization is preserved with the capture.

Work directory: `out/liuqin-r101-a4-work/`.
Capture: `evidence/a/boot-A4-20261121-094931/` (Asia/Shanghai, 2026-11-21).

| Artifact | SHA256 |
| --- | --- |
| Accepted behavior baseline A3r1 boot | `85e02fede9faad5527010843d073ab50c208fa45f3423437780835f9e0d13be9` |
| A4 boot | `61dc0156e78e9d179216a7db48a27b629a16df1de22a80eee0ae5f758ac5f467` |
| A4 kernel | `c447e32bd0b8cf52f7a01948f894da9f52dcd2d69ff03c9271d0ba96b0c7887f` |
| Raw USB log | `6aa530fb225306f4ee7febb2be46343aeb371db140de6f4f2e80480c9b40c957` |
| Per-chunk guard trace | `d068e0d73cf6c3837330b89f5480f71e3492fdcd9a7225297af913df87c81201` |

Host verification passed: only four observer source files differ, `start.s` and USB sources match A3r1, device inputs match, parser/slice/section tests and exact A3r1 guard replay pass. Initial compilation required replacing unavailable `strstr` with a local helper; the failed candidate was never booted. TEXT `0x1cc000`, DATA `0x27c000`, TEXT_EXEC `0x9a4000`; const VMA `0xfffffff0070064e0`, **3,040 B above the gate**. Further code changes need renewed layout checks.

## Capture and evidence contracts

**Measured:** cooldown 120 s; capture 480.192 s; 1,538,872 USB bytes; no panic marker, guard abort, capture exception or USB disconnect. Exact replay passes all **2,203** guard calls. Fastboot serial `be7ca114` was verified automatically after capture and checked again on the host. 82 registration end markers.

| Snapshot | Count / FNV-1a | Target capture | Prefix completion |
| --- | --- | --- | --- |
| 60 s | 243 / `fa7e852dacc10911` | Both tasks, complete | 13 ms |
| 120 s | 115 / `8e9449ec66bac8ff` | Both tasks, complete | 4 ms |
| 300 s | 115 / `70e104c08863d777` | Both tasks, complete | 4 ms |

All snapshot checksums were verified directly against the raw log; no framing recovery touches snapshots. All six task identity/frame captures and all three registry coverage checks pass the predeclared target contract. Independent scalar banks preserve each task's registers before any target-memory reads. All main-image reads and frame walking remain behind the completion fence.

Raw anchored observer records total 331,682 B; including the exactly recovered embedded suffix gives **331,836 B**, below 512 KiB. Maximum observer record including LF is **187 B**. The concatenated physical line is 243 B. Last OUTPUT reports bytes=328543, detail=204748, suppressed=0, line_trunc=0, summary_failed=0; its timestamp/window differs from the complete host byte inventory. Last LOSS: ring_drop=0, saturation=0, writer_overflow=0; history_overwrite=94 and payload_trunc=87 are bounded-history/undecoded-payload coverage, not proof of complete IPC decoding.

### Why exit 5 is retained

At observer **+8.037 s**, BLK_WINDOW `t_ms=1480505` declares 14 writers, 3,702,784 B and 465 submissions. The frozen line-anchored parser sees 13 rows. Raw **line 3608** contains:

```text
TRAP ae0f esr 96000047 far fffffff757947000 pc fffffff00c2a199c rec 0 lr fffffff00bf54d58LQ102 BLK_WRITER: t_ms=1480505 pid=194 comm=eligibilityd bytes=212992 writes=13 legacy_bytes=212992 legacy_writes=13 context=block-submitter path=unknown
```

This accounts exactly for the missing 212,992 B / 13 submissions, including the legacy bucket. The supplemental recovery accepts only a complete TRAP prefix plus a complete strictly parsed writer suffix, with no invented fields or bytes. **All 97 block windows then reconcile**, including their legacy breakdowns; block-context overflow is zero. There is exactly one embedded observer prefix in the full raw log.

`block-framing-recovery.json` preserves the original line, split position, both lengths, raw hash and reconciled window. Raw `usb.log`, boot-record, assessment and frozen rules remain unchanged. This is evidence of a record-boundary defect, not byte loss or a panic. The transport and early sampler are source-identical to A3r1 and the first new target snapshot is later; the precise low-level concatenation mechanism is not proven. Future capture/parser hardening must preserve strict snapshot verification rather than silently declaring this run exit 0.

## clocksyncd and WindowServer

**Measured:** clocksyncd pid **150**, main tid **932**, workqueue tid **955**; WindowServer pid **112**, main tid **688**, workqueue tid **962**. Each has two captured threads at all snapshots. Both tasks independently report shared-region slide **`0xc0b4000`**, cache UUID **`8b1e17c672d6301791a4916022e3612e`**. Their equality is observed, not assumed.

clocksyncd's own main-image base is **`0x1008c6000`**, CPU subtype `0x80000002`, UUID **`91f59f6a64c3321c88b00cc7a485ab1c`**. This matches the previously audited arm64e slice and its pinned SHA256. Its main relocation is **`0x8c6000`**, independently derived from host TEXT vmaddr `0x100000000`. WindowServer base `0x100faf000`, UUID `25f292d9a7083643b52b279c1d043847`, is separately recorded.

Each invalid-address probe returns **EFAULT=14**; all target frame reads report **0 unavailable**. The LR candidates for each target are identical across 60/120/300 s.

clocksyncd's main candidates symbolicate, from deepest caller toward the wait:

```text
dyld start
clocksyncd start + 0x214  [return 0x1000012dc; BL CFRunLoopRun at 0x1000012d8]
CFRunLoopRun + 64
_CFRunLoopRunSpecificWithOptions + 536
__CFRunLoopRun + 1172
__CFRunLoopServiceMachPort + 160
mach_msg + 24
mach_msg_overwrite + 480
```

Main raw PC/LR normalize to `_mach_msg2_trap + 8` / `_mach_msg2_internal + 76`, consistent with the captured receive wait. The workqueue candidate is `_start_wqthread + 8`. Per snapshot, **9/10** raw daemon candidates pass BL/BLR callsite checks: the remaining candidate is a **terminal zero LR**, preserved as unresolved. Thus the whole raw-record `callsite_validation_passed` is false, not silently upgraded. The eight nonzero main candidates plus workqueue candidate pass; this is bounded frame evidence, not an independently validated backtrace.

WindowServer's **17/17** candidates per snapshot pass callsite checks, including its workqueue candidate. Its main 16 candidates remain the synchronous TimeSync reply wait through `DisplayExternalSyncObserver.startObservingSSAMDevices` → `TSXDaemonServiceClient.getSyncEntityManagerProxy` → synchronous XPC/dispatch Mach receive. Final legacy CPU row: 176 ms cumulative, alive=1, exits=0. **`native_reader_validated=false` remains for both targets.**

### Registry and causal boundary

All three valid, untruncated IOService-plane traversals (visited 231/228/228 nodes) find exactly:

```text
IOResources
  IOTimeSyncRootService
    IOTimeSyncClockManager
      IOTimeSyncTranslationMach
    IOTimeSyncDaemonService
```

Each reports hits=4, printed=4, exact_daemon=1. No TimeSync/gPTP/Clock keyword hit was suppressed by a bound; there is no `IOTimeSyncgPTPManager` instance in these sweeps. Host framework initialization explicitly matches `IOTimeSyncClockManager` and `IOTimeSyncgPTPManager`; preserved disassembly verifies those literal names.

**Inference:** clocksyncd is not currently in gate 1's forever semaphore; a missing daemon service is ruled out at the sampled times. **Not established:** successful completion of initialization, delivery of the clock callback, registration/delivery of the gPTP callback, or creation/resumption of the expositor listener. Main calls CFRunLoopRun even after `TSDDaemon` initialization returns nil, so the runloop cannot prove initialization success. No current worker is captured inside `getSyncEntityManagerWithReply:`, but asynchronous listener state is not reconstructed from this alone.

**Next evidence needed:** bounded nonfaulting reads of the identity-qualified daemon global and host-verified notifier/server readiness state, or equivalent callback/listener event observation, to separate failed initialization, clock readiness, gPTP readiness and post-listener handling. [The offline follow-up](liuqin-r101-a4-timesync-followup.md) records addresses and limits. No single-variable behavior fix is justified yet; none was built or booted in this round.

## Baseline context

**Measured:** all eight CPUs retain nTWE=1/nTWI=0 at all snapshots. The uncapped undefined-word histogram has events=0, overflow=0 through observer **+430.641 s**, with no raw WFE detail in the full capture. Raw tail detail is capped; do not claim a final unsampled uncapped counter.

59 early Data samples; below-16-MiB bracket **(+20.096, +21.100] s**, inside the predeclared screen. Last free space **5.574219 MiB**, 7,358 syscall errno-28 events, writer_overflow=0, WindowServer=0 at +430.641 s. Minimum sampled free RAM **3,562 pages / 13.914063 MiB** at +40.178 s, with reclaimable queues also present. No Data resize is supported. Two per-process-limit jetsam kills; vnode num 66,560, free 48,972, dead 576. Nine detailed EL0 fault records remain in the raw/analysis inventories; do not infer zero faults from **EL0 TRAP=0**.

## Evidence and remaining scope

The capture folder contains raw USB/host trace, boot and capture-assessment records, source authorization, target-specific raw frames and UUID/SHA/callsite validation, `analysis-a4.json`, and supplemental block-framing recovery. Preboot manifest: `out/liuqin-r101-a4-work/evidence/review-manifest.json`. The accepted A3r1 preboot manifest and A4 preboot manifest were rechecked unchanged (127 entries). A separate result manifest freezes all final analysis inputs/results.

A3r1 stays the accepted behavior baseline. A4 provides usable targeted TimeSync evidence with the explicit inherited raw-framing failure. Device is in verified fastboot. No further boot, behavior change, flash or key operation was performed. Owner-key disposition and real-key offline signing remain unchanged owner items.
