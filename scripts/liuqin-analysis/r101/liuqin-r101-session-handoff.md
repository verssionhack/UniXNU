# Liuqin r101 session handoff

Updated: 2026-11-21. Workspace: `/home/kurumin/Codes/Github/UniXNU`.
Device: Xiaomi Pad 6 Pro, Liuqin, SM8475, Adreno 730.
Target: macOS 27.3 **26C5035r**, native 4 KiB XNU, arm64e.

## Start here

The active task is **host-only completion of Milestone 1 prerequisites for an
A730/SM8475 adaptation**, using the existing Adreno740/AdrenoMetal stack.
The owner accepted the Linux hardware parity matrix. They explicitly hold
**A730/XNU driver edits and graphics hardware boots** until full KMD link/
placement and pinned macOS userspace ABI gates are closed. A read-only
platform-input discovery plan is required before any later probe.

The latest host-gate report and discovery plan have been delivered, but the
owner has **not yet reviewed/accepted those new reports**. Do not promote their
open gates to passed. The latest request was to write this handoff.

Read these documents in order (paths relative to this repository):

1. `docs/contributing/repository.md` (AGENTS.md says “See docs/”).
2. `scripts/liuqin-analysis/r101/gpu-m1/liuqin-r101-a730-a740-parity-matrix.md`
   — owner-accepted Linux hardware parity portion of Milestone 1.
3. `scripts/liuqin-analysis/r101/gpu-host-gates/liuqin-r101-gpu-host-gates.md`
   — latest measurements, HFI binary finding, target ABI/trust audit and gaps.
4. `scripts/liuqin-analysis/r101/gpu-host-gates/liuqin-r101-platform-discovery-plan.md`
   — strictly read-only future probe design, not implementation/boot permission.
5. `scripts/liuqin-analysis/r101/layout-audit/liuqin-r101-layout-and-retirement-plan.md`
   and `scripts/liuqin-analysis/r101/skylight-audit/liuqin-r101-skylight-compositor-audit.md`
   — accepted hard layout constraints and closed compositor dead ends.

## Standing authorization and holds

- Earlier in the session the owner withdrew the separate-go-per-boot rule.
  **Later explicit graphics boot and driver-edit holds override that standing
  authorization for this track. Do not boot a GPU experiment.**
- Preserve accepted A7 behavior: **nTWE=1 / nTWI=0**, genuine
  `LiuqinIdentityEthernet`, 512 MiB Data, unchanged SMP/EPSS/display/Metal setup.
- No flashing or partition writes. No owner.key access, relocation, rotation,
  disposition or real-key signing. Those r95 owner decisions remain unanswered.
- Do not publish fake AGX/IOAccelerator/Metal capability services.
- Keep `native_reader_validated=false`; `EL0 TRAP=0` is not proof of no faults.
- Display/input deep extraction stays deferred until real ring/fence execution
  and Metal discovery milestones justify it.
- All segment, const-floor, fileset header/placement and AES gates remain hard.
- Preserve frozen raw logs, manifests, reports and assessments. Do not change an
  old parser/result to make a later profile pass.
- Do not infer a headless churn-isolation behavior change from this research.
  WindowServer suppression has not been designed/implemented/authorized here.
- Do not spawn subagents unless the user or applicable instructions explicitly
  request delegation. None were used for this research.

## Accepted hardware baseline and why GPU work is next

Latest accepted behavior baseline is **A7**:

- Boot SHA256 `ffdec111a73bdfafd5be42574dbf71d0542c0c78daffb8d98fde8942a91a3d5a`.
- Emitted kernel SHA256 `a03200b0c3e0879745c515b378b98c5407421177d168604a95b403f783dc6777`.
- Capture: `out/liuqin-r101-a7-work/evidence/a/boot-A7-20261121-164915`.
- Result: `scripts/liuqin-analysis/r101/a7/liuqin-r101-a7-result.md`.
- A7 completed 480.251 s, runner exit 0, automatic verified fastboot return
  (`be7ca114`), 2,223 exact guard replays, all three snapshots verified.
  Last known device state was verified fastboot after A7; no device query has
  been performed during this host research, so do not assume current visibility.
- All eight CPUs retain nTWE=1/nTWI=0; WFE traps eliminated. A3r1 originally
  established this one-bit fix; A7 retains it.
- A7's genuine minimal identity Ethernet interface, carrier=0, cleared both
  TimeSync readiness gates. Clock manager/gPTP/server state became ready.
- WindowServer then advanced from its synchronous TimeSync XPC reply wait to
  the real 30-second no-Metal semaphore/abort path. It had 13 exits;
  ReportCrashServi had 19 exits. This is not a successful desktop.
- A7 hook `ring_drop=68,558`, history overwrite=56,555, payload truncation=13,408.
  Snapshots remain usable, but missing history entries are not negative evidence.
- Data free 44.519531 MiB at the final sampled point; minimum free RAM
  15.628906 MiB. Do not enlarge wired RAM-backed Data or assume runtime GPU
  allocations fit merely because static link sections fit.
- EXC_CRASH high byte is **terminating signal**, not exit-reason namespace:
  `0x06000000` is SIGABRT; `0x09000000` is SIGKILL. Earlier DYLD/EXEC namespace
  speculation was withdrawn.

Accepted SkyLight audit proves normal startup hits the no-Metal abort before
software fallback. GOP-off, startup Noop mode and BootToMetalCompositor plist
guesses are not qualified escape paths. The earlier r96/r97 zero-display escape
explanation was withdrawn. Visible desktop needs actual graphics support.

## What Linux research established

Do not resume from the unreliable original working tree. Use local immutable
snapshots under `out/liuqin-r101-gpu-m1/`:

| Directory | Meaning |
| --- | --- |
| `linux-head` | Git-object export of kernel `e6ed309612463f1c891d58b0c357b79a8be640e8` |
| `linux-release-clean` | Authoritative primary reference, companion-selected `fe81794b5e1b8a3f11a165f3acbfdb8fa671dbb3` |
| `linux-boundary` | Extra committed EL/SMCCC/virt/regulator reference files |
| `companion-safe` | 127 regular companion files; absolute overlay links recorded, not materialized |
| `unixnu-comparator` | Frozen actual local Adreno740/Metal/kits and catalog-pinned platform sources |
| `sm8550-reference` | Separate sparse checkout of catalog platform revision |
| `kernel-reference.git` | Isolated fetched release Git objects |
| `evidence` | Hash inventories, tree diffs, derived tables, firmware layouts and exact function excerpts |

**Do not use `linux-release`**: it is an incomplete failed copy attempt.
`linux-release-clean` is the verified release snapshot. A partial `companion`
extraction also exists; use `companion-safe`.

Original repositories are at `/media/disk_4/xiaomi_pad_pro6_linux_workspace`.
That mount produced I/O errors during `git status` on unrelated DTS files.
Original working-tree cleanliness is not established. Both local kernel
snapshots have **2,570 Git blob IDs verified** (2,566 regular files, four
symlinks), and SHA256 inventories. Source tree identity is established;
identity of the actual reported accelerated Linux session is still unknown.

Commit reconciliation:

- Companion HEAD: `0ea1508088ea83936c34a9a04ab1c02482e2a84a`.
- Earlier supplied HARDWARE.md reference resolves to
  `b077845366409367c3fc44e9f8c86fdc3957f945`. That document was not found in
  the tracked inventory inspected here; do not invent its contents.
- HEAD→release: 13 changed selected files. Only Adreno change is a recovery
  correction: force **cold GMU boot after a hang**, because retained-TCM state
  can survive TCM loss. Catalog/XML/CP/submission/preemption/GPUCC/IOMMU are
  unchanged. Existing PAS and MDT load function bodies are unchanged.
- b077→HEAD: six selected files (board DTS, DP and PMIC-GLINK), no selected
  Adreno/GPUCC/IOMMU/SCM/MDT implementation changes.

Important A730 facts are in the parity report and machine-readable JSON:

- Chip `0x07030001`, GEN1, 2 MiB GMEM. Do not select A740 by changing an ID.
- A730 HWCG 53 writes versus A740 54; 11 differing/exclusive addresses.
  Protection values match the existing XNU table exactly (46 writes/48 slots).
- All 55 compared generated register offsets match after domain/base correction.
  GMU→GPU aperture displacement is **0x1a800 dwords**.
- Current Linux power-up list has 17 entries; native generated list has 16,
  missing GRAS_NC_MODE_CNTL at dword 0x8602. This is source-version drift,
  not an A730-only hardware distinction. Common CP init packets match.
- A730 skips GMEM-range min/max writes, uses SM8475 LUCID_OLE PLL config,
  150 MHz hub, CGC mode 0x20000, RSCC sequencer base 0x180 and hidden TCS
  0x80000000. A740 uses different values.
- Active source GPU OPPs 220–818 MHz; alternative 900 MHz table is commented.
  No ACD levels: do not copy Sheng's `enable_acd=1` policy.
- Preemption backing 2,860 KiB/ring versus A740 4,192 KiB; defined prefix 64 B.
  Linux supports one ring with preemption init/start skipped, useful for the
  first real CP/fence milestone. Safe stop/DMA ownership remains mandatory.
- GPU SMMU CB0 is reserved for GPU; GMU bank is dynamically allocated nonzero.
  SID mask 0x400 is not a CB index; SID is not an SMR slot. ACTLR=0x303.
- Runtime ARC levels and command addresses must come from SM8475 cmd-db.
  Static A730 BW rows are fully extracted; do not borrow Sheng addresses.
- ZAP PAS ID 13, metadata 3,564 B, load span 4 KiB inside the 8 KiB reservation
  at 0x8b91a000. Linux PIL metadata avoids caller-created SHM bridges.
  Source `smc` instruction does not prove direct EL3 delivery.
- Pinned Mesa `85fda3b36405bcaea8bffc64aa4f2651dc90770d` recognizes FD730
  GEN1 with its real capabilities. The full patched Darwin Mesa tree is absent.

## Latest host-gate findings and limitations

Artifacts: `out/liuqin-r101-gpu-host-gates/{evidence,objects}`.
Research scripts: `scripts/liuqin-analysis/r101/gpu-host-gates/`.

### Footprint / placement — still open for full qualification

Actual local comparator revisions (not catalog pins):
Adreno740 `08a32b56e1b9e9d0e9d2ee0644d1c5825e8215fe`, AdrenoMetal
`c68f9a1db77961e0f7e18e48f95aeb95ac649650`.
Sm8550Platform pinned `a9f45dc60c035084b95463781538380f4c3606c9`.

`measure-reference.py` compiled unmodified frozen sources with the actual
source-kernel arm64e recipe, warnings suppressed for size measurement.
**50 attempted, 47 compiled, three platform objects fail** on missing generated
headers. No kernel link/image was made. Mapped object-section totals:

| Section destination | Bytes |
| --- | ---: |
| TEXT_EXEC | 184,220 |
| TEXT | 4,065 |
| DATA_CONST | 19,432 |
| DATA | 20,364 |

These are **diagnostic inventory sums**, neither aligned linked sizes nor a
lower/upper bound on the actual full closure. Some inventory sources are
excluded by the board recipe; missing generated headers remove feature branches.
Do not claim a full build, Werror pass or fit proof from these measurements.

Important correction: executable code maps to TEXT_EXEC, **not** the 48 KiB
TEXT window. Actual linker rename rules are captured in MakeInc.def.
Additional A7 layout measurements:

- TEXT policy cap 0x1d8000, slack 49,152 B; DATA cap 0x284000, slack 32,768 B.
- Const VMA floor 0xfffffff007005900, current first const
  0xfffffff007005fe0: 1,760 B **header-padding** margin, not code allowance.
- Native code/KLD→DATA gap 6,127,616 B.
- LASTDATA_CONST tail→first retained AppleARMPlatform constants: 567,912 B.
- Do not mix Layout's original collection VA namespace (`0xfffffe...`) with
  the emitted native slide-adjusted namespace (`0xfffffff...`). Use the JSON.

Documented sheng recipe was fetched at
`516a780473a2ac59c8b438e132bb60204dda9e22`, saved as text/provenance only.
It embeds firmware into **DATA_CONST**, not writable DATA. A730 blobs total
143,556 B (GMU 57,272, SQE 74,676, ZAP 11,608); with existing per-image 4 KiB
alignment and size symbols, extent is **146,784 B**. This gives a concrete
existing-segment strategy; it is not a final link result. No Tier-1 retirement
was implemented or credited as savings.

Missing full-build inputs: generated ShengGmuSource.h,
ShengGmuCommandDbSource.h, ShengGpuSmmuSource.h, enabled vote policy and
board-specific `kits/sheng/ShengGmuVotes.c`/matching recipe closure.
Do not fabricate headers to make a footprint check pass.

### 26C5035r userspace ABI — selected contracts pass, full gate open

- Extracted IOGPU/Metal/IOSurface metadata, ObjC and symbols with ipsw.
- Four backing cache files were SHA/UUID checked; 501 saved ARM64 instruction
  words verified against bytes. All 17 audited IOSurface called symbols exist.
- Target UUIDs: IOGPU `f4f1377aec8d3a2d8ff1586823d6c92d`,
  Metal `62a7aa51d7e635ca9ee5070f24e66a60`,
  IOSurface `300744bde7573041ac85e8a13e9278f9`.
- IOGPU registration reads MetalPluginName, calls gpu_bundle_find_trusted,
  resolves plugin class, checks isSubclassOfClass:, calls
  initWithAcceleratorPort:, associates service/device, then MTLAddDevice.
  `cmdBufArgsSize` returns 48, matching the shim.
- Original initializer calls IOGPUDeviceCreateWithOptions. Native plugin
  deliberately avoids that initializer and uses its own frontend object;
  this makes adapter/lifetime qualification essential.
- Generic uint64-zero missing-selector stubs are not universal ABI-correct
  implementations for floating/aggregate returns. Do not call this qualified.
- Local SDK is minimal (usr-only), missing Metal.framework and private
  IOGPU.framework. Full patched Mesa tree/dylib/plugin also absent. No complete
  target build/import/PAC/method-type/user-client ABI or runtime proof.

Trust design: scripts use ad-hoc `codesign --sign - --pagesize 4096`, then
CDHash trust modules; no owner.key required. This is separate from real-key
offline signing. AMFI trust and IOGPU trusted bundle placement are distinct.
Source supports GPUBundles/rootless storage-class protection, but active
reachability in A7 was not established. Do not claim trust registration passed.
Do not append gpu-addon=1 to the already 999-byte boot arguments.

### HFI initializer and strict parser — new concrete result

Pinned GMU firmware's **CM3 VA 0x8cd0** initializer (caller 0x8fa4) accepts
queue count <=20, header stride 48 B, and queue ID byte < count. Seventeen
exact instruction predicates are asserted by `audit-hfi-init.py`.
The MMIO literal 0x1807e610 agrees with Linux HFI_QTBL_INFO offset/base.

Both Linux count=2/types a00,a01 and native count=3/types a00,a01,a02 satisfy
this **actual binary initializer**. Count 21 or ID>=count returns 0x70.
This closes the strict-two initialization hypothesis. It does not prove later
queue uses, interrupts, coherence, wakeup or operational firmware execution.
Conservative first-profile design still uses the known Linux two-queue layout.

`audit-firmware.py` is a host parser prototype, not XNU code. It verifies the
real 15 headers (11 metadata, four data), full digest, bounds/alignment/regions/
policy/nonoverlap and rejects seven malformed controls. No CM3 execution.
The broad `gmu-thumb-linear-candidates.txt` includes data decoded as instructions;
never use it as an exhaustive CFG/reachability proof. The bounded initializer
audit is the authoritative narrow finding.

## Read-only discovery design and runtime unknowns

The separate plan is ready but not implemented. CurrentEL is a safe CPU fact;
it does not establish hypervisor identity or SMC routing. Do not read HCR_EL2/
SCR_EL3 from EL1. Source DT cmd-db is **0x80860000/0x20000, no-map**; it is
not automatic permission to map secure/AOP memory. Linux maps it WC, but XNU
access safety must be established before reads. Never scan adjacent carveouts.

After host gates and safe-access conditions, plan collects: handoff FDT/ADT
provenance, bounded cmd-db/ARC records, optional non-destructive SCM
IS_CALL_AVAIL self-query, and SMMU IDRs only if already safely powered/readable.
Skip/unavailable is valid and is not zero. Generic nonfaulting userspace copy
does not contain peripheral SError risk. Probe never programs clocks, GPU, PAS,
SMMU contexts/streams or TLBs. Capability observations are not ownership leases.

WindowServer churn must be accounted for separately; lossless dedicated
checksummed telemetry/fences are required, and history absence remains unusable.
No separate churn-isolation experiment has been selected.

## Frozen artifacts and verification

| Manifest | SHA256 |
| --- | --- |
| `out/liuqin-r101-gpu-host-gates/evidence/audit-manifest.json` (194 artifacts/inputs) | `2973fe3ceb19c62ff29f813c178c52d01167810660f4a1c0a6812e667aa72204` |
| `out/liuqin-r101-gpu-m1/evidence/research-manifest.json` (5,536 regular files, eight symlinks) | `dd2707afdeff822a06f4f85833b013ce92d6fafa59ffbe61e4e530cfbafbd5ac` |
| `out/liuqin-r101-layout-audit/evidence/audit-manifest.json` | `be61f7510a83701f04fdc9557b53ca6326365358e1f0ccd878a3e0ad15af9878` |
| `out/liuqin-r101-skylight-audit/evidence/audit-manifest.json` | `102e9d8289e925999ef5bba888e7a9679fc1d4f5a28d20203153e7c0f5c7eaf4` |
| `out/liuqin-r101-a7-work/evidence/result-manifest.json` | `fba43e50f7e9b9c493166b2fb768bed08dbf3241f6e83cc33f03dfc328661afb` |
| `out/liuqin-r101-a7-work/evidence/host-manifest.json` | `cfae2cc7a720b7e5e5350b5b24e79e9efe9d29b927e0f2e07f2c282aaedc948b` |

Safe read-only verification commands, from repository root:

```sh
python3 scripts/liuqin-analysis/r101/gpu-m1/verify-research.py
python3 - <<'PY'
from pathlib import Path
import hashlib, json
r = Path.cwd()
p = r / 'out/liuqin-r101-gpu-host-gates/evidence/audit-manifest.json'
assert hashlib.sha256(p.read_bytes()).hexdigest() == '2973fe3ceb19c62ff29f813c178c52d01167810660f4a1c0a6812e667aa72204'
d = json.loads(p.read_text())
for name, expected in d['files'].items():
    assert hashlib.sha256((r/name).read_bytes()).hexdigest() == expected, name
print('PASS:', len(d['files']), 'host-gate artifacts/inputs')
PY
```

**Do not blindly rerun audit/generator scripts in place.** Most write outputs
that are now frozen. `collect-evidence.py`, `extract-parity.py`,
`measure-reference.py`, `audit-firmware.py`, `audit-hfi-init.py`, and
`verify-target.py` all write evidence. Use a new revision/output directory for
new work. In particular, importing `skylight-audit/scan.py` writes earlier
frozen audit files; never import it just to borrow its Reader class.

## Practical environment and workspace hygiene

- Linux zsh. Toolchain `/opt/unixnu-linux/llvm/bin/clang-24`; actual recipe:
  `out/liuqin/macos-27.3-26C5035r/liuqin/tree/build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/iokit/DEVELOPMENT/IOPlatformExpert.cpo.json`.
- Source kernel tree: same target tree's `.cache/xnu-work`.
- Pinned KC:
  `/media/disk_4/unixnu_workspace/ramdisk_dir/unixnu/ipsw/26C5035r/kernelcache.decompressed`,
  SHA256 `d1003b5143ffd88439b4d45b6017f587171cfe6855660bed05370a2ea5db9fe9`.
- Pinned host cache: `/media/disk_4/unixnu_workspace/ramdisk_dir/liuqin-r101-host-cache`.
  Its accepted per-file manifest is
  `out/liuqin-r101-work/evidence/review-A1/host-cache-manifest.json`.
- `ipsw` is `/home/kurumin/.local/bin/ipsw`; capstone 5.0.7 available in python3.
  No decompiler/LLM backend was invoked; use local bounded disassembly.
- `out/liuqin-r101-gpu-host-gates/evidence/host-symbols.a2s` is a regenerable
  ipsw acceleration cache, about **1.7 GB**, intentionally excluded from the
  evidence manifest. `/home` has about **2.6 GB free** at handoff. Avoid large
  unplanned clones/cache copies; do not delete valuable frozen evidence to fit.
- No running hardware process was started. Latest known compile/audit processes
  finished; inspect process state if a subsequent interruption changes that.
- Existing tracked dirty state predates this research: submodules
  `drivers/ArmCpu`, `kits/XnuPrelink`; `profiles/os/macos-27.3-26C5035r/profile.toml`,
  `scripts/build-xnu-4k-baseline.sh`, `scripts/unixnu/ipsw.py`. Many research files
  under scripts/liuqin-analysis are untracked. Do not reset/clean this workspace.
  Earlier context also noted untracked VerifiedRoot content and a zip archive;
  tracked-only status does not inventory those. No commits were made here.

## Next-session work sequence

1. Read the latest reports and verify frozen manifests. Distinguish accepted
   hardware parity from latest unreviewed host-gate findings.
2. Continue host-only: locate/reproduce the **matching generated reference board
   closure** and correct archive recipe without fabricating inputs. Measure
   actual fully enabled link/placement in a new isolated output revision.
3. Obtain a proper matching userspace SDK and complete pinned/patch-qualified
   Darwin Mesa/frontend build inputs; qualify imports, method types, PAC,
   custom user-client wire ABI and bundle trust/placement. Symbol presence
   and a build-script target are not sufficient.
4. Carry forward the closed HFI initializer finding and tested parser contract;
   do not spend a boot to rediscover queue count.
5. Only after remaining host gates are closed and the current hold is explicitly
   resolved, consider implementing the reviewed platform discovery profile.
   Do not skip directly to GPU power-on, PAS auth/reset or a WindowServer test.

The next agent should act on available host work and report concrete blockers;
do not ask for another generic go while the latest explicit hold remains active.
