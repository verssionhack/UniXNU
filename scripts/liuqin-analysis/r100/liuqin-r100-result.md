# Liuqin r100a / r100b — first hardware display run, 2026-11-20

## Outcome

**Measured:** r100a failed before desktop startup because the packaged configuration omitted RAM Data preparation. The same kernel, repackaged as r100b with the preparation gates restored, reaches WindowServer and an IOMobileFramebuffer user client. WindowServer then parks; a working desktop is **not established**. `applekeystored --init` still exits 1. Keystore initialization remains unverified. **Review correction:** r100b's first >=95% idle sample matches r99p (~75 s accounting proxy); the previously claimed ~124 s regression was an analysis error. ENOSPC was already present in r99p. See `liuqin-r100-review-response.md` and the saved raw-log audit.

All device runs used `fastboot -s be7ca114 boot`, never flash. No partitions, `userdata`, or owner key were modified. The second run returned the panicked device to fastboot through the existing debug-console command.

## Artifact identities and evidence

Common XNU kernel SHA256: `8d27ff88ca1d8589732b17497c27bf26bff7c528b1871eccac1bda1ebeca17f5`.

| Variant | Boot image SHA256 | Evidence directory |
| --- | --- | --- |
| r100a | `4d9a3eb1c989eeb5e18e5aea9052070f1b802ad127050b26446820e5be7bd304` | `out/liuqin-r100-work/evidence/boot-r100a-20261120-155217/` |
| r100b | `e38ab9fc300ae4a92377e34f6a1a3fcae4a7278137b164593ef75f675a41c417` | `out/liuqin-r100-work/evidence/r100b/boot-r100b-20261120-155900/` |

r100b image and packaging validation: `out/liuqin-r100-work/evidence/r100b/{boot.img,validation-summary-r100b.json}`. The original r100a candidate and original payload were preserved. Runner/package hashes: `out/liuqin-r100-work/evidence/r100-session-source-manifest.json`. Evidence hashes and machine-readable measurements accompany this result in the r100b evidence directory.

## r100a failure and configuration repair

**Measured:** fastboot transfer and boot succeeded. USB capture lasted 98 s, including the configured 35 s fatal tail. All 82 registration end markers appeared; eight CPUs came online, with zero secondary-start failures. The runner observed `PANICc5`, and the full panic says `userspace panic: boot task failure: mount-phase-1 - exited due to SIGABRT`. `max_pid=4`; WindowServer was never reached. A null `abort_reason` in this run means no rate guard fired; the separate `fatal` field records the panic.

**Host-verified:** the r100a command line omitted both `liuqin-scratch-probe=1` and `liuqin-parkd-prepare=1`, present in r99p. In the compiled source's `bsd/kern/kern_exec.c`, `liuqin-scratch-probe` gates scratch mounting, Data population/layout, and mount-adapter preparation. Without it, the other three supplied arguments never activate those steps. The absent setup log lines and failed APFS boot task agree with this explanation.

The staged runner also pointed to nonexistent `validation-summary.json` and defaulted to `r98a`. Corrected it to validate the r100a-specific report and bind both image/kernel hashes. Preserved that runner in `scripts/liuqin-analysis/r100/run-r100.py`, and fixed the original package script to stage it rather than the stale r98 runner.

r100b is a **configuration repair**, not a controlled test of either individual gate. `package-r100b.py` reuses the exact kernel and trust bundle, restoring both required preparation flags. To fit the command line (999 bytes), it moves the unchanged lock-panic timeout scale 40 into `/chosen/machine-timeouts/lock-panic-scale` (32-bit little endian, explicitly supported in `osfmk/kern/machine.c`) and uses `/var/liuqin/parkd`, which resolves through the Data layout's `/var` alias to the installed `/private/var/liuqin/parkd`.

The packager reads back config/ADT/kernel/trust from FAT, checks kernel/trust hashes, and asserts that removing the sole new ADT node reconstructs every original ADT byte. The normal boot-image builder unpacks/verifies the resulting Android image. XNU instructions, segment sizes, signing policy, and display arguments were unchanged.

## r100b hardware findings

**Measured within the first 150 s:**

- RAM Data layout: `err=0`, 18 aliases, one skipped entry, three chains, four I/O checks.
- Signed parkd staging: `err=0 bytes=16892 verified=1`.
- Mount adapter: `err=0 phase=overlay resources=4 rosp=2 volatile=1`.
- 82 registrations; zero trustcache-denial strings, zero `LIUQIN EL0 TRAP` lines, zero scratch I/O errors, and no panic/abort guard.
- WindowServer and loginwindow remain alive; WindowServer's cumulative CPU is ~201 ms, with later windows at 0 ms. A live IOMobileFramebuffer user-client line reports `UserClient display type is 0`. Host disassembly shows this is a client-supplied scalar stored by `s_map_display_type`, which returns success without an enum check; it is not the framebuffer reporting its kind.
- Default IOSurface allocation succeeds: 1800×2880, stride 7296, allocation 21,012,480 bytes, `status=0x0 valid=1`. This source-surface stride is distinct from the panel's 7200-byte scanout stride.
- `NativeLegacyDisplay: display object not attached (kext 0)`; host disassembly identifies the cause: the original `IODisplay::MetaClass::alloc()` returns null. This abstract class cannot be allocated by name. Framebuffer registration itself did succeed.
- `applekeystored` pid 11 exits with status 1. The proposed ScratchDisk property change has **not** established successful keystore initialization; additional tracing is required to identify the current return path.

The boot is not otherwise error-free (these background failures also require comparison against r99p): 12 detailed `LIUQIN EL0_FAULT` lines were captured in the first 150 s (including parkd crash reports, locationd, mediaremoted/AirPlayXPCHelper, appinstalld, and ReportCrashServ), plus 20 bounded ENOSPC reports. `EL0 TRAP=0` must not be represented as absence of userspace faults. ENOSPC reports include diagnostic/SQLite/cache writes; no scratch transport error was recorded. The first runner's max-pid field is observer-window based (275), while the offline analyzer sees process events up to pid 290; these are different measurements.

**Inference:** a framebuffer user client is reachable, but display publication and one successful surface allocation do not establish frame presentation. The planned en0/IOTimeSyncFamily step remains a hypothesis for the WindowServer wait; this capture does not yet prove that wait's cause. Avoid adding HID/GPU changes until the next display/net experiment is isolated.

## Extended registry observation (measured)

At observer uptime **306 s**, `PE_VIDEO` confirms initialized display 1, 1800×2880×32, row bytes 7200, physical base `0xb8000000`. Registry results include `NativeLegacyDisplay` under the `NativeGOPFramebuffer` IOService, plus `IODisplayWrangler`. Thus framebuffer service publication is established. The bounded dump prints the concrete NativeLegacyDisplay class; it does not independently list every superclass or IOSurface root service. IOSurface allocation success is separate evidence from the earlier default-surface log.

At the same sweep, WindowServer pid 112 and loginwindow pid 110 are `state=running`, each `exec_ok=1`, `exits=0`; CPU totals are 202 ms and 143 ms. `applekeystored` is `state=exited`, `exec_ok=1`, `exits=1`, `last_status=0x100`.

**Corrected after raw-log review:** the first >=95% sample is already in the initial r100b `usb.log` at line 5095: `tot=595963`, `idle_pct=96`, versus r99p line 5004: `tot=596005`, `idle_pct=96`. Both are approximately 74.5 s using aggregate CPU accounting / 8. The formerly cited `994386` value is the same aggregate CPU counter at `usb-follow.log:392`: it is the first qualifying sample in the follow-up alone, not in the full capture. The error was selecting the wrong capture scope, not using a different counter. The chronological extractor now records capture filename/local line; `r101/check-idle-extraction.py` guards this exact initial/follow-up/combined case. There is no established +50 s regression. Matched 50 s TASK_CPU windows actually contain 150994 ms in r100b versus 186400 ms in r99p. These are single runs, not a variance estimate. The RAM Data APFS volume also emits ENOSPC beyond the bounded 20-line observer log, including launchd writes near the end of follow-up; no scratch transport-error string was observed.

Capture completed: first 150 s plus 210 s follow-up, with a roughly 40 s gap and no replay during follow-up. Neither interval reports a panic or abort guard. Offline parsing of the concatenated captured intervals confirms 82 registration end markers, zero trustcache-denial strings, zero EL0 TRAP lines, 12 detailed EL0 fault lines, and zero scratch transport-error strings. These are captured-interval observations, not proof of events during the gap. The device was initially left running r100b; it was returned to verified fastboot during the review response (`review-fastboot-20261120-161443/state.json`). Full output: `analysis-combined.txt`; machine-readable results: `hardware-summary.json`; evidence hashes: `evidence-sha256.json` in the r100b boot evidence directory.

## Resume

Use r100b as the repaired display candidate. Do not rerun the original r100a configuration expecting a desktop. Preserve its failure evidence.

The r100b runner is `out/liuqin-r100-work/evidence/r100b/run-r100b.py`; its boot is volatile and its validation is bound to r100b. `follow-r100.py` extends capture without resetting or replaying the ring, retaining abort counters and documenting the historical timestamp limitation. Repackaging refuses to overwrite the existing r100b FAT image.

Next: instrument WindowServer waits before adding another behavior variable. The previously reported quiescence regression is withdrawn. No en0 or display behavior change is selected solely because the framebuffer remains idle. The revised r101 plan requires a named blocked object or validated user-side state, with explicit unknown branches; missing IODisplay attachment and keystore initialization remain separate diagnoses. Keep the verified SMP fixes, original trust bundle, and no-flash/no-key constraints.

Review additions: both runs use 512 MiB Data (131072 × 4096), with no layout resize. r100b records three per-process-limit jetsam kills in the first 150 s and four by the end of follow-up, attributed to ReportCrashService; r99p records three in its 150 s. Vnode count reaches 66560 with ~49000 free entries in both. The old statement “EL0 TRAP=0 is not zero faults” remains applicable.
