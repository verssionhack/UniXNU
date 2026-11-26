# r101 A3r1 — rebuilt on accepted A2r1; host-verified, not booted

**Status:** built, prelinked, packaged and host verification **PASS**. **Hardware boots: 0.** A3r1 requires its own explicit go. This replaces the old A3 candidate as the potential paired experiment; old A3 `abcc9a4c...` is preserved and must not be booted as an A2r1 comparison.

The accepted parent is A2r1 boot `2d084a20a7a77a08caa4122408a080310d93207e228df746db53604325af5597`, capture `boot-A2r1-20261121-055146`, raw log SHA256 `ca8251369da34d8862677bb0beea3002125a5cd6de5b5f97a6ef6d48e8e3ee71`. Parent identity is recorded in preparation/verification metadata. No TimeSync, display, network, Data, forced-note policy, USB descriptor or key change is included.

## Exact source and machine-code delta

`out/liuqin-r101-a3r1-work/evidence/A2r1-to-A3r1.patch` adds one line in `osfmk/arm64/start.s`:

```asm
Lq76AfterToken:
    orr x0, x0, #0x40000
    dsb sy
    MSR_SCTLR_EL1_X0
    isb sy
```

Only SCTLR_EL1.nTWE bit 18 is added. nTWI bit 16 is preserved. The instruction is outside the optional EL0-access argument branch and lies in common_start used by cold and secondary/reset paths. `proc_reg.h:SCTLR_EL1_REQUIRED` already includes nTWE. Eight per-CPU readbacks must establish the effective hardware state; source does not rule out higher-EL trap routing. No WFE-as-NOP trap fallback is bundled.

Decoded bytes from the actual linked standalone image:

| Address | Bytes | Instruction |
| --- | --- | --- |
| 0xfffffff007597848 | 00006eb2 | orr x0, x0, #0x40000 |
| 0xfffffff00759784c | 9f3f03d5 | dsb sy |
| 0xfffffff007597850 | 001018d5 | msr sctlr_el1, x0 |

All A2r1 observer source files are byte-identical, including the corrected atomic USB-fence helper, early sampler, CPU readback hook, frame reader, syscall counters and frozen fault rule. The device's non-patch inputs, storage driver/seed, 999-byte arguments, ADT and trust bundle match A2r1. Native instruction/layout/UUID bytes can change with linking; identical behavior inputs do not imply a bit-identical kernel outside one four-byte file edit.

## Host artifacts and gates

| Item | Value |
| --- | --- |
| Work root / image | `out/liuqin-r101-a3r1-work/evidence/a/boot.img` |
| Boot SHA256 | `85e02fede9faad5527010843d073ab50c208fa45f3423437780835f9e0d13be9` |
| Kernel SHA256 | `c3de6b1e6d01b2b7e1f7c7e83063d688fd21e3484689bc916064adccd11727ce` |
| TEXT / DATA / TEXT_EXEC | `0x1cc000 / 0x27c000 / 0x9a4000` |
| Const VMA / gate margin | `0xfffffff007009920` / 16416 B |
| Data capacity | 536870912 bytes, unchanged 512 MiB |
| Fault-rule SHA256 | `74741e291322c5cedb5d1d679f7c4524fda5ecd75b6b5987f37c152a538145e2` |

`verify.py` passes: native build/prelink, AES/fileset checks and package readback; segment/header-padding caps; exact observer and device input comparison; preserved original source hashes; critical exec/VM/security/cache inputs unchanged; actual OR/barrier/SCTLR instruction decode; walker-last ordering and bounded USB fence; identical guard Monitor AST; replay of all **2202** accepted A2r1 guard calls; actual included fence fixtures; six post-capture assessment tests; runner `--check` with **device_action=false**. Reports, build/package logs and hashes are under `evidence/`.

No diagnostics were retired and no argument was added. The known pre-existing forced-note takeover and high-speed maxpacket policy remain as in A2r1. The optional host TimeSync work is kept in separate artifacts and makes zero kernel changes.

## Frozen runtime comparison

A future authorized run uses one volatile boot, nominal 120 s fastboot cooldown, **480 s capture**, the same abort guards and automatic verified return to fastboot. No temperature source is qualified. The available runner is:

```sh
python3 scripts/liuqin-analysis/r101/a3r1/run-a3r1.py --variant a --tag A3r1 --seconds 480
```

Do not execute it without the separate go. Runner exit 0 means the observer capture passed its acceptance contract; WFE-fix effectiveness is evaluated separately below.

1. At +60/+120/+300 s, require all 8 readbacks and **nTWE=1 on every CPU**, with nTWI unchanged. Compare MPIDR, MIDR and all other SCTLR bits, reporting any unexpected difference.
2. Preserve the exact A2r1 boundary: **two sampled WFE events through +430.631 s** (lsd and opendirectoryd, overflow=0), plus a **third raw logd WFE detail at host +474.716 s after the final dump**. Do not merge that tail record into the sampled histogram count.
3. Primary sampled-window comparison: select A3r1's latest fully accounted histogram sample **at or before observer +430.631 s**, requiring its endpoint to be at least +420 s. Report its exact endpoint; A2r1 already has both sampled events by +189.748 s and remains at two through +430.631 s. A3r1 success requires **WFE word 0xd503205f count 0**, zero histogram overflow and complete accounting through the selected sample. If coverage ends earlier, mark the comparison incomplete.
4. Independently scan the whole raw capture for WFE details, especially after the last histogram dump. Any such event contradicts WFE elimination even if an earlier sampled counter is zero. No raw record in a capped tail is not proof of a final live-counter zero; state the unsampled interval. Do not change the observers or add a final flush only to A3r1. **EL0 TRAP=0 does not mean zero faults.**
5. Compare the frozen fault inventory, ReportCrash CPU/exits/jetsam, process growth, Data/free-memory curve, syscall ENOSPC and block-submitter windows under matched timestamps. This is one pair, not a variance/rate-significance estimate. Retain per-name detail caps and separate primary histogram events from later EXC_CRASH callbacks.
6. Snapshot counts/FNV, all loss/budget fields and frame-callsite checks must pass. Keep `native_reader_validated=false` as before; raw frames remain bounded/racy. Keep the Data crossing screen and >=50 early samples. Record WFE outcomes even if the unchanged Data volume still fills or WindowServer still waits for TimeSync.

The register correction is the sole behavior variable. It is not required to fix Data fill, TimeSync, display or keystore to count as an nTWE result. Data is held at 512 MiB; A2r1's measured 14.15 MiB sampled free-page minimum is not a basis for adding 512 MiB wired storage.

## Holds

B remains optional/deferred. The separate host note `liuqin-r101-timesync-offline.md` describes concrete clocksyncd startup gates for a later targeted observation; it is not an en0 or display plan. No A3r1 boot, key access, signing, flash or device partition change occurred. A2r1 and all older evidence remain preserved. Owner-key disposition and real-key signing validation remain owner items.
