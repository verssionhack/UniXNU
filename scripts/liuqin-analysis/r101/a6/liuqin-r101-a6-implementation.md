# r101 A6 — public clock-manager publication state

A6 extends only the existing TimeSync IOService registry sweep. A3r1 remains the behavior baseline: nTWE=1/nTWI unchanged, 512 MiB Data, no interface/dummy-service/display change. No flash, partition, key or signing operation. The standing session authorization permits the volatile observer boot without a separate go.

One static helper in `iokit/Kernel/IOUserClient.cpp` records public `getState()` bits and registry entry ID for each existing TimeSync/Clock/gPTP sweep hit. It prints state/registered/matched/inactive and labels the source IOService. The same record is emitted for **IOTimeSyncDaemonService and IOTimeSyncTranslationMach** in the same sweep as the manager; the daemon supplies the in-run positive control. No classes are allocated, registered or waited for by the observer.

On IOTimeSyncClockManager it retains each of two local properties with `copyProperty`: **TimeSyncTimeClockID** and **TimeSyncTimeCoreAudioClockDomain**. Each record includes presence, runtime type, decoded flag, OSNumber bit width and unsigned value. Missing values are marked present=0/decoded=0/type=none; a present non-number is explicitly undecoded and cannot be mistaken for absence. A numeric zero is a present value. Every retained object is released after the record. The initial compile exposed OSPtr being a raw-pointer alias in this configuration; the helper uses explicit raw retained references/releases accordingly. The failed build was not booted.

All existing user-memory tables, waits/stacks, version6 state reader, USB completion bookkeeping, abort guards and early sampling are byte-identical to accepted A5r1. Public property/state reads occur during the existing kernel-registry prefix stage, before the unchanged fail-closed completion fence and final user reads. State and property reads remain separate observations, not an atomic registry snapshot.

## Gates and tests

Host source/package checks PASS: only IOUserClient.cpp changes; args999B, ADT, trust, device/seed/driver sources and segments match A5r1. TEXT `0x1cc000`, DATA `0x27c000`, TEXT_EXEC `0x9a4000`; const VMA **`0xfffffff0070061e0`**, **2272 B above `...5900`**. The actual fileset AES/header-vs-payload gate passes. No observer retirement or cap relaxation was needed.

Tests execute the exact C++ helper with mocked public objects to check positive control bits, registry ID, numeric zero vs absent/wrong type, balanced retained-property release and record length. Eleven host decoder cases check decision branches, failed controls, alias IDs, missing/duplicate properties, inconsistent flags, unsupported types and inactive objects. Guard Monitor AST matches A5r1; all 2128 A5r1 guard calls replay exactly. All 127 prior result-manifest entries are checked unchanged.

The host-only [complete branch audit](liuqin-r101-a6-host-contract.md) covers all candidate priority groups, the functional cold TSN fallback, prefix/unit ordering, MAC extraction and ID construction, initial publication, interface callback scheduling and delayed publication retry. It verifies vtable slots using KC authenticated fixups. It defines a meaningful interface-side contract without implementing or authorizing it.

## Fixed run criteria and branches

One volatile boot, 120 s fastboot cooldown, 480 s capture, unchanged guards, automatic verified fastboot return. Preserve all artifacts and raw verdicts. No behavior boot follows this capture.

Require all existing 60/120/300 s snapshot checksums/target/state protocols plus unique nonzero IDs and consistent public-state records for manager, daemon and translation control, and two unique manager-property records per snapshot. Record all outcomes, including unknown.

- Clock manager registered bit **0**, both ID properties **absent**, daemon control registered/matched and active: **attached-unregistered/no-clock-ID publication gate**.
- Clock manager registered and matched bits **both set**, while same-snapshot clocksyncd state remains clock_pending and daemon control passes: **registration exists; investigate matching notification delivery/filtering**.
- Failed positive control, inactive manager, ambiguous/missing records, ID alias, unregistered manager with present ID properties, registered-only state, or unreadable/unsupported value: **explicit unknown/partial branch**, never absence by inference. Translation control state is always reported, not presumed to match the daemon.

Bits are statically checked against pinned XNU (`registered=0x2`, `matched=0x4`, inactive=0x1). The property schema is expected to be OSNumber64/32 by host disassembly, but unexpected runtime types remain visible. Getter/ABI and line-budget correctness are checked by the controls and package gates, not assumed from registry presence.

The 512 KiB total, 448 KiB detail, 96 KiB snapshot reserve and 253 B record limit remain. At the current four service hits the addition is six records per snapshot; the existing 64-hit cap bounds larger sweeps, with truncation explicit. Verify real totals after capture. `native_reader_validated=false` remains. **EL0 TRAP=0 does not mean zero faults.** Data-fill divergence stays context only unless it blocks further progress.
