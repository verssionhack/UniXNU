# Read-only SM8475 platform-input discovery plan

Status: host design only. No probe implementation or hardware boot. Depends on
the remaining KMD link and target ABI gates; does not lift the graphics hold.

## Purpose and exclusions

Collect a minimal, provenance-qualified input record for a later A730 backend.
No GPU power-on, clock/rate write, reset, PAS INIT_IMAGE/MEM_SETUP/AUTH_AND_RESET,
SHM bridge creation, SMMU translation/TLB/stream write, partition write, Data
resize or key operation. Preserve nTWE=1/nTWI=0 and genuine identity Ethernet.

Read-only CPU access is not automatically safe hardware access. An invalid
physical read can produce SError; the generic nonfaulting userspace reader does
not contain that risk. Map permission is not proof a peripheral is powered or
a secure carveout is CPU-accessible. Fail-closed **skip/unavailable** results
are valid; never convert them into zero-valued hardware facts.

## Phase 0: host prerequisites

1. Pin an exact profile, runner, result assessor, layout/ABI inputs and probe
   output budget. If retiring Tier-1 observers, use a newly named profile with
   documented snapshot changes; preserve A6/A7 raw evidence and assessments.
2. Establish the DT/ADT handoff chain. Linux source DTS gives cmd-db
   `0x80860000/0x20000`, no-map. ABL can rewrite the live FDT, so record whether
   a preserved post-ABL FDT exists, its checksum, source pointer/length, and
   any conversion to Apple's ADT. Do not treat a compiled source DTB as live FDT.
3. Qualify an appropriate CPU-visible mapping/access policy for the cmd-db
   reservation and any peripheral ID registers. A `no-map` declaration is not
   permission to map all adjacent TZ/AOP memory. If those prerequisites are not
   established, the first run may report the address from DT and skip its bytes.
4. Account for WindowServer churn separately. Its A7 abort loop is real behavior;
   observer retirement does not remove it. A quiet baseline needs its own
   separately designed behavior experiment, without appending a deny-exec path
   to the 999-byte arguments. No churn-suppression behavior is selected here.

## Phase 1: safe CPU and handoff facts

Read `CurrentEL` on the executing CPU and record CPU ID, MPIDR, boot identity and
timestamp. Keep the existing eight-CPU SCTLR readbacks/WFE accounting. Do not
attempt to read HCR_EL2/SCR_EL3 from EL1. Record hypervisor identity only from an
authenticated handoff/source or an independently justified read-only interface;
otherwise report unknown. CurrentEL alone does not identify who intercepts SMC.

Copy only a validated, bounded handoff tree that already resides in accessible
RAM. Report source and post-ABL node properties separately: GPU/GMU/SMMU windows,
clock/power bindings, reservations, enabled OPPs, and cmd-db range. No arbitrary
physical-memory scan. Set an explicit tree-byte cap and validate all node lengths,
integer arithmetic and offsets before traversal.

## Phase 2: command database, only with access proof

The pinned Linux cmd-db driver acquires the reserved resource and uses
`memremap(...,MEMREMAP_WC)`; it checks magic and exposes a read-only debugfs view.
This documents a Linux access pattern, not automatic XNU/hypervisor qualification.

If access has been established, retain an exact bounded snapshot of the **128 KiB
cmd-db resource only**, never adjacent carveouts, and hash it. Parse on the host:
version, magic, resource/slave/entry counts, all arithmetic and extents, duplicate
IDs, addresses, auxiliary offsets and rail-array lengths. Extract only the
needed public resource records: SH0, MC0, ACV, CN0, gfx.lvl, cx.lvl, mx.lvl and
gmxc.lvl. Distinguish authoritatively absent gmxc from unreadable/parse-failed.
Compute ARC words from captured rail arrays and the recorded OPPs; preserve
the source index/level used for every output word. No votes are issued.

## Phase 3: optional SCM convention query

Only after establishing that a bounded SMC query is appropriate for this boot,
use Linux's **IS_CALL_AVAIL** self-query, with no pointer/buffer arguments.
The source candidate for ARM64 fast-call convention discovery is
`x0=0xc2000601, x1=1, x2=0x02000601`, other arguments zero. This derives from
INFO service 6, command 1, SIP owner 2, querying its own availability.
Record transport return and result registers separately. A successful reply
establishes a caller-visible convention, **not direct EL3 routing**.

No automatic 32-bit/legacy fallback, retry storm or WAITQ resume is part of the
first bounded probe without its own source-qualified design. Undefined/trapped,
unsupported, busy or interrupted responses remain explicit inconclusive outcomes.
Log and USB-complete the prior evidence prefix before any call that could hang.
Never use PAS AUTH_AND_RESET as a convention test.

## Phase 4: SMMU IDs only if safely powered/readable

GPU SMMU is `0x03da0000/0x40000`, powered from CX, with six clock dependencies.
Do not enable these resources in a read-only observer. If already-safe access
cannot be established from verified handoff/power ownership, report IDRs skipped.
If safe, read only the explicitly bounded ID capability registers needed for
version, granule, VA/PA width, context count and stream-match capability.

Record register offset, raw value and timestamp. Do not assign GMU bank 1 merely
because the Linux allocator starts at the first nonzero bank. Do not equate SID
with SMR slot, or idle register values with exclusive ownership. The probe
observes capabilities; **leases must later be established by the backend's
ownership mechanism**, including secure-world reservations. No CBAR/TCR/TTBR/
SCTLR/SMR/S2CR writes or TLB invalidation occur in this phase.

## Output, failure handling and acceptance

Use a bounded dedicated record stream with sequence/count/checksum/end marker,
independent of lossy hook history. Flush and USB-complete evidence before risky
boundaries; do not relax the transport fence. Keep output and prefix limits
within a reviewed new-profile budget, with explicit skipped/truncated/error fields.
An early disconnect or missing end marker is incomplete, regardless of runner exit.

History-gate results remain separate from snapshot integrity; no negative claims
from missing hook entries while ring loss/filtering/overwrite/truncation exist.
Do not base SMC/peripheral safety on passing software parser controls.

Acceptance is a provenance-qualified input bundle, not successful GPU execution:
exact boot/profile/tree identities, explicit CurrentEL, cmd-db snapshot or reason
for skipping, derived ARC inputs/words, caller-visible SCM query outcome, SMMU
capabilities or skipped reason, and a clean capture/return result. Unknowns remain
unknown. Any later GPU programming is a separate milestone with its own design.
