# Liuqin r101 A7 Ethernet publication experiment — host design

2026-11-21. **Design only: no driver implementation, candidate build, packaging,
or hardware boot in this step.** A6 remains the accepted zero-interface control;
A3r1 remains the behavior baseline. This document does not assert boot readiness.

Labels: **measured** means existing capture evidence; **host-verified** means
source/binary inspection; **inference** and **hypothesis** remain distinguished.

## Frozen comparison

- A6 boot: `1cdc0aaac49066ae68e84e879c2fe32b9d88831711640407533e2dd49eca4566`.
- A6 kernel: `ce3b2d20657fb0ff10c9b27dfe70b73935bed407a8d851773478b1a46049afd2`
  (the result's kernel artifact identity, distinct from boot-container fields).
- A6 result manifest:
  `da52a985607fdd4f0d0b85691e887a892574ea7c6e1f882463a2876c7d12813c`.
  All 120 entries rehashed successfully during this design audit.
- Pinned 26C5035r KC:
  `d1003b5143ffd88439b4d45b6017f587171cfe6855660bed05370a2ea5db9fe9`.
- A6 observers, user-read tables, USB fence/transport, sampling schedule, runner,
  parsers and abort guards stay unchanged. Preserve their source hashes and guard
  AST, then verify placed observer references after linking; new addresses alone
  are not evidence of a source change.
- Keep nTWE=1/nTWI=0, SMP/EPSS, display/Metal, ADT, exact 999-byte arguments,
  trust bundle, seed and 512 MiB Data unchanged. No `ethernet=1` or
  `-timesync_bringup` argument. No flash, key access or signing change.

## Resolved host findings

### Delayed lookup and quiet-state dependency

**Host-verified:** `IOTimeSyncClockManager::init` at `0xfffffe000b10417c` loads
`-timesync_bringup`, calls `PE_parse_boot_argn` at `0xfffffe000c436dfc`, and stores
the nonzero result at object byte `+0x128` (`...4198`). This is an explicit boot
flag, not an unidentified platform condition. A6's validated arguments omit it.

In `delayedClockIDLookup` (`0xfffffe000b104780`), a non-null platform and set
byte select `IOSleep(5000)` at `...47cc`; a clear byte selects
`platform->waitQuiet(UINT64_MAX)` at `...47d8`–`...47e0`. A null platform skips
both waits. Do not enable the flag to conceal the dependency.

**Measured:** A6 raw `usb.log` line 3662 contains `IOKit busy 0:`. Its producer,
`device-a/package/LegacyDisplayProbe.cpp::busyReport`, reads the service root's
busy state. This proves the baseline root reaches quiet; it is not a direct
record of the future candidate's platform `waitQuiet` return.

**Proposed lifecycle:** use a dedicated worker outside IOConfig matching,
provider `start`, workloop command gates and all service locks. Load the native
network family and initialize the adapter class there. Before publishing the
interface, require a non-null platform, available BSD resource, and a successful
bounded platform quiet wait (30 s). No manual busy-count changes. After native
BSD naming/attachment completes, allow driver-owned matching work to finish and
check platform quiet again with the same bound. Log both results. The worker
must never hold a matching busy reference while waiting for TimeSync progress.

**Residual risk:** quiet at one instant cannot prove a later unlimited wait will
complete. The proposed path relies on the native delayed thread-call running
outside interface matching and on all driver-owned matching work completing.
Before implementation is accepted, audit that ownership/order in the pinned
callback and startup call graph. If it cannot be established, use an early
publication design with proved ordering before clock-manager `start`; do not
assume a late probe is safe, add the bringup flag, or patch TimeSync. A quiet
timeout is an activation failure, not evidence against the clock-ID hypothesis.

### Native naming and notification semantics

**Host-verified:** the TimeSync start path's export `0xfffffe000c9fbb80` is
`gIOMatchedNotification`, not `gIOFirstMatchNotification` (`...b848`). This matters
because interface matching can run again after BSD attachment.

Pinned `IONetworkStack::attachNetworkInterfaceToBSD` (`0xfffffe000acad124`):

- Reads native prefix/unit (`+0x8d0`/`+0x908`), formats `%s%u`, and sets exact
  `BSD Name` at `...d218`–`...d230` before data-link attachment.
- On the successful active-interface branch, invokes native `registerService`
  slot `+0x5e0` at `...d424`–`...d43c` after naming/attachment.

Pinned `IOEthernetController::createInterface` (`0xfffffe000ac96334`) allocates
and initializes a genuine `IOEthernetInterface` (allocation size `0x148`). The
adapter must inherit this implementation; do not substitute an IOService child.
Pinned controller `start` (`0xfffffe000aca0760`) tests feature bit 0 before its
`IOBSD` wait, consistent with `kIONetworkFeatureNoBSDWait` in the source reference.

**Requirement qualification:** standard native lifecycle initially publishes an
unnamed interface so the network stack can discover/name it. TimeSync ignores a
callback without `BSD Name`; native re-registration supplies a later actionable
callback with that property already present. Therefore this design guarantees
the name before the **actionable post-naming notification**, not before every
initial notification. A literal prohibition on any unnamed initial notification
is not satisfied by this design. Do not silently fabricate a BSD name to claim
otherwise. An early-before-TimeSync alternative needs its own proved ordering.

IONetworkingFamily-188 is a public source reference, not asserted byte-identical
to 26C5035r. Its `reserveInterfaceUnitNumber` requires published state, so calling
its naming API on an unpublished interface is not a demonstrated workaround.

### Packaging and layout

**Host-verified:** the current driver archive mechanism uses linker
`-force_load` in `scripts/build-xnu-4k-baseline.sh`, including GopFramebuffer and
LiuqinSourceStorage. An external `.a` still changes the standalone Mach-O.
It does **not** preserve A6 standalone kernel bytes.

**Selected proposal:** a separate experimental adapter source/archive, linked by
the existing mechanism with pinned-family ABI bindings. Keep its code separate
from the A6 observer sources. This is one behavior variable (adding the network
controller/interface), with unavoidable binary-layout changes reported honestly.
The current fileset emitter retains existing kext addresses; adding a new
independently loaded Mach-O is not a qualified drop-in route. Do not expand this
experiment into new loader/relocation support merely to promise byte identity.

A6 bounds: TEXT `0x1cc000 <= 0x1d8000`; DATA `0x27c000 <= 0x284000`;
const VMA `0xfffffff0070061e0 >= 0xfffffff007005900` (2,272 B margin).
These are **baseline measurements**, not projected A7 results. Archive placement
does not exempt any code/constants from these gates. Do not retire A6 observers
or relax caps if the candidate fails; stop and redesign placement first.

## Minimal controller contract

Provisional class `LiuqinIdentityEthernet : IOEthernetController`; no interface
subclass and no physical transport backend in this experiment.

1. Native family load must succeed and its required metaclasses must be present
   before the subclass's deferred constructors run. Use pre/post-modload handling
   already qualified by existing native adapters; do not run these constructors
   at early kernel static-init time. Resolve the parent class size and full ABI
   from the exact pinned KC.
2. Initialize, attach and start on the existing IOResources provider from the
   dedicated worker. A compile-time experiment selection activates only this
   adapter; do not alter display source or add a boot argument/ADT setting.
3. Return `kIONetworkFeatureNoBSDWait` to avoid a provider-start/IOBSD dependency;
   the worker independently checks BSD availability before activation. Native
   `createInterface`, `getController`, prefix/unit and provider getters remain
   intact. Never promise a literal `en0`; accept native unit allocation.
4. Use fixed experiment address `02:4c:51:10:00:01`, a documented locally
   administered unicast address for this one tablet. It is not the Wi-Fi MAC or
   a production uniqueness scheme. `getHardwareAddress` returns exactly 6 bytes;
   native Ethernet property publication supplies controller `IOMACAddress`.
5. Override `configureInterface`: call the qualified native superclass method,
   then set `IOBuiltin` using `kOSBooleanTrue` and `IOMACAddress` using six-byte
   `OSData` on the genuine interface before its first registration. Check return
   values and types. Also set controller `IOBuiltin` consistently; do not rely
   on undocumented controller-to-interface property propagation.
6. Publish only the medium information needed by native interface creation.
   Report link valid but inactive; do not fake carrier, speed negotiations,
   timestamp support, AVB, TSN, gPTP, checksum offload or hardware capabilities.
   The audited clock-ID selection requires identity/class properties, not carrier
   up; downstream gPTP requirements remain a distinct measured branch.
7. Enable/disable manage local administrative state without changing carrier.
   Output consumes/frees each accepted mbuf exactly once and returns dropped.
   No packet injection, DHCP shim, Wi-Fi backend or successful-transmit claim.
   Unsupported optional operations return the appropriate unsupported result;
   implement mandatory filter callbacks with bounded, documented semantics.
8. Native interface publication, unit assignment, BSD attachment and
   re-registration must run without service locks held by the worker. Bound
   the worker's readiness polling; a missing name or failed attach is explicit
   activation failure. No manual TimeSync property/registration mutation.
9. On failure, unwind only owned resources in reverse order: detach/release the
   interface through native controller APIs; stop only a successfully started
   controller; detach only if attached; release media/dictionaries and references.
   Partial `start` failure must clean allocations itself. Keep the successful
   controller/interface alive for the capture; no asynchronous unload experiment.

## Implementation sequence and qualification gates

The following are planned changes, not files already implemented.

1. Close the quiet-wait ownership and initial-notification qualification above.
   Trace the exact proposed activation caller; a comment saying “late probe” is
   insufficient. Keep the existing observer/USB paths untouched.
2. Stage an isolated `out/liuqin-r101-a7-work` from frozen A6. Add experimental
   source under `scripts/liuqin-analysis/r101/a7/` and a dedicated archive builder;
   keep normal device/catalog integration out of the experimental patch. Record
   future component ownership before proposing production integration.
3. Generate/revalidate the ABI fixture against pinned KC bytes. A read-only
   sibling reference has parent instance size `0x118` and 400 vtable slots, but
   it is not sufficient authority by itself. Verify every inherited target,
   override slot, PAC key/discriminator and abstract slot, plus qualified base
   calls and the native `configureInterface` binding. Compile with the actual
   XNU recipe and appropriate network headers/private slots, not guessed offsets.
4. Add only archive selection and one dedicated worker activation hook in the
   staged build. Driver-local diagnostics are bounded lifecycle facts (class,
   provider, MAC type/length, IOBuiltin, BSD name/unit, quiet return and errors),
   outside snapshot checksums. They must not modify the exact A6 observer set.
   Budget all new lines within existing output limits; no print loops.
5. Before accepting any build: rehash all A6 comparison inputs, show the full
   source/configuration diff, and prove observer/guard equality. Run ABI object
   checks, all segment/const-VMA checks, final fileset collision/fixup/original-
   branch checks, and actual prelinker header-vs-payload/AES checks. Report actual
   sizes/hashes; do not claim standalone byte identity. Freeze before hardware.
6. Test meaningful failure cases on the host where possible: wrong fixture hash,
   slot mismatch, malformed MAC/type, failed native configuration, partial-start
   cleanup and absent BSD/quiet readiness. Native lifecycle and notification
   delivery still require hardware; a source fixture cannot validate them.
7. Only after qualification, the proposed experiment is one volatile boot with
   the frozen A6 runner/guards, 120 s cooldown and 480 s capture. Return to verified
   fastboot. Standing authorization removes a separate-go requirement but does
   not turn this design-only step into a boot instruction.

## Predeclared interpretation

| Observation | Interpretation / next boundary |
| --- | --- |
| Wrong metaclass, MAC type/length, IOBuiltin, missing native BSD name or quiet readiness | Adapter contract/activation failure; no conclusion about TimeSync eligibility |
| Valid native interface; clock manager still state 0 / ID absent | Publication hypothesis not confirmed; inspect eligibility/order and delayed lookup, without adding another behavior variable |
| Clock manager registered/matched; OSNumber64 clock ID and OSNumber32 domain `0x63690000` | Publication gate cleared; record actual identity rather than predicting random ID bits |
| Clock notifier matched >=1, pending 0, clock singleton non-nil; gPTP pending | Gate 2 cleared; Gate 3 is the next active boundary; do not fake gPTP capabilities |
| Typed server created and listener progress evidenced; WindowServer advances | Follow the new wait/exit through unchanged stacks, histories and process counters |
| Server non-nil alone | Allocation evidence only; not proof listener was resumed or XPC reply delivered |
| WindowServer exits/aborts after progression | Record reason/timing; Metal absence remains a hypothesis until the exit evidence identifies it |
| Transport/snapshot/guard failure | Preserve raw failure and existing exit status; no clean behavioral comparison |

Retain exact 60/120/300 s snapshots, positive-control publication states/IDs,
clock-ID types/values, local clocksyncd clock/gPTP/server reads, WindowServer
waits/stacks/exits, 8-CPU SCTLR, uncapped WFE histogram and storage/memory series.
Keep `native_reader_validated=false`. “EL0 TRAP=0” does not mean zero faults.
Data exhaustion is not required for the existing TimeSync stall; do not chase its
earlier divergence or resize Data. Owner-key disposition and real-key offline
signing remain separate owner items and are untouched.

## Evidence from this design audit

`out/liuqin-r101-a7-design/evidence/` contains four pinned networking method
disassemblies, selector exports, the reference ABI fixture, public source files
with URL/SHA256 inventory, and `audit-summary.json`. Public source tag
IONetworkingFamily-188 is reference material only. Existing A6 host-branches
evidence supplies init/start/delayed-lookup and notification disassembly.
New evidence and this plan have a separate manifest; no A6 manifest was changed.
