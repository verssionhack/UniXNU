# Liuqin r101 A7 — Ethernet clears TimeSync; WindowServer reaches Metal wait

2026-11-21. **One authorized volatile boot completed.** Native identity-only
Ethernet clears the clock-manager publication gate and both clocksyncd readiness
callbacks. WindowServer progresses beyond its synchronous TimeSync wait into
SkyLight's Metal-device availability wait and repeatedly exits. This is a
publication/progression result, not a display result.

The frozen runner reports **exit 0 / complete-observer-capture**, automatic return
to verified fastboot `be7ca114`, no guard abort, panic marker or USB disconnect.
This status does **not** mean lossless hook histories: final sampled
`ring_drop=68558`. Snapshot evidence and event-history limitations are separated
below. No second boot, flash, partition write or private-key operation occurred.

## Identity and capture integrity — measured

Capture: `out/liuqin-r101-a7-work/evidence/a/boot-A7-20261121-164915`.

- Boot SHA256: `ffdec111a73bdfafd5be42574dbf71d0542c0c78daffb8d98fde8942a91a3d5a`.
- Kernel SHA256: `a03200b0c3e0879745c515b378b98c5407421177d168604a95b403f783dc6777`.
- Raw USB SHA256: `b9995ac0c357defa5532ff406a4166a5463b1dab249765a06c62509b2b73a156`.
- Guard trace SHA256: `32f5c9eabd36318a826f59062088b75747ccb74965ae9e27ff49f346d7bf3c9e`.
- Cooldown 120.000073 s; capture 480.250871 s; 1,146,774 raw bytes.
- Exact replay of all **2,223** recorded guard calls passes; max_pid 351,
  abort_reason/fatal null. No sensor temperature was available.

| Snapshot | Emitted lines | FNV-1a | Raw verification |
| --- | ---: | --- | --- |
| 60 s | 445 | `4ab19b6cddf5d9fc` | count/hash/emitter status pass |
| 120 s | 438 | `59da4a941869c4f8` | count/hash/emitter status pass |
| 300 s | 432 | `a3358d81c2817398` | count/hash/emitter status pass |

All snapshots have complete=1, suppressed_delta=0, trunc_delta=0 and
logger_failed=0. No embedded observer prefix/framing split was found. Tagged
observer output is 328,612 bytes plus 270 bytes of driver lifecycle diagnostics;
combined 328,882 < 524,288 B. Maximum observer line including LF is 187 B.
The final emitted OUTPUT summary precedes the last sampler records and reports
327,541 bytes; use the direct raw-byte total for whole-capture accounting.

All eight CPUs retain nTWE=1/nTWI=0, scale readback remains chosen-DT 40, and the
uncapped undefined-instruction/WFE histogram is zero with overflow=0 through
observer +430.667 s. No raw WFE detail appears in the tail.

The launch adapter executes frozen A6 runner code with only two evidence-path
constants redirected from A6 to A7. Original assessment/dependency paths,
Monitor AST, timing, device commands and recovery policy remain unchanged.
`launch-authorization.json` records the original/effective source hashes and
those substitutions. A7's postprocessor is separate from the frozen assessor.

## Adapter, native publication and clocksyncd — measured / host-qualified

Exact driver lifecycle records:

```text
LQ107 ETHERNET: stage=family rc=0 parent_bytes=280
LQ107 ETHERNET: stage=prequiet rc=0
LQ107 ETHERNET: stage=postquiet rc=0
LQ107 ETHERNET: stage=ready cls=IOEthernetInterface bsd=en0 unit=0 builtin=1 mac_bytes=6 carrier=0
LQ107 ETHERNET: stage=complete rc=0 retained=1
```

This confirms native class/name allocation, worker readiness and quiet checks
completed without a timeout or observed ABI/PAC fault. The ready log proves the
OSData cast/length and builtin boolean check. MAC value `02:4c:51:10:00:01` is
frozen host-source provenance; the log does not dump all six live MAC bytes.

At 60/120/300 s the clock manager (`rid=0x100000216`) consistently has
`state=0x1e`, registered=1/matched=1/inactive=0, with:

- OSNumber64 `TimeSyncTimeClockID=0x024c51f18b900000`.
- OSNumber32 `TimeSyncTimeCoreAudioClockDomain=0x63690000`.

The clock ID's leading MAC OUI bytes agree with the configured `02:4c:51`, but
this is not a direct readback of the remaining MAC bytes. Root, daemon service
and translation positive controls remain registered/matched. Untruncated
TimeSync sweeps visit 248/246/246 nodes, print 12 hits each, and find registered/
matched `IOTimeSyncgPTPManager`, `IOTimeSyncDomain` and `IOTimeSyncTimeSyncTimePort`.
An inactive carrier therefore did not prevent these native publication paths.

clocksyncd pid 141 uses own image base `0x100a2e000`, pinned UUID
`91f59f6a64c3321c88b00cc7a485ab1c`, and shared-region slide `0x12608000`.
All three state captures have 36 successful requested reads plus the expected
invalid-address probe (EFAULT 14); typed daemon/server/listener pointers are
non-nil and stable across the snapshots.

The frozen A5r1 decoder returns after qualifying a stored server, so it does
not classify notifier counts on that branch. Separate A7 postprocessing applies
the **same pinned local notifier/collection layout rules** to the existing raw
words, without another target read or parser mutation. Identity, read return,
address, ISA and begin/end cell stability checks pass, as do negative controls
for unavailable reads and wrong ISA. Each snapshot yields:

| Local notifier | matched | pending | singleton |
| --- | ---: | ---: | --- |
| clock | 1 | 0 | non-nil |
| gPTP | 1 | 0 | non-nil |

**Inference:** the predeclared Gate 2 and Gate 3 readiness blocks are cleared.
The typed server/listener state supports the host-audited initialization path;
allocation alone does not prove current listener activity or a particular XPC
reply. WindowServer's independently changed stack below provides the progression
evidence. These remain bounded, racy reads, not suspended atomic snapshots.

## WindowServer progresses, then cycles — measured / inference

| Sample | WindowServer pid | main tid | leading main-thread frame candidates |
| --- | ---: | ---: | --- |
| 60 s | 244 | 1836 | dispatch semaphore wait → WSSystemCanCompositeWithMetal |
| 120 s | 261 | 2151 | same |
| 300 s | 323 | 2964 | same |

Host symbolication/callsite checks identify:

```text
_dispatch_semaphore_wait_slow + 76
___WSSystemCanCompositeWithMetal_block_invoke + 260
... dispatch_once ...
activate_compositor_default
WSCompositorActivateDefault
WSInitialize
SLXServer
```

The top ten main-thread return candidates pass BL/BLR callsite checks. Across
all sampled threads, each WindowServer snapshot has **62/64** plausible return
candidates; the two unresolved entries are an own-main-image address and zero
terminator. The bounded walker also emits `snapshot-frame-budget` for additional
threads after its 64-frame allowance. These are not complete validated
backtraces. clocksyncd has 10/11 plausible candidates per snapshot (zero
terminator unresolved) and a runloop main stack. `native_reader_validated=false`
and whole-chain `callsite_validation_passed=false` are retained verbatim.

**Host-verified:** the exact SkyLight function containing the sampled wait
constructs a 30,000,000,000 ns deadline, waits on a semaphore, and on timeout
formats `No suitable Metal devices present after %llu seconds.` (30), then
calls `abort`. Assembly is preserved as
`WSSystemCanCompositeWithMetal.asm.txt`.

**Measured:** final legacy TASK_CPU row has WindowServer exits=13, alive=1,
cumulative CPU 10,848 ms. Three capped detailed crash records (pids 111/244/255)
share EXC_CRASH code `0x06000000`, PC `0x192b59650`, LR `0x192b95960`.
With the recorded slide, these symbolicate to `__pthread_kill + 8` and
`pthread_kill + 296`. ReportCrashServi's final row has 19 exits and 37,606 ms CPU.
Only three WindowServer crash details are emitted; do not assign their detailed
signature to every later exit without evidence.

**Inference:** WindowServer has passed the former synchronous TimeSync wait and
is now cycling through compositor Metal-availability initialization. Its sampled
wait, timeout/abort host path and SIGABRT records strongly support the predicted
missing-Metal failure. The captured abort PC/LR do not identify the full caller
chain at termination, so the exact abort cause is not asserted as measured.
Captured matching requests now include AGXAccelerator, IOAccelerator,
IOMobileFramebuffer and the earlier display/HID classes; these are matching
requests, not proof of outstanding notifications or complete history.

### Correction: EXC_CRASH high byte is a signal, not a reason namespace

Pinned `bsd/kern/kern_exit.c:2152` explicitly builds the code as:

```c
((WTERMSIG(rv) & 0xff) << 24) |
((ut->uu_exception & 0x0f) << 20) |
((int)ut->uu_code & 0xfffff)
```

Therefore `0x06000000` here means **SIGABRT**, not OS_REASON_DYLD; `0x09000000`
means **SIGKILL**, not OS_REASON_EXEC. Earlier namespace interpretations based
only on these values are superseded, including my preliminary live update.
The separate logged `sig=5` is not the termination signal encoded here. The
actual `p_exit_reason->osr_namespace` is a different field and was not captured
by these detail records. This also retracts any prior claim that the old
appinstalld/ReportCrash records proved dyld failures solely from this high byte;
their underlying causes remain unresolved. Frozen old artifacts are preserved.

## Loss, storage and interpretation limits

Final sampled LOSS: ring_drop=68,558; history_overwrite=56,555;
payload_trunc=13,408; saturated=0; writer_overflow=0. Hook histories are lossy;
absence of a lookup/open/event is not negative evidence. Snapshot count/hash
verification is independent of this hook-event loss. The frozen assessor's
`no_reported_output_loss` checks OUTPUT suppression/line truncation/summary
failure, not LOSS.ring_drop. Its exit 0 is retained alongside explicit
`hook_history_lossless=false`; no clean lossless-baseline claim is made.

There are 96 Data samples, including 59 early samples. Last free space is
44.519531 MiB at +430.667 s, capacity still 512 MiB. One errno-28 event is
attributed to coresymbolicationd's `grow.*` pwrite, with nonzero reported free
blocks; WindowServer's errno-28 count is zero. No Data-exhaustion conclusion is
drawn from that isolated event. Minimum sampled free RAM is 15.628906 MiB at
+159.668 s; jetsam count remains zero. A larger wired RAM Data volume remains
unsupported. The earlier A4→A5 usage divergence is not investigated here.

Last aggregate EL0 fault count is 19, with six detailed records: three expected
parkd kills and three new-in-comparison WindowServer aborts. Detail caps remain;
EL0 TRAP=0 does not mean zero faults. Final vnode count is 66,560 with 49,262
free, no vnode exhaustion evidence. No performance claim follows from one boot.

## Disposition

The single-interface publication experiment achieved its primary behavior
criteria: clock registration/typed ID, clock and gPTP callbacks completed, and
WindowServer beyond TimeSync. It did not produce a visible-display result.
Next work should preserve these facts and investigate the compositor/Metal
boundary offline, while explicitly addressing hook-history loss before using
history absence to choose another behavior change. No additional behavior fix
or boot was attempted in this session.

All 151 preboot A7 host-manifest entries and 120 A6 result-manifest entries are
rechecked during result freezing. The new result manifest covers raw capture,
assessment, supplemental interpretation, host frame validation and this report.
Owner-key approval/rotation/relocation and real-key offline signing remain
separate untouched owner items.
