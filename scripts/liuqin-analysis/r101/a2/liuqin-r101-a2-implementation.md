# Liuqin r101 A2 observer implementation — built, not booted

**Host-verified:** A2 is built, prelinked, packaged and validated in a separate work directory. **Hardware boots: zero.** It requires its own explicit go. No flash, device partition change, owner-key operation or signing occurred. A1's raw capture, image and guard sources remain unchanged.

Offline findings and all requested A1 extractions are in [the A1 review follow-up](../liuqin-r101-a1-review-followup.md). That audit confirms WFE instruction signatures in r99p and r100b, not just A1. The strongest next behavior experiment remains a separately scoped nTWE change; this A2 image applies no such change.

## Artifact and baseline identity

| Item | Value |
| --- | --- |
| Boot image | `out/liuqin-r101-a2-work/evidence/a/boot.img` |
| Boot SHA256 | `ee669210dd62ce41046531450552a6bf9b527359b6541fbd74af37c8ba8823e2` |
| Kernel SHA256 | `2f6fbe7e15b2d93a227ea66cde362579023bdc03246c5f451f450e8b5cf02af8` |
| Observer patch SHA256 | `bff0c4f9b7852acfdd4e5bd2bbd2a011115052c82fedb578b020f0c6dafccca1` |
| Arguments | exact A1/r100b, **999 bytes**; no new argument |
| ADT and trust bundle | exact A1 identity |
| Data | **512 MiB**, identical seed payload and SparseDisk behavior |
| SCTLR write path | unchanged `start.s` and `proc_reg.h`; no nTWE/nTWI change |
| SMP, EPSS, display, keystore | same A/r100b configuration |

The A1 artifacts remain at `out/liuqin-r101-work/evidence/a/`. The new work root is `out/liuqin-r101-a2-work/`; it references the preserved r100b source freeze and stages its own device/observer inputs. Only A is built. B remains optional, multi-variable and unqualified as a runtime control.

| Layout | A2 | Gate |
| --- | --- | --- |
| `__TEXT` | `0x1cc000` | <= `0x1d8000` |
| `__DATA` | `0x27c000` | <= `0x284000` |
| `__TEXT_EXEC` | `0x9a4000` | recorded |
| `__TEXT,__const` VMA | `0xfffffff007009920` | >= `0xfffffff007005900` |

The const-address gate passes with **16416 bytes** of headroom. Segment headroom is 48 KiB TEXT and 32 KiB DATA; these are different constraints. Further observer additions need another full layout check. AES/fileset/package gates passed; no runtime FIPS/AMFI/registration success is presumed.

## Added observations

1. **Data and memory:** nominal 1 s cadence for the first 60 s after observer initialization, then 10 s for Data/memory/block counters. Actual timestamps are emitted; scheduling, vfsstatfs and locks can delay the worker. Free/active/inactive/speculative/wired page counts and page size are reported as non-atomic samples. No Data resize occurs.
2. **Syscall errno-28:** writer table grows 64→256 entries, with a separate snapshot copy in allocated observer state. Uncapped total and overflow count are reported at the same sampling cadence. A dedicated WindowServer total is updated before table lookup, so table saturation cannot hide its errno-28 count. Path examples retain their bounded rate; uncovered syscalls and asynchronous writeback still do not gain a fabricated path.
3. **Block submission context:** a separate 256-entry per-window table records PID/comm, bytes and writes, then resets under the existing storage gate. It records each named context's contribution to the **legacy 31-entry overflow bucket**, with matching per-window legacy totals. The original cumulative diagnostic remains. This RAM driver records positive copied/completed bytes after `ramSparseIO`, including partial positive copies, not failed zero-byte attempts; A1 had no physical IO failures. Repeated copies still do not measure unique allocation. New-table overflow bytes/writes remain explicit unknowns. Fine CPU output keeps top four plus named pins; legacy top-15 output is unchanged. This identifies the block submitter, not necessarily the logical attempted writer or vnode path. Repeated physical writes and unmaps prevent a unique-allocation accounting claim.
4. **CPU correlation:** independent per-command CPU windows at the early sampling cadence, top four plus WindowServer/ReportCrash/logd_helper/coresymbolication pins. Exited-process totals are included from the existing exit accounting table. Sampling uses separate cumulative/previous buffers and never changes legacy 50/30 s CPU windows, filters or abort guards. If exits occur across the live-process snapshot, that CPU sample is explicitly skipped and the previous baseline retained; the next valid interval can exceed 1 s. Live snapshot limit is 384, comm limit 256; missing/overflow metadata are reported. Commands aggregate multiple PIDs and comm strings are bounded.
5. **Per-CPU SCTLR:** each CPU records its own SCTLR/MIDR/MPIDR in `cpu_init` after the existing CPU-running assignment. The callback only stores scalar values; it does not print, allocate, cross-call or write control registers. The worker reports all seen entries at initialization and snapshots, including nTWE/nTWI and an expected-eight coverage line. Eight successful readbacks are a runtime criterion.
6. **Undefined instruction events:** uncapped primary `ux_sig` / EXC_BAD_INSTRUCTION / SIGILL / EXC_ARM_UNDEFINED counters by command and instruction word, with a 64-key table, independent total and overflow. They use the subcode already supplied by the existing hook, add no instruction read, and run before the old detail cap. WFE and WFI words stay separate; the later `exc_crash` stage is excluded. These count primary hook events, not unique crashes or all EL0 faults; zero capped detail/TRAP lines still does not mean zero faults. Deltas are sampled with Data; a host test verifies 100 WFE events beyond the legacy three-detail cap.
7. **User-state candidates:** A2 selects the already implemented raw frame mode. A walk first requires a failed invalid-address non-fault read, then reads at most depth 16, with 64 frames per snapshot in total. Target-map reads disable VM faults and restore the map; unavailable/nonresident-or-unmapped reads are observer limitations, not target errors. Range/alignment/progression limits remain. Native thread tags identify the main/workqueue roles where the kernel tagged them. Raw LRs are retained; native walking is **not yet hardware validated**.

The recorded block/memory/CPU timestamps share the worker's nominal sampling endpoint. Gate wait, process enumeration and filesystem sampling are not one atomic system snapshot. Initial block/CPU records are labelled initial with dt=0; do not treat pre-observer writes or initial cumulative totals as one-second rates. Resetting the new per-window table recycles slots across PID churn without modifying disk contents.

## Walker validation and limits

The host cache set is now extracted and SHA/UUID pinned; main UUID `8b1e17c672d6301791a4916022e3612e` and unslid base `0x180000000` match A1. A1's two saved WindowServer LRs both follow valid call instructions under the recorded 39-bit VA geometry and shared-region slide. The bounded frame engine's host fixtures pass, and the native candidate branch compiles. The unused legacy known-two-LR native fixture hook was retired in A2 to make room for the instruction counter; A1 retains its original diagnostics. No trusted native-walk gate is silently enabled.

That validates the host address/callsite route and synthetic engine, **not native copyin or an actual user stack**. A2 supplies raw candidates plus invalid-read evidence; `frames-from-log.py` exports them only from checksum-verified snapshots. `validate-user-frames.py` strips PAC bits using the recorded VA width, subtracts the slide, verifies cache UUID/SHA/mapping permissions and requires BL/BLR/authenticated-BLR at LR−4. Main-executable, nonresident or invalid frames remain unresolved; no kernel-side trust flag is enabled from plausibility. Symbolication is separate from proving a complete backtrace.

A2 snapshot checksum/export helpers include both **LQ101 and LQ102** evidence, so new SCTLR/thread-tag lines cannot be silently excluded from transport verification.

To reserve log space for the fine series, unchanged histories now carry a checked reference to the earlier full snapshot. Open-history revisions advance on both entry and completion updates; IPC history uses its monotonic captured-message head. A change forces a new dump. Host analysis requires the referenced source snapshot and its row count/checksum to verify, with matching n/revision. Unsupported IPC wire-text formatting is retired in A2; IDs/peers/object metadata, bounded in-memory prefix capture, loss counters and explicit undecoded coverage remain. A1's original wire text is preserved. These are diagnostic-output changes, not service or policy changes.

## Bounds and diagnostic retirement

The hook ring remains 256×224 = **57344 bytes**, drop-new for hooks only. Snapshot evidence continues directly from the worker with retrying logger append, begin/stage/end markers and end-to-end line count/hash checks. Maximum formatted text is 252 bytes plus newline; total new-output budget remains **512 KiB**. Future snapshots reserve **96 KiB each**, with the existing summary reserve, to permit the denser early series. A1 used about 32 KiB per snapshot; raw frames and eight readbacks add bounded evidence. Budget suppression, formatter rejection, incomplete windows or missing snapshots are failures/coverage limits, not absence evidence.

Compiler DWARF reports `r101_state` **106696 B** and independent `r102_cpu_state` **48136 B**. Two block-window arrays are 256×56×2 = **28672 B** on the native LP64 layout, totaling **183504 B** for these allocated tables, versus A1's 82568 B state. The SCTLR array is 8×32 = 256 B static storage. Existing transient snapshot references/frame buffers remain bounded. Allocation failure is reported and does not change the disk's success/failure policy. The 8 KiB framebuffer panic tail and independent USB panic stream are preserved.

## Frozen rule, checks and pre-declared outcomes

The five-field fault rule is frozen **before A2 build/capture**:

- fields: comm, stage, exc, sig, code; no guessed PC normalization;
- source SHA256: `74741e291322c5cedb5d1d679f7c4524fda5ecd75b6b5987f37c152a538145e2`;
- frozen source and descriptor: `out/liuqin-r101-a2-work/evidence/analysis-rule-frozen.py.txt` and `analysis-rule.json`;
- A2 analysis refuses a changed rule source. Baseline caps and “not globally new/absent” limits remain.

`verify-a2.py` passes: native build/prelink/package and AES gates; exact A1 arguments/ADT/trust/seed/read-write transport; unchanged SCTLR write path and critical VM/SMP/Data source; 6143 original source hashes; frozen observer source identity; guard Monitor AST equality; replay of all 2130 actual A1 guard calls; twelve new A2 parser/replay tests; the actual native block-observer host harness (PID separation, conservation, legacy-bucket breakdown, overflow and recycling); an actual instruction-counter host harness (stage filtering, WFE/WFI separation, 100 uncapped events, deltas, overflow and line bounds); eleven host callsite/export tests and five fault/radix tests. The saved A1 log/guard replay still passes. All checks are host-side.

Success criteria, fixed before this unbooted run:

- complete 60/120/300 s snapshots and matching count/hash; no reported output loss;
- scale 40, same 512 MiB Data identity/ancestry; eight CPU readbacks with nTWE/nTWI values;
- observed early one-second Data/memory/CPU/block series with actual dt, at least 50 successful Data samples in the first 60 s, explicit skipped CPU races and conservation of named+unknown block bytes/writes; sampler output reaches within 15 s of the observer-lifetime lower bound derived from INIT delivery and host capture end;
- intact/reconstructable histories, instruction-word totals accounted without capped-detail inference, and complete legacy-bucket breakdown when new-table overflow is zero; dedicated WindowServer errno count even if the syscall table fills;
- raw candidates exported with invalid-read evidence and host callsite validation attempted; unresolved/read failures remain explicit.

Null outcomes: generic receive/workqueue waits, nonresident frames or no named user dependency do not select en0/display/Metal changes. Missing readbacks, snapshot/window loss, overflow, a panic or a worker hang is an observer failure/coverage limit. A1's fixed guards and >16 printed ENOSPC lines/s for two 10 s windows remain; uncapped errno event rates do not reuse that threshold.

## Concrete commands — no boot run yet

Recheck without device action:

```sh
python3 scripts/liuqin-analysis/r101/a2/verify-a2.py
python3 scripts/liuqin-analysis/r101/a2/run-a2.py --variant a --check
```

Only after a **separate explicit A2 go**, the prepared volatile run is:

```sh
python3 scripts/liuqin-analysis/r101/a2/run-a2.py --variant a --tag A2 --seconds 480
```

The runner retains the logged 120 s cooldown, exact chunk/empty-poll trace, existing guards, full capture and verified return to fastboot. It never flashes. It has not been invoked without `--check`.

After that authorized capture, `a2/analyze-a2.py <folder>` checks both prefixes and block-window conservation, and `a2/frames-from-log.py <usb.log> --target 60 --output <frames.json>` provides raw host-validator input. A3 remains a separate one-variable behavior experiment; Data, nTWE, nTWI, en0 and display behavior are unchanged here. Owner-key items remain untouched.

## Review revision before first A2 boot

Earlier unbooted A2 revisions and their manifests are preserved under `evidence/a2-before-walker-last/` and `evidence/a2-before-fence-gap-check/`. The hashes above select the final revision, including fail-closed gap detection.

The worker first collects wait/register evidence without target-map reads, then emits histories, storage, all SCTLR readbacks and coverage. `stage=walker-begin` is the final stage marker. It captures the logger byte fence and waits at most 2000 nominal 1 ms sleeps for a successful complete USB bulk-IN transfer through that fence. Only then does it read saved FP/SP candidates; a timeout skips walking. USB completion is delivery evidence, not proof of host-file persistence. A panic/hang during the native reader leaves the prefix and walker-begin marker on the host; a normal return produces WALK_END and the snapshot end checksum. Saved scalar state remains racy; task lifetime is retained through the final stage. A detected short USB transfer or console-ring cursor gap makes the fence fail closed for the rest of the boot; later completions cannot conceal that loss. A bounded 64×24-byte scalar array (1536 B) is additional static storage. The hook ring and allocated table sizes above are unchanged. USB completion bookkeeping is observer code; the USB data path is no longer byte-identical to A1.

Observer-effect screen, fixed before A2: use the first free-space sample below 16 MiB. A1 brackets this crossing in (+10.292,+20.328] s, rather than measuring an exact fill time. Flag A2 as outside the baseline timing envelope if its crossing bracket does not overlap (+9.292,+21.328] s, or if fewer than 50 successful one-second samples occur before +60 s. Report all actual dt and memory/CPU/block rows. A single pair can flag sensitivity, not establish causation or variance. The first walker starts after that interval. Guards remain unchanged. Actual output bytes, snapshot sizes and overflow must be audited after capture; no A2 totals are predicted from A1.

A1's final state is 82568 B; 82528 B was the earlier checkpoint before snapshot bookkeeping. The final A1 const VMA was `0xfffffff007005ea0`; `...6140` belonged to an earlier checkpoint. The gate protects room for expanding Mach-O load commands (including the sparse-index section) before the first section payload, not a monotonic executable-code budget. The revised A2 crosses a 16 KiB layout boundary: const VMA is `...9920`, with 16416 B above the conservative `...5900` gate. Every later build must pass both this check and the prelinker's actual header-versus-payload collision check.
