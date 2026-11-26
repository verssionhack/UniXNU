# r101 A2 offline diagnosis and A2r1 host checkpoint

**Verdict:** the requested offline audit is complete, but the +33.6 s disappearance remains **unattributed**. The terminal TRAPs do not supply a distinctive fatal signature: successful A1 contains the same `_memmove` / `_cs_validate_hash` fault class. Two fence correctness defects were found and repaired in a clean **A2r1**, built and host-validated without booting. Those defects concern false delivery acknowledgment; they do **not** explain the early disappearance by an established causal path. **Any A2 retry and A3 remain held. No new go is requested by this report.**

No hardware boot, flash, device partition access, signing or owner-key operation occurred in this audit. Executed A2, A1 and held A3 artifacts/manifests are preserved. Existing A3 `abcc9a4c...` has the old observer code; if A2r1 later becomes the accepted baseline, a paired A3 must be rebuilt with identical A2r1 observers and only nTWE changed. The old A3 image must not be treated as that pair.

## 1. Terminal TRAPs

Reproduce the exports with `python3 scripts/liuqin-analysis/r101/a2-audit/audit.py`. Outputs are in `out/liuqin-r101-a2-offline-audit/`:

- `A2-last-50-lines.verbatim.txt`: byte-preserved last 50 lines, including the final unterminated line; SHA256 recorded in the audit manifest.
- `A2-terminal-traps.json`: every parsable TRAP occurrence in that tail, with ESR/FAR/PC/LR, decoded exception class, access/level and image-specific symbol lookup.
- `trap-comparison.json`: A1/A2 raw records, log hashes and symbol classes. No guessed address mask is applied.

**Host-verified format:** `osfmk/kern/startup.c:liuqin_kabort_enter` emits the hex global sequence, ESR, FAR, PC, `rec` and LR. It carries **no CPU ID**, saved PSTATE, fault result or timestamp. Thus CPU=unknown for these records. A nearby `WDc5` identifies the watchdog thread's CPU only; it cannot be assigned to an interleaved TRAP. The `b0`/`b6` strings are separate beacon output, not CPU fields. `rec=0` means `find_copyio_recovery_entry(PC)` returned NULL; it does **not** mean VM recovery failed.

The last 50 lines contain 27 TRAP occurrences covering 18 sequence values, with duplicate forced-note/ring reports and cross-core ordering. Three LR tokens in this tail are over 64 bits because an adjacent `b0` beacon was concatenated into the token. They remain explicitly **ambiguous**, without truncation; clean copies of those same sequence records also appear. Whole-log ambiguous LR occurrences: A1=7, A2=4. Counts below are counts of emitted occurrences, not unique crashes or fault rates.

| Terminal ESR | EC / context | DFSC | Access | Tail occurrences |
| --- | --- | --- | --- | --- |
| 0x96000046 | 0x25, current-EL data abort, handled by EL1 kernel hook | 0x06, translation fault level 2 | write | 2 |
| 0x96000047 | same | 0x07, translation fault level 3 | write | 19 |
| 0x9600000b | same | 0x0b, access-flag fault level 3 | read | 6 |

All tail PCs resolve to `_bzero+0x20` or `_memmove` (+0x4c/+0xa8/+0xac). Clean LRs name `_exec_save_path+0x48`, `_bcopy_phys_internal+0x24c`, `_cs_validate_hash+0x154` and `_cs_native4k_prepare+0xa7c`. In particular, the final printed sequence 0x5094 is a write translation fault at `_memmove+0xac`, LR `_cs_native4k_prepare+0xa7c`; it is not the `_cs_validate_hash` record immediately before it. An ESR access-flag fault here is not a user-mode WFE exception.

**Comparison measured from preserved logs:** A1 has 263 parsable TRAP occurrences / 157 distinct raw records, versus A2 128 / 90. A1 contains 106 clean `_memmove+0xa8` / `_cs_validate_hash+0x154` occurrences (54 sequence values); A2 contains 14 (8 sequence values). A1's first such record is at line 1493, before the complete 60/120/300 s snapshots and long after which logs continue. A1 also contains the `_memmove+0xac` / `_cs_native4k_prepare+0xa7c` class. These observations rule out treating that class of line as an automatic panic marker; unequal windows, caps and duplicate transport prevent a rate comparison.

**Host-verified handler:** `sleh.c:handle_kernel_abort` calls the trace hook on entry, before ref/modify handling and `vm_fault`. For a non-translation fault, successful `arm_fast_fault` returns normally; a translation fault can be serviced by `vm_fault`, even with no copyio recovery entry. A failed service can still panic. The trace is therefore evidence of an EL1 fault attempt, not its final disposition. No panic/reset reason was captured for A2, so the last particular fault cannot be declared recovered or fatal from its entry line alone.

### Host USB timeline

Read-only kernel journal exports `host-kernel-USB-window.txt` and `host-kernel-A1-USB-window.txt` corroborate the host trace:

- A2: device `1209:0002`, LIQDBG001, at port `3-2.2.1.4`, enumerated 23:19:54; ttyACM0 appeared 23:19:55; the kernel logged **USB disconnect, device number 23 at 23:20:00**. No hub/controller reset or re-enumeration is present in the exported boundary window. This corroborates device disappearance, beyond a competing-open explanation for the Python serial error.
- A1: the same port/device enumerated 17:57:29 and remained until normal post-capture cleanup at 18:05:03.
- Both enumerations print `bulk endpoint ... has invalid maxpacket 64` at high speed. This is a pre-existing descriptor/USB configuration issue, not an A2-only observation. The source comment that 64 is the high-speed bulk maximum is inaccurate (high-speed bulk uses 512). A1's success means this warning alone is not an explanation for A2. No packet-size change is bundled into A2r1.

Neither host journal nor target tail establishes whether the origin was a kernel failure, target USB/PHY/power event or another link failure. No broad “USB fixed” claim follows from the fence repairs.

## 2. Exact A1 → A2 USB audit

`A1-to-A2-USB.patch` contains the complete executed change against A1's unchanged baseline USB file: two cursors, one sticky gap flag, a getter, completion stores before owner release, and cursor-gap/pending-cursor stores in `transmit`. It added no lock, sleep, interrupt-mask operation, endpoint command, transfer length change or disconnect/reset branch. Before +60 s, its getter is not consulted by the sampler or USB transfer policy. The callback only becomes a walker gate at the final snapshot stage. Therefore no direct source path from its lost flag to early endpoint teardown was found. Timing/cache effects remain possible; source review cannot prove their absence.

**Concrete fence defects found:**

1. `complete()` published the cursor for `left==0` before `event()` checked the transfer event's bus-error bit. A full-length completion with an error could be counted as successful delivery. The existing failure routine also did not invalidate an already published observer cursor.
2. The forced-note takeover path can abandon an in-flight ring transfer after its bounded wait. A2 left the old pending ring cursor intact, allowing a later note completion to acknowledge bytes it did not send. Contrary to the old comment, the takeover fallback is reached by any timed-out forced note, not only a panic: the code does not test `liuqin_panic_active` there. TRAP hooks use forced notes. This endpoint-takeover behavior predates A2; it is a potential source of transport disruption under pressure, not a new proven regression.
3. The new pending cursor was an ordinary cross-context variable. Ownership and DMA barriers supply practical sequencing on normal paths, but no C atomic publication/exchange protected that added metadata from note/USB completion contexts. A2r1 makes this metadata atomic rather than relying on the implicit device/owner sequence.

**Ring/short-transfer review:** `liuqin_debug_copy` updates `u.cursor` under the ring lock. A zero-byte lock-contention return leaves it unchanged. The A2 gap comparison runs before intentional newline/short-packet trimming; those paired n/cursor decrements do not trigger it. A clamped cursor or partial transfer sets the sticky loss flag, which affects only the later walker fence. Replay can rewind the cursor and produce conservative coverage loss; it does not reset the log's monotonic sequence. No modified path from that comparison to a halt/reset or a different USB transaction was found. A2r1 retains conservative fail-closed semantics.

**Early sampler review:** the four received fine block windows conserve bytes and show no context overflow. The source copies/resets the 256-entry block window under the existing storage gate and emits outside it; the fine CPU reader releases the CPU-exit mutex before its bounded live-process scan and reports exit races without advancing the prior baseline. The active fine path contains no native target-map walk. No concrete early-sampler lock-order defect or out-of-bounds write was found. Existing allocations/locks and repeated process enumeration can block or perturb timing; the partial trace cannot exclude that hypothesis. The early sampler is unchanged in A2r1.

### A2r1 repair scope (host-only)

A2r1 passes event status into completion bookkeeping **before releasing the existing ep3 owner**, atomically consumes pending metadata, invalidates delivery evidence on a short transfer/error/failure or forced takeover, and clears pending ring metadata for a note. Lost evidence remains sticky; a later good transfer cannot rehabilitate a dropped prefix. The pure helper never changes endpoint state, waits, masks interrupts or writes a system register. New host fixtures exercise the actual included helper on full/short/error completion, subsequent completions after loss, takeover, ordinary notes, cursor gaps, copy contention and failure.

Verification strips only the new observer calls and normalizes the status parameter, then compares the affected `fail`, `complete`, `transmit`, `note_push` and `event` transport bodies against A1. They are equal. This checks preservation of existing transport policy, not timing equivalence or absence of pre-existing races. The forced-takeover policy and descriptor settings were deliberately left as separate issues; changing them would require its own reviewed experiment.

These repairs remove false fence assurances; the fence was not yet in use in the received early interval. They are **not an attributed disconnect fix**.

## 3. Missing CPU 7

**Source and actual A2 binary verified:** the hook is immediately after `cdp->cpu_running=TRUE` in `cpu_init`. It passes `cdp->cpu_number`, not MPIDR or a cluster index. `ml_bootstrap_processors` assigns each logical cpu_id to that field. Both bootstrap `arm_init` and secondary/reset `arm_init_cpu` call `cpu_init`; no special CPU-7 bypass was found. The native readback function compares w0 to 7 and rejects only larger values, uses a 32-byte stride, writes SCTLR/MIDR/MPIDR, increments the slot's sample count and publishes `seen` with release ordering. The reader loads `seen` with acquire ordering. There is no modulo alias or normal cold-boot clear-after-store path. Captured logical slots 0–6 match MPIDR affinities 0x000–0x600.

`A1-CPU-functions.asm.txt` and `A2-CPU-functions.asm.txt` preserve native disassembly. ArmCpu's actual A2 `startThread` computes `200*logicalId + 800` and calls `_IOSleep` before registration: CPU 7 sleeps **2200 ms**, versus 1000 ms for CPU 1. Each helper then registers/starts its CPU asynchronously. A1's corresponding staggering is the same. Observer initialization has no barrier waiting for all eight stores; its initial dump is a per-slot acquire scan, not a coherent all-CPU snapshot.

**Inference:** a last secondary completing after the INIT scan is plausible and consistent with `seen=7`; the next +60 s dump could have shown it. **Not established:** actual CPU-7 completion time in A2. Its boot/SMP diagnostics and later snapshots did not arrive, and no per-slot timestamp was stored. A1's later `avail=8`, running-secondary count 7 and MPIDR slot 7 prove that A1 reached the core, not that A2 did. Index aliasing is ruled out by source/binary layout; CPU-7 bring-up success or exact timing is not ruled in by this truncated run. No unsupported CPU-hook fix is included in A2r1.

## 4. Guard hygiene and automation

**Verified:** A2 contains no `LIUQIN TASK_CPU_HDR:` or `LIUQIN EXEC_TOP:` line. `max_pid_seen` initializes to zero and is updated only by TASK_CPU_HDR.max_pid; `max_si_seen` initializes to zero and is updated only by EXEC_TOP.si. Importantly, **si is the stand-in exec count** (`stood_in`), not an idle/CPU statistic or the WFE count. Neither zero is a measured process/CPU health result. IDLE rows are not inputs to these two guard fields.

There is no universal first-window-at-50-s rule here. The watchdog first calls the PID1/perf dump at beat 5 (nominal 10 s), then the configured periodic interval; perf output coalesces detailed tables on its own ~28 s gate. In A1, the first TASK_CPU_HDR was delivered at host capture +37.703 s and first EXEC_TOP at +37.717 s, after A2's last +33.612 s chunk. Their absence in A2 is consistent with early truncation. Exact replay of A2 still passes all 4721 calls with the original guard Monitor AST unchanged.

A2r1's runner adds a separate post-capture acceptance decision. Missing snapshots/readbacks/fine series, an unfilled tail, budget failure, a terminal USB disconnect or analysis failure produces explicit incomplete status and **exit code 5**, even if capture/cleanup returned normally. Existing exceptions/recovery failure, abort guards and panic exits retain their own nonzero precedence. This acceptance step does not modify abort thresholds or infer physical recovery from USB loss; an owner record remains necessary for that attribution. Six decision tests pass, and assessing the preserved A2 capture now returns **5 / incomplete-observer-capture** without booting or rewriting the old record. The original runner and historical exit-0 record remain immutable.

## 5. Host revision identity and hold

A2r1 work root: `out/liuqin-r101-a2r1-work/`. Report: `evidence/host-verification.json`; delta: `evidence/A2-to-A2r1-USB.patch` plus `kernel/liuqin_r103_usb_fence.h` in this source directory's sibling `a2r1/`.

| Item | A2r1 |
| --- | --- |
| Boot SHA256 | `2d084a20a7a77a08caa4122408a080310d93207e228df746db53604325af5597` |
| Kernel SHA256 | `f9a990d856addcb8dd14780f25b9e1f011dceb52a8d99f3d0b3b6eef4d76095a` |
| Patch SHA256 | `aa380af65e47357fe1a4efa2e9ffdd6ffa762520ff7b228d691f93a17c1335f6` |
| TEXT / DATA / TEXT_EXEC | `0x1cc000 / 0x27c000 / 0x9a4000` |
| Const VMA / margin | `0xfffffff007009920` / 16416 B |
| Arguments / ADT / trust / Data | exact executed A2; 999 B args, 512 MiB Data |
| CPU hook, early sampler, other kernel observers | exact executed A2 source |
| start.s, nTWE/nTWI, exec/security/VM paths | unchanged A2 baseline |
| Host gates | native build, prelink/AES/fileset/package readback, input/source comparisons, fence fixtures, six assessment tests, exact guard replay and runner `--check`: PASS |
| Hardware boots in audit / A2r1 | **0 / 0** |

All runtime acceptance criteria remain unmeasured for A2r1. The offline audit weakens the “terminal TRAP proves reset” hypothesis and repairs fence evidence correctness, but **does not diagnose the actual disconnect**. Keep any retry and A3 held pending review. No display, WFE, Data-size or owner-key decision is made from this result.

## Appendix: last 50 USB lines

The following is the verbatim UTF-8 tail; Markdown adds a display newline after the original unterminated final line. The raw export retains original byte boundaries. CPU IDs and handler outcomes are not encoded and cannot be added to these records.

```text
TRAP 5026 esr 96000046 far fffffffa0d6d1000 pc fffffff00c2a1440 rec 0 lr fffffff00bedc4d8TRAP 5027 esr 96000047 far fffffffa0d6d0000 pc fffffff00c2a12bc rec 0 lr fffffff00bb7c96cTRAP 5026 esr 96000046 far fffffffa0d6d1000 pc fffffff00c2a1440 rec 0 lr fffffff00bedc4d8
TRAP 5027 esr 96000047 far fffffffa0d6d0000 pc fffffff00c2a12bc rec 0 lr fffffff00bb7c96c
b0
b6
b0
b6
AMFI: Launch Constraint Violation (not enforcing), error info: c[6]p[2]m[3]e[255], (Process was launched as a system service unexpectedly but met System Service constraints) launching proc[vc: 1 pid: 59]: /System/Library/CoreServices/ManagedClient.app/ConASP: Sleep interrupted: ref 2, signal 0x100, pid: 97
ASP: Security policy would not allow process: 97, /private/var/liuqin/parkd
LIUQIN EL0_FAULT: stage=exc_crash pid=97 comm=parkd exc=10 sig=5 code=0x9000000 sub=0x0 pc=0x100e4b660 lr=0x0 sp=0x16efb4ce8 n=2
TRAP 502c esr 96000047 far fffffffa0d7d2000 pc fffffff00c2a12bc rec 0 lr fffffff00bb7c96cb0
b6
TRAP 502c esr 96000047 far fffffffa0d7d2000 pc fffffff00c2a12bc rec 0 lr fffffff00bb7c96c
LIUQIN UI_ERR: comm=securityd pid=79 code=38 (crossarch_trap) err=45 a0=0x0 a1=0x0 path=-
LIUQIN UI_ERR: comm=securityd pid=79 code=483 (csrctl) err=1 a0=0x0 a1=0x16f84342c path=-
LIUQIN UI_ERR: comm=securityd pid=79 code=38 (crossarch_trap) err=45 a0=0x0 a1=0x16f84342c path=-
TRAP 502f esr 96000047 far fffffffa0d3ca000 pc fffffff00c2a12bc rec 0 lr fffffff00bb7c96cb0
b6
LIUQIN UI_ERR: comm=securityd pid=79 code=38 (crossarch_trap) err=45 a0=0x0 a1=0x400 path=-
TRAP 502f esr 96000047 far fffffffa0d3ca000 pc fffffff00c2a12bc rec 0 lr fffffff00bb7c96c
LIUQIN UI_ERR: comm=securityd pid=79 code=483 (csrctl) err=1 a0=0x0 a1=0x16f84358c path=-
LIUQIN UI_ERR: comm=securityd pid=79 code=38 (crossarch_trap) err=45 a0=0x0 a1=0x4f path=-
LIUQIN UI_ERR: comm=securityd pid=79 code=483 (csrctl) err=1 a0=0x0 a1=0x16f84342c path=-
LIUQIN UI_ERR: comm=securityd pid=79 code=38 (crossarch_trap) err=45 a0=0x0 a1=0x16f84342c path=-
LIUQIN UI_ERR: comm=securityd pid=79 code=38 (crossarch_trap) err=45 a0=0x0 a1=0x74000 path=-
LIUQIN UI_ERR: comm=securityd pid=79 code=483 (csrctl) err=1 a0=0x0 a1=0x16f84335c path=-
LIUQIN UI_ERR: comm=securityd pid=79 code=483 (csrctl) err=1 a0=0x0 a1=0x16f84337c path=-
w
b0
b6
WDc5 3 st 57 in 0
b0
b6
TRAP 5038 esr 96000047 far fffffffa0d4cc000 pc fffffff00c2a12bc rec 0 lr fffffff00bb7c96cTRAP 5039 esr 9600000b far fffffffb6bf2c260 pc fffffff00c2a1318 rec 0 lr fffffff00bf57130TRAP 5038 esr 96000047 far fffffffa0d4cc000 pc fffffff00c2a12bc rec 0 lr fffffff00bb7c96c
TRAP 5039 esr 9600000b far fffffffb6bf2c260 pc fffffff00c2a1318 rec 0 lr fffffff00bf57130
b0
b6
TRAP 503f esr 9600000b far fffffffb6beb0760 pc fffffff00c2a1318 rec 0 lr fffffff00bf57130TRAP 503f esr 9600000b far fffffffb6beb0760 pc fffffff00c2a1318 rec 0 lr fffffff00bf57130
TRAP 5041 esr 96000047 far fffffffa0c6b0000 pc fffffff00c2a12bc rec 0 lr fffffff00bb7c96cb0
b6
TRAP 5041 esr 96000047 far fffffffa0c6b0000 pc fffffff00c2a12bc rec 0 lr fffffff00bb7c96c
b0
b6
b0
b6
TRAP 504d esr 96000047 far fffffffa0ddde000 pc fffffff00c2a12bc rec 0 lr fffffff00bb7c96cTRAP 504d esr 96000047 far fffffffa0ddde000 pc fffffff00c2a12bc rec 0 lr fffffff00bb7c96c
b0
b6
b0
b6
TRAP 5052 esr 9600000b far fffffffb6bb46d20 pc fffffff00c2a1318 rec 0 lr fffffff00bf57130TRAP 5054 esr 96000047 far fffffffa0d5ce000 pc fffffff00c2a12bc rec 0 lr fffffff00bb7c96cTRAP 505a esr 96000047 far fffffffa0d9d6000 pc fffffff00c2a12bc rec 0 lr fffffff00bb7c96cTRAP 505d esr 96000047 far fffffffa0d2c8000 pc fffffff00c2a12bc rec 0 lr fffffff00bb7c96cTRAP 5066 esr 96000047 far fffffffa0b792000 pc fffffff00c2a12bc rec 0 lr fffffff00bb7c96cTRAP 5067 esr 96000047 far fffffffb6fe83000 pc fffffff00c2a131c rec 0 lr fffffff00bf54d58TRAP 508b esr 9600000b far fffffffb6bad7700 pc fffffff00c2a1318 rec 0 lr fffffff00bf57130TRAP 5071 esr 96000047 far fffffffb6fe8c000 pc fffffff00c2a131c rec 0 lr fffffff00bf54d58TRAP 5094 esr 96000047 far fffffffb6fe88000 pc fffffff00c2a131c rec 0 lr fffffff00bf54d58
```
