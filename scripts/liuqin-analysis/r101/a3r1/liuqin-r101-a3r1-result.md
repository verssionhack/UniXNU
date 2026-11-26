# r101 A3r1 result — nTWE correction observed

**Verdict (measured):** A3r1 completes the pre-declared nTWE experiment. All eight CPUs read back **only SCTLR_EL1 bit 18 added**, with nTWI and every other sampled bit unchanged from A2r1. The fixed sampled-window comparison reports **WFE=0, overflow=0**, and no raw WFE fault detail arrives anywhere in the capture, including its tail. Capture/acceptance exit **0**, all snapshot checks pass, exact guard replay passes, and the device returns automatically to verified fastboot. **Data exhaustion and the WindowServer TimeSync wait remain.** No display, TimeSync, network, Data-size, USB-policy, signing, flash or owner-key change was bundled.

The user explicitly withdrew the separate-per-boot go requirement: “go, we have no separate go rule, you can go without asking”. `session-authorization.json` records this. Subsequent authorized volatile experiments in this session do not need another confirmation; existing preservation, guard, one-variable, no-flash and no-key boundaries remain. Older pre-boot notes requiring a separate go are historical and superseded by that user instruction.

## 1. Capture and identity

Evidence: `out/liuqin-r101-a3r1-work/evidence/a/boot-A3r1-20261121-091739/`.

| Item | Value |
| --- | --- |
| Boot SHA256 | `85e02fede9faad5527010843d073ab50c208fa45f3423437780835f9e0d13be9` |
| Kernel SHA256 | `c3de6b1e6d01b2b7e1f7c7e83063d688fd21e3484689bc916064adccd11727ce` |
| Paired baseline | accepted A2r1 `2d084a20...`, raw log `ca825136...` |
| Cooldown / host capture | 120.000086 / 480.215126 s |
| Raw USB bytes | 1478038 |
| Raw USB SHA256 | `fa86e1187e12913a29d276cc69e0689c0ad61b72fdd5fd6d021d9c4319c2489f` |
| Trace SHA256 | `1b239ec85fed471e20eddf94712442d1debc3f693b8be851fba0eb45f8460e59` |
| Capture/acceptance | complete-observer-capture, exit 0 |
| Guard replay | PASS, all **2197** recorded calls |
| Abort / received panic / serial disconnect | none / none / none |
| Return | automatic, verified `be7ca114` fastboot |
| Registrations / scale | 82; chosen-DT scale 40 |

This is one A2r1/A3r1 pair. No variance, statistical crash-rate or general performance claim follows. The source/host audit established the one-instruction behavior delta before boot; runtime readback confirms it per CPU. Old A3 `abcc9a4c...` was not used.

## 2. Register and WFE comparison

All 31 received readback rows have nTWE=1 and nTWI=0: INIT captures CPUs 0–6; all +60/+120/+300 s snapshots capture 0–7. Samples remain 1 per CPU. The complete per-CPU comparison is in `comparison-a3r1.json`.

| CPU/core group | A2r1 SCTLR | A3r1 SCTLR | XOR |
| --- | --- | --- | --- |
| CPU 0, A510 | 0x3450d98d | 0x3454d98d | 0x40000 |
| CPUs 1–3, A510 | 0x3450d985 | 0x3454d985 | 0x40000 |
| CPUs 4–6, A710 | 0x3450d805 | 0x3454d805 | 0x40000 |
| CPU 7, X2 | 0x3450d985 | 0x3454d985 | 0x40000 |

The pre-boot `comparison-spec.json` selects the latest A3r1 histogram endpoint **not later than +430.631 s**, requiring it to reach at least +420 s. A3r1's selected endpoint is **+420.620 s**. A2r1's latest sample no later than that is **+420.596 s**, containing both baseline WFE events (already present by +189.748 s).

| Scope | A2r1 | A3r1 |
| --- | --- | --- |
| Matched sampled endpoints | +420.596 s: WFE **2**, overflow **0** | +420.620 s: WFE **0**, overflow **0** |
| Original baseline boundary retained | +430.631 s: WFE **2**, overflow **0** | primary comparison stays at +420.620 s |
| Last actual A3r1 dump (secondary evidence) | — | +430.659 s: undefined events **0**, overflow **0** |
| Raw capture, including unsampled tail | third WFE detail: logd, host +474.716 s, after last dump | **no WFE detail received** |

All sampled undefined-word windows conserve their totals without overflow. A3r1 has no primary undefined-word event, including WFE, through its last actual dump. The raw-tail scan is separate: legacy details remain capped, and no raw tail record cannot establish an uncapped final live-counter zero. No final counter flush was added only to A3r1. **EL0 TRAP=0 does not mean zero faults.**

**Inference supported by source and runtime:** setting nTWE closes the observed EL0 WFE→EL1 undefined-instruction failure in this experiment. This is more than a zero-event observation: the intended bit changed on every core and the previously trapping instruction now has the required EL0 permission. It does not prove every possible instruction/trap path correct or claim a final live count after the sampled boundary.

## 3. Observer transport, frames and WindowServer

All boolean observer acceptance checks pass. Snapshots verify against the final raw log:

| Target | Count / FNV-1a | Prefix wait |
| --- | --- | --- |
| 60 s | 191 / `d036c06021fe34e3` | 12 nominal ms |
| 120 s | 63 / `f40acb9fe8d4c945` | 4 nominal ms |
| 300 s | 63 / `56dd90568fc877c4` | 4 nominal ms |

WindowServer pid 111 remains alive, exits=0, latest cumulative CPU **182 ms**. Main tid 626 (main tag=1) remains in an indefinite receive wait. Workqueue tid 932 has hint 15 and zero saved user registers at all three snapshots; no frame is fabricated for it. Both waits are captured without thread truncation.

The main thread supplies **16 raw frames per snapshot**, depth-capped. All **48** return addresses pass UUID/SHA-qualified BL/BLR-family callsite checks; invalid-address probes return EFAULT 14. Main raw frames are stable across snapshots. Shared-region UUID is unchanged, slide **0x0b6d0000**. `native_reader_validated=false` remains: these are bounded, racy candidates with plausible callsites, not an independently proven unwind.

The same chain remains:

```text
QuartzCore DisplayExternalSyncObserver.startObservingSSAMDevices
  TimeSync TSSyncEntityManager.sharedSyncEntityManager / init
    TSXDaemonServiceClient.getSyncEntityManagerProxy
      NSXPCConnection synchronous invocation
        xpc_connection_send_message_with_reply_sync
          dispatch_mach_send_and_wait_for_reply
            mach_msg
```

Thus the nTWE correction **does not unblock this TimeSync reply wait**. clocksyncd is alive as pid 144 at t=376 s, age=374 s, CPU=91 ms; its own blocked stage is still uncaptured. The default expositor service and host startup gates are documented in `liuqin-r101-timesync-offline.md`: an indefinite IOTimeSyncDaemonService match, then clock-manager and gPTP-manager readiness before listener resume. These are candidates for a targeted daemon observation, not grounds for a blind en0/display change.

IPC decode coverage is still observed=144, attempted=144, decoded=0, undecoded=144; endpoint_unknown=7. Matching records are matching requests, not proof of outstanding notifications. No live server-port owner or reply-failure cause is inferred from those undecoded payloads.

## 4. Data, memory and remaining crash traffic

A3r1 retains 512 MiB Data and exact A2r1 observers. It delivers **59 valid Data samples before +60 s** (minimum 50); 97 memory/block samples and 60 fine CPU windows are present. The Data crossing is **(+20.099,+21.104] s**, within the pre-declared (+9.292,+21.328] s timing screen. A2r1 crossed in (+19.085,+20.090] s. Sampling endpoints and one pair do not establish a fill-rate change.

At +21.104 s Data free is 12.238281 MiB; the last sample is **5.574219 MiB at +430.659 s**. The initial fill therefore persists even with zero sampled WFE. Last syscall errno-28 total=**7310**, writer overflow=0, dedicated WindowServer total=0. All received block windows/accounting and old-overflow breakdowns reconcile, with zero new context overflow. APFS printed 1872 ENOSPC lines; one-to-one syscall correlation remains unavailable and those prints must not be added to syscall/block totals.

Free memory reaches **3502 pages = 13.679688 MiB at +43.197 s**. At that instant active=381433, inactive=389529, speculative=10569, wired=262184; this is a sampled free-page floor with potentially reclaimable pages, not proof of global OOM. Last sampled free=197736 pages = **772.406250 MiB** at +430.658 s. Nothing here supports blindly adding another 512 MiB of wired Data storage.

At closely matched coarse CPU endpoints, ReportCrashServi still consumes substantial CPU:

| Metric | A2r1 +237.916 s | A3r1 +237.933 s |
| --- | --- | --- |
| Cumulative CPU | 63098 ms | 55122 ms |
| Exits | 31 | 27 |
| Last approximately 30 s CPU window | 2108 ms | 1904 ms |

The cumulative difference is -7976 ms at those near-matched endpoints; one pair does not attribute the change to removed WFE events or establish repeatability. Latest emitted A3r1 ReportCrashServi row at +297.963 s reports cumulative 56864 ms / 28 exits; later filtering means that is not a terminal total. Two jetsam kills are recorded, both ReportCrashService per-process-limit, versus three in A2r1. Crash/report/symbolication churn remains.

Nine capped detailed faults arrived: expected parkd x3, pre-existing ReportCrashServ packed-SIGKILL x2, appinstalld packed-SIGABRT x3, locationd x1. No WFE detail is present. This differs from A2r1's 13 details by the three WFE process records and one ReportCrashServ detail; caps and timing prevent a unique-crash interpretation. Last sampled fault hook total=25, overflow=0 (not unique faults). EXC_CRASH high bytes remain terminating signals, not DYLD/EXEC namespaces.

Last vnode num=66560/free=48966: **17594 in use (26.4%)**, no exhaustion indicated. First >=95% idle sample aggregate tot=517201 gives an eight-CPU proxy **64.650 s**, versus A2r1's 84.521 s. This proxy and one pair do not constitute a performance or quiescence attribution.

## 5. Output, artifacts and next diagnostic

Received tagged observer bytes=**318570** within the 524288-byte budget; maximum observer line=**187 B**. Last output summary has suppressed=0, line_trunc=0, summary_failed=0. Hook ring_drop=0 and saturation=0; history_overwrite=94 and payload_trunc=87 remain explicit history/decode limitations. They are not silent snapshot loss. Byte totals after the last output summary differ from its sampled byte count as expected.

Artifacts include `boot-record.json`, `capture-assessment.json`, `analysis-a3r1.json`, `comparison-a3r1.json`, `Data-space-series.csv`, `memory-series.csv`, final raw-frame exports/validation JSON for 60/120/300 s, raw USB/chunk trace and automatic-reset log. Reproduce the pre-frozen comparison with:

```sh
python3 scripts/liuqin-analysis/r101/a3r1/analyze-result.py out/liuqin-r101-a3r1-work/evidence/a/boot-A3r1-20261121-091739
```

The corrected image is the appropriate nTWE baseline for subsequent work. The next diagnostic is **clocksyncd's own waits/stacks and IOTimeSyncDaemonService readiness**, with its main-executable base/UUID and shared-region identity; do not reuse WindowServer's slide for that executable. No TimeSync, display, Metal or network behavior has been selected from this run. B and Data resizing remain deferred, owner-key disposition remains an owner item, and no key operation occurred.

Per the user's updated authorization, future necessary volatile experiments can proceed without another per-boot confirmation. This result records one A3r1 boot and automatic return to verified fastboot; it makes no new flash or key authorization.
