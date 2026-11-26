# r101 A4: targeted TimeSync observation

A4 adds observers to the accepted A3r1 behavior baseline (`85e02fed...`). No behavior fix is included. The user's session authorization permits volatile observer boots without a separate go. No flash, partition, signing or owner-key operation is involved.

The source delta is confined to four observer locations: worker orchestration, native task wait capture, bounded nonfaulting main-image identity reads, and a read-only IOService registry traversal. `start.s` (nTWE=1), USB transport/fence, early sampling, 999-byte arguments, ADT, trust bundle, device drivers and 512 MiB Data seed remain identical to A3r1.

Each 60/120/300 s snapshot labels WindowServer and clocksyncd waits and walks separately. A second 64-entry scalar bank prevents one task overwriting the other. Tasks are retained independently; PID lookup rechecks the process name. The saved registers remain racy: neither target is suspended. Per-target depth is 16 and candidate output is capped at 64 frames, 128 maximum per snapshot. Thread coverage and truncation are explicit.

The worker records each task's own shared-region identity and `mach_header_vm_address` before the fence. Behind the same fail-closed, 2000 ms USB completion fence, it performs the invalid-address test, reads the main Mach-O header and at most 128 commands / 32768 command bytes using faults-disabled target-map copyin, and reports LC_UUID/subtype or an explicit coverage failure. Main-image reads and both walkers run last. Metadata pages that are unavailable are never faulted in.

Host validation selects clocksyncd's actual host slice using live UUID/subtype and pinned full-binary/slice SHA256. Its main-image relocation is load-base minus host `__TEXT` vmaddr. Shared-cache frames use clocksyncd's own captured shared slide and cache UUID. No WindowServer slide is borrowed. Native-reader validation remains false even when return addresses follow plausible BL/BLR callsites.

The TimeSync sweep visits the IOService plane recursively, counts exact `IOTimeSyncDaemonService` metaclass matches, and prints class/name/provider for TimeSync, gPTP and Clock substrings. It caps visits at 4096 and printed hits at 64, reports counts/truncation/iterator validity, and registers no notification, publishes no service and changes no property. A complete zero count supports absence in this plane at the stated snapshot; it is not a claim about unavailable kexts or all possible class names.

The 512 KiB total / 448 KiB detail budgets, 96 KiB reservation per snapshot, line cap 253 B including LF, hook drop counters, reliable worker writes, snapshot FNV-1a checksums, existing abort guards and exact replay remain. Added two-target evidence consumes budget; actual output totals and all loss flags are acceptance gates. Exceeding a bound is incomplete evidence, not a negative dependency result.

Host tests exercise the exact native metadata parser (8 cases), both pinned executable slices, UUID/SHA mismatch rejection, target-section isolation, and unbalanced phases. The initial build failed because this kernel has no `strstr` declaration; a local bounded-caller substring helper replaces it. No failed candidate was booted.

## Predeclared run and interpretation

One volatile `fastboot boot`, 120 s fastboot cooldown, 480 s capture, existing guards, automatic verified fastboot return. Preserve all logs and per-chunk timestamps. No repeat or behavior boot is part of this capture.

Success requires the inherited observer contract plus three complete target-labelled captures for each task, own main-image identity, bounded frame evidence, and three valid untruncated TimeSync sweeps. Frame callsite checks and symbolication are reviewed separately; they do not independently validate the native reader.

- clocksyncd's main stack in `DaemonServiceMatcher.waitForService` and absence of `IOTimeSyncDaemonService` supports gate 1 (the forever semaphore before daemon start/listener creation).
- Daemon readiness/runloop evidence after that gate requires identifying the clock-manager or gPTP callback boundary before any fix.
- A listener/worker stack inside shared sync-entity initialization points to the post-listener reply boundary.
- Generic waits, unavailable identity, truncated registry or unresolved frames remain a null/incomplete result. No en0, dummy service, display, Metal or Data-size change follows from a null answer.

WFE histograms, SCTLR readbacks, Data fill and memory are context checks against A3r1. EL0 TRAP=0 does not mean zero faults. Owner-key disposition and real-key offline signing remain owner items outside this run.
