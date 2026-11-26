# r101 post-A7 layout provenance and observer-retirement plan

Date: 2026-11-21. Scope: host-only inspection of frozen A7 and prelinker sources.
No observer edits, candidate build, image emission, device commands, or key operations.
Labels: **host-measured**, **source-verified**, **inference**, **(verify)**.

## Result

A7's 1,760 B const-VMA margin is a conservative header-padding margin, not an
executable-code allowance. Independent TEXT and DATA policy headroom is 48 KiB
and 32 KiB. All existing caps remain binding. Retiring solved diagnostics is a
reasonable next design step, but no reclaimed capacity is established without
a rebuild. This plan does not select a new behavior experiment or lift the
graphics boot hold.

## Placement and header provenance

**Host-measured:** `inspect-layout.py` reconstructs `fileset_layout.Layout` from
the pinned KC, frozen A7 standalone and 85-entry closure without emitting an
image. It compares placement with the frozen emitted kernel. Machine-readable
results: `out/liuqin-r101-layout-audit/evidence/placement-and-headers.json`.
Pinned KC SHA256: `d1003b5143ffd88439b4d45b6017f587171cfe6855660bed05370a2ea5db9fe9`.
Emitted A7 SHA256: `a03200b0c3e0879745c515b378b98c5407421177d168604a95b403f783dc6777`.

| Constraint | A7 value | Policy | Meaning |
| --- | --- | --- | --- |
| TEXT size | `0x1cc000` | <= `0x1d8000` | 49,152 B policy slack |
| DATA size | `0x27c000` | <= `0x284000` | 32,768 B policy slack |
| First const VMA | `0xfffffff007005fe0` | >= `0xfffffff007005900` | 1,760 B policy margin |
| Standalone header to first backed section | 2,000 B | nonoverlap | Actual padding |
| Emitted native header to first backed section | 2,016 B | nonoverlap | Actual padding |
| Root commands to mapping end | 26,024 B | fit root TEXT mapping | Separate root-header slack |

**Source-verified:** policy constants are in `r100/package.py:26–28`, inherited
by r101. The const-floor assertion explicitly calls a violation `headerpad risk`.
`fileset_layout.py` uses 16 KiB placement alignment (`PAGE=0x4000`).

**Host-measured:** emitted TEXT starts at `0xfffffff00719c000`. The next retained
TEXT, AppleAudioClockLibs, starts at `0xfffffff007377750`: available extent
`0x1db750`. Its largest fitting 16 KiB-aligned extent is exactly the policy
`0x1d8000`. Physical bytes after current TEXT total 63,312 B; only 49,152 B are
within policy. DATA starts at `0xfffffff00c884000`; retained Libm DATA begins
at `0xfffffff00cb08000`, giving exactly the `0x284000` window.
These establish the current placement rationale; they do not establish the
historical reason for every earlier cap revision.

The native base is `0xfffffff007004000`. Const begins at relative `0x1fe0`,
against floor `0x1900`. Standalone `sizeofcmds=0x17f0`, with header ending
at `0x1810`. Emitted native `sizeofcmds=0x17e0`, header ending at file
`0x199800`, payload beginning at `0x199fe0`. Root commands end at `0x1a58`
within a `0x8000` mapping. Deleting code or strings can change section alignment
and cross 16 KiB boundaries; improvement of the const margin is not guaranteed.

## Active prelink checks versus legacy checks

**Source-verified:** A7 uses the MH_FILESET dispatch in `emit_prelink.py` and
`fileset_emit.emit_images`, with `fileset_segmented.SegmentedEmit`.

- `fileset_segmented.py:285` rejects native load commands exceeding the
  original available header space.
- `fileset_segmented.py:385` rejects root commands exceeding their header mapping.
- `fileset_layout.Layout.validate()` checks alignment, retained/native overlaps,
  root bounds/overlaps and constant placement.
- The separate AES fileset gate checks AES ABI, branches and fixups; it is not
  the general header/payload overlap checker.

The legacy non-fileset sparse-index path adds an 80-byte `__macho_list` section
and explicitly checks first-payload padding. That path is not active for A7.
Keep the policy floor, actual fileset placement/header checks, and AES checks
as separate acceptance requirements. No cap or floor relaxation is proposed.

## Retirement dependency inventory

All paths below refer to frozen `evidence/a/sources` under the A7 work directory.
This is a removal plan, not an implemented capture profile.

| Candidate | Dependencies and evidence to retain | Proposed treatment |
| --- | --- | --- |
| A5 local clocksyncd state reads (`r105_state`, collection/notifier helpers in `liuqin_r101_walk.inc`) | Own-image UUID/base, ISA/ivar offsets, Gate 2/3 success archived in A7 | First retirement tier; remove state call and its exclusive helpers together |
| Targeted TimeSync registry/publication sweep (`r104_contains`, `r106_publication`, `liuqin_r104_timesync_dump` in `IOUserClient.cpp`) | Snapshot callsite, counts/checksums, bounded output expectations | First tier after archival; preserve actual Ethernet driver and native TimeSync behavior |
| clocksyncd target slot in waits/walker | `r104_main_uuid`, `r104_main_base`, saved threads, retained task lifetime and slot-specific state call | Remove only after deciding whether future workload needs this target; keep identity checks for every surviving target |
| WindowServer open/IPC/matching histories | Producers, enqueue/drain, rolling-history consumers, summary/loss counters | Later profile decision; requires complete producer/consumer audit and does not stop crash churn |
| Generic target-map reader and frame walker | Nonfaulting reads, bounded traversal, USB completion fence, error probes and task lifetime | Retain if needed for appinstalld/locationd or other future fault work; do not remove with clocksyncd-only helpers |

**Source-verified:** `liuqin_r102_task_walk` first checks main-image identity,
then invokes `r105_state` only for slot 1, then walks saved frames. A retirement
must preserve identity failure behavior and walker-last ordering for surviving
targets. Native reads remain behind the fail-closed USB completion fence.

Memory accounting is separate from linked-code capacity:

- Saved walker scalars are `[2][64]` entries of three uint64 values: **3,072 B**,
  not the older single-target 1,536 B figure.
- The 256-entry hook ring accounts for 57,344 B; two 50-entry rolling histories
  account for 22,400 B. These are fields of heap-allocated observer state.
- The A2-era 106,696 B observer state, 48,136 B CPU state and 28,672 B block
  state are not all standalone static DATA, nor all exclusive TimeSync overhead.
- SCTLR readbacks occupy 256 B. Keeping this small check protects the nTWE
  baseline. CPU/memory/storage/ENOSPC and undefined/fault counters remain useful.
- Inlining mixes targeted helpers into shared functions. Symbol extents alone
  cannot establish reclaimable bytes; no code-saving estimate is claimed.

## Acceptance contract for any future retirement

1. Archive and rehash accepted A6/A7 and SkyLight evidence; keep frozen source,
   runners, parsers and assessments immutable.
2. Create a new named observer profile and matching versioned assessor. Document
   removed fields and changed snapshot counts; do not claim A6 observer equality.
3. Preserve abort guards, trust/storage/media safety, nTWE, identity Ethernet,
   512 MiB Data and unchanged display/Metal/SMP/EPSS behavior. Preserve snapshot
   counts/FNV, output bounds, loss reporting and fence consumers that remain.
4. Host-build only when implementation is selected. Recheck every segment cap,
   const floor, actual fileset headers/placement and AES ABI/fixup gate. Compare
   emitted sizes and hashes before claiming savings; stop on any failed gate.
5. For history-dependent work, include the separate `history-gate.py` assessment.
   A checksum-valid snapshot does not imply lossless hook history. Even ring
   drop zero does not authorize absence claims when histories filter/overwrite
   or payloads truncate.

Observer retirement cannot resolve WindowServer's 30-second abort loop. A quiet
headless workload baseline requires a separately designed churn-isolation
behavior experiment. No such experiment is selected or implemented here.
Graphics behavior boots remain held. Keep `native_reader_validated=false` and
the `EL0 TRAP=0` caveat; owner-key decisions and real-key signing remain untouched.
