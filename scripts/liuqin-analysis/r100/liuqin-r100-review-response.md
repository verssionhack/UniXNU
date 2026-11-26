# Liuqin r100 review response — raw-log audit, 2026-11-20

Labels: **measured**, **host-verified**, **inference**, **hypothesis**, **(verify)**. All findings below were checked locally against preserved files. No new hardware boot was performed for this response. The device was returned to verified fastboot `be7ca114`; reset evidence is `out/liuqin-r100-work/evidence/review-fastboot-20261120-161443/`.

## Two corrections to the original r100 result

**Measured:** the claimed +50 s quiescence regression was my analysis error. I selected a follow-up sample rather than searching the initial capture. The actual first >=95% samples are:

| Capture | Raw log line | idle_pct | Aggregate CPU-ms | CPU-ms / 8 | Time after first IDLE sample |
| --- | ---: | ---: | ---: | ---: | ---: |
| r99p | 5004 | 96 | 596005 | 74.501 s | 70.039 s |
| r100b initial usb.log | 5095 | 96 | 595963 | 74.495 s | 70.032 s |

Both first cross the threshold in the eighth captured IDLE sample. These are accounting proxies and relative observer times, not exact host boot timestamps. There is no established quiescence regression to explain. There is also only one run per variant, so no variance estimate exists.

**Measured:** ENOSPC was already present in r99p. Its boot record has `enospc_hits=20` (the observer cap), and its raw log has 388 APFS `fs_tx_enter_internal ... ENOSPC` lines. r100b's initial 150 s has 323 such APFS lines and the same 20 capped detailed syscall records. Its longer combined capture has 1586 APFS lines; comparing that longer total with r99p's 150 s would be invalid. This is a shared unresolved space-pressure problem, not an established new r100 regression. The r98/r99 result omitted it; my r100 result failed to audit that baseline.

The old r100 result is archived under `out/liuqin-r100-work/evidence/review/liuqin-r100-result-before-review.md`. `report-revision.json` records its hash and the prior evidence-manifest hash. Raw logs and images were preserved; the main result and handoff now carry these corrections.

## 1. Exact r99p → r100b delta

**Measured artifact identities:** both retained images and kernels were rehashed and match the recorded metadata (`review/artifact-integrity.json`).

| Artifact | r99p | r100b |
| --- | --- | --- |
| Kernel SHA256 | `289bc6cc26bafc508ccaee0933cbbca54b3810e3e2e611beb197237feacc01c6` | `8d27ff88ca1d8589732b17497c27bf26bff7c528b1871eccac1bda1ebeca17f5` |
| Boot SHA256 | `1a477a1d2dfc30e1aac6bdbe48259044e357632eaad63318894396b6ed142b6e` | `e38ab9fc300ae4a92377e34f6a1a3fcae4a7278137b164593ef75f675a41c417` |
| Original kernelcache | Same `d1003b51…5db9fe9` | Same |
| Trust bundle | Same `daf5a74e…678a5e5` | Same |
| Owned-memory setting | `0x100000000` | Same |
| Logical scratch / Data size | 536870912 bytes | Same |

**Host-verified staged source delta:** nine device-tree files differ between the retained r99 and r100 device work directories. The full hashes are in `review-audit.json`.

- `board.toml`, `configs/liuqin_defconfig`: add GopFramebuffer and its archive builder/configuration; remove startup/CPU diagnostic arguments for space.
- `drivers/LiuqinSourceStorage/LiuqinScratchDisk.cpp`: add the Internal protocol characteristic.
- `drivers/LiuqinSourceStorage/ScratchSeed.inc`: move the same seed array to `__BOOTDATA,__data`.
- `patches/xnu/zzz-liuqin-panic-screen.patch` and `zzz-liuqin-zzz-switch-progress.patch`: reduce the panic tail from 64 KiB to 16 KiB.
- Add `package/LegacyDisplayProbe.cpp`, `scripts/build-liuqin-legacy-display.py`, and `scripts/legacy-display-26C5035r.json`.

The preserved r99 source copies of `liuqin_perf.c`, `liuqin_data_layout.h`, `start.s`, and `caches.c` are byte-identical to the current compiled-source tree. This is an explicit comparison of retained staged files and those four frozen sources, not a claim that a complete immutable r99 source snapshot exists. Both prelink reports identify the same original kernelcache and matcher version 8.

**Exact argument-set changes:**

| Change | Arguments |
| --- | --- |
| Removed | `startup_debug=1`, `armcpu-diagnostics=1`, `liuqin_vm_sec=30`, `liuqin_page_rehash_sec=60`, `liuqin_page_rehash_count=256` |
| Moved to ADT | `ml-timeout-lock-panic-scale=40` → `/chosen/machine-timeouts/lock-panic-scale`, u32 40 |
| Equivalent path change | `exec-stand-in=/private/var/liuqin/parkd` → `/var/liuqin/parkd` |
| Deny-list change | Remove `/System/Library/PrivateFrameworks/Heimdal.framework/Helpers/digest-service` from `deny-exec` |
| Added | `offline-mobile-graphics-load=1`, `offline-legacy-register=1`, `offline-legacy-gop=1`, `offline-legacy-unit-scale=2`, `offline-legacy-pm=1`, `offline-legacy-validate=1`, `offline-legacy-transfer=1`, `offline-legacy-cpu-present=1`, `offline-legacy-phase=4` |

All other argument values are identical, including both repaired Data/parkd preparation gates, SMP and EPSS. Ordering differs; the audit compares argument keys/values and retains the full lines. Thus r99p → r100b is not a single-variable display experiment. In particular, the rehash observer was removed, and future summaries must not call an absence of rehash lines a passed rehash test.

**Exact ADT diff:** a different 256-byte random seed, plus the `machine-timeouts` node and its scale property. No other node/property differs. Both already used the 4 GiB owned-memory setting; the old handoff's 372 MiB figure is obsolete for these artifacts.

## 2. Data size, space pressure, and writer evidence

**Measured:** both logs report `bsize=4096 blocks=131072`, exactly 512 MiB. Initial free space is `124557` blocks (486.551 MiB); the last 150 s sample in each is `1430` blocks (5.586 MiB). r100b ends follow-up at `1427` free blocks (5.574 MiB). Neither run was resized by Data layout; the layout source is byte-identical and verifies the selected mount's device identity.

Existing Data statfs samples are approximately 28 s apart, not 10 s, and lack explicit timestamps. The audit retains each sample's line number and preceding IDLE-relative time; it does not manufacture a precise 10 s series.

**Measured writer attribution already available:** after the 20 detailed pid-less syscall records, APFS prints still name processes. In r100b's complete captured intervals, 1374 of 1586 APFS ENOSPC prints name launchd, and 150 name locationd. These are counts of diagnostic messages, not distinct failed transactions or all errno-28 returns. The first detailed records name coresymbolication cache data, logd's Persist trace, trustd/analyticsd WALs, LaunchServices stores and nsurlsessiond's WAL. r99p likewise shows launchd, logd_helper and coresymbolication pressure. CPU and physical-block writer observers are separate layers and must not be added together.

**Hypothesis:** crash/log/symbolication traffic fills Data and contributes to background work. Supported by writer names and paths, but not by a complete live-file allocation census. PID/full-path attribution beyond the capped detail logger remains an r101 observer requirement.

## 3. Matched TASK_CPU windows and the 12 faults

**Measured:** the matching first nonzero CPU windows have `dt_ms=50029` (r99p) versus `50024` (r100b). Total task CPU is 186400 versus 150994 ms. The largest common-row deltas (r100b minus r99p) are ReportCrashService −18506 ms, lsd −9706 ms, logd_helper −2096 ms, ReportMemoryException −1188 ms and coresymbolication −1121 ms; analyticsd is +739 ms. WindowServer is 0 ms in both windows. Full available rows and the following ~30 s window are in `review/cpu-window-diff.md`.

A true top-15 comparison cannot be recovered: the source emits the top 10 plus pinned UI tasks. Missing rows are marked unknown, never zero. The r101 requirement is to emit at least the top 15 with explicit uptime on each window.

| r100b detailed faults | Count | Classification relative to r99p's 150 s sample |
| --- | ---: | --- |
| parkd, `exc_crash`, code `0x9000000` | 3 | Expected consequence of the existing denied-daemon/AMFI arrangement; three also appear in r99p. This is not healthy desktop behavior or fake-success evidence. |
| locationd, SIGSEGV | 1 | Pre-existing unresolved process failure; r99p has three locationd fault records, including SIGSEGV. Exact fault pointer/signal mix varies. |
| ReportCrashServ, `exc_crash`, code `0x9000000` | 3 | Pre-existing unresolved failure; same count/signature in r99p. Not classified as expected merely because it recurs. |
| appinstalld, `exc_crash`, code `0x6000000` | 3 | Pre-existing unresolved failure; same count/signature in r99p. |
| AirPlayXPCHelpe, SIGILL, subcode `0xd503205f` | 1 | New process occurrence in this compared capture; r99p has the same instruction subcode in lsd. Cause unresolved. |
| mediaremoted, SIGILL, subcode `0xd503205f` | 1 | New process occurrence in this compared capture; same caveat. |

The total is 12 versus 13 detailed r99p records. Observer caps and one sample per variant prevent declaring a fault globally new or absent. **EL0 TRAP=0 is not zero faults.**

## 4. Display attachment and display type

**Host-verified:** [NativeLegacyDisplay.cpp](../../../drivers/GopFramebuffer/NativeLegacyDisplay.cpp), function `attachDisplayObject`, lines 1175–1190, produces the message. It loads IOGraphicsFamily, allocates `IODisplay` by name, casts to IOService, obtains `NativeDisplayEDID`, then calls `init()` and `attach(self)` only if those prerequisites succeed.

The exact original kernelcache's `IODisplay::MetaClass::alloc()` at `0xfffffe000aabaee4` is `bti c; mov x0, #0; ret`. Thus this abstract class's allocator always returns null. The attempted allocation cannot pass the `display` prerequisite, even with `kext 0`. This explains the child attachment failure directly; no missing parent or EDID hypothesis is needed to explain that message. It does not prove this failure is WindowServer's current blocker, nor justify a behavior change before wait observation.

**Host-verified:** `IOMobileFramebufferUserClient::s_map_display_type` at `0xfffffe000ac1cb28` loads scalar input 0, stores its low 32 bits at client offset `0x10c`, logs it, and returns success unconditionally. Here “0” is client-supplied input, not a framebuffer-reported classification. This method has no type whitelist. **(verify):** the higher-level semantic enum and CoreDisplay/WindowServer acceptance rules remain unverified. The log does not establish which process issued the request.

Reproducible host inspection: `audit-display-host.py`; pinned-input hash and bounded disassembly are saved in `review/host-display-audit.json`, outside git-facing source.

## 5. WindowServer, keystore, jetsam and vnodes

**Measured:** WindowServer is alive at 306 s with exits=0 and flat CPU. **Inference:** it has not traversed the previously described no-Metal abort path. Its earlier blocked object remains unidentified. en0/IOTimeSyncFamily is a hypothesis; no network interface will be built on the current evidence.

**Measured + host-verified:** r100b selects `/dev/disk8s1`, mounts `LiuqinR93Scratch`, UUID `C7D5AD67-0CE2-4AAB-BC37-BCE0F85F6720`, and reports mounted verification success. `liuqin_scratch_volume()` in `LiuqinScratchDisk.cpp:185–202` returns a match only after walking its provider chain and finding a `LiuqinScratchDisk`. `kern_exec.c` and Data layout then verify the mounted device equals that selection. The hypothesis that Data is on an unrelated media is inconsistent with these checks. A direct property/ancestor dump is still useful to establish exactly what keystore sees. The current exit-1 return path remains unknown; the Internal property did not establish success.

**Measured:** jetsam and vnode observers remain active. In the first 150 s, each run records three per-process-limit kills. r100b reaches four by the end of follow-up, attributed to ReportCrashService, cause 7, configured limit 15 MiB. Both reach vnode count 66560; r100b ends with 49040 free and 543 dead entries. A maximum count with many free entries does not itself prove vnode exhaustion. These values were missing from my original summary and are now included.

## 6. Packaging limits, scale readback, and r101 readiness

**Host-verified:** DarwinBoot uses a 1024-byte command-line array and rejects a character at index >=1023, reserving the terminator. Its maximum text length is 1023 bytes. UniXNU's payload tooling deliberately enforces the stricter 1000-byte limit; r100b is 999. Keep that limit. Only settings whose consumer explicitly supports DT may be moved into DT; there is no generic boot-arg-to-DT substitution.

**Host-verified, not live-readback-verified:** the ADT encodes u32 40 and `machine.c` explicitly consumes `/chosen/machine-timeouts/lock-panic-scale`. There is no captured line proving the selected live scale was 40. The original result should not imply such a measurement. r101 must print the read result, selected source and effective value from the timeout initialization path.

The proposed observer run cannot literally have the same image/kernel bytes while adding absent kernel observers. It needs a new instrumented kernel, preserving r100b behavior and recording a new hash, with the identical observer patch on the r99p control. No image, build, boot, repeated-run variance estimate or blocked-port diagnosis is claimed complete here. The concrete protocol and success criteria are in the [r101 observer protocol](../r101/liuqin-r101-observer-plan.md).

Prepared host-side guard work: the existing r100 guards were replayed on r100b, plus a diagnostic-print-rate guard set to >16 APFS ENOSPC lines/s in two successive 10 s windows (twice the observed complete-interval peak of ~8/s). All three first-anchor timing assumptions passed; threshold/sustained-window checks passed. `review/guard-replay.json` records the limits: original USB chunks have no arrival timestamps, so exact original wall-clock guard behavior cannot be certified. The print guard does not measure uncapped errno events; a new errno counter needs a separately calibrated policy. The new runner must record chunk offsets/timestamps and integrate this guard before use.

Owner-key authorization/rotation and real-key offline signing remain open owner matters. No key or partition access occurred. Current comparison baseline is r100b. The device is in fastboot, ready for a separately authorized run.
