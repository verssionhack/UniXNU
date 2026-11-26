# Liuqin r101 implementation checkpoint — 2026-11-20

> **Hardware update:** A1 subsequently completed its authorized 480-second volatile run and returned to fastboot. See [A1 results](liuqin-r101-result.md). This document records the preboot implementation checkpoint; its original “not booted” statements describe that earlier state. A1 took the null dependency branch; B and A2 remain unbooted.

**Host-verified:** A and B kernels are built, prelinked, packaged and validated. **Hardware-tested: false for both.** No r101 boot, owner-key access or partition write occurred. Device remains in fastboot. This implements the bounded capture/analysis pipeline; the two coverage gates below remain open and must not be described as completed diagnostics.

## Review revision and pre-declared A1 outcomes

**Inference:** A1 will most likely return the null branch: generic receive waits, no decoded service names and no validated user stack. It is a pipeline shakedown and an ENOSPC/CPU/media capture. No en0, display-attach or Metal choice is permitted from generic waits or incomplete decoding.

- Success: observer worker reaches all three complete snapshots, end-to-end line counts/checksums verify, scale 40 is read back, syscall writers are named and Data ancestry is shown.
- Null: only generic receive waits; prioritize the validated user-stack path before A2, without changing service/display behavior.
- Failure: panic, hang, missing end marker, checksum mismatch or budget/format suppression; use the last snapshot stage and independent USB panic stream to attribute it. Make no behavior conclusion.

The prior checkpoint packages are preserved at `out/liuqin-r101-work/evidence/checkpoint-before-review/{a,b}`; the table below describes the refreshed, still unbooted packages. No boot is authorized by this implementation revision.

## Artifacts

| Variant | Purpose | Boot SHA256 | Kernel SHA256 |
| --- | --- | --- | --- |
| A | r100b behavior + observers | `78d622042af44ac1eb555d431e826e3cfa3993fbb5a0dcca22d951b77452f75f` | `35b9f85828809d5cf68912dd285243c356f4be17c3d7a906ec181c1688542742` |
| B | reconstructed r99p contrast + same observers | `b16683aaffd2d0048f81d3381d3a77178e37ea207a146e64a0bbc94b38fa793d` | `3ec3526ad383347de8b8f0c95970fae54a10c38e682edeac5a448de931c0cffd` |

Images and reports: `out/liuqin-r101-work/evidence/{a,b}/{boot.img,validation-summary.json}`. The first unbooted A link is retained separately as `a-first-link`, superseded before packaging to add Data/root identity checks, history overwrite accounting and the compiled validation-gated native frame reader. Full r100b source was frozen before changing the shared generated tree; its 6143-file hash manifest still verifies. The generated build tree currently contains the B build; all A artifacts and changed sources are frozen independently.

Both retain the existing trust bundle `daf5a74e200f7390c86981cfe8fe84ddbb0d490d07610895bd5b48806678a5e5`, 512 MiB Data capacity, signed task contents, SMP/EPSS settings and read-only OS windows. A uses the exact r100b arguments (999 bytes) and ADT; B uses the exact recorded r99p arguments (992 bytes) and ADT. No boot argument was added.

| Segment/layout check | A | B | Limit |
| --- | --- | --- | --- |
| `__TEXT` | `0x1c8000` | `0x1c8000` | `0x1d8000` |
| `__DATA` | `0x27c000` | `0x278000` | `0x284000` |
| `__TEXT_EXEC` | `0x9a4000` | `0x994000` | recorded, no new cap invented |
| `__TEXT,__const` VMA | `0xfffffff007005ea0` | `0xfffffff007006220` | >= `0xfffffff007005900` |

AES/fileset gates and normal Android boot-image unpack/verification passed. These are host checks, not runtime FIPS/AMFI/registration success claims.

## Implemented capture

- Dedicated observer worker with 60/120/300 s snapshots, 10 s Data space/counter sampling and 30 s coverage summaries. Times identify their clock/origin. Data sampling waits for root readiness and verifies the mounted device against the selected scratch volume before reporting its space.
- WindowServer thread references are retained under task locking. Scalar wait state and native saved user registers are copied while the thread is locked; IPC objects are retained before releasing that lock. Port locking and formatting happen afterward to avoid reversing the port/waitq→thread lock order. Up to 64 threads are captured; additional threads are counted as truncated coverage.
- Receive-port/object type, owner PID where safely available, wait event, block hint, timer-armed state and best-effort deadline are recorded. Unknown ownership, port-set ownership and inaccessible deadlines remain explicit unknowns. Raw PC/LR/SP/FP and shared-region base/slide/cache UUID are recorded without the prior arbitrary PC mask.
- Last 50 open attempts/results, last 50 observed IPC records, IOKit matching predicates, ring loss and history replacement accounting. IPC hooks copy bounded metadata/prefixes under their existing locks; the worker formats output. Unsupported complex/other layouts remain undecoded.
- Uncapped 64-bit errno-28 totals and per-PID/process counters, with bounded path examples (up to eight per 10 s epoch) captured outside the observer spinlock. Paths are resolved at syscall exit while holding file/vnode references; unavailable/truncated paths remain flagged. A fixed 64-writer table reports overflow rather than pretending complete attribution.
- Top 15 task CPU rows plus pinned processes and explicit time anchors. Existing fault/jetsam/vnode observers remain. The host analyzer classifies faults against both retained r99p and r100b inventories; recurrence is not labelled expected unless supported by the existing parkd denial policy. **EL0 TRAP=0 is not zero faults.**
- Scratch IOMedia/provider ancestry and Protocol Characteristics; actual timeout initialization records DT value/length, boot-arg presence, selected scale source, combined scale/global multiplier and effective timeout ticks. Live value 40 remains a hardware acceptance check.

## ENOSPC coverage boundaries

The uncapped errno-28 counter covers all BSD syscall exits reaching the existing perf wrapper, not just `write`. Descriptor/path attribution is limited to `write` (4), `write_nocancel` (397), `writev` (121), `pwrite` (154), `pwrite_nocancel` (415), `guarded_pwrite_np` (486) and `ftruncate` (201), from the pinned `bsd/kern/syscalls.master`; examples are rate bounded. Other syscall errors, including fsync-family exits reaching the wrapper, count without descriptor-path attribution. Pure asynchronous APFS writeback/pageout does not pass through this hook. Existing `LIUQIN SCRATCH_BLK_WRITERS` identifies physical block-submission context separately; it is not the attempted logical writer or an APFS path.

The analyzer adds `apfs_enospc_print_lines_not_matched_to_syscall_event`. APFS print lines have a process name but no shared PID/TID/request ID/time anchor, and syscall exemplars are bounded. Therefore all such prints remain **unmatchable**, with zero claimed proven matches; nearby/equal-name records do not establish identity. This counter is a coverage measure, never an async-writer count and never summed with syscall or physical block counters. More precise async APFS path attribution is still unavailable.

## Bounded memory/output and diagnostic retirement

The event ring is 256 × 224 = **57344 bytes**, below the planned 64 KiB ring bound. The full allocated observer state, including two last-50 histories and the writer table, is **82568 bytes** (compiler DWARF sizes verified). Additional state is dynamically allocated, not a large static __DATA array.

New output is metered to 512 KiB. The worker emits snapshot evidence directly; it never enters the 256-entry hook ring. Each not-yet-completed snapshot reserves 144 KiB, with a further 16 KiB held against ordinary detail output for summaries; ordinary detail also retains the 448 KiB cap. Non-snapshot output cannot consume future snapshot reservations. Snapshot evidence bypasses the ordinary detail cap but remains subject to the total byte/line contract. If any contract fails, the snapshot is explicitly incomplete.

Worker evidence and begin/end markers use a worker-only logger append that retries contention with interrupts restored and sleeps 1 ms between attempts, breaking on panic. No hook waits on output. Snapshot begin, waits/histories/storage stages and end markers locate a hung phase. The end marker records emitted line count, FNV-1a checksum, suppression/truncation deltas and logger failures. The host analyzer verifies count/checksum against captured lines and rejects incomplete, missing, duplicated or altered snapshots. This detects loss in the downstream USB/log transport; it does not claim that transport is lossless. CPU rows may interleave and are excluded from snapshot checksums. The formatter permits at most 252 text bytes plus newline, rejects overlong lines and increments a counter. Snapshot-only emission failures determine completeness; global suppression deltas also expose unrelated interleaved output. Summary records expose bytes, suppression, line truncation, ring drops, history replacements, payload truncation, writer overflow and saturation. The ring uses drop-new rather than overwrite; old-history replacement is separately reported. Counter updates continue when detail emission is suppressed. Raw old boot logging is outside the new-output byte budget.

Retired diagnostic storage: panic tail shrinks from r100b's 16 KiB to **8 KiB**, saving **8192 static bytes** in A. For the normalized B control this is 64 KiB → 8 KiB. The independent USB panic path remains. `check-panic-path.py` reproduces `evidence/panic-path-review.json`: the r100a span from `PANICc5` through the last userspace panic reason is **5820 bytes**, within 8192. `consdebug_putc_unbuffered` calls `liuqin_panic_usb_putc`, whose separate 192-byte PNB buffer uses `liuqin_usb_force_note`; debugger flush precedes framebuffer painting. The 8 KiB tail is only the framebuffer screen excerpt. USB remains best effort. B also adopts the same unchanged scratch-seed bytes in `__BOOTDATA,__data`, rather than r99p's old const placement. These diagnostic/layout normalization choices are explicit; B is not a bit-identical r99p kernel.

## Coverage gates still open

**Bootstrap/XPC service-name decoding is not implemented or verified.** Current capture records IDs, endpoint PID/object metadata and bounded prefixes for supported simple messages. Unsupported/complex layouts are counted as undecoded/truncated, with `decoded=0` and outstanding requests explicitly unknown. The analyzer always prohibits “no lookup” claims. This is a wire-capture/coverage implementation, not a working modern libxpc service-name decoder. A verified target ABI profile and proper request/reply correlation remain work before that success criterion can be met. OOL payloads are not dereferenced by the hook.

**The frame walker and non-faulting target-map reader compile, but execution is gated.** The reader switches only the observer thread to a referenced target map, disables faults for the bounded copy, restores fault handling and restores the original map. The frame engine checks range, alignment, progression, depth 16 and read failure; signed/raw LR values are preserved, not masked. Host synthetic fixtures pass. The validator requires two independently pinned LRs from a known user-thread stack plus a failed invalid-address read before enabling walking. The legacy independent-LR fixture hook is **not wired**, so A1 snapshots report deferred validation and raw registers only. The new candidate-only path bypasses that legacy fixture requirement without claiming trusted frames. No live fixture or native-reader test is claimed. Raw/symbolicated PC evidence must not be upgraded into a full backtrace.

**Walker prioritized over XPC decoding for A2:** `validate-user-frames.py` now implements host PAC-bit removal using an explicit target VA width, slide removal, UUID/SHA-pinned cache-set checking, executable mapping lookup and BL/BLR/authenticated-BLR callsite checks at LR−slide−4. Raw LRs remain in the report. A failed invalid-address native read is mandatory input. It never enables walking by itself, guesses masks, or treats missing/non-cache frames as valid. Eleven host tests exercise signed LRs, slide, wrong UUID, invalid-read gating, missing mappings and actual BL/BLR versus branch/return opcodes. Actual target frames and cache-set validation remain pending; synthetic callsite tests do not prove the native reader. A1 remains gated. `prepare.py --walker-candidates` explicitly stages the later raw-candidate mode (not selected for these images): every walk first requires a failed invalid-address nonfault read, preserves raw frames, and counts unavailable reads. It bounds depth to 16 and total output to 64 frames per snapshot; further threads are marked frame-budget limited. It does not enable trusted backtraces. `frames-from-log.py` exports only a count/checksum-verified snapshot with recorded native geometry and per-thread invalid-read evidence into `validate-user-frames.py`. This wires the host validation route before A2 without a live known-stack fixture; a future candidate image still needs a fresh build/package and separate go. Actual native/callsite validation remains pending on that capture. XPC decoding stays lower priority.

The snapshot records authoritative map bounds and machine maximum; a compile-time assertion pins this build's BCM2837 native-4K user range to 39 bits. Reader unavailability counters distinguish observer read limitations from target errors; copyin cannot distinguish nonresident from unmapped and reports that combined category. No page-in is attempted.

IOKit observations are matching requests and bounded class/name predicates, not proof that a notification is outstanding or its callback fired. Generic receive waits without correlated complete coverage remain unknown. Temperature is unavailable because no qualified readable sensor is configured; ambient temperature can be supplied to the runner.

## Common-source contrast

`out/liuqin-r101-work/evidence/source-comparison.json` verifies equality of all 13 frozen changed kernel source files. Device source differences are limited to `configs/liuqin_defconfig` (GOP enabled/disabled) and `drivers/LiuqinSourceStorage/R101Variant.h` (Internal property enabled/disabled). Both share the same observer patch.

`variant-config.diff` and `control-normalization.diff` record those choices and the reconstruction from retained r99 inputs. **B is a multi-variable contrast, not a display-only control.** Relative to A it changes GOP configuration, the scratch Internal property, arguments, ADT random seed/scale delivery and the stand-in path. Any A/B difference is not attributable to display alone. If A1 indicates a display dependency, a later separately authorized **GOP-only** boot must keep all other A settings fixed.

The exact r99p → r100b argument audit is retained in `out/liuqin-r100-work/evidence/review/review-audit.json`: adds nine `offline-*` display arguments; changes `exec-stand-in` from `/private/var/liuqin/parkd` to `/var/liuqin/parkd`; removes digest-service from `deny-exec`; removes `armcpu-diagnostics`, `liuqin_page_rehash_count/sec`, `liuqin_vm_sec`, `startup_debug` and the scale boot argument. ADT adds `/chosen/machine-timeouts/lock-panic-scale=40` and changes random-seed. Driver/config changes add GOP and the Internal property; diagnostic tail and BOOTDATA seed placement also differ. Data capacity stays **536870912 bytes (512 MiB)** in both, with the same logical seed contents. The immutable kernel hashes differ as recorded in that audit. These are the exact retained-input differences, not a display-only attribution. Registration=82, ~74.5 s idle proxy, matching ENOSPC pressure and the rest of B's acceptance criteria are **unmeasured** until a separately authorized control run. Host source equality alone does not qualify the hardware contrast.

## Runner and verification

`run-r101.py` verifies the packaged image/kernel, requires the expected fastboot device, applies a logged 120 s cooldown, and starts capture before issuing the nonblocking fastboot transfer. It captures continuously for 400–600 s, records the exact raw chunks/offsets/timestamps, empty guard polls, replay/reconnect/fatal/control events, source hashes and guard results. It preserves original guards and the >16 APFS ENOSPC print-lines/s for two 10 s windows guard. It verifies return to fastboot in cleanup and reports a failed return; it never flashes. `replay-exact.py` reproduces every recorded guard call. This does not make the old r100b replay exact.

Host validation completed:

- Six changed translation units compile; full A/B kernel builds, prelinks and packages pass.
- Both variants pass `run-r101.py --check` and artifact/source comparison checks.
- Nine runner/analyzer tests pass: partial serial lines, split panic markers, retained CPU guard, clock ordering, exact empty-tick/ENOSPC abort replay, corrupt logs, offset holes, wrong image hashes and rejection of a capture missing its required observers/snapshots.
- Bounded frame-walk host fixtures pass, including known chains, depth limit, read failure, cycles, alignment and invalid addresses. Native target-map/user-thread validation remains pending. Eight snapshot/ENOSPC coverage tests and eleven host callsite/parser/export tests also pass.
- The original r100 result was corrected at `r100/liuqin-r100-result.md:55`: 994386 came from the follow-up-only log; the initial sample is 595963. Corrected idle-extraction regression check passes. Both frozen baseline inputs and original staged r100 images remain preserved.

Recheck without device access:

```sh
python3 scripts/liuqin-analysis/r101/verify-staged.py
```

After a **separate explicit go for A1**, the concrete volatile run command is:

```sh
python3 scripts/liuqin-analysis/r101/run-r101.py --variant a --tag A1 --seconds 480
```

Then run `replay-exact.py <boot-folder>` and `analyze.py <boot-folder>`. Decide whether B and A2 remain useful from A1's evidence; each needs its own go and cooldown. Do not choose en0/display/Metal behavior changes from incomplete decode or generic wait results. Owner-key signing/rotation/relocation items remain untouched.
