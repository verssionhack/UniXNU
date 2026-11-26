# Liuqin r101 A6 — clock manager attached, unregistered, no clock ID

**Verdict: the predeclared publication-gate branch is confirmed.** At 60/120/300 s, IOTimeSyncClockManager has public state **0**, registered=0, matched=0, inactive=0, and **neither TimeSync ID property exists**. In the same sweeps IOTimeSyncDaemonService and IOTimeSyncTranslationMach both have state **0x1e**, registered=1/matched=1/inactive=0, with distinct nonzero registry IDs. The local clocksyncd clock notifier still reports **matched_count=0 / pending_count=1**.

**Measured:** one volatile 480 s capture, exit0 `complete-observer-capture`, all snapshot/target/state/publication protocols pass, automatic return to verified fastboot `be7ca114`; no abort, panic marker or USB disconnect. **Inference:** missing clock-manager publication is the active Gate 2 boundary; the alternative “already registered/matched manager whose notification failed to reach userspace” is not the observed branch. Why clock-ID discovery has not succeeded remains a host-grounded hypothesis, not a live internal-flag or selected-interface measurement.

The [complete host interface/branch contract](liuqin-r101-a6-host-contract.md) is ready for review. No interface, en0, dummy service, display or Data-size behavior change was built or booted. A3r1 (`nTWE=1`) remains the behavior baseline; no partition, flash, signing or owner-key operation.

## Capture identity and implementation

Capture: `out/liuqin-r101-a6-work/evidence/a/boot-A6-20261121-150526/` (2026-11-21, Asia/Shanghai).

| Artifact | SHA256 |
| --- | --- |
| A6 boot | `1cdc0aaac49066ae68e84e879c2fe32b9d88831711640407533e2dd49eca4566` |
| A6 kernel | `ce3b2d20657fb0ff10c9b27dfe70b73935bed407a8d851773478b1a46049afd2` |
| Raw USB | `1c37b41fb8147d927f963cb700572e5eb18bc53d0cfff83d89c54ba025f48611` |
| Per-chunk host trace | `7e0ecdb910d06ec3274fc2e473634a60527d0d42f146c1220cac7c261f276684` |
| Parent A5r1 boot | `013687e48b19f1e17f3de8d8dff5d31fabf3f2f23cb182f4f4a98142aa10a434` |

Only `iokit/Kernel/IOUserClient.cpp` changes from A5r1: a public read-only helper within the existing TimeSync sweep. It reads getState/getRegistryEntryID and retains/releases two local properties. No new user-memory table, service publication, matching registration, loading or waiting is added. All existing waits, version6 local state reads, USB/fence/early sampler, 999-byte args, ADT, trust and device/seed/driver files match A5r1. Public-property numeric zero is distinguished from absence; a present unsupported type remains explicitly undecoded.

TEXT `0x1cc000`, DATA `0x27c000`, TEXT_EXEC `0x9a4000`; const VMA **`0xfffffff0070061e0`**, **2272 B above the gate**. Segment/const and actual fileset AES/header-vs-payload gates pass. No cap relaxation or observer retirement was needed. An initial host compile used `.get()` on OSPtr, which is a raw-pointer alias in this configuration; it was corrected to explicit retained-reference release before any boot. The failed build log is preserved.

Tests cover the exact C++ helper's positive controls, numeric zero, absent/wrong type, balanced releases and record cap; eleven decoder cases cover branches/controls/ambiguity/alias IDs/bit consistency. Monitor AST matches A5r1; all 2128 A5r1 guard calls replay before A6. All 127 prior result-manifest entries remain unchanged. Session authorization records the explicit A6 observer scope and standing withdrawal of separate-go requirements.

## Integrity and live publication state

**Measured:** 120 s cooldown; **480.184 s**, **905712 B** capture; **2196** exact guard calls replay cleanly, max_pid=304/max_si=6. No recovery/framing split is needed. Ring drop, saturation, writer/context overflow, suppression, line truncation and summary failure are zero. All block windows/history references reconcile. Observer records total **234093 B**, maximum **187 B including LF**, below the 512 KiB / 253 B limits. Last OUTPUT is bytes233016/detail129286; its native emission precedes the final host inventory. History overwrite94 and payload trunc87 retain their bounded-history/undecoded-IPC meaning.

| Snapshot | Count / FNV-1a | Prefix USB completion | Publication outcome |
| --- | --- | --- | --- |
| 60 s | 272 / `77d95786c8e19c12` | 13 ms | unregistered, no ID |
| 120 s | 144 / `9f498d328588dd3b` | 5 ms | unregistered, no ID |
| 300 s | 144 / `b211dd6c477e3133` | 4 ms | unregistered, no ID |

All counts/hashes verify directly against raw USB. The kernel traversal remains valid/untruncated, visiting 230/228/228 nodes and reporting four TimeSync hits each time.

The following values are identical in all three snapshots. IDs identify entries **within this boot**:

| Class | Registry ID | State | Registered | Matched | Inactive |
| --- | --- | --- | --- | --- | --- |
| IOTimeSyncRootService | `0x100000212` | `0x1e` | 1 | 1 | 0 |
| **IOTimeSyncClockManager** | **`0x100000213`** | **`0`** | **0** | **0** | **0** |
| IOTimeSyncDaemonService | `0x100000214` | `0x1e` | 1 | 1 | 0 |
| IOTimeSyncTranslationMach | `0x100000215` | `0x1e` | 1 | 1 | 0 |

On manager ID `0x100000213`:

| Property | Present | Type | Decoded |
| --- | --- | --- | --- |
| TimeSyncTimeClockID | **0** | none | 0 |
| TimeSyncTimeCoreAudioClockDomain | **0** | none | 0 |

The zero value placeholders in those raw records are **not numeric property values**. Both properties are absent, rather than present OSNumber zero or present unsupported objects. Successful controls reject a blanket zero/incorrect bit interpretation; distinct IDs prevent conflating manager and controls. These are repeated public-state/property observations, not an atomic suspended registry snapshot or a direct read of the private +0xbb byte.

## User-state correlation

clocksyncd pid145 (main tid908 / workqueue918) has own main base **`0x100458000`**, UUID **`91f59f6a64c3321c88b00cc7a485ab1c`**, subtype `0x80000002`; shared slide **`0x3a7c000`**, cache UUID `8b1e17c672d6301791a4916022e3612e`. Own executable relocation and this task's shared slide remain distinct and qualified.

All three inherited state snapshots show:

- Typed nonnil daemon **`0x100bb7830`**, stable; diagnostics/server **0/0**.
- Typed local clock notifier **`0x100bb5440`**, matched set **count0**, retained availability array **count1**.
- Clock singleton/queue/once **0/0/0**; local gPTP notifier/singleton/queue/once **0/0/0/0**.
- All **25 actual state reads rc=0**. STATE_END attempts26/unavailable1 includes only the expected **EFAULT=14 invalid-address probe**; no target page was unavailable.

**Inference:** clocksyncd is waiting for publication of the manager before its clock-ready callback, gPTP subscription and expositor listener creation. The absent gPTP manager is downstream, not the active wait. Callback counts cover this process's notifier; individual block ownership was not decoded and the state reads remain racy.

WindowServer pid111 (main tid688 / workqueue948) remains in the same 16-frame synchronous TimeSync XPC reply wait. Its main 16/16 return candidates pass callsite checks at every snapshot; the workqueue has zero saved user registers in this run, so no workqueue frames are fabricated. clocksyncd has 9/10 plausible candidates per snapshot, with the terminal zero LR preserved unresolved; the whole raw-record validation flag stays false. Both processes retain **`native_reader_validated=false`** despite identity checks, successful reads and callsite plausibility.

## Host branch audit completed

The host-only audit uses the original KC SHA256 `d1003b5143ffd88439b4d45b6017f587171cfe6855660bed05370a2ea5db9fe9`. It covers the entire finder, its functional cold TSN outline, all priority/fallback groups, sorting helper, initial publication, notification wrapper/body and delayed retry. Extra failure outlines and their two shared formatting helpers were checked: allocation/no-candidate exits log and return without setting readiness, rather than supplying another eligible-interface path. Raw code and authenticated virtual-slot mappings are preserved.

The verified contract is more specific than “add en0”:

1. Genuine IOEthernetInterface metaclass/lifecycle, working controller/prefix/unit getters, and eligibility under the wired-builtin, Wi-Fi-builtin, or fallback filters. Builtin must be **OSBoolean true** when relying on the builtin groups.
2. **OSData IOMACAddress** on interface or controller; use a proper six-byte valid stable address. Short-data permissiveness in the error/log path is not a sound experiment contract.
3. For arrival after manager startup, a nonnull **`BSD Name`** property before matching notification, proper registration, and a controller not excluded by the verified Thunderbolt/USB-copy filters.
4. The ID finder chooses the first priority group's ordered candidate; it publishes OSNumber64 TimeSyncTimeClockID and OSNumber32 TimeSyncTimeCoreAudioClockDomain, sets the ready byte, and the initial or delayed path then invokes the independently verified **registerService** slot. Delayed retry includes the documented platform quiet/sleep boundary.

There is **no literal en0 requirement**, and an IOService merely named IOEthernetInterface does not satisfy the real metaclass/virtual/lifecycle contract. The full audit preserves numeric TSN types, exact filter/order conditions, MAC fallback and ID construction rather than assigning unverified enum names or assuming any existing fixture works.

**Measured conclusion:** manager publication is missing at the sampled times. **Hypothesis for a future proposal:** no eligible interface has supplied a clock ID. A6 does not inventory rejected interfaces, read private ready state, or prove the exact failed candidate/filter. The verified host contract can now ground a separately authorized single-variable interface experiment; none is built or executed here. No direct clock-service publication bypass is proposed.

## Context and disposition

A6 retains 512 MiB Data with **191.992 MiB free** at the last sample (+430.663 s), **0 errno28**, minimum sampled free RAM **376.695 MiB** at +139.578 s, and jetsam0. Thus ENOSPC did not recur or block this observation; the earlier A4→A5 storage divergence remains unattributed and was not investigated further. There are 59 usable early space samples. Vnodes num66560/free50504/dead509.

All eight CPUs read nTWE=1/nTWI=0. Scale readback remains chosen-DT40, effective_ticks503316480. Uncapped undefined-word/WFE events0/overflow0 through **+430.663 s**; no raw WFE detail appears in the capture. Aggregate EL0 fault count6; three received detailed records are expected parkd signatures, with the legacy detail cap retained. **EL0 TRAP=0 does not mean zero faults.** No performance or fault-rate improvement claim follows.

Artifacts include original boot/assessment, authorization, raw USB/trace, publication/state outcomes, both target frame exports/validation, `analysis-a6.json`, Data/memory CSVs and the completed host branch inventory. Preboot manifest is `out/liuqin-r101-a6-work/evidence/review-manifest.json`; final analysis is frozen separately by a result manifest. Device is verified in fastboot. A3r1 stays the behavior baseline; all explicit behavior/key/flash holds remain.
