# Liuqin r101 A5 / A5r1 — clock readiness is pending

**Verdict:** A5r1 identifies **Gate 2, the clock-manager availability callback**, as the pending readiness stage. At 60/120/300 s the typed local clock notifier has **matched_count=0, pending_count=1**; the clock singleton, diagnostics object and daemon server are nil. The local gPTP notifier has not been created. All three qualified state reads agree, with no failed target reads. **Inference:** clocksyncd has not progressed through its clock-ready callback to the gPTP subscription/listener stage. The missing gPTP manager is therefore not the currently observed wait.

**Measured:** A5r1 completes 480 s, exit0 `complete-observer-capture`, with automatic return to verified fastboot and no guard abort/disconnect/panic marker. A3r1 remains the behavior baseline. No en0, dummy service, display, Data-size, partition, flash, signing or owner-key change was made.

**Important correction:** the first A5 boot read the wrong notifier implementation (framework `_TSF_` classes rather than clocksyncd's local classes). It produced an honest null result and is preserved separately. A5r1 corrects that observer error; neither capture is hidden or rewritten.

## Identity and scope

Capture: `out/liuqin-r101-a5r1-work/evidence/a/boot-A5r1-20261121-102912/` (2026-11-21, Asia/Shanghai).

| Artifact | SHA256 |
| --- | --- |
| Accepted A3r1 behavior baseline boot | `85e02fede9faad5527010843d073ab50c208fa45f3423437780835f9e0d13be9` |
| A5r1 boot | `013687e48b19f1e17f3de8d8dff5d31fabf3f2f23cb182f4f4a98142aa10a434` |
| A5r1 kernel | `d278f549faa400e706be4ddb730be4f8f726951a83b36bb97e21a50bb5fd2df1` |
| Raw USB | `3027bc2c87322f9ca188ed025c2c614368a89fdb889a224d5c0bf8e82ad37290` |
| Host guard trace | `83806c8655fd0a1733bb8a084f2e900ba044c402beb676e36046c8a3b69da658` |

A5 changed two observer files from A4; A5r1 changes only `liuqin_r101_walk.inc` from A5. USB transport/bookkeeping, snapshot fence, early sampler, 999-byte args, ADT, trust bundle, device/driver files and nTWE instruction are unchanged. Host source/package tests pass. TEXT `0x1cc000`, DATA `0x27c000`, TEXT_EXEC `0x9a4000`; const VMA `0xfffffff0070062e0`, **2528 B above the gate**. Runtime Data capacity remains **512 MiB**. Standing user authorization removes a separate-go requirement; both volatile boots have scope/authorization records.

## The A5 audit error and correction

A5's initial host audit correctly described framework `_TSF_TSDKextNotifier` and its count layouts, but failed to verify which implementation clocksyncd calls. The executable defines its own `TSDClockManager`, `TSDgPTPManager` and `TSDKextNotifier`. Chained fixups prove the actual GOT/class references are **rebases into the executable**, not binds to the framework copies:

| Actual reference | Main-image rebase target |
| --- | --- |
| GOT TSDClockManager `0x100063448` | `0x10006d918` |
| GOT TSDgPTPManager `0x100063498` | `0x10006d8c8` |
| TSDKextNotifier class reference `0x100062c80` | `0x10006ce28` |

A5 completed 480.204 s, exit0, clean 60/120/300 s snapshots and 2198 exact guard calls. Its valid main-image reads show a typed nonnil daemon and nil server at all three times. Seven framework-global reads per snapshot returned EFAULT; these were never decoded as nil. Its scientific readiness outcome remains **unknown**. The old source/audit/decoder/raw assessment are immutable. [A5 result](../a5/liuqin-r101-a5-result.md) and [corrective audit](liuqin-r101-a5r1-host-audit.md) disclose the error and exact evidence.

A5r1 uses own main base plus the local offsets `0x6e1a0/0x6e180` for clock/gPTP notifiers and adjacent singleton/queue/once globals. Shared-cache slide is used only for actual libobjc/CoreFoundation data. Local notifier field offsets and availability semantics were independently verified on the local implementation before coding the correction. A regression test rejects the old framework addresses. No behavior fix was bundled.

## Capture integrity and read bounds

**Measured:** 120 s fastboot cooldown; **480.250 s**, **936174 B** raw capture; 82 registration end markers. Exact replay passes all **2128** guard calls, max_pid=307, max_si=6, no fatal/abort. Fastboot serial `be7ca114` was verified by cleanup and checked again after analysis.

| Snapshot | Count / FNV-1a | Prefix USB completion | State outcome |
| --- | --- | --- | --- |
| 60 s | 270 / `a18acb3964956be2` | 12 ms | clock_pending |
| 120 s | 142 / `0e1e981378ba3894` | 5 ms | clock_pending |
| 300 s | 142 / `fe17c9a8b880263c` | 4 ms | clock_pending |

All counts/hashes verify directly against raw log bytes. Inherited observer, both-task target, and bounded state protocols all pass. No embedded observer prefix/framing recovery is needed in A5r1. Ring drop, saturation, writer overflow, block-context overflow, suppressed output, line truncation and summary failure are zero. All block windows and history references reconcile. New observer records total **229731 B**, maximum **187 B including LF**, under the original 512 KiB / 253 B limits. Last device OUTPUT reports bytes229620/detail127307; complete-host totals include its later emitted records and other observer-prefixed accounting.

Per snapshot: **25 target word reads / 400 B**, plus one invalid-address probe; native attempts=26 and unavailable=1 includes that known **EFAULT=14 probe**. All 25 actual state records have rc=0. The bound remains 64 requests; no faulting reads, target calls/writes, pointer-authentication execution or suspension were added. Identity checks and all reads remain behind the existing fail-closed USB completion fence. **`native_reader_validated=false`** remains independent of these successful observations.

## Qualified live state

**Measured:** clocksyncd pid152, main tid939 / workqueue964. Own main base **`0x10042a000`**, UUID **`91f59f6a64c3321c88b00cc7a485ab1c`**, subtype `0x80000002`; own main relocation **`0x42a000`**. Its recorded shared slide is **`0x6ea0000`**, cache UUID **`8b1e17c672d6301791a4916022e3612e`**. These are separate recorded identities/relocations, not borrowed from WindowServer.

All three snapshots give the same state:

| Qualified field | Measured value |
| --- | --- |
| TSDDaemon global | `0x100c7f6c0`, stable; ISA matches own TSDDaemon class |
| Diagnostics / server fields | `0 / 0`, stable |
| Local clock notifier | `0x100c7e650`, stable; ISA matches own TSDKextNotifier class |
| Clock matched-ID set | `0x100c7e690`, exact `__NSSetM` ISA; **count 0** |
| Clock availability array | `0x7a52c0c090`, exact `__NSArrayM` ISA; **count 1** |
| Clock singleton / queue / once | `0 / 0 / 0` |
| Local gPTP notifier / singleton / queue / once | `0 / 0 / 0 / 0` |
| Match / terminate notification objects | both nonnil |
| Shared matcher notification queue | nonnil |

ISA constants and CoreFoundation storage/count offsets match their pinned values live. Counts are decoded only for those exact classes. Nil values above have successful reads and stable rereads; no failed read becomes nil. The local availability implementation checks matched count, queues retained callbacks when zero, and invokes/clears them after matching. The typed daemon rules out nil initialization; nil server rules out the created/resumed-server outcome at the sampled times. Clock singleton/queue/once staying zero also supports not reaching the clock callback's `sharedClockManager` call.

**Inference:** the unique supported branch is **clock availability pending**, before gPTP readiness subscription and before expositor listener creation. The availability array counts callbacks retained by this process's notifier; individual callback block ownership was not decoded. Reads are racy and bounded, not an atomic or suspended object snapshot. Repeated identical state strengthens the finding without removing those limits.

clocksyncd remains in the same main CFRunLoop receive path. Each snapshot has 9/10 plausible raw daemon return candidates; the tenth is a terminal zero LR, preserved as unresolved, so the whole raw-record callsite-validation flag remains false. All 9 nonzero candidates pass. WindowServer pid106, main tid582 / workqueue970, has 17/17 plausible candidates at each snapshot and remains in its synchronous TimeSync XPC reply wait. Raw candidates, UUID/SHA checks, executable/cache relocation and symbolication are preserved separately; no independently validated backtrace is claimed.

## Why a registry object can coexist with zero clock matches

All three valid untruncated sweeps (228/227/227 visited nodes, hits=4, exact_daemon=1) show the same root/clock-manager/translation/daemon services as A4. `IOTimeSyncgPTPManager` remains absent. This is **registry presence**, not a measured registered-state bit or delivered first-match notification.

The new [kernel host follow-up](liuqin-r101-a5r1-kernel-followup.md) gives a concrete publication branch in the original SHA-pinned IOTimeSyncFamily:

- `IOTimeSyncClockManager::start` attempts `findTimeSyncTimeClockID`, creates its translation child, then calls **registerService** only on the branch whose clock-ID-ready byte is set.
- The alternative branch sets up **IOEthernetInterface / TSNInterface** matching. The ID finder scans interface candidates and MAC properties and can publish `TimeSyncTimeClockID` / `TimeSyncTimeCoreAudioClockDomain`.
- The registerService virtual slot was independently resolved through authenticated KC fixups to the exported IOService method, rather than guessed from an offset.

**Hypothesis:** clock-ID discovery is preventing publication of the already attached manager. Notification delivery failure remains an alternative. **Next evidence:** public IOService state bits, registry ID, and presence/type/value of those clock-ID properties. That separates attached/unregistered from registered-but-undelivered before an interface or notification behavior change. An arbitrary en0 is not proven sufficient by the host function's multiple candidate/filter paths. No such change or additional boot was performed.

## Data usage changed — explicitly unattributed

The pending clock state is observed on a run **without Data exhaustion**:

| Run | Data capacity | Last free MiB | Minimum free RAM MiB | Last syscall errno28 |
| --- | --- | --- | --- | --- |
| A4 | 512 MiB | 5.574 | 13.914 | 7358 |
| A5 | 512 MiB | 191.910 | 378.148 | 0 |
| A5r1 | 512 MiB | **194.309** | **411.004** | **0** |

A5r1 has 98 space samples, 59 before +60 s; no below16-MiB crossing occurs. The last sample is +450.644 s; free RAM minimum is at +149.605 s. Consequently the older below16 crossing screen cannot be treated as a passed same-fill timing comparison. The Data curve is different.

This is not a resize or seed replacement: the **exact 74048 compiled seed bytes** occur uniquely at standalone offset `0xde0000` in A4, A5 and A5r1, all SHA256 **`072eda49e3a55e5c7e762604cdf7406d9a2421e23a8d26ea557f6f6723c32505`**. Device sources, args, ADT and trust are identical. A fresh audit of the current assembled tree checks **6132 non-observer baseline files, zero differences or missing files**, against frozen r100b. New state reads start at +60 s, after the early usage divergence. Kernel bytes/layout/observer code are different; the usage change remains **unattributed**, not an improvement claimed for A5. No causal crash/CPU/performance assertion follows.

**Inference limited to necessity:** an exhausted Data volume is not required for the pending clock readiness state observed here. Its underlying publication/notification cause still needs the evidence above.

All eight CPUs retain nTWE=1/nTWI=0. Uncapped WFE/undefined-word events=0, overflow=0 through **+450.644 s**, with no raw WFE detail in the capture. Last aggregate EL0 fault count is **6**; only **3** detailed records were received, all expected parkd denial signatures, with the per-name detail cap retained. Do not turn the detail inventory into a claim of only three total faults. Jetsam=0; vnodes num66560/free50683/dead350. **EL0 TRAP=0 does not mean zero faults.** No Data increase is proposed.

## Preserved evidence and disposition

The capture contains raw USB/trace, immutable boot/assessment records, session authorization, state words and strict decoder outcomes, both tasks' raw frames/validation, `analysis-a5r1.json`, and Data/memory CSVs. Preboot manifest, corrected host audit, full-source/compiled-seed audits, kernel publication disassembly and separate result manifest are under `out/liuqin-r101-a5r1-work/evidence/`.

Both A5 and A5r1 were volatile observer boots under existing authorization. Their records and the earlier A4 raw exit5 are preserved. A3r1 remains the accepted behavior baseline. Device is verified in fastboot. Owner-key disposition and real-key offline signing remain untouched owner items.
