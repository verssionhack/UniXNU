# r101 post-A7 SkyLight compositor audit — host only

2026-11-21. **No candidate built, no device command, no hardware boot.** A7 is
the accepted TimeSync-unlocked behavior baseline; hardware behavior boots remain
held. No accelerator/Metal stand-in, GOP change, Data resize, key operation or
kernel observer change was made.

**Finding:** normal startup still requires the Metal-availability check even
with zero hardware displays. Noop exists as a runtime debug-selected backend,
but no clean non-Metal startup selector was established. GOP-off is not yet a
grounded way to obtain a stable, initialized WindowServer on the A7 baseline.

Labels: **host-verified** refers to pinned binary/source inspection; **measured**
to accepted captures; **inference** and **unverified** remain distinguished.

## Inputs and reproduction boundary

- 26C5035r shared cache UUID `8b1e17c672d6301791a4916022e3612e`, matching A7's
  recorded live shared region.
- SkyLight image UUID `331822b11c9f367badd2310ddeeff7c9`.
- SkyLight `__TEXT,__text`: `0x1826b1cb8`, length `0x58b4d0`, SHA256
  `2bb7a8c492d5d100f9021738c177de27ffa88560b506c318828b484da89b49b7`.
- Code subcache `.01`: SHA256
  `b954fa0249bb2c9ab5b3d7207bb05f4767bb70d3c675b3cab6a37aafc9c6c890`.
- CFString metadata subcache `.25.dylddata`: SHA256
  `9dc730e90aff466e4954194cdb7f1f7e1d6f3f2a084a09931f6f3f77defeb2da`.

Artifacts: `out/liuqin-r101-skylight-audit/evidence/`. `inputs.json` records image
geometry and verified code input, `data-inputs.json` records CFString input,
and the final audit manifest pins all new evidence and rechecks A7/A6 manifests.
Symbol names guide lookup; branch conclusions below come from instructions.

Use the existing ipsw tool's `dyld disass CACHE --vaddr ADDRESS --cache A2S
--no-color` with the function addresses below. `scan.py` independently scans all
aligned direct B/BL instructions in SkyLight text. `control-flow.py` evaluates
the saved instruction graphs. Its calls-return model is conservative for normal
returns; it does not model blocking calls, exceptions, callbacks or other images.
`data-references.py` records bounded ADRP provenance candidates; it is explicitly
not an exhaustive alias-aware proof of every possible global writer.

## 1. What selects entry to the Metal wait?

The relevant normal startup chain is:

```text
SLXServer
  → WSInitialize
      → WS::Displays::CAManager (earlier initialization can block here)
      → WSCompositorActivateDefault
          → initialize_compositors once
          → activate_compositor_default once
              → WSSystemCanCompositeWithMetal once
                  → MTLCopyAllDevicesWithObserver
                  → device probe / semaphore signal or device-added callback
                  → 30-second semaphore wait
                  → success sets metal_lovin=1; timeout logs and aborts
          → select Metal or software from default_to_metal
```

**Host-verified:** `WSInitialize` (`0x182a8d14c`) calls
`WSCompositorActivateDefault` at **`0x182a8fca8`**. It does not test the hardware
display count, GOP registration or active compositor value before this call.
The active-compositor value is read **after** the call at `...fcb0`.

The direct intraprocedural CFG has one normal return at `0x182a8fe98`. Removing
the default-activation instruction makes that return unreachable, even with all
conditional branch outcomes unconstrained. There are no unresolved indirect or
tail branches in this function's saved graph. Thus default activation dominates
every normal return in this model. Earlier callees may still park/fail rather
than return; parking is not successful headless initialization.

**Host-verified correction to the older display analysis:** `0x1828d407c` is
**`CGXInitializeGL`**, not a standalone `disp_check` function that bypasses
compositor initialization when no displays exist. It calls
`CGXNextHardwareDisplayDevice`; its zero-device branch at `...40ec` goes to
`...4230`, then reaches **`WSCompositorActivateDefault` at `...424c`**. The same
call dominates its sole normal return (`...4398`). Safe-mode handling also
reaches this default call. A third direct caller is the CAWSManager accelerated-
compositing initialization block (`0x182aed538`, call at `...d544`).

**Inference:** GOP/display publication can affect earlier discovery/callback
paths and how far startup gets, but it is not a necessary condition for the
default Metal check in the audited normal-return path. Removing GOP alone is
not supported as a Metal-abort bypass. It might cause an earlier park, which
would not establish a usable headless user session.

**Measured context / correction:** A6 with GOP present was parked before this
point on synchronous TimeSync initialization; A7 changed only the native
interface and reached this Metal wait. The earlier r96 zero-display survival is
real, but its attribution to display absence was an inference. The claim in
r97 preflight §4/§6 that removing GOP avoids the 30-second Metal wall is
**withdrawn as an established explanation**. Earlier frozen documents/logs are
preserved. This audit does not retroactively identify r96's exact wait object.

## 2. Default compositor selection has no usable no-Metal fallback here

`WSCompositorActivateDefault` (`0x182837070`):

1. Initializes compositor objects through `initialize_compositors` once.
2. Invokes `activate_compositor_default` once at `...37108`.
3. Only after that returns, reads private byte `default_to_metal` at
   `0x1eb1b6fb0`: zero chooses Metal; one chooses software.

Despite its name, **byte value 1 chooses software**. The once block at
`0x1828382b0` first ensures the Metal-check once (`0x1eb1b7640`) has completed,
then reads `metal_lovin` (`0x1eb1b7638`); only if false does it store 1 into
`default_to_metal`. It does not read a defaults dictionary, environment variable,
launch argument or active Noop selector in this block.

The pinned Metal-check block (`0x1828dfd58`) does not return false on an ordinary
absent-device timeout. It waits **`0x6fc23ac00` ns = 30 s**, formats
`No suitable Metal devices present after %llu seconds.`, and calls `abort` at
`0x1828dff30`. Successful semaphore completion sets `metal_lovin=1`.

**Inference:** the apparent software fallback does not rescue a fresh no-device
startup from this fatal timeout. Forcing a later compositor byte, or merely
requesting Noop before another default activation, does not by itself establish
a bypass of the preceding once/Metal check. No private-memory patch is proposed.

## 3. Exact Noop selector: runtime debug opcode, not a qualified launch mode

The genuine Noop selector is:

```text
WSCompositorSetDebugOptions(0x800000c2)
```

**Host-verified:** at `0x182836900` the function compares against
`0x800000c2`; the matching branch `...69bc` calls `debug_set_acceleration(true)`,
stores **2** into `active_compositor` (`0x1eb1b6f64`) at `...69d0`, and emits
`Noop compositor activated.` Other compositor values are Metal=0, software=1.
Opcode `0x800000fe` selects the software helper. These are imperative debug
operations, not boolean defaults keys.

All direct callers of the compositor debug selector in SkyLight text come from
`set_debug_options` (`0x18293f5ac`, calls at `...3f924` / `...406cc`). The client
entry `SLSSetDebugOptions` (`0x1826e8f30`) calls `AbortIfRunningInServer`, obtains
the server port, and sends the option through `__CGSSetDebugOptionsPSN`. This is
not a demonstrated pre-initialization launch channel. No helper was built or run,
and request authorization/delivery before initialization was not tested.

The startup parser in `SLXServer` (`0x182775938`) recognizes `-debug`, `console`,
`-daemon`, `-exit`, `-virtual`, `-virtualonly` and `-x`. The inspected flags alter
daemon/virtual-console/safe-mode/exit behavior; their paths still reach
`WSInitialize`. No one of these flags was found to select the Noop debug opcode
or bypass default initialization. `-exit` is checked after `WSInitialize` and is
not a shortcut around its Metal check.

### `BootToMetalCompositor` is not a proven selector

This key exists in a configuration dictionary loaded from the SkyLight bundle's
**Resources/Configuration.plist**, via `_SkyLightConfiguration` and its once
block at `0x18286ee1c`. It is not loaded by the audited compositor selector as a
CFPreferences user-default key.

The string's CFString object is at `0x1e2256ed0`; the tool finds **one** direct
reference to that object within SkyLight, at `0x182941a68` in
`DumpWSCDIOPWSAA`. That code reads the dictionary value solely to print
`WS-Boot-to-Metal plist: Set (Enabled)/Set (Disabled)/Not Set`, then separately
prints the current compositor. It does not set the compositor or once state.
The direct cstring xref search finds no direct code reference to the cstring.

This makes setting `BootToMetalCompositor=false` an **unqualified experiment**,
not a host-established escape. Other images, indirect dictionary iteration and
all possible private configuration mechanisms were not exhaustively audited;
the precise conclusion is that no effective startup Noop/non-Metal selector was
established on the audited normal initialization path.

## 4. Noop is real, but a globally clean headless path is not proved

`initialize_compositors` (`0x1828381a4`) constructs 16-byte software and Noop
objects, with type fields 1 and 2 and native vtables. `WSGetCompositorForAccelerator`
(`0x182837cc8`) returns the Noop object directly when active type is 2, without
its Metal lookup branch.

The ten audited Noop methods at `0x18295220c`–`0x182952244` are genuinely
non-rendering: reset/flush/composite return; capture/stream/texture factories
return null; shadow factories return an empty object; deletion calls delete.
These methods contain no Metal call or TODO assert. They cannot create a
visible desktop.

That local fact does not prove safe activation or a complete user session:

- `debug_set_acceleration` (`0x182836784`) updates acceleration state, obtains
  CAManager and invokes per-display virtual hooks. The selector also updates
  sessions and the desktop on a mode transition. Those indirect downstream
  paths are not an established no-Metal startup contract.
- Default initialization still performs the mandatory check described above;
  it does not accept active type 2 as an early return.
- `desktop_window_effects_update` (`0x182ab93b4`) contains a non-Metal-type
  branch at `...b9638` to the assertion
  `WSCompositorGetType(compositor) == kWSCompositorMetal` at `...ba160`.
- `WS::Displays::SLCADisplay::render_update` (`0x182ad1bf0`) has a non-Metal
  type branch at `...d2d18` to `TODO: software compositor support.` and a skip
  path; another path asserts `compositor->GetType() == kWSCompositorMetal`
  (`...d34d8` / assert call `...d34e0`). These are conditional paths, not a claim
  that every Noop invocation immediately asserts. Their reachability during a
  proposed headless session would need qualification.

**Disposition:** neither a stable startup Noop mode nor a functional software
desktop is established. Do not fabricate a Metal/IOAccelerator service, force a
private global, or consume a boot on an assumed defaults key based on this audit.

## 5. Hook-loss visibility: tested future host gate, frozen results untouched

`history-gate.py` is a separate offline proposal. It reads explicit LOSS records,
fails closed on missing/malformed records, exposes ring loss separately from
payload prefix truncation and bounded-history eviction, and reports a proposed
exit 5 when an experiment requires a lossless hook ring. It does **not** change
the A6/A7 runner, assessor, raw logs or existing exit codes.

| Existing capture | LOSS rows | ring_drop max | Proposed required-ring gate |
| --- | ---: | ---: | --- |
| A6 | 17 | 0 | pass / 0 |
| A7 | 17 | 68,558 | fail / 5 |

Missing-record, embedded-prefix and positive-drop negative controls pass.
Even A6 reports payload_trunc=87/history_overwrite=94; zero ring drops do not
make the full filtered/undecoded history complete. `absence_claim_permitted`
stays false. A7's verified snapshots and positive stack/state evidence remain
usable independently of its lossy hooks.

Before a future history-dependent experiment, integrate an explicitly required
history gate or qualify a narrowly scoped/rate-limited hook revision against the
relevant workload. That is future work, not an installed policy or a kernel
change in this audit. No attempt was made to increase the 256-entry kernel ring
or consume A7's 1,760-byte const-VMA margin.

## Decision and remaining work

Keep hardware boots held. The two tracks remain separate:

- **Headless/user session:** no next single-variable behavior boot is qualified
  by this audit. A legitimate startup non-rendering path would need to be shown
  to bypass mandatory Metal initialization and avoid downstream assumptions.
  GOP-off can be retained as a contrast hypothesis, but not sold as a proven
  crash-loop fix or useful-session path.
- **Visible desktop:** real Adreno 730 GPU/Metal support remains the substantive
  dependency. The existing GOP/verbose console is a separate low-level facility;
  an empty accelerator service cannot satisfy the compositor/shader runtime.

The useful correction is concrete: stop treating the old zero-display park,
the software-mode enum or the diagnostic plist key as ready-made startup
solutions. No fresh candidate or device action follows from these findings.

nTWE=1/nTWI=0, identity Ethernet, Data=512 MiB and all frozen A7 behavior remain
untouched. `native_reader_validated=false` and the EL0 TRAP=0 caveat remain.
Owner-key disposition and real-key offline signing remain separate owner items;
owner.key was not accessed. Last device state is A7's recorded verified fastboot;
this host-only turn did not re-query it.
