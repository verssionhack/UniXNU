# Liuqin r101 — approved observer protocol

**Implementation checkpoint:** A/B capture images are now built and host-validated, not booted. Verified bootstrap/XPC name decoding remains unsupported, and frame walking is compiled but gated on a known user-stack fixture. See [implementation status and artifacts](liuqin-r101-implementation.md); requirements below remain acceptance criteria, not claims of live success.

Baseline: validated r100b, boot SHA256 `e38ab9fc300ae4a92377e34f6a1a3fcae4a7278137b164593ef75f675a41c417`. Labels: **measured**, **host-verified**, **inference**, **hypothesis**, **(verify)**. Approval covers this revised plan; each hardware boot still needs a separate explicit go. No en0, display-attachment fix or Metal change is authorized by an observer result alone.

## Corrected idle extraction and baseline evidence

**Measured:** `tot=994386` is a real aggregate CPU-accounting sample, not a different counter. It is the first >=95% sample in `usb-follow.log` alone, line 392. Selecting that follow-up-only sample and calling it the first for the full boot caused the erroneous ~124 s claim. The initial `usb.log`, line 5095, already has `idle_pct=96 tot=595963`, approximately 74.495 s when divided by eight CPUs. r99p's first qualifying sample is `usb.log:5004`, `idle_pct=96 tot=596005`, approximately 74.501 s. These are accounting proxies, not exact host boot timestamps. There is no established +50 s regression to attribute.

The [r100 result](../r100/liuqin-r100-result.md) is corrected; the previous report is archived in `out/liuqin-r100-work/evidence/review/`. `audit-review.py` selects the first qualifying sample in chronological capture order and now includes the source capture filename and local line number. `check-idle-extraction.py` verifies the original r99p, initial r100b, follow-up-only, combined and concatenated-sample cases, plus threshold/no-match cases. It must pass before analyzing r101. Never label a follow-up-only result as full-boot quiescence. Missing capture intervals and observer overflows must be reported separately.

## Exact variant contrast and Data size

**Measured/host-verified:** r99p and r100b differ by more than display. Full hashes and staged-file comparisons are in the [r100 review response](../r100/liuqin-r100-review-response.md) and `out/liuqin-r100-work/evidence/review/review-audit.json`.

| Area | r99p → r100b |
| --- | --- |
| Kernel SHA256 | `289bc6cc26bafc508ccaee0933cbbca54b3810e3e2e611beb197237feacc01c6` → `8d27ff88ca1d8589732b17497c27bf26bff7c528b1871eccac1bda1ebeca17f5` |
| Display | Add GopFramebuffer, archive builder, ABI fixture and LegacyDisplayProbe; enable `CONFIG_XNU_NATIVE_LEGACY_DISPLAY=y` |
| Scratch property | Add `Protocol Characteristics / Physical Interconnect Location = Internal` |
| Segment budget | Panic tail 64 KiB → 16 KiB; identical scratch seed bytes move to `__BOOTDATA,__data` |
| Arguments removed | `startup_debug=1`, `armcpu-diagnostics=1`, `liuqin_vm_sec=30`, `liuqin_page_rehash_sec=60`, `liuqin_page_rehash_count=256` |
| Deny list | Remove `/System/Library/PrivateFrameworks/Heimdal.framework/Helpers/digest-service` |
| Stand-in path | `/private/var/liuqin/parkd` → equivalent `/var/liuqin/parkd` |
| Timeout scale | `ml-timeout-lock-panic-scale=40` → u32 40 at `/chosen/machine-timeouts/lock-panic-scale` |
| Arguments added | `offline-mobile-graphics-load=1`, `offline-legacy-register=1`, `offline-legacy-gop=1`, `offline-legacy-unit-scale=2`, `offline-legacy-pm=1`, `offline-legacy-validate=1`, `offline-legacy-transfer=1`, `offline-legacy-cpu-present=1`, `offline-legacy-phase=4` |
| Other ADT delta | Different 256-byte random seed; no other property change beyond the timeout node |
| Unchanged | SMP/EPSS values, both repaired Data/parkd preparation gates, original kernelcache, trust bundle, read-only storage policy, signed task contents, 4 GiB owned-memory setting |

**Measured:** logical scratch size and APFS Data size after layout are **512 MiB in both variants**: `131072 × 4096 = 536870912` bytes. Data layout did not resize it; retained layout source is byte-identical. Initial free blocks are 124557 in both, falling to 1430 (~5.586 MiB) at the last initial-150 s sample. ENOSPC is shared: r99p has 388 and r100b 323 APFS diagnostic lines in their respective 150 s captures. Counts of messages are not counts of all errno-28 returns. Differences from r97a remain a separate question.

## Six observers and fixed success criteria

### 1. WindowServer waits, deadlines and null-answer branches

At 60/120/300 s, snapshot every accessible WindowServer thread's stable identity, scheduling/wait state, wait event, IPC object type and ownership where meaningful. Record timed versus indefinite waits and the deadline in its actual clock domain, plus snapshot time and conversion basis. Mark deadline/ownership **unknown** when not safely readable; do not interpret zero as indefinite. Distinguish a server receiving on its own port, a port-set receive, a client waiting for a reply, and a wait for IOKit matching/notification. A pointer alone does not name a dependency.

Fix the decision branches in advance:

| Observation | Interpretation and next step |
| --- | --- |
| Outstanding/failed request for a named bootstrap service, correlated to its blocked thread/reply object | Verify that service's required semantics and provider; propose supplying that specific service in a subsequent single-variable run. A decoded name alone is not proof it blocks progress. |
| IOKit matching/notification wait with an identified display-class predicate | Correlate it with registry state; propose the concrete display-child attachment/provider fix for that predicate. If the predicate names another class, investigate its actual provider instead. |
| Only generic receive waits on own ports; no outstanding request with **complete** lookup coverage | Kernel waits do not identify the dependency. Obtain user-side state through validated user backtraces and symbolication; do not infer en0, display-child or Metal. |
| Generic waits plus incomplete IPC decoding, missed snapshots, lost records or inaccessible thread state | Result is **unknown**, not “no lookup” or “no dependency.” Resolve coverage gaps before choosing a behavior change. |

Subject to segment and runtime-memory budgets, add a user-mode frame-pointer walk of at most 16 frames per thread, run from the observer thread. Read saved user PC/LR/SP/FP and retain raw values. Use a verified **non-faulting read of the target task's map**; ordinary `copyin` from the kernel observer's current map is not sufficient. Never fault in pages to obtain a diagnostic. Hold valid task/thread/map references using the native source's lifetime/locking rules. Check mapped/readable memory, alignment, user address range, monotonic stack progression, loops and bounded stack distance; stop with an explicit reason on any failure. Split output into bounded records if necessary.

Record shared-region base, slide, cache identity, architecture/address geometry, and raw versus normalized addresses for host symbolication. Do not revive the old arbitrary PC mask: use verified architecture/PAC handling, and mark an address unsymbolicatable if normalization is uncertain. A missing frame chain, optimized/elided frames or failed read is not proof the thread has no user stack.

Before applying the walker to WindowServer, validate against an already trusted thread/fixture with known call frames, expected image ranges and saved PC, and exercise an invalid/unmapped pointer without faulting the target. A newly signed fixture would require the normal separately authorized signing flow; do not use owner.key. Save the validation evidence. If validation fails or the walker does not fit, defer it explicitly and leave the generic-receive branch unresolved pending another user-side diagnostic.

**Budget status:** the bounded walker/native reader compile, but live fixture validation is pending. The panic-tail diagnostic was reduced to 8 KiB (8192 static bytes saved versus r100b); measured segment sizes and normalized control details are in the implementation report. Before building, publish segment sizes and a list of any retired diagnostics with exact static/runtime byte savings. If no acceptable retirement fits the caps, mark the walk deferred instead of silently dropping it or claiming null results are success.

### 2. Opens, bootstrap/XPC requests and decode coverage

Retain the last 50 WindowServer open attempts and relevant bootstrap requests/results before each snapshot, with uptime, thread/request correlation, full-length/truncation status and errno/result. Preserve task/port references safely; defer payload decoding and formatting out of syscall/IPC locks.

**Host-verified existing-hook coverage:** `liuqin_perf_record_kmsg(int spid, int rpid, uint32_t msgh_id)` in the retained `bsd/dev/liuqin_perf.c` only tallies message ID and process-name pairs; `ipc_kmsg.c` supplies those three values. It does **not** decode a bootstrap name or an XPC payload. Existing `UI_KMSG` records cannot establish “no lookup.” A name decoder and request/reply correlation are new work.

Verify message layouts against the actual launchd/libxpc ABI, including XPC-carried lookups and inline/out-of-line forms. Never infer a name from a message ID or port number alone. Unsupported XPC layouts, short/oversize payloads, unavailable out-of-line data or copy failures must produce explicit undecoded reasons, not empty service names.

At each window and snapshot, emit `observed`, `candidate`, `endpoint_unknown`, `decode_attempted`, `decoded`, `undecoded`, `truncated`, `dropped` and outstanding-request counts. Define denominators: `decode_attempted = decoded + undecoded`; truncation/failure reasons may be subsets and must not be added as independent totals. Track observation start time so an earlier unobserved request is not excluded by assumption. A zero decoded-name count means no lookup only with verified endpoint coverage, capture from before the relevant startup, and no undecoded/truncated/dropped records. Otherwise report **decode coverage incomplete**.

### 3. Data space and ENOSPC writers

Every 10 s, record Data device/UUID, total/free/available blocks, block size and uptime. Add uncapped, overflow-detectable errno-28 counters by process, with bounded pid/path/errno examples and per-window totals beyond the old 20-line detail cap. Report failed-write attribution separately from asynchronous block-writer context. Keep file-write and block-write counters separate; do not add them together. Report inaccessible paths, truncated paths and counter/ring overflow explicitly. Success requires named writers and a space time series; message totals alone are insufficient.

### 4. CPU, faults, jetsam and vnodes

Emit top 15 TASK_CPU rows plus pinned tasks with explicit uptime/dt, CPU milliseconds and overflow counts. Compare matched windows and repeat spread; do not sum header totals with process rows.

For each EL0 fault, classify **expected by an identified existing policy**, **pre-existing unresolved**, **new occurrence in this comparison**, or **unknown due to incomplete coverage**. Match task plus exception/signal/code and, where verified, cache-relative PC/image identity; preserve raw addresses and symbolication confidence. Recurrence alone does not make a fault expected, and one absent/capped sample does not prove a fault globally new.

Use the r99p/r100b raw-log inventory: three parkd code-0x9000000 reports in each are expected consequences of the current denied-daemon/AMFI arrangement; locationd, ReportCrashService and appinstalld failures are pre-existing unresolved. AirPlayXPCHelper and mediaremoted SIGILLs are new process occurrences in r100b's compared 150 s, sharing an instruction subcode previously seen in lsd. They are not automatically expected. Reclassify only with evidence. **EL0 TRAP=0 is not zero faults.** Report fault-detail caps alongside totals, jetsam totals/causes, vnode/free/dead counts and Data pressure in every result.

### 5. Data ancestry and keystore view

Dump Data's IOMedia/provider ancestry, UUID/device identity and Protocol Characteristics values. Preserve the existing identity checks: r100b selected disk8s1, and its selector returns a match only after finding a LiuqinScratchDisk ancestor. The observer verifies the property view; it must not presume an unrelated volume or a successful keystore initialization. Classify missing/unreadable properties explicitly.

### 6. Effective timeout-scale readback

At lock-panic timeout initialization, print DT lookup success/length/value, boot-arg override state, selected source and effective scale. **Required effective scale: 40 in both variants.** Source is expected to differ: r99p uses its boot argument; r100b uses DT. A different selected source is not a failure. Neither a packaged DT value nor silence is live readback proof.

## Common-source control reconstruction and acceptance

Adding absent observers changes kernel/image hashes and may affect timing. Use isolated work directories and preserve all r99/r100 source evidence and binaries before touching the shared generated build tree. Use one identical observer patch for both variants.

The contrast is **not** a quiescence-regression test. If both variants wait on the same correlated object under adequate coverage, display enablement did not distinguish that observed wait; this does not prove every display path is irrelevant. A changed wait requires diagnosis, not an automatic behavior fix.

Before a control run, publish hashes of the frozen inputs, their raw nine-file variant diff, the common observer patch, and an explicit frozen-to-common normalization patch. Where variant source differences exist (GOP inclusion, Internal property, panic-tail size and seed placement), encode them as documented build/configuration choices in a shared source base while preserving each variant's original behavior. Then publish the post-observer source diff: common source and observer code must be identical, with differences limited to the enumerated variant configuration/fixtures. Do not call the original raw variants configuration-only, hide source differences as “observers,” or claim this gate already passed. If faithful reconstruction/common-source validation is not possible, report the control unavailable; do not silently substitute another baseline.

Fix these **provisional acceptance bounds before building/running** the reconstructed r99p control:

- Exactly 82 registration end markers, eight CPUs online, matching EPSS maxima, zero trustcache denials and no panic/abort guard.
- First >=95% idle crossing at 60–90 s using the same aggregate CPU accounting / 8 proxy (historical value ~74.5 s). This is a screening band of roughly one to two observer intervals, not a measured variance or an equivalence proof. Retain absolute/relative timestamps and subsequent busy bursts.
- Data remains 512 MiB; starts with approximately 486.55 MiB free and shows the historical pressure pattern by 150 s: nonzero ENOSPC, named logging/symbolication/launchd writers and <=16 MiB free. Do not require an exact ENOSPC print count. If this differs, preserve it and mark baseline acceptance unresolved rather than changing storage behavior to force a match.
- Preserve expected-versus-new fault classification and report jetsam/vnode data. Any unexplained reconstruction difference withholds a causal contrast claim.

Keep the 1000-byte command-line cap and segment limits: `__TEXT <= 0x1d8000`, `__DATA <= 0x284000`, and `__TEXT,__const` VMA at least `0xfffffff007005900`, with layout validation against the original collection. r100b uses 999 bytes; do not rely on the one remaining byte for another setting. New settings use fixed constants or explicitly implemented DT consumers. Do not remove security checks, add en0, fix abstract IODisplay allocation, change Metal behavior, resize Data or change signed task contents during r101.

## Bounded observer output

New r101 observer output has a **512 KiB per-boot byte budget**, including a reserved 64 KiB for coverage/overflow/final summaries; details use at most 448 KiB. This is additional-observer output, not a claim that the existing boot log fits 512 KiB. Every emitted line must be **shorter than 255 bytes including its newline**. Split long records with stable IDs and part numbers; flag any truncated service name/path/address record as incomplete evidence.

Use a bounded event ring with a planned 64 KiB runtime allocation, not a large new static __DATA array. Validate actual record sizes/allocation against the build/runtime budget. Report `bytes_emitted`, `ring_overwrite`, `ring_drop`, `payload_trunc`, `line_trunc`, `budget_suppressed` and counter saturation. Maintain event counters after detail output is suppressed; use reserved summary budget to report loss. Missing records or suppressed output invalidate “no outstanding request/no writer” claims. Exceeding the reserved-summary capacity is itself a capture failure. No allocation or unbounded printing is permitted from locked IPC/syscall hooks.

## Staged ABA capture, cooldown and guards

Stage **A1 = r100b behavior + observers** first, after a separate go. Capture continuously for 400–600 s from before fastboot transfer. Evaluate whether it identifies the blocked object and writers, and whether coverage/validation passed. Then make an explicit evidence-based decision whether B and A2 are still useful; each requires its own go. If continuing, preserve order **A1 → B (qualified r99p contrast) → A2 (r100b repeat)**. If stopping after A1, report that control and repeat were not performed and no spread estimate exists.

Apply the same **120 s cooldown in fastboot immediately before each authorized boot**, including A1; record cooldown start/end, actual boot time and preceding fastboot residency. Record ambient conditions and temperature before/after each run and periodically if an already supported, safe temperature sensor is available. Log sensor identity/units; otherwise record **temperature unavailable**, never a fabricated zero. A fixed cooldown does not establish equal temperature or independent trials. Two A samples estimate only observed spread.

Record replay/reconnect/truncation events; initial ring recovery is the only planned replay. The new runner must save the exact raw chunks, monotonic arrival timestamps, byte offsets and guard tick/control events, including no-data ticks, thresholds and runner hashes. An exact future replay must reproduce the same guard calls, not just approximate arrival times from lines. **Implementation status:** the timestamped r101 runner and exact-call replay are implemented and pass synthetic host tests. They have not been exercised in an r101 device run. The existing r100b replay remains approximate because its per-chunk timestamps are absent.

Keep CPU/AKS/respawn/SI/fatal guards and integrate/test `guards.py` before use. Its ENOSPC diagnostic-print guard remains **>16 APFS lines/s for two consecutive 10 s windows**, preserving the margin over the single observed ~8/s peak. Do not reuse that threshold for the new uncapped errno counter. `replay-guards.py` and its saved result explicitly retain their approximate-timing label. Keep the idle-extraction regression check in the analysis gate.

Return the tablet to verified fastboot at the end of each run/session. Observer patches, bounded walker/native reader, source-normalized control, builds, packaged candidates and timestamped runner are now present; kernel source comparison and host checks pass. No hardware boot or control acceptance is complete; name decoding and known-user-stack validation remain open as specified in the implementation report. Owner-key approval/rotation, relocation and real-key offline-signing validation remain separate open owner matters; do not access owner.key for this work.


## Implementation-review clarification (2026-11-20)

See `liuqin-r101-implementation.md` for the revised A1 scope and exact A/B delta.
A1 is expected to take the null branch; generic receive waits cannot justify en0,
display attachment or Metal changes. B varies GOP, Internal, args and ADT: a
positive contrast requires a GOP-only follow-up for display attribution.
Snapshot lines bypass the hook ring; worker output retries logger contention and
reserves future snapshot budget. Begin/stage/end markers and count/checksum
validation make incomplete snapshots failures. APFS print lines without proven
syscall correlation remain explicitly unmatched and non-additive. The walker
host validation path takes priority over XPC decoding before A2, but A1 native
walking remains gated. The 5820-byte r100a panic span fits the 8 KiB screen tail;
USB panic streaming is independent. Every boot still needs a separate go.
