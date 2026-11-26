# Liuqin r101 A1 review follow-up and offline audit

**No additional boot occurred.** A1's image, raw capture, trace and guard sources remain preserved. A2 is built separately; see [A2 implementation](a2/liuqin-r101-a2-implementation.md). The device is left in fastboot. Labels below distinguish measured evidence, host verification and hypotheses.

## WindowServer extractions

**Measured:** all three snapshots contain exactly two threads. Their saved-register records identify tid **676** and tid **951** explicitly. A1 did not capture `THREAD_TAG_MAINTHREAD`; 676 is the older TID and first task-list entry, which suggests the initial thread but does not prove main-thread identity. A2 records the native tag.

The only captured matching-request predicates are `IOProviderClass=IOHIDSystem` (tid 676, observer +5.046 s) and `IOProviderClass=AppleDisplayManager` (+5.079 s). These are matching requests, not proof of registered notifications, matching success or service availability.

There are **39 unique open attempts**, below the last-50 cap. The same 39 records appear in every snapshot, all with observed exits and no path truncation. They finish by +5.040 s. Seven return ENOENT; none returns ENOSPC. Relative `.` paths retain their original meaning; A1 did not record the corresponding dirfd for reconstruction. Full rows are below and in `windowserver-open-history.csv` (117 snapshot records, 39 unique attempts).

**Measured:** WindowServer's errno-28 count at the +20.328 s sampling point is **zero**. locationd's is also zero. The next global summary, after +30 s, still has writer_overflow=0, proving the table had not lost any earlier writer entries. Later there is no WindowServer entry or bounded path event. The 22 later overflow events are unlabelled; their identities cannot be recovered from the table. Pinned syscall windows also show no later WindowServer activity, but those windows are not a replacement for an uncapped per-process counter. A2 adds a dedicated WindowServer counter independent of table capacity.

**Inference:** this is consistent with an idle receive/event loop, possibly early in initialization. The absence of later activity does not identify the event that should wake it. The recorded startup opens and matching requests occur well before the first nearly-full Data sample; the existing snapshots do not prove when its idle wait began. Later userspace observations still occur under severe Data pressure.

### UUID-checked symbolication

**Host-verified:** extracted main cache UUID is `8b1e17c672d6301791a4916022e3612e`, exactly matching A1. Its first mapping begins at **0x180000000**. The main cache SHA256 is `f4aefea64cb86bf2f82a0af1e0f6fde7f56b2ef67eaeba9ff3ae0cdfc1e1c36f`. The relevant text subcache is `.01`, UUID `7c9b5fa1846d3cde85d2750588409133`. All 82 cache files have saved sizes, UUIDs and SHA256s in `host-cache-manifest.json`.

For tid 676, using the recorded slide 0xbcdc000:

| Saved register | Raw | Unslid | Symbol in libsystem_kernel.dylib |
| --- | --- | --- | --- |
| PC | 0x18c224c20 | 0x180548c20 | `_mach_msg2_trap + 8` |
| LR | 0x18c237964 | 0x18055b964 | `_mach_msg2_internal + 76` |

These are **two saved register addresses, not a validated backtrace**. Disassembly confirms the `svc #0x80` at 0x180548c1c and the call at LR−4, 0x18055b960: `bl 0x180548c18`.

Tid 951 separately resolves to `___workq_kernreturn + 8` (PC) and `__pthread_wqthread + 368` (LR), consistent with the parked workqueue hint. Both saved LRs pass the host callsite plausibility check. The sampled TCR_EL1 has T0SZ=25, independently confirming a 39-bit EL0 range on the sampled cores, consistent with the source/map bounds; the mask was not selected by looking for plausible symbols. Native stack reads have not been validated by this offline work; the profile deliberately keeps `invalid_address_read_failed=false` and `native_reader_validated=false`.

WindowServer used **278 ms** cumulative CPU in A1 versus the previously reported **202 ms at 306 s** in r100b, a difference of 76 ms across unequal windows. The comparison can reflect variance or observer effect; it establishes neither.

## Data series, early errno counts and attribution limits

**Measured:** the last 43 of the 45 samples stay between **5.566406 and 5.585938 MiB** free. The initial drop is 504.406250 MiB over 20.076 s between the first and third samples. ENOSPC is an allocation failure despite nonzero statfs space; zero free blocks were not observed. The complete series is below and in `data-space-45-samples.csv`.

At observer +20.328 s, all nonzero syscall errno-28 counters are:

| PID | Process | Count |
| ---: | --- | ---: |
| 188 | coresymbolicatio | 1 |
| 105 | logd_helper | 25 |
| 51 | DumpPanic | 2 |
| 139 | triald_system | 1 |
| 108 | cfprefsd | 1 |
| 106 | dirhelper | 2 |
| 228 | triald_system | 1 |

These seven entries total **33**; WindowServer and locationd are zero at that sampling point. These are returned syscall errors, not an inventory of successful writes or physical allocation provenance.

The two selected cumulative physical counters (`logd_helper` and `kernel_task`) total 245.699219 MiB. Subtracting those from the 504.406250 MiB Data-space drop gives an arithmetic gap of 258.707031 MiB **relative to those two counters only**. It is not a rigorous lower bound on unidentified allocation: the old physical overflow bucket alone contains 233.496094 MiB, other named writers exist, the displayed top eight sum to 591.921875 MiB submitted, and windows/repeats/unmaps differ. The RAM driver calls the writer recorder with positive copied bytes after `ramSparseIO`; no physical IO failures were reported in A1, so its successful submitted/completed counts agree. A1 cannot turn those repeated copied bytes into unique allocated Data blocks. It also cannot recover the identities hidden in its legacy 31-entry physical overflow bucket. A2 records window deltas, more contexts, and each context's contribution to that legacy bucket.

### What changed from r97a to r99p?

**Host-verified:** `LiuqinScratchDisk.cpp` and `SparseDisk.h` are byte-identical between retained r97a and r99p staging. Both use the same **74048-byte seed payload**, SHA256 `072eda49e3a55e5c7e762604cdf7406d9a2421e23a8d26ea557f6f6723c32505`; r100b changes its section placement but keeps those bytes. Both report **512 MiB Data and 4 GiB kernel RAM**. The Data populate/layout/probe, stand-in preparation, CS4K, compressor and keystore settings are retained.

The exact argument delta adds `epss_step=4 smp=1 armcpu-self-ipi=1` and removes `deny-exec-audit=1` and `liuqin-storage-diag=1`. The latter starts a registry-printing diagnostic thread, not a different Data allocator. The source changes in r98/r99 enable EPSS/SMP and fix secondary startup/cache coherency; this is not a Data-size or seed change. The saved audit records these differences and hashes.

**Measured last available samples, not equal time windows:**

| Quantity | r97a | r99p |
| --- | ---: | ---: |
| statfs free blocks, 4 KiB | 49656 | 1430 |
| statfs free MiB | 193.968750 | 5.585938 |
| Sparse resident bytes | 336089088 | 531046400 |
| logd_helper submitted bytes | 12414976 | 127963136 |
| kernel_task submitted bytes | 28893184 | 199348224 |
| launchd submitted bytes | 203681792 | 151535616 |
| printed ENOSPC lines (all signatures containing ENOSPC) | 0 | 408 |

The change is a substantially different write workload under the same storage setup. Faster/concurrent startup, logging/symbolication and newly exposed faults are **hypotheses** for why; no existing run isolates a cause. EPSS-only r98b also reported no ENOSPC; r99 additionally introduced eight active CPUs. This narrows the transition without establishing that SMP alone filled Data.

### locationd mapping hypothesis

A1 did not capture the faulting task's VM map, vnode association or its shared-region slide. **The proposed full-disk file-mapping cause remains unverified.** Under the explicit *common cache slide* assumption, 0x1f9300180−0xbcdc000 = **0x1ed624180** falls in `/usr/lib/dyld`'s **`__TPRO_CONST.__data`**, symbol `lsl::sAllocatorBuffer`. This is a host-cache mapping observation, not proof of locationd's actual fault-time mapping or backing vnode, and it does not identify a private RAM Data file. The fault code is `KERN_PROTECTION_FAILURE` (0x2). A1 does not establish that a Data-backed mmap caused it.

## WFE verification and prior occurrences

**Host-verified:** 0xd503205f decodes to A64 **WFE**. Pinned `proc_reg.h` defines nTWE at SCTLR_EL1 bit 18, nTWI at bit 16, and includes nTWE in `SCTLR_EL1_REQUIRED`. The port's `start.s` instead reads/preserves firmware SCTLR, adjusts SPAN/cache/MMU/UCI/UCT/DZE bits, and does not explicitly set nTWE. `sleh.c` dispatches `ESR_EC_WFI_WFE` to `handle_wf_trap`, which delivers EXC_BAD_INSTRUCTION / EXC_ARM_UNDEFINED with the copied instruction word as subcode.

**Measured:** A1 CACHE samples show `SCTLR=0x3450d805` on MIDR 0x412fd470 and `0x3450d985` on MIDR 0x412fd480. **nTWE=0 and nTWI=0** in both. These are sampled CPU types, not an eight-core inventory; A1 lacks the faulting CPU and ESR in this record. A2 samples each CPU in its own `cpu_init` without a cross-call or register write.

The common-slide lookup of ReportCrashServ's PC yields **`_dispatch_wait_for_enqueuer + 12`** in libdispatch, and the host instruction at that address is precisely WFE. This independently agrees with the logged subcode. The per-task slide was not captured, so that lookup retains its common-slide qualification. The source, legal instruction and sampled SCTLR state strongly support the nTWE defect; an A3 bit-18-only change would test the causal effect separately.

**Measured prior records:** r99p already logs `lsd` with `sub=0xd503205f`; r100b logs both `AirPlayXPCHelper` and `mediaremoted` with the same EXC_BAD_INSTRUCTION/SIGILL/undefined/WFE signature. r97a has no such detailed record and its sampled SCTLR also has nTWE/nTWI clear. Thus the mechanism predates A1. The new A1 classification is the affected **ReportCrashServ** process/signature, not a globally new instruction-trap mechanism. The frozen five-field classification rule remains unchanged; this cross-process mechanism audit is separate.

The detail cap prevents a “one WFE fault per 480 s” rate claim. At least one A1 WFE record is visible; other events can be hidden after three details for a process name. A latent nTWE defect exposed by SMP contention, followed by crash-report/write churn, is a coherent **hypothesis**, not an established full causal chain. No WFE or WFI behavior fix was applied in A2.

## Memory at A1 end

**Measured:** `memSize=0x100000000` = **4 GiB**. The final VM row has free=225745, active=275598, inactive=282347, speculative=3413 and wired=260679 pages. Native page size is 4096 bytes; free memory is **881.816406 MiB**. The lowest captured free count is 27202 pages, **106.257812 MiB**. Counts are sampled rather than one atomic global snapshot, and the 30 s legacy cadence cannot bound a lower transient minimum. These figures do not establish safe peak headroom for a further 512 MiB of wired RAM disk. Data remains 512 MiB in A2.

## Full Data-space series

Times are seconds since observer INIT, not host capture start. Each row has blocks=131072 and bsize=4096; free=avail in every row.

| Relative seconds | Free blocks | Free MiB |
| ---: | ---: | ---: |
| 0.252 | 130558 | 509.992188 |
| 10.292 | 92375 | 360.839844 |
| 20.328 | 1430 | 5.585938 |
| 30.365 | 1427 | 5.574219 |
| 40.402 | 1425 | 5.566406 |
| 50.439 | 1427 | 5.574219 |
| 60.474 | 1427 | 5.574219 |
| 70.509 | 1427 | 5.574219 |
| 80.545 | 1427 | 5.574219 |
| 90.583 | 1427 | 5.574219 |
| 100.618 | 1429 | 5.582031 |
| 110.658 | 1429 | 5.582031 |
| 120.691 | 1429 | 5.582031 |
| 130.728 | 1429 | 5.582031 |
| 140.765 | 1429 | 5.582031 |
| 150.800 | 1429 | 5.582031 |
| 160.839 | 1429 | 5.582031 |
| 170.876 | 1429 | 5.582031 |
| 180.914 | 1429 | 5.582031 |
| 190.952 | 1425 | 5.566406 |
| 200.989 | 1427 | 5.574219 |
| 211.025 | 1427 | 5.574219 |
| 221.061 | 1427 | 5.574219 |
| 231.099 | 1427 | 5.574219 |
| 241.137 | 1427 | 5.574219 |
| 251.175 | 1427 | 5.574219 |
| 261.213 | 1427 | 5.574219 |
| 271.250 | 1427 | 5.574219 |
| 281.285 | 1427 | 5.574219 |
| 291.321 | 1427 | 5.574219 |
| 301.359 | 1427 | 5.574219 |
| 311.396 | 1427 | 5.574219 |
| 321.434 | 1427 | 5.574219 |
| 331.470 | 1427 | 5.574219 |
| 341.506 | 1427 | 5.574219 |
| 351.544 | 1427 | 5.574219 |
| 361.579 | 1427 | 5.574219 |
| 371.614 | 1427 | 5.574219 |
| 381.648 | 1427 | 5.574219 |
| 391.687 | 1427 | 5.574219 |
| 401.723 | 1427 | 5.574219 |
| 411.760 | 1427 | 5.574219 |
| 421.797 | 1427 | 5.574219 |
| 431.834 | 1427 | 5.574219 |
| 441.872 | 1427 | 5.574219 |

## Full unique open history (same at 60/120/300 s)

All have observed syscall exit and untruncated captured paths. Syscalls: 5=open, 398=open_nocancel, 463=openat, 464=openat_nocancel. errno 2 is ENOENT. Relative paths are not promoted to absolute paths.

| Sequence | Syscall | errno | Captured path |
| ---: | ---: | ---: | --- |
| 15 | 5 | 0 | `/System/Library/dyld/` |
| 17 | 5 | 0 | `/System/Library/PrivateFrameworks/SkyLight.framework/Versions/A/Resources/WindowServer` |
| 19 | 5 | 0 | `/System/Library/PrivateFrameworks/SkyLight.framework/Versions/A/Resources/WindowServer` |
| 21 | 5 | 0 | `/dev/dtracehelper` |
| 41 | 5 | 0 | `/System/Library/PrivateFrameworks/SkyLight.framework/Resources/WindowServer` |
| 43 | 5 | 0 | `/System/Library/PrivateFrameworks/SkyLight.framework/Versions/A/Resources` |
| 45 | 5 | 0 | `/System/Library/PrivateFrameworks/SkyLight.framework/Versions/A/Resources/Info.plist` |
| 47 | 5 | 2 | `/System/Library/PrivateFrameworks/SkyLight.framework/Versions/A/Resources/SkyLight` |
| 49 | 5 | 0 | `/System/Library/PrivateFrameworks/SkyLight.framework/Versions/A/Resources` |
| 51 | 5 | 0 | `/System/Library/PrivateFrameworks/SkyLight.framework/Resources/WindowServer` |
| 53 | 5 | 0 | `/System/Library/PrivateFrameworks/SkyLight.framework/Versions/A/Resources` |
| 55 | 5 | 0 | `/System/Library/PrivateFrameworks/SkyLight.framework/Versions/A/Resources/Info.plist` |
| 57 | 5 | 2 | `/System/Library/PrivateFrameworks/SkyLight.framework/Versions/A/Resources/SkyLight` |
| 59 | 5 | 0 | `/System/Library/PrivateFrameworks/SkyLight.framework/Versions/A/Resources` |
| 69 | 5 | 0 | `/System/Library/PrivateFrameworks/SkyLight.framework/Resources/WindowServer` |
| 71 | 5 | 0 | `/System/Library/PrivateFrameworks/SkyLight.framework/Versions/A/Resources` |
| 73 | 5 | 0 | `/System/Library/PrivateFrameworks/SkyLight.framework/Versions/A/Resources/Info.plist` |
| 75 | 5 | 2 | `/System/Library/PrivateFrameworks/SkyLight.framework/Versions/A/Resources/SkyLight` |
| 77 | 5 | 0 | `/System/Library/PrivateFrameworks/SkyLight.framework/Versions/A/Resources` |
| 92 | 463 | 2 | `/Library/Preferences/Logging/com.apple.diagnosticd.filter.plist` |
| 94 | 463 | 2 | `/System/Library/Preferences/Logging/Processes/com.apple.SkyLight.plist` |
| 96 | 463 | 2 | `/Library/Preferences/Logging/Processes/com.apple.SkyLight.plist` |
| 126 | 463 | 2 | `/Library/Preferences/Logging/com.apple.diagnosticd.filter.plist` |
| 130 | 398 | 0 | `/System/Library/Sandbox/Profiles/com.apple.WindowServer.sb` |
| 132 | 398 | 0 | `/System/Library/Sandbox/Profiles/system.sb` |
| 134 | 398 | 0 | `/System/Library/Sandbox/Profiles/system.sb` |
| 136 | 398 | 0 | `/System/Library/Sandbox/Profiles/dyld-support.sb` |
| 138 | 398 | 0 | `/System/Library/Sandbox/Profiles/dyld-support.sb` |
| 140 | 398 | 0 | `/System/Library/Sandbox/Profiles/com.apple.corefoundation.sb` |
| 142 | 398 | 0 | `/System/Library/Sandbox/Profiles/com.apple.corefoundation.sb` |
| 146 | 398 | 0 | `/System/Library/PrivateFrameworks/SkyLight.framework/Versions/A/Resources` |
| 148 | 464 | 0 | `.` |
| 150 | 5 | 0 | `/System/Library/PrivateFrameworks/SkyLight.framework/Versions/A/Resources/WindowServer` |
| 156 | 398 | 0 | `/System/Library/PrivateFrameworks/SkyLight.framework` |
| 158 | 464 | 0 | `.` |
| 160 | 398 | 0 | `/System/Library/PrivateFrameworks/SkyLight.framework/Resources` |
| 162 | 464 | 0 | `.` |
| 164 | 5 | 0 | `/System/Library/PrivateFrameworks/SkyLight.framework/Resources/Info.plist` |
| 166 | 5 | 0 | `/System/Library/PrivateFrameworks/SkyLight.framework/Resources/Configuration.plist` |

## Evidence and next boundary

Reproducers: `review-a1-offline.py`, `symbolicate-a1.py`, and `a2/verify-a2.py`. Offline evidence lives in `out/liuqin-r101-work/evidence/review-A1/`; the isolated A2 package is in `out/liuqin-r101-a2-work/evidence/a/`. Host extraction used the APFS library in read-only mode (DeviceLinux opens O_RDONLY), with no host mount or device partition access. Cache binaries and generated symbol caches stay outside tracked source.

A2 is observer-only and still needs its own explicit go. A3 remains a separate one-variable decision; no Data resize, nTWE fix, nTWI fix, en0 or display behavior change was bundled. Owner-key signing/rotation/relocation and offline real-key signing remain untouched owner items.
