# r101 A2 result — USB loss; observer baseline incomplete

**Verdict:** A2 was booted once, volatily, under the explicit A2-only go. It did **not** establish the required observer baseline. The host recorded a USB disconnect at capture +33.612 s and received no later data. The owner physically restored fastboot; `be7ca114` was verified before the monitoring deadline and again afterward. **A3 remains held and has not been booted.** No flash, device partition write, signing or owner-key access occurred.

This result supersedes the “not booted” status of the earlier A2 implementation checkpoint, whose pre-boot document/manifests remain preserved. The A3 build is still host-only.

## Identity and capture accounting

Evidence directory: `out/liuqin-r101-a2-work/evidence/a/boot-A2-20261120-231726/`.

| Item | Measured value |
| --- | --- |
| Command | `run-a2.py --variant a --tag A2 --seconds 480` |
| Boot image SHA256 | `ee669210dd62ce41046531450552a6bf9b527359b6541fbd74af37c8ba8823e2` |
| Kernel SHA256 | `2f6fbe7e15b2d93a227ea66cde362579023bdc03246c5f451f450e8b5cf02af8` |
| Fixed cooldown | 120.000082 s |
| Host monitoring window | 480.073985 s |
| First / last nonempty chunk | +28.153446 / +33.612370 s |
| Span of data delivery | 5.458924 s; not 480 s of usable target evidence |
| Raw USB bytes | 149479 |
| Raw USB SHA256 | `434d1e6780d9fed03916b246f21bcd160a6d422bf16468d8abb2d4752d6dccfc` |
| Guard trace SHA256 | `1c7356b3ef76134c88ca5a28a7806cc81983223cec369494e5efed7e3408257f` |
| Exact guard replay | PASS, 4721 recorded calls, including empty polls |
| Guard abort / received panic marker | none / none; silence prevents a healthy-runtime claim |
| Physical recovery | owner reported recovery; fastboot verified at 23:26:24 CST and after capture |

Fastboot download/boot exited 0. The runner also exited 0 after the owner restored fastboot; neither exit code establishes observer success. `owner-recovery.json` distinguishes physical recovery from automatic USB-command recovery. The cleanup helper found the device already in fastboot. No retry was made. Temperature remains unavailable.

## Pre-declared criteria

| Criterion | Received evidence / outcome |
| --- | --- |
| 8 per-CPU readbacks | **Incomplete:** CPUs 0–6 only; `seen=7 expected=8`. CPU 7 unknown in this dump. |
| A510 SCTLR state | **Measured:** CPUs 0–3 MIDR 0x410fd463, nTWE=0 and nTWI=0. |
| Other sampled cores | CPUs 4–6 MIDR 0x412fd470, nTWE=0 and nTWI=0. |
| Uncapped undefined counter | Four early samples, all events=0 / overflow=0; **nonzero WFE baseline not established**. |
| 60/120/300 s snapshots | **Absent:** no begin/end markers, checksums, history references or native frames. |
| Native walker / USB prefix fence | No walker-begin marker received; hardware execution/validation **not established**. |
| Fine Data series | **Incomplete:** 3 valid samples versus minimum 50; memory/block/CPU have 4 initial samples. |
| Data crossing screen | **Not evaluable:** trace ends far before the (+9.292,+21.328] s screen. |
| Scale readback | **Measured:** chosen-DT source, scale 40, effective_ticks=503316480. |
| Cache registrations | **Measured:** 82 end markers. |
| Full-run output/loss accounting | **Unavailable:** no COVERAGE/LOSS/OUTPUT summary or Data media ancestry snapshot. |

The readback dump occurs at observer initialization, then later snapshots would refresh it. The missing eighth row does not by itself distinguish late CPU initialization from a readback-hook coverage defect or another failure. It is not proof CPU 7 was offline throughout the run. It does confirm clear nTWE on all four observed little cores, extending A1's A710/X2 evidence.

## The early samples

The observer INIT is at native t_ms=18893788. Received memory samples end at relative_ms=3013. The initial Data identity was not ready; the three subsequent samples identify `/dev/disk7s1`, a 512 MiB APFS volume.

| Observer-relative time | Data free |
| --- | --- |
| +1.006 s | 486.625000 MiB |
| +2.009 s | 486.550781 MiB |
| +3.013 s | 486.484375 MiB |

This shows no exhaustion in the received interval. It does not test the A1 fill curve or establish later ENOSPC absence. At the last memory sample, free=875654 pages (3420.523438 MiB); this is an early value, not an end-of-run memory figure and not evidence for resizing Data.

Four received block windows account for their submitted bytes with zero context overflow, and the four undefined-counter windows account for zero observed events. These checks cover those early windows only. Four fine CPU windows were received; the initial one is a baseline. No comparable steady-state CPU/quiescence or crash-reporter churn window exists.

Two detailed faults were received: parkd pid 58 and pid 97, both `exc_crash/10/5/code=0x09000000`, classified **expected-existing-denial-policy** against both frozen inventories. No WFE event was recorded in the four early histogram samples; the rest of target execution is unknown. Detail records are capped. **EL0 TRAP=0 does not mean zero faults.** The guard's max_pid=0/max_si=0 are unpopulated monitor sentinels here, not valid process/CPU measurements.

## Failure boundary and uncertainty

**Measured:** the last nonempty chunk ends at +33.612370 s. The next serial read reported readiness followed by no data (“device disconnected or multiple access on port?”). Later read-only host checks found neither LIQDBG001/ttyACM nor fastboot until owner recovery. No panic marker or abort-guard trigger was received. The terminal text contains raw kernel TRAP lines; nearest-symbol lookup in this image places their PCs in `_memmove`, with one LR in `_cs_validate_hash`. Those lines do not establish an observer panic or the cause of USB disappearance.

**Inference limit:** the received failure boundary precedes the first scheduled snapshot; there is no evidence of the first native stack read. No conclusion about WindowServer's dependency, a display fix, Data exhaustion, WFE-fix effectiveness, or a specific observer defect follows. USB/power disappearance and kernel failure have not been distinguished. The new sampling and completion bookkeeping remain candidate observer effects, not attributed causes.

6514 tagged observer bytes were received, with no received line at or above 255 bytes. This partial byte count does not validate the full-run budget or zero loss. The generic analyzer's `no_reported_output_loss=true` is vacuous because no end-to-end loss summaries arrived. Its host-derived `observer_lifetime_lower_ms` assumes continued target execution and is **inapplicable after disconnect/physical recovery**; it must not be read as measured kernel lifetime. `result-summary.json` records this censoring explicitly. No frozen fault rule or parser was altered to accommodate the run.

## Reproduction and next boundary

Host-only analysis:

```sh
python3 scripts/liuqin-analysis/r101/a2/analyze-a2.py /home/kurumin/Codes/Github/UniXNU/out/liuqin-r101-a2-work/evidence/a/boot-A2-20261120-231726
python3 scripts/liuqin-analysis/r101/a2/summarize-a2-result.py out/liuqin-r101-a2-work/evidence/a/boot-A2-20261120-231726
```

The analyzer reports **A2-observer-contract-incomplete**. `analysis-a2.json`, `result-summary.json`, `boot-record.json`, `owner-recovery.json` and the exact trace are preserved with the raw bytes. Next work is offline diagnosis of the disconnect boundary and CPU-readback coverage; no new image behavior is selected from this run. A2 retry and A3 each require their own explicit go. The device is in verified fastboot; no additional boot is authorized or attempted.
