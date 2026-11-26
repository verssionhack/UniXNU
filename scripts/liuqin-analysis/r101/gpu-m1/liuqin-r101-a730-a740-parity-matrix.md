# r101 Milestone 1: A730 / SM8475 versus existing A740 backend

Date: 2026-11-21. **Host research only. No XNU driver edits, builds, image
emission, device commands, partition writes or key access.** Display/input
driver investigation remains deferred. A7 and the graphics boot hold are intact.

Labels: **source-verified**, **host-measured**, **reported**, **inference**,
**(verify)**. Source references below use the locally extracted release snapshot,
not the unreliable source working tree. Evidence root:
`out/liuqin-r101-gpu-m1/evidence/`.

## Status and implementation boundary

The source parity matrix and concrete tables are delivered. A730 is implemented
in the Linux reference, and the pinned Mesa source recognizes its exact chip ID.
The existing XNU backend has reusable contracts, but it is not an A730 driver
selected by changing one chip constant. Important differences include clock
gating, GMEM policy, RSCC offsets, firmware, HFI queue provisioning, preemption
storage and platform policy.

**Do not call hardware qualification complete.** Neither repository supplies,
in the inspected material, the running kernel identity/dirty delta associated
with the accelerated session, a live SM8475 command-database dump, or evidence
of the actual entry EL and hypervisor SMC interception. Exact derived ARC vote
words, live SMMU addresses, and physical SMC routing cannot be manufactured
from source alone. Those boundaries are itemized below; no driver code is
written while claiming they are resolved.

## 1. Snapshot integrity and commit reconciliation

**Host-measured:** selected GPU, clock, IOMMU, firmware/SCM, SoC, interconnect,
power-domain, Qualcomm DTS and binding trees were exported with `git archive`
from the original object database to the local `/home` filesystem. This reads
committed objects rather than copying the failing working tree. The archive is
33,679,360 B. The extracted tree has **2,570 Git entries: 2,566 regular files
and four symlinks**. Every blob ID, including symlink-target bytes, was checked
against the corresponding commit tree. SHA256 inventories accompany the copies.

| Reference | Exact identity | Qualification |
| --- | --- | --- |
| Original local kernel HEAD | `e6ed309612463f1c891d58b0c357b79a8be640e8` | Object-exported, readable local snapshot `linux-head` |
| Companion-selected release | `fe81794b5e1b8a3f11a165f3acbfdb8fa671dbb3` | Fetched into a separate local bare repo; materialized as `linux-release-clean`; every one of 2,570 blob IDs verified |
| Earlier hardware-document reference supplied by owner | `b077845366409367c3fc44e9f8c86fdc3957f945` | Resolved in original object DB; selected-tree comparison preserved |
| Companion | `0ea1508088ea83936c34a9a04ab1c02482e2a84a` | 127 regular files exported under `companion-safe`; four overlay symlink targets recorded without materializing absolute links |
| Existing local Adreno740 / AdrenoMetal | `08a32b56e1b9e9d0e9d2ee0644d1c5825e8215fe` / `c68f9a1db77961e0f7e18e48f95aeb95ac649650` | Tracked status clean; comparator source copies and individual hashes frozen |
| Catalog-pinned Sm8550Platform | `a9f45dc60c035084b95463781538380f4c3606c9` | Separate sparse checkout of UniXNU-sm8550-common; kit copied into comparator snapshot |

The existing driver checkouts differ from the catalog revision pins. This audit
compares the **actual local backend**, with its precise revision and source
hashes, rather than silently treating it as the catalog version.

The release snapshot was reconstructed from the exported HEAD plus differing
release blobs, then checked against the release tree. Two earlier failed copy
attempt directories (`linux-release`, partially populated) are **not reference
inputs**. The authoritative release directory is `linux-release-clean`.

**Host-measured:** HEAD→release has **13 changed files** across all selected
trees (`head-release-tree-diff.json`, full `head-to-release.patch`):

- Within `adreno/`, only `a6xx_gmu.c` changes: recovery forces **cold boot**
  when `a6xx_gpu->hung`, because retained-TCM status can survive loss of TCM.
  The release has this fix; HEAD and b077 do not.
- GPUCC is identical; the clock-tree change is `camcc-sm8450.c`.
  All selected IOMMU files, register XML, catalog, CP initialization,
  submission and preemption files are identical.
- SCM/MDT additions support QSEE application handling. Extracted PAS init,
  memory setup, auth/reset, MDT PAS init and existing MDT load functions are
  byte-identical between HEAD and release. Thus these additions do not alter
  the extracted GPU PAS call contract.
- Liuqin DTS differences concern camera/fingerprint and associated resources;
  its GPU activation, ZAP filename, and inherited GPU/GMU/SMMU nodes are unchanged.
  Other differences are DP handling and GPU busy/devfreq telemetry.

b077→HEAD changes six selected files: Liuqin DTS, three DP files and two
PMIC-GLINK files. **No selected Adreno/GPUCC/IOMMU/SCM/MDT implementation
changes.** The supplied `HARDWARE.md` provenance is not a runtime proof; that
file was not located in the tracked repository inventory inspected here.

**Inference:** use the release snapshot as the primary source reference because
the companion selects it and it adds a relevant recovery correction. Both trees
carry the same basic A730 bring-up. **(verify)** which exact build produced the
reported accelerated session remains dependent on its build/run identity.

## 2. Core parity matrix

Numeric tables: `clock-gating-parity.json`, `protection-parity.json`,
`powerup-parity.json`, `register-offset-parity.json`. Register indices in these
tables are **dwords**, with byte offsets recorded separately. Annotated exact
function bodies are in `source-excerpts.txt` and `source-excerpt-index.json`.

| Area | Linux A730 reference | Existing A740 / SM8550 backend | Adaptation decision |
| --- | --- | --- | --- |
| Identity | `0x07030001`, `ADRENO_7XX_GEN1` | A740 `0x43050a01`, GEN2; GMU override `0x07020100` | Explicit chip/platform profile, never reinterpret A730 as A740 |
| GMEM | 2 MiB | 3 MiB Linux A740 profile | Report correct size through ABI and compiler; change allocation/restore assumptions |
| Quirks | Cached-coherent, HW APRIV, preemption | Same three catalog quirks | Shared capability intent, not proof of correct CPU/GPU cache handling |
| HW clock gating | 53 writes, A730 table | 54 writes; native generated A740 table exactly equals Linux A740 table | Replace profile data; 11 differing/exclusive addresses below |
| CP protection | 48 slots, skips 45/46, writes 46 slots including final infinite span | Native table exactly equals Linux shared A730/A740 protection data | Reuse verified values and write order |
| Common scalar registers | A7XX XML | 55 generated native definitions checked | All 55 resolve equally after domain/base normalization; not a proof for all GPU registers |
| CP power-up list | 17 current Linux entries, shared by A730/A740 | Native generated list has 16 | Reconcile source-version drift: missing native `GRAS_NC_MODE_CNTL`, dword `0x8602`; not an A730-only generation delta |
| CP initialization | Same `a7xx_cp_init` for GEN1/GEN2 | `NativeAdrenoCpInit` matches packet payload | Reuse encoding after A730 power-up data is valid |
| GMEM range setup | `hw_init` explicitly skips range-min/max writes on A730 | A740 writes base 16 MiB and size-dependent maximum | Do not replay A740 range programming on A730 |
| GMU clock gating mode | `0x00020000` | `0x00020202` | Profile-specific data |
| RSCC sequencer | Base dword `0x180`; hidden TCS data `0x80000000` | Base dword `0x154`; hidden TCS data `0x80000021` | Replace offset/value selection, even though sequencer payload is shared |
| Preemption records | 2,860 KiB per ring | 4,192 KiB per ring | Profile-specific allocation; same named record fields do not imply same backing size |
| HFI provisioning | Two queues, table size 120 B | Existing `AdrenoHfi.c`: three queues, 168 B table | Qualify A730 firmware queue contract before reuse; difference is not automatically a defect in the working A740 path |
| GMU memory | Debug `0x7000`, dummy `0x2000`, icache `0xffc000` | Sheng validator pins dummy `0x4000` and exact firmware/hash/block policy | Replace firmware/platform policy; retain bounded loader abstractions |
| ARC/BW votes | A730 static BW rows, runtime ARC levels/addresses | Sheng chip/OPP/BCM policy and command-DB pins | New SM8475 vote profile; no borrowed SM8550 addresses or synthesized rail levels |

Clock-gating differences (dword offsets; `—` means no write in that table):

| Register | Offset | A730 value | A740 value |
| --- | --- | --- | --- |
| CLOCK_CNTL2_SP0 | `0xb4` | `0x02022222` | `0x22022222` |
| CLOCK_HYST_SP0 | `0xbc` | `0x0000f3cf` | `0x003cf3cf` |
| CLOCK_DELAY_TSE_RAS_RBBM | `0x109` | `0x4000` | `0` |
| CLOCK_CNTL2_UCHE | `0x10c` | — | `0x00222222` |
| CLOCK_DELAY_UCHE | `0x10f` | `2` | `0x222` |
| CLOCK_HYST_UCHE | `0x110` | `4` | `0x444` |
| CLOCK_MODE_VFD | `0x111` | `0x2222` | `0x00222222` |
| CLOCK_DELAY_VFD | `0x112` | `0x2222` | `0` |
| CLOCK_DELAY_HLSQ_2 | `0x117` | `2` | — |
| CLOCK_HYST2_VFD | `0x12f` | — | `0` |
| CLOCK_MODE_CP | `0x260` | `0x223` | `0x222` |

All 53/54 ordered entries and all protection encodings are in the JSON, not
only the differences. Protect encoding is `(length & 0x3fff)<<18 |
(start & 0x3ffff)`, with bit 31 for NORDWR; skip-zero entries are not writes.
`CP_PROTECT_CNTL` enables protection, fault-on-violation and infinite final span.

**CP packet contract:** Type-7 `CP_THREAD_CONTROL` opcode `0x17`, payload
`[0x08000000]`; then `CP_ME_INIT` opcode `0x48`, seven payload words
`[0x14b, 3, 0x20000000, 2, list_iova_lo, list_iova_hi, 0x80000000]`.
The existing `AdrenoPM4Type7` supplies odd parity on count and opcode.
The power-up buffer starts with a zeroed 16-byte CPU/GPU lock header,
IFPC count 0, preemption-pair count 17, dynamic-triplet count 0, followed by
17 `(register,current_value)` pairs: **152 bytes total** (native list: 144 B).
The list is populated from live registers, not filled with invented constants.

The shared A7xx setup order is GMU OOB keepalive → clear GBIF halt/trusted range
→ clock gating/GBIF/UCHE → UBWC and protection/APRIV/interrupts → SQE address
→ ring and RPTR/BV shadows → optional preemption setup → SQE enable → list
capture → CP init → secure-mode exit using authenticated ZAP. See exact
`hw_init` excerpt for every conditional write and error branch. A730 skips
the A740 GMEM-range programming. Linux's common A7xx values include GBIF QoS
`0x02120212`, UCHE GBIF config `0x010240e0`, cache ways bit 23, hang control
`0x40cfffff`, and UCHE client PF `0x81`.

**Register-coordinate correction:** GMU XML offsets are relative to GMU, while
some native definitions use the GPU aperture. Add
`(0x03d6a000-0x03d00000)/4 = 0x1a800` dwords when comparing those definitions.
For example `0x9309` becomes native `0x23b09`. Legacy AXXX-domain ring names
must not be confused with A6XX/A7XX names. The extraction excludes that domain.

**Submission:** both chips use Linux `a7xx_submit`, including BR thread selection,
page-table switch, indirect buffers, timestamp/fence packets and conditional
preemption pseudo-register/yield work. No separate GEN1 packet format appears
in those shared kernel functions. This does not make A740 userspace state valid
on A730: pinned Mesa has distinct GEN1 profiles and magic-register streams.

## 3. GMU firmware, HFI, power and votes

**Cold/warm order:** establish CX runtime power, acquire GX runtime reference
(GX's CPU power-on callback deliberately does nothing), set GMU core 200 MHz
and A730 hub **150 MHz** (A740 200 MHz), bulk-enable clocks, apply the current
GPU OPP, clear/unmask GMU IRQ, select retention state, start RSCC, load firmware
on cold boot, configure CM3/HFI/fence/chip/log/idle state, start CM3 and HFI,
send HFI startup messages, enable HFI fault IRQ, then apply initial GPU frequency.
Release recovery overrides retained state with cold boot after a hang.

RSCC wake sets CONTROL_REQ bit 1, polls ACK bit 1 and sequence idle at 100 us
interval / 10 ms timeout, then clears request. The A730 sequencer words at
RSCC `0x180..184` are `eaaae5a0 e1a1ebab a2e0a581 ecac82e2 0020edad`.
PDC sequencing is AOP-owned for A7xx. Shutdown/force-off, bus draining and
DMA ownership must be preserved; removing an OPP vote is not itself DMA-stop
proof. Normal stop puts GX synchronously before disabling clocks and putting CX.

**Firmware parsing (host-measured):** the already verified `gmu_gen70000.bin`
is 57,272 B with 15 block headers. Eleven have size zero (metadata/preallocation
descriptions); four carry data: `(0,476)`, `(0x4000,56492)`,
`(0x10007f98,40)`, `(0x10007fdc,24)`. Headers are four little-endian u32s
`addr,size,type,value`, followed by `size` bytes. Linux skips size-zero headers;
ITCM is `[0,0x4000)`, DTCM `[0x10004000,0x10008000)`, other data targets mapped
GMU allocations. `firmware-layout.json` retains every header. A new loader
must validate full extents, arithmetic and alignment rather than copy the
Linux loader's permissive unmatched-block behavior.

**HFI:** 16 KiB shared allocation, 24-byte table header and 48-byte queue headers;
Linux uses two 4 KiB/1,024-word command and response rings at +4/+8 KiB, types
`0xa00`/`0xa01`. Table `size` is **120 bytes in code**, despite a stale comment
calling it dwords. Header offset/size fields are 6/12 dwords. Modern messages
align to four words, padding `0xfafafafa`; sequence is modulo `0xfff` in bits
31:20, type in 19:16, total words in 15:8, ID in 7:0. Host-to-GMU doorbell is 1.
Startup is performance table (4), BW table (3), optional ACD feature/table
(11/7), core firmware start (14), start (10). A730 static OPPs have no ACD
levels, so the optional ACD messages do not follow from this source profile.
Do not automatically reuse Sheng's `inputs.enable_acd=1` policy.

**IRQ mapping:** GIC SPI **304 is HFI**, **305 is GMU**. HFI handler reads/clears
GMU2HOST status and handles CM3 fault; GMU handler reads/clears AO status and
handles watchdog, AHB and fence errors. GPU is SPI 300. GIC interrupt IDs used
by another OS must account for the SPI numbering convention (+32), not blindly
copy a Linux interrupt number.

**Votes:** `a730-bandwidth-table.json` contains every exact A730 BW row: 12 DDR
levels, three commands `SH0/MC0/ACV`, wait mask 7; CNOC `CN0`, wait mask 1,
rows `0x40000000` and `0x60000001`. Command addresses come from runtime cmd-db.
ARC primary keys are `gfx.lvl` and `cx.lvl`, with `gmxc.lvl` or authoritative
fallback `mx.lvl`. For each OPP, choose the first primary level >= requested
level, the first suitable secondary (or maximum nonzero), then encode
`(primary_level<<16)|(secondary_index<<8)|primary_index`.

**(verify)** exact numerical ARC votes and command addresses remain unknown
without the SM8475 cmd-db data. Existing `ShengGmuCommandDb.c` enforces its own
generated base/size/version/resource policy; reusing its parsing ideas does not
authorize borrowing Sheng's addresses or level arrays. Linux's initial bus
operation is `dev_pm_opp_set_opp` at the selected performance index; this tree
does not establish an independent fixed MB/s quota to copy into XNU.

## 4. GPUCC, OPPs and LLCC

Seven clocks, in GMU DTS order; enable offsets below are **bytes** relative to
their controller, with bit 0 enabled:

| Name | Provider / branch | Enable offset | Relevant behavior |
| --- | --- | --- | --- |
| ahb | GPUCC / AHB | `0x911c` | Halt-delay branch, hub AHB divider parent |
| gmu | GPUCC / CX_GMU | `0x913c` | AON branch, GMU source parent |
| cxo | GPUCC / CXO | `0x9144` | XO source parent |
| axi | GCC / DDRSS_GPU_AXI | `0x81154` | AON, halt-skip; HW clock gating bit 1 |
| memnoc | GCC / GPU_MEMNOC_GFX | `0x81010` | Voted halt; HW clock gating bit 1 |
| hub | GPUCC / HUB_CX_INT | `0x9148` | AON, hub divider parent |
| demet | GPUCC / DEMET | `0x900c` | AON, demet divider parent |

GPUCC base `0x03d90000`; `gpu_cc_sm8450_probe` selects **LUCID_OLE** for
SM8475, not SM8450's LUCID_EVO. PLL0/PLL1 offsets are `0/0x1000`; L/alpha are
`0x1d/0xb000` and `0x34/0x1555`. SM8475 configs include config-hi1
`0x82aa299c`, test-hi/hi1/hi2 `3/0x9000/0x34`, user-hi `5`. GMU source RCGR
`0x9318` supports 19.2/200/500 MHz; hub RCGR `0x93ec` supports 150/240/300 MHz.
Bulk enable uses CCF parent/rate/halt operations; branch writes alone are not
a complete clock sequencer. Generic `clk-alpha-pll.c`, `clk-rcg2.c`,
`clk-branch.c` and `gdsc.c` are retained in the snapshot for those algorithms.

CX GDSCR `0x9108`, HW-control `0x953c`, clock-disable wait 8,
VOTABLE/RETAIN_FF. GX GDSCR `0x905c`, clamp `0x9504`, three reset lines,
CLAMP_IO/AON_RESET/SW_RESET/POLL_CFG; `gdsc_gx_do_nothing_enable` leaves actual
power-up to GMU. Do not infer a CPU-driven GX collapse-clear sequence from
the ordering of runtime-PM references.

**Source-verified OPPs:** GPU ascending MHz:
`220,285,317,350,421,492,545,599,640,734,791,818`.
Levels respectively:
`LOW_SVS_D1,LOW_SVS_D1,LOW_SVS,LOW_SVS,LOW_SVS_L1,SVS,SVS_L0,SVS_L1,SVS_L2,NOM,NOM_L1,TURBO`.
GMU OPPs are 200/500 MHz at LOW_SVS/SVS. The alternative 900 MHz SM8475 GPU
table is commented out. Linux prepends frequency-zero off entries, yielding
13 GPU and three GMU levels; the initial GPU index is highest available.
**Boundary:** this is source DTS, not a captured post-ABL live FDT.

AOSS/QMP uses `{class: gpu, res: acd, val: N}`. With no OPP ACD properties,
N is zero if QMP is available; absent QMP is tolerated when ACD is disabled.
IFPC is not thereby qualified. Cache policy also needs its own adaptation:
SM8450 LLCC GPUHTW slice 11 has 512 KiB, GPU slice 12 has 2,048 KiB, both
fixed/retained, GPU write-SCID enabled. `a7xx_llc_activate` repeats GPU SCID
in GBIF_SCACHE_CNTL1's six 5-bit fields and writes `(SCID<<10)|bit8` in CNTL0,
then activates HTW. Missing LLCC MMIO is explicitly tolerated in Linux; that
does not prove equivalent performance/coherency when disabled.

## 5. SMMU contract and ArmSmmu4K mapping

SMMU base/span `0x03da0000/0x40000`, compatible SM8450 SMMU-500 plus Adreno.
GPU stream specifiers are `(0,0x400)` and `(1,0x400)`, GMU `(5,0x400)`.
The second field is stream matching mask data, **not a context-bank number**.
SMR slot numbers are runtime allocations and must not be assumed equal to SID.

**Source-verified:** `qcom_adreno_smmu_alloc_context_bank` reserves **CB0 for
GPU**. Other devices allocate from CB1 upward; GMU commonly gets the first
available nonzero bank, but its actual bank cannot be asserted from DT alone.
Both compatible clients get ACTLR `PREFETCH_DEEP|CPRE|CMTLB = 0x303`.
GPU supports AArch64 stage-1 split tables: global/kernel mappings via TTBR1,
client mappings via TTBR0. GMU uses its own lower-table context.

Linux programming order is CBA2R → CBAR → TCR2 → TCR → TTBR0/TTBR1 →
MAIR0/1 → SCTLR. TTBR values carry ASID in bits 63:48 (Linux assigns ASID
from CB index), and table roots come from allocations. TCR fields derive
from discovered address widths/granule/cache/shareability; initial GPU split
configuration sets EPD0 and enables TTBR1. Installing TTBR0 clears EPD0/EPD1
as appropriate. SCTLR stage-1 baseline is `0x1067`; Adreno adds HUPCF bit 8
(`0x1167`) and optional stall CFCFG bit 7 (`0x11e7`). These are context-control
registers, unrelated to the CPU SCTLR nTWE experiment.

SMMU power is CX; clocks are gmu, hub, hlos, bus, iface, ahb from the DTS.
Register ID capability reads, SMR leases, context ownership and TLB completion
remain required before any writes. Actual TTBR roots, TCR address-width fields
and GMU CB are **runtime inputs**, not missing constants to guess.

The existing ArmSmmu4K encoder already exposes lower/upper 4 KiB contexts,
ASID, coherent walk, stall and continue-after-fault; it encodes the same SCTLR
baseline and CBA2R AArch64 semantics. `ShengGpuSmmu.c` already distinguishes
GPU CB0/upper mappings from nonzero GMU/lower mappings and requires exclusive
stream leases and physical table audits. Reuse those ownership concepts with
SM8475 windows/SID masks and measured capabilities; do not copy generated
SM8550 constants. ArmSmmu4K uses its own MAIR `0xff44`; compare semantic page
attributes and indices with Linux, not raw MAIR numbers in isolation.

## 6. ZAP and EL / hypervisor boundary

The existing verified ZAP was parsed, not replaced or re-signed.
`firmware-layout.json` records all ELF headers. File size is 11,608 B:
one loadable segment at file `0x1000`, ELF physical `0x1000`,
filesz=memsz=2,236 B, flags `0x08000007` (relocatable). The header segment is
148 B; hash metadata at file `0x2000` is 3,416 B. PAS metadata is therefore
148+3,416 = **3,564 B**. Aligned load span is **4,096 B**, fitting the DTS
`no-map` reservation `[0x8b91a000,0x8b91c000)` of 8 KiB.

Exact caller contract:

1. `GPU_PAS_ID=13`; request the board `qcom/sm8475/liuqin/a730_zap.mbn`.
2. Compute MDT span; map the 4 KiB load span at `0x8b91a000` as MEMREMAP_WC.
3. `qcom_mdt_load(dev,fw,filename,13,mapped,0x8b91a000,4096,NULL)` calls
   PAS init with assembled metadata, then PAS memory setup for relocatable
   span `(13,0x8b91a000,4096)`, then copies the loadable segment to base+0.
4. `qcom_scm_pas_auth_and_reset(13)` authenticates the image; only after success
   does CP secure-mode exit follow. No manual SECVID fallback is qualified.

SCM service PIL is 2, SIP owner 2. Under Linux's selected **64-bit standard-call**
convention, initial request registers (not interrupted-call resumptions) are:

| Operation | x0 | x1 arginfo | x2 | x3 | x4 |
| --- | --- | --- | --- | --- | --- |
| INIT_IMAGE, cmd 1 | `0x42000201` | `0x82` (VAL,RW) | 13 | metadata physical address | 0 |
| MEM_SETUP, cmd 2 | `0x42000202` | 3 | 13 | `0x8b91a000` | 4096 |
| AUTH_AND_RESET, cmd 5 | `0x42000205` | 1 | 13 | 0 | 0 |

Linux probes 64/32/legacy convention, so these are **conditional derived
arguments**, not a measured live calling convention. INIT_IMAGE metadata is
physically contiguous, 4 KiB aligned and noncacheable via coherent allocation.
SCM explicitly avoids TZMem/creating an SHM bridge for this PIL metadata:
its comment says the hypervisor creates bridges on Linux's behalf and an
already bridged buffer will fail. Payload WC mapping and metadata allocation
are distinct requirements. Return handling includes interrupted calls,
busy retries, optional WAITQ resume and both transport/result status.

**Source-verified:** `qcom_scm-smc.c` uses `arm_smccc_smc_quirk`, not an HVC
replacement or a caller-side Gunyah RPC route. No Gunyah-named driver appeared
in the inspected `drivers/virt` snapshot. Linux's `head.S` handles EL1 or EL2
entry; that code cannot tell us which branch Liuqin actually used. The DTBO
note in the board DTS says ABL applies vendor overlays after the boot-image
DTB and can drop/rewrite root additions while /soc children survived observed
Linux boots. It says nothing about HCR_EL2.TSC or SMC interception.

**Unresolved:** live entry EL, hypervisor identity, interception, applicable
shared-memory ownership and passthrough behavior. A source `smc` instruction is
not proof of direct EL3 delivery. No Gunyah-specific caller transport is justified
by these sources, and no direct-to-EL3 claim is justified either.

## 7. Preemption and minimal execution

A730's 2,860 KiB backing size differs from A740's 4,192 KiB, despite shared
record fields. The record starts with eight u32 words (magic `0xae399d6e`, info,
errno, data, cntl, rptr, wptr, pad), then u64 RPTR address, ring base, counter
address and BV RPTR address: **64-byte defined prefix**, not merely the older
56-byte prefix mentioned in the native header commentary. SMMU info has
magic `0x241350d5`, TTBR0, ASID, CONTEXTIDR and context-bank fields in a 4 KiB
allocation. Preserve field offsets and alignment explicitly in a port.

Linux normally selects four rings when preemption is enabled by the catalog;
it also explicitly supports a **single-ring** path. `a6xx_preempt_init`,
`a6xx_preempt_hw_init`, and `a7xx_preempt_start` skip their work when there is
one ring. Thus multi-ring preemption setup is not a Linux source prerequisite
for a bounded first CP/fence experiment. CP init still needs its register list,
APRIV/protection and shadows. Safe stop still requires bounded drain/GMU stop,
fault handling and DMA ownership; disabling preemption does not authorize
freeing mappings while execution is uncertain.

## 8. Userspace profile and workarounds

The companion uses a pinned Ubuntu desktop ISO/rootfs extraction and Kali
debootstrap tooling; the inspected packaging does not establish a custom Mesa
source revision or A730 Mesa build flags. It reports desktop acceleration, but
no package-version inventory or renderer/Vulkan run trace was present in this
selected material. Do not infer Vulkan/Turnip hardware qualification solely
from a working GNOME desktop (which may use Freedreno OpenGL).

Tracked environment workarounds are:

- `GDK_DISABLE=dmabuf`: copy-upload path for reported stale-cache-line corruption.
- `WEBKIT_DISABLE_DMABUF_RENDERER=1`: reviewed legacy compositor workaround.
  The same file reports that `WEBKIT_DMABUF_RENDERER_FORCE_SHM=1` failed with
  tiled/ghosted corruption and an Epiphany SIGSEGV; do not adopt that alternative.
- The Snapshot camera wrapper clears `GDK_DISABLE` for that application only.

These are import/cache/coherency workarounds, not evidence that the IR3 compiler
requires equivalent macOS environment variables.

**Pinned UniXNU Mesa check:** fetched three exact source files at compiler pin
`85fda3b36405bcaea8bffc64aa4f2651dc90770d` into `evidence/mesa-pinned`, with
URL/hash manifest. `freedreno_devices.py` includes `0x07030001` and wildcard
fallback as FD730, GEN1: four CCUs, 64×32 tile alignment, 1,024×1,024 max tiles,
32 VSC pipes, 32 KiB compute shared memory, highest-bank-bit 16, and A730 magic
register tables. GEN1 flags include nonzero fragment constlen, TP UBWC hint,
shading-rate SMASK and compute lock/unlock quirks. They must not be substituted
with GEN2's atomics/ray/image-processing capabilities.

The Darwin KMD patch computes GPU ID from chip ID (A730→730), preserving the
actual chip and ABI-provided GMEM, VA and trap properties. Its special A740
override is limited to `0x43050a01`; no A730 identity override is needed.
AirNir's local backend selects `fd_dev_info_raw` by chip and accepts generation 7.
`build-turnip-darwin.py` selects freedreno Darwin KMD and a `macos27` target,
but the actual patched Mesa tree is absent locally. **(verify)** a complete
pinned/patch-qualified Darwin build, A730 compiler output, KMD feature/VA contract,
and macOS 26C5035r ABI remain untested. Three source files establish profile
presence, not build or rendering success.

## 9. What this research authorizes next

The matrix supports a host design of an explicit A730/SM8475 backend profile,
using common packet, memory/fence and parser interfaces where matched above.
Before implementation is accepted, close or explicitly gate runtime-derived
inputs: SM8475 cmd-db/ARC data and ownership, post-ABL DT/resource differences,
entry/SMC/shared-memory contract, measured SMMU capabilities/leases, and exact
compiler/OS ABI qualification. Preserve the release recovery fix in the design.

No hardware boot is proposed here. Firmware discovery was not reopened; only
the already identified signed ZAP and GMU blobs were inspected. Real-key signing
remains untouched. No display/input driver deep extraction was performed.
Existing layout/const/header/AES gates remain hard limits; a GPU backend's
footprint is not assumed to fit A7's available segment slack.
