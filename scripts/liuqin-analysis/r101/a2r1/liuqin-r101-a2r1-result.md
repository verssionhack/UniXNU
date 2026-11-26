# r101 A2r1 result — complete observer baseline; A3 held

**Verdict (measured):** the single authorized A2r1 volatile boot completed the 480 s capture, returned automatically to verified fastboot, and exited **0 / complete-observer-capture**. All three snapshots verify; all eight CPUs appear by +60 s; the uncapped undefined-instruction histogram supplies a nonzero WFE baseline. No guard abort, received panic marker, serial disconnect, reported observer suppression or context-table overflow occurred. No flash, signing or owner-key access occurred. **A3 was not booted and remains held for review.** Existing A3 `abcc9a4c...` has old observers and cannot be used as the paired experiment; any future A3 must be rebuilt from this A2r1 baseline with only nTWE changed.

**New lead (bounded stack evidence):** WindowServer's main thread is waiting for a **synchronous TimeSync XPC reply**, through `TSXDaemonServiceClient.getSyncEntityManagerProxy`, called during QuartzCore `DisplayExternalSyncObserver.startObservingSSAMDevices`. This updates the earlier “idle event loop” model. It does not yet identify why the server is not replying or authorize an en0/display change.

## 1. Identity, capture and acceptance

Evidence: `out/liuqin-r101-a2r1-work/evidence/a/boot-A2r1-20261121-055146/`.

| Item | Measured / verified value |
| --- | --- |
| Boot SHA256 | `2d084a20a7a77a08caa4122408a080310d93207e228df746db53604325af5597` |
| Kernel SHA256 | `f9a990d856addcb8dd14780f25b9e1f011dceb52a8d99f3d0b3b6eef4d76095a` |
| Command | `run-a2r1.py --variant a --tag A2r1 --seconds 480` |
| Cooldown | 120.000085 s; temperature unavailable |
| Host capture | 480.227044 s, including boot/initialization |
| USB bytes | 1483671 |
| USB SHA256 | `ca8251369da34d8862677bb0beea3002125a5cd6de5b5f97a6ef6d48e8e3ee71` |
| Trace SHA256 | `0e738aee4cb4e5f5236e1a9b88fd38f74424175f056a2907a34b4356b24116fe` |
| Exact guard replay | PASS, all 2202 recorded calls |
| Return / exit | verified fastboot, automatic USB-command recovery; runner and assessment exit 0 |
| Native observation tail | last Data/memory/instruction sample at observer +430.631 s; this is not 480 s after observer INIT |
| Registrations / scale | 82 end markers; chosen-DT scale 40 |

A2's early disappearance **did not reproduce in this run**. A2r1 has repaired bookkeeping and different bytes/timing; one successful run cannot attribute A2's loss to a transient, prove which repair mattered, or estimate variance. No forced-note takeover policy or maxpacket change was made.

| Pre-declared criterion | Result |
| --- | --- |
| Eight CPU readbacks by +60 s | **PASS**: INIT saw 7; +60/+120/+300 each saw 8. CPU 7: MPIDR 0x81000700, MIDR 0x412fd480, nTWE=0, nTWI=0, samples=1. |
| All observed CPU nTWE/nTWI | **0/0** on A510, A710 and X2 in this same run. |
| Snapshots, count/FNV-1a | **PASS**: 60 s=195 lines / `72fef887a3571632`; 120 s=67 / `60b772e3cba050df`; 300 s=67 / `8d14a2afea0959c4`. |
| Prefix fence / walker | Prefix completed after 11/4/4 nominal ms waits; 17 raw frames per snapshot, all 51 callsites plausible. See limits below. |
| Early Data samples | **59 valid samples before +60 s**, above minimum 50. |
| Data below-16-MiB timing screen | Crossing bracket **(+19.085,+20.090] s**, inside the pre-declared (+9.292,+21.328] s envelope. No timing-screen flag. |
| Nonzero uncapped WFE baseline | **PASS** through sampled windows: two WFE events, zero histogram overflow; a third raw WFE detail occurs after the last dump. |
| Loss/history/budget contracts | All boolean acceptance checks pass; all six history dumps/references verify; hook ring_drop=0, saturation=0, context/writer overflow=0. |

The INIT-to-60 change from seven to eight readbacks supports the previously proposed late-arrival explanation for CPU 7; its exact initialization timestamp was not recorded. No indexing or hook repair was needed.

## 2. WindowServer: a synchronous reply wait

**Measured:** WindowServer pid 112 stays alive with exits=0. Main-thread tag=1 identifies tid 645; tid 907 has workqueue tags and wait hint 15. The main thread's receive wait is indefinite and owns the receive port (`receiver_pid=112`), as in the earlier generic-port observations. A reply receive port owned by the caller does not imply an idle event loop.

At each of 60/120/300 s the reader's invalid-address test returns **EFAULT 14**. The main thread yields 16 frames (depth cap), and the workqueue thread one frame; all frame reads report unavailable=0. Raw FP/LR values are identical across the three snapshots. The host validates the recorded 39-bit VA geometry, shared-region UUID `8b1e17c672d6301791a4916022e3612e`, slide `0x15878000`, exact cache file SHA/UUID inputs and each LR-minus-four call instruction. **All 51 return addresses pass BL/BLR-family callsite checks.**

The main-thread chain, shown from its caller toward the receive wait, is:

```text
QuartzCore: DisplayExternalSyncObserver startObservingSSAMDevices
  TimeSync: TSSyncEntityManager sharedSyncEntityManager / init
    TimeSync: TSXDaemonServiceClient getSyncEntityManagerProxy
      Foundation: NSXPCConnection synchronous invocation
        libxpc: xpc_connection_send_message_with_reply_sync
          libdispatch: dispatch_mach_send_and_wait_for_reply
            libsystem_kernel: mach_msg / mach_msg_overwrite
```

**Inference:** WindowServer is blocked during this initialization call, not merely idle after completing initialization. The selected chain ends at depth 16; no claim is made about omitted older frames.

**Offline host verification:** TimeSync's `+[TSXDaemonServiceClient serviceName]` returns the constant at `0x26ce59d10`, decoded as **`com.apple.timesync.expositor`**. The method disassembly, TimeSync symbol/string output and the symbolicated frame JSON are preserved. This is the host implementation's default service name; the live XPC payload and remote endpoint owner were not decoded. The captured inventory contains **clocksyncd pid 140**, alive at t=306 s, age=304 s, CPU=111 ms. Thus this is not evidence that simply creating a missing daemon will solve the wait. Its own blocked state and the reason for the missing reply remain unobserved.

The native reader remains marked `native_reader_validated=false` by the host validator: callsite plausibility, EFAULT handling and stable raw frames are useful evidence but not an independent known-stack fixture or a trusted unwind. The target was not suspended; the stacks are racy and bounded. Do not promote them to a fully proven backtrace. The main-thread and workqueue register/stack records are separate.

Bootstrap decoding remains explicitly incomplete: observed=144, attempted=144, decoded=0, undecoded=144; endpoint_unknown=7, history_overwrite=94, payload_trunc=87. The new stack evidence names the TimeSync path despite that limitation. Matching records remain **matching requests**, not proof of outstanding notifications. No service, en0, display attachment or Metal behavior was changed.

## 3. WFE baseline and faults

| Sample / detail | Evidence |
| --- | --- |
| First histogram WFE | lsd pid 152, word `d503205f`, total=1, first reported at +23.102 s; previous +22.097 s sample was zero. |
| Second histogram WFE | opendirectoryd pid 73, same word, first reported at +189.748 s. |
| Last histogram sample | +430.631 s: events=2, overflow=0; all sampled windows account for their totals. |
| Late raw WFE | logd pid 31, same ux_sig/EXC_BAD_INSTRUCTION/SIGILL/undefined signature, received at host +474.716 s, **after the final histogram dump**. |

The measured histogram baseline is **two events through +430.631 s**, plus a separately preserved third raw fault detail in the unsampled tail. It must not be summarized as “only two WFE faults in the whole capture.” A final live-counter flush was not part of these observers. Future comparisons must state the same sample-window/tail boundary. Under the common-shared-region slide assumption, all three PCs resolve to the already verified libdispatch `_dispatch_wait_for_enqueuer+12` WFE instruction. Fault-task private/shared-region identity was not separately captured.

Thirteen detailed fault records arrived under the unchanged frozen five-field rule (SHA256 `74741e291322c5cedb5d1d679f7c4524fda5ecd75b6b5987f37c152a538145e2`):

| Group | Count / classification |
| --- | --- |
| parkd | 3, expected existing exec-denial policy |
| ReportCrashServ, SIGKILL-packed EXC_CRASH | 3, pre-existing unresolved |
| appinstalld, SIGABRT-packed EXC_CRASH | 3, pre-existing unresolved |
| locationd | 1, pre-existing signature; raw PC/sub `0x8000007d7e0010e0` remains unclassified, without a guessed mask |
| lsd WFE | 1, pre-existing in r99p; not seen in compared r100b details |
| opendirectoryd / logd WFE | 1 each, new processes in compared capped inventories; same systemic instruction defect |

Last sampled legacy fault total=30, overflow=0; that count is hook invocations, not unique crashes, and precedes the late logd detail. The legacy per-name detail cap still applies, whereas the new instruction histogram is uncapped within its stated sampled windows. **EL0 TRAP=0 does not mean zero faults.** EXC_CRASH high bytes encode terminating signals, not exit-reason namespaces.

## 4. Data, writers and memory

The 96 valid Data samples and 97 memory/block samples are exported as CSV. The first Data lookup reports identity-not-ready, so there is no fabricated +0 free-space value. Valid samples identify `/dev/disk2s1`, UUID `C7D5AD67-0CE2-4AAB-BC37-BCE0F85F6720`, capacity 512 MiB.

| Observer-relative time | Data free |
| --- | --- |
| +1.005 s | 486.625000 MiB |
| +10.044 s | 373.925781 MiB |
| +19.085 s | 28.304688 MiB |
| +20.090 s | 15.980469 MiB |
| +21.094 s | 5.578125 MiB |
| Minimum sampled | 5.566406 MiB |
| +430.631 s | 5.578125 MiB |

The valid +1.005→+20.090 samples lose **470.644531 MiB**. The same interval family has 181.910156 MiB of submitted block-writer bytes when including the initial pre-observer window. Those are unlike measures: APFS free-block allocation/reservation versus submitted/copied bytes, including repeats and initial activity. They do not close allocation accounting or prove a 288.734375 MiB unidentified physical writer. Async origin/path attribution remains limited.

Largest submitters through the below-16-MiB crossing, including that initial window:

| PID / submitting context | Submitted MiB |
| --- | --- |
| 126 analyticsd | 53.179688 |
| 188 coresymbolicati | 26.203125 |
| 102 syspolicyd | 26.046875 |
| 0 kernel_task | 22.878906 |
| 1 init | 19.929688 |
| 175 com.apple.geod | 18.160156 |

Across all 97 block windows, named submitted bytes total **618.050781 MiB**, including rewrites. Largest name aggregates: launchd 210.601563 MiB; logd_helper 184.417969; kernel_task 63.492188; analyticsd 53.179688. The old 31-name overflow bucket contributes **101.835938 MiB**, now broken down by the new observer: principally analyticsd 53.179688, coresymbolicati 26.203125 and com.apple.geod 18.160156 MiB. **New context overflow is zero**; every received window and legacy-bucket breakdown reconciles. These are block-submission contexts, not necessarily the original asynchronous writer or file path. Per-window rows, rather than only cumulative aggregates, are retained in `block-writer-windows.csv`.

At the last syscall-counter sample (+430.631 s), errno-28 total=**7274**, writer overflow=0, dedicated WindowServer counter=**0**. The 72 retained PID/name rows sum to 7274 at that sample: launchd 5920, locationd pid 183 494, dirhelper 185, logd_helper 179, analyticsd 116, cfprefsd 70, plus the remaining named rows. APFS produced 1617 matching print lines; none can be correlated one-to-one with a syscall because no shared correlation ID exists. This is a coverage limit, not proof that all were asynchronous writes; do not sum print, syscall and block counters.

**Measured memory limit:** free pages reach a one-second sampled minimum of **3623 pages = 14.152344 MiB at +25.110 s**, substantially below A1's coarse sampled minimum. Active=354812, inactive=386228, speculative=102229, wired=200479 at that instant; reclaimable pages exist, so this is not by itself proof of global OOM. Last sampled free=196219 pages =766.480469 MiB at +430.631 s. There is no basis here for blindly adding another 512 MiB Data volume allocation.

Data is already near 5.6 MiB free at +21.094 s, while the WFE histogram is still zero at +22.097 s. Therefore the **observed WFE events do not initiate this run's initial fill**. Expected parkd crashes and other boot writers are already active; this timing does not isolate which allocations filled APFS or rule out later WFE/crash-report amplification.

The media match is disk2s1, matching the selected Data device. Its ancestry includes LiuqinScratchDisk with `Protocol Characteristics/Physical Interconnect Location=Internal`. applekeystored still exits once with status `0x100` (exit 1); the previous wrong-media hypothesis is not supported by this ancestry observation, and keystore success is not claimed.

## 5. CPU, resource and output accounting

All 60 fine CPU windows arrived with no reported exit-race skips. The existing coarse top-15/UI windows remain separate and are exported with native timestamps. WindowServer's latest cumulative CPU is **213 ms**, with alive=1 and exits=0; later windows are flat. The latest emitted ReportCrashServi row, at observer +327.959 s, reports **64857 ms cumulative CPU and 32 exits**, alive=0. It is a latest observed row, not a claim about an unprinted terminal total. Three jetsam kills are recorded, all ReportCrashService per-process-limit (15 MiB). No Data-volume or jetsam policy was changed.

Last vnode sample: num=66560, free=48920, hence 17640 in use (26.5%); no vnode exhaustion follows. First >=95% idle sample has aggregate `tot=676166`; the eight-CPU proxy is 84.521 s. Different observers and one run provide no performance or variance claim.

Received tagged observer output totals **327601 bytes**, below the 524288-byte budget; maximum received observer line is **187 bytes**. Snapshot byte spans including markers are 22199 / 6246 / 6246 bytes, each below its 96 KiB reserve. The last output summary reports suppressed=0, line_trunc=0 and summary_failed=0; the final received evidence adds some bytes after that summary, which explains the smaller summary byte count. Hook ring_drop=0 and saturation=0. History overwrite/payload truncation are explicit decode/history limits, not silent snapshot loss.

## 6. Evidence, reproduction and next boundary

The folder contains `boot-record.json`, `capture-assessment.json`, `analysis-a2r1.json`, `result-summary.json`, the raw stream/trace and:

- `frames-{60,120,300}.json` and matching `*-validation.json`: final-log exports and UUID/SHA-qualified callsite results; provisional first-snapshot exports are separately labelled.
- `Data-space-series.csv`, `memory-series.csv`, `block-writer-windows.csv`, `ENOSPC-counts.csv`, `fine-CPU-rows.csv`, `TASK_CPU-all-windows.csv`.
- Host TimeSync strings/symbols and method disassembly used for the default service-name inference.

Host-only reproduction uses `assessment.py`, `validate-capture-frames.py --target 60|120|300`, and `summarize-result.py` in this directory. The acceptance result establishes the observer baseline within its explicit sampling/stack limits; it does not render a desktop or show a Metal abort.

**Next boundary:** review this baseline, including the sampled WFE tail and TimeSync lead. A future A3 must use these exact A2r1 observers and only `SCTLR_EL1.nTWE` bit 18 changed; old A3 is not eligible. No A3 rebuild/boot, A2 repeat, display/en0 change, Data resize or key operation was performed under this A2r1-only go. The device is in verified fastboot. Each future boot still needs its own explicit go.
