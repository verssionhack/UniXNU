# Liuqin r101 A1 result — 2026-11-20

Labels: **measured** = captured hardware/host output; **host-verified** = pinned source or reproducible analysis; **inference** and **hypothesis** are distinguished below.

## Verdict and scope

**Measured: A1 completed the 480-second capture, all three snapshots verify, and the device returned to fastboot.** Pipeline shakedown succeeded. WindowServer dependency diagnosis takes the pre-declared **null branch**: its own receive port and a parked workqueue do not name an external dependency. No en0, display-attach or Metal change is justified.

ENOSPC syscall writers and example paths are named, but attribution is partial: the 64-entry writer table filled, async APFS context is not correlated, and path examples are rate bounded. The result does not meet the broader criterion of naming every writer or WindowServer's awaited service. No B control, A repeat or A2 boot occurred. The owner's `go` authorized A1 only; `continue` was handled as continued analysis of that run. Nothing was flashed, no owner key was accessed, and no security policy was changed.

Evidence directory: `out/liuqin-r101-work/evidence/a/boot-A1-20261120-175501/`.

| Capture evidence | Measured result |
| --- | --- |
| Cooldown | 120.000071 s, temperature unavailable, ambient not supplied |
| Capture | 480.162930 s; 1,408,024 USB log bytes |
| Boot | volatile `fastboot boot`; exit 0 |
| Guard result | no abort, no fatal marker; max_pid=438 |
| Exact replay | PASS, 2,130 recorded calls, including empty polls |
| ENOSPC print guard | peak 7.4 lines/s over 48 complete 10 s windows; threshold >16/s for two windows; no abort |
| End state | `returned_to_fastboot=true`; independently rechecked `be7ca114` |
| Boot SHA256 | `78d622042af44ac1eb555d431e826e3cfa3993fbb5a0dcca22d951b77452f75f` |
| Kernel SHA256 | `35b9f85828809d5cf68912dd285243c356f4be17c3d7a906ec181c1688542742` |
| USB log SHA256 | `139aeeb87726bb748c6cf48bba4ebb3686de8f2675cbbcf33e00d0094388f223` |

The run started at 17:55:01 CST, including cooldown; capture ended at 18:05:01 CST. Kernel observer `t_ms` is an absolute counter-derived clock with an inherited epoch; observer-relative times subtract `INIT t_ms=6165897`. It is not host boot wall time.

## Snapshot and coverage contract

**Measured:** 60/120/300 s snapshots each contain 209 evidence lines. Their begin/end markers, count and FNV-1a checksums all verify against captured bytes. All three reach waits, histories and storage stages. No snapshot truncation, logger failure or output suppression was reported.

New observer/CPU output occupies **208,849 bytes**, below 512 KiB. Maximum captured observer line is **164 bytes including newline**, below 255. The last output summary predates the capture end and reports 200,294 bytes; the larger host count includes later output.

The last coverage sample reports ring_drop=0, history_overwrite=94, payload_trunc=87, saturated=0, writer_overflow=22. History replacement and unsupported IPC payload truncation are separate from intact snapshot transport. IPC: observed=144, candidate=20, endpoint_unknown=7, decoded=0, undecoded=144, outstanding=unknown. Therefore no “no lookup” or “no outstanding request” claim is permitted. IOKit observations remain **matching requests**, not outstanding notifications. A1's user frame walker remained gated.

## WindowServer: stable null result

**Measured:** pid 111 has the same two captured threads at all three snapshots:

| Thread | Wait | Object/owner | Timing |
| --- | --- | --- | --- |
| 676 | hint=2, port receive | object `fffffff81927a700`, receiver_pid=111, receive_name=`b03` | indefinite; timer not armed |
| 951 | hint=15 | event `fffffffacc3c2bd0`; ownership not resolved | timer not armed; observer timing classification unknown |

**Host-verified:** pinned `osfmk/kern/block_hint.h` defines hint 15 (`0x0f`) as `kThreadWaitParkedWorkQueue`. The receive port belongs to WindowServer itself. Neither wait names an external service. The main thread's raw saved PC/LR are `18c224c20`/`18c237964`; shared-region base=`180000000`, slide=`bcdc000`, UUID=`8b1e17c672d6301791a4916022e3612e`. Raw addresses are retained; no guessed mask or validated backtrace is claimed.

WindowServer remains alive with exits=0 and cumulative CPU 278 ms. Its first CPU row is cumulative (279 ms window rounding); every later window reports 0 ms. loginwindow also remains alive. This establishes a parked server, not rendered display output, Metal initialization or a dependency on en0.

## Data, ENOSPC and keystore

**Measured:** Data is `/dev/disk5s1`, UUID `C7D5AD67-0CE2-4AAB-BC37-BCE0F85F6720`, APFS block size 4096, blocks=131072: **536870912 bytes (512 MiB)**. Forty-five space samples were captured.

| Observer-relative time | Free space |
| --- | ---: |
| +0.252 s | 509.992 MiB |
| +10.292 s | 360.840 MiB |
| +20.328 s | 5.586 MiB |
| Minimum sampled | 5.566 MiB |

ENOSPC occurs while statfs still reports a small amount of space. The observation does not identify the APFS reserve/allocation rule involved or attribute every allocated byte.

The **last overall errno-28 summary**, at observer +421.546 s, reports **9342 events**, with **22 events unable to obtain a writer-table entry**. Counts continue beyond the last overall summary. The table below contains the latest individually sampled per-PID/process totals, some at +441.872 s; these are lower bounds over the captured run, with different sample times. Do not sum them against 9342 or use that number as their common denominator.

| Writer | Latest observed total |
| --- | ---: |
| launchd | 8186 |
| locationd | 514 |
| dirhelper | 279 |
| logd_helper | 245 |
| analyticsd | 105 |
| cfprefsd | 66 |
| triald_system (recorded PIDs combined) | 59 |
| mobileassetd | 53 |

Bounded syscall examples identify:

- launchd, pid 1, `write_nocancel` (397): `/private/var/log/com.apple.xpc.launchd/launchd.log`.
- logd_helper, pid 105, `writev` (121): `/private/var/db/uuidtext/...` temporary files.
- coresymbolicatio, pid 188, `pwrite` (154): `/System/Library/Caches/com.apple.coresymbolicationd/grow.qZZJeoj`.
- analyticsd, pid 133, `guarded_pwrite_np` (486): `/private/var/db/analyticsd/state.sqlite-wal`.
- trustd, pid 137, `guarded_pwrite_np` (486): `/private/var/protected/sfanalytics/.../trust_analytics.db-wal`.

For uncovered syscall path attribution, the raw sentinel `<not-a-write-fd>` means the observer did not attempt descriptor-path resolution for that syscall; it is not proof that the syscall had no descriptor or pathname.

There are **1853 captured APFS `fs_tx_enter_internal` ENOSPC print lines**, all unmatchable to a proven individual syscall event because no shared correlation identifier is available. That coverage counter is separate from errno-28 totals. Physical block-writer telemetry separately records logd_helper=193,613,824 bytes and kernel_task=64,020,480 bytes, with a substantial overflow bucket. Those are submitted bytes, including repeated writes, not unique Data occupancy or logical attempted-writer identity. Neither layer is summed with the other.

**Measured Data ancestry:** AppleAPFSVolume → AppleAPFSContainer → AppleAPFSMedia → AppleAPFSContainerScheme → IOMedia (`Liuqin ScratchAPFS Media`) → IOBlockStorageDriver → **LiuqinScratchDisk (`Protocol Characteristics`, location=`Internal`)** → IOPlatformExpertDevice → root. This settles the earlier wrong-media hypothesis for this run: Data does descend from the device carrying Internal. applekeystored still reports `last_status=0x100`, exit status 1. The property alone did not resolve initialization.

## CPU attribution and idle proxy

**Measured:** the first >=95% idle sample is `usb.log:5471`, idle_pct=96, tot=517740. The eight-CPU accounting proxy is **64.718 s**, versus r100b's **74.495 s** (595963/8). This is the first threshold crossing, not sustained idle or host elapsed time. Later samples can fall below 95%. One sample per image and added observers do not establish a performance improvement or a causal regression.

`cpu-r100b-comparison.md` and `evidence-summary.json` contain all twelve ordinal CPU-window comparisons available against r100b. The first interval is cumulative, the next is about 50 s, and subsequent intervals about 30 s. r100b only logged top10 plus pinned processes; missing baseline rows are **unknown**, never zero. A1 logs top15 plus pinned rows.

In the first complete ~50 s window (50023 ms A1 / 50024 ms r100b):

| Process | A1 CPU ms | r100b CPU ms | Delta |
| --- | ---: | ---: | ---: |
| ReportCrashServi | 33166 | 51253 | -18087 |
| lsd | 32027 | 32354 | -327 |
| ReportMemoryExce | 14813 | 17169 | -2356 |
| logd_helper | 5941 | 5843 | +98 |
| analyticsd | 3950 | 4458 | -508 |
| launchd | 2916 | 3241 | -325 |
| WindowServer | 0 | 0 | 0 |
| Aggregate header | 126674 | 150994 | -24320 |

**Inference:** crash/report processing is a major varying workload; it is a better-supported CPU lead than WindowServer. This does not prove that ENOSPC caused that CPU, that ReportCrash filled Data, or that observer overhead is negligible. Across A1, ReportCrashServi reaches 65,068 ms cumulative CPU and 31 exits. Per-window data remain available for reviewing the timing relationship.

## Fault inventory, jetsam and vnodes

**Measured:** EL0 TRAP=0; ten detailed EL0 fault records; final `EL0_FAULT_SUM tot=28 ovf=0`. **EL0 TRAP=0 is not zero faults.** The summary counts observer invocations before duplicate-thread suppression; it is not a count of unique crashes. Detail logging is capped at three records per process name.

The analyzer was corrected after capture to compare `(comm, stage, exc, sig, code)` instead of process names alone. Raw PCs are not normalized. Five new host regression tests pass, including two radix checks: native `%llx` fields now retain explicit hexadecimal notation even when they contain only digits. Raw lines remain unchanged. Against both retained r99p and r100b inventories:

| Detailed records | Classification |
| --- | --- |
| parkd pids 97, 58, 114; exc_crash/10/5/0x9000000 | expected existing denial policy (3) |
| ReportCrashServ pids 230, 250; exc_crash/10/5/0x9000000 | pre-existing unresolved signature (2) |
| appinstalld pids 251, 259, 264; exc_crash/10/5/0x6000000 | pre-existing unresolved signature (3) |
| locationd pid 81; ux_sig/1/10/0x2 | signature not observed in either compared capture (1) |
| ReportCrashServ pid 275; ux_sig/2/4/0x1, sub=0xd503205f | signature not observed in either compared capture (1) |

“Not observed” is bounded by the baseline captures and their caps; neither unmatched signature is declared globally new or expected. Process-name matching alone previously hid these differences. Missing AirPlay/mediaremoted details do not prove those processes are fault free.

Jetsam ends at **3 kills**, all attributed by `JETSAM_TOP` to **ReportCrashService**, cause 7 (`per-process-limit`), reported limit 15 MiB. These are not a newly established A1-only effect: retained r99p ends at 3, r100b at 4. Vnodes end at num=desired=max=66560, with **49160 free**, vk=0/0, va=0. Exhaustion is not established by the high allocated vnode count.

## Next decision and reproducibility

The next diagnostic direction is the user-side wait path, using the already staged candidate-walker/host-validation route, not an en0 or display behavior change. Before a candidate build, address the writer-table overflow and preserve A1's images/logs. Every further boot still requires a separate go. B adds no immediate named-dependency answer and remains an optional, multi-variable contrast; it has not been hardware qualified. No conclusion is drawn about display-only effects.

Reproduce from the finalized capture:

```sh
python3 scripts/liuqin-analysis/r101/replay-exact.py out/liuqin-r101-work/evidence/a/boot-A1-20261120-175501
python3 scripts/liuqin-analysis/r101/analyze.py out/liuqin-r101-work/evidence/a/boot-A1-20261120-175501
python3 scripts/liuqin-analysis/r101/summarize-a1.py out/liuqin-r101-work/evidence/a/boot-A1-20261120-175501
```

`boot-record.json`, `guard-trace.jsonl`, `analysis-r101.json`, `evidence-summary.json` and `cpu-r100b-comparison.md` retain the raw evidence, sampling times and limitations. Owner-key approval/rotation/relocation and offline real-key signing remain untouched owner items.
