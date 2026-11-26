# r101 A2 review follow-up (offline; no new boots)

A2 has been revised to put the first native reader last and preserve its evidence prefix. A3 is prepared as A2 plus nTWE only. Neither has been booted. Each still needs a separate explicit go. No flash, device partition write, signing or owner-key access occurred.

## Services

**Measured from retained logs:** both r100b and A1 contain `cls=IOHIDSystem name=IOHIDSystem parent=IOResources`. Neither contains an AppleDisplayManager class/name or a captured child with that provider. Both sweeps report `svc=173 tree_io=229 tree_dt=24 disp_hits=6 ext_hits=5`.

**Host-verified coverage:** `LiuqinRootPolicy.cpp:liuqin_ioreg_display_dump` iterates IOService matches without a service-count cap, printing display-keyword class/name hits up to 64; only six hits were counted. `AppleDisplayManager` contains “display” and would pass that filter. The service-tree supplementary walk has depth 10 / 2048-node limits, but the service iterator does not use those limits. HID/other extended hits have their own 24-line cap; only five were counted. Thus the evidence supports **no registered AppleDisplayManager returned by that service sweep at its sample time**, while IOHIDSystem exists. It does not prove lifetime absence, lack of an unpublished instance, or that WindowServer registered a notification. Classes with arbitrary names whose provider is AppleDisplayManager would not necessarily pass the print filter. This is a concrete display-service hypothesis, not a reason to change A2 or bundle a display fix with A3.

## All visible detailed faults

Reproduce with `python3 scripts/liuqin-analysis/r101/review-a2-offline.py`. Full rows, raw addresses, line numbers, symbols, crash-code decoding and log hashes are in `out/liuqin-r101-a2-work/evidence/review/offline-review.json`.

| Run | Recorded shared slide | Detailed records | PC in cache TPRO_CONST | Fault address in cache TPRO_CONST |
| --- | --- | --- | --- | --- |
| r99p | 0x1e814000 | 13 | 0 | 0 |
| r100b | 0xa058000 | 12 | 0 | 0 |
| A1 | 0xbcdc000 | 10 | 1 | 1 |

**Inference conditional on the run's common shared region:** the single TPRO record is locationd A1, with PC equal to fault subaddress at dyld `lsl::sAllocatorBuffer` (`0x1ed624180` unslid). This is one record counted in two columns, not two faults. KERN_PROTECTION_FAILURE alone does not establish a write: PC equals the data address and no ESR/access-direction observation was captured. An attempted instruction fetch/invalid branch is also possible. No fault-task VM map or task-specific shared-region identity was captured; private regions cannot be excluded. Kernel source assigns slide/UUID from the attached shared-region object, so a common slide is structurally supported but not demonstrated for every fault task.

The nine parkd PCs are below the shared-cache range (stand-in image; not cache segments). Three r99p locationd addresses and one r100b locationd address fall outside the native 39-bit user VA range; no guessed PAC/address mask was applied. These remain unclassified raw addresses. All remaining visible PCs resolve to cache `__TEXT.__text`: four WFE records at libdispatch `_dispatch_wait_for_enqueuer+12`; eight ReportCrashServ records at libsystem_kernel `__proc_info+8`; nine appinstalld records at `__abort_with_payload+8`. These are register locations at signal/exit reporting, not necessarily initiating root causes. EXC_BAD_INSTRUCTION subcodes are instruction words, EXC_CRASH sub=0 carries no fault address. The three-detail cap means this inventory cannot classify unseen faults or establish global absence. EL0 TRAP=0 does not mean zero faults.

## EXC_CRASH correction

**Host-verified:** pinned `bsd/kern/kern_exit.c:2145–2155` packs `(WTERMSIG(rv)&0xff)<<24 | (uu_exception&0xf)<<20 | (uu_code&0xfffff)`. Therefore 0x09000000 means terminating **SIGKILL**, and 0x06000000 means **SIGABRT**; both have original exception/code zero in these records. Although reason.h assigns EXEC=9 and DYLD=6 to separate namespaces, those namespaces are not encoded here. A1 ReportCrashServ's two EXC_CRASH details carry 0x09, not 0x06. The proposed five-record DYLD grouping is unsupported. Exit-reason namespace/code would need separate `p_exit_reason` evidence. appinstalld's abort-with-payload PC is consistent with a deliberate abort but does not itself identify the namespace.

## TPRO handling

**Host-verified kernel:** `shared_region_tpro_protect()` returns false; native `pmap_set_tpro_internal()` is a no-op, `pmap_get_tpro()` and `is_pte_tpro_protected()` return false. Generic VM metadata and checks still exist: shared-region entry construction preserves explicit TPRO only for a TPRO map/task; the region syscall rejects VM_PROT_TPRO without VM_PROT_WRITE; exec has entitlement/enforcement logic (`com.apple.security.hardened-process.dyld-ro`). A segment name does not prove hardware TPRO was active.

**Host-verified UUID-matched dyld:** symbol/disassembly files in `evidence/review/` identify `lsl::MemoryManager::writeProtect(bool)` at 0x1804f91e4 and `vmProtectCacheTPROMappings(void*,int)` at 0x1804f9404. The former selects protection 1 (read) or 3 (read/write), conditionally calls dyld `_vm_protect` on its allocator range, then invokes the latter for cache TPRO ranges. The latter iterates ranges and also calls `_vm_protect` (0x18048c63c). The inspected path uses VM protections, not a hardware TPRO register toggle. Runtime branch selection, VM protection results and locationd's actual mapping were not recorded. No TPRO behavior fix is included.

## Other verifications and experiment boundaries

**Host-verified:** Linux's arm64 cputype definitions identify MIDR part 0xd47 as Cortex-A710 and 0xd48 as Cortex-X2 (0xd46 is A510). A1's two samples therefore do not establish little-core SCTLR state. A2 retains eight per-CPU readbacks; missing CPUs are a coverage failure.

**Measured:** A1's INIT line reports `state_bytes=82568` (matching the final native layout);  82528 B was the pre-review checkpoint, before snapshot bookkeeping. The revised A2 allocated tables remain 183504 B, with an additional 1536 B static saved-stack scalar array. Its implementation document records current hashes and the changed layout. Const-VMA margin is a conservative header-padding gate, not monotonic code capacity; the prelinker separately checks rebuilt load commands against the first payload.

A2 observer-effect criteria are fixed in its revised implementation: below-16-MiB crossing bracket versus A1's (+10.292,+20.328] s, with a one-second margin; actual sampling gaps and CPU/memory/block series reported. Single-run timing changes flag possible sensitivity only. The first-use walker is after the +60 s evidence prefix and a bounded USB completion fence. A fence timeout skips it; a panic/hang after walker-begin has no behavior conclusion. Real A2 log totals/budgets and native walker validity remain unmeasured.

A3's only behavior variable is nTWE bit 18; nTWI, Data, observers, services, trust and arguments are held fixed. Data resizing and a display-service fix remain separate future experiments. Owner-key disposition and real-key offline signing remain owner items; this work does not resolve them by touching the key.
