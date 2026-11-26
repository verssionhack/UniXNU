# Liuqin r101 A7 — host implementation and qualification

2026-11-21. **Host-qualified candidate; no hardware boot performed.** Isolated
work: `out/liuqin-r101-a7-work`. Comparison is frozen A6 on A3r1 behavior.
The design's four pre-build checks are closed on the host; native activation,
quiet completion and TimeSync progression remain unmeasured.

## Candidate identity and hard gates

| Artifact/check | Result |
| --- | --- |
| Boot SHA256 | `ffdec111a73bdfafd5be42574dbf71d0542c0c78daffb8d98fde8942a91a3d5a` |
| Emitted kernel SHA256 | `a03200b0c3e0879745c515b378b98c5407421177d168604a95b403f783dc6777` |
| TEXT | `0x1cc000 <= 0x1d8000` |
| DATA | `0x27c000 <= 0x284000` |
| TEXT_EXEC | `0x9a8000` (A6 `0x9a4000`, +16 KiB) |
| const VMA | `0xfffffff007005fe0 >= 0xfffffff007005900` |
| const margin | 1,760 B (A6 2,272 B; -512 B) |
| Actual emitted fileset/header-vs-payload/AES | PASS |
| Original prelink mapping | Complete; no missing mappings |

The driver archive is linked into the standalone kernel. Standalone bytes are
not identical to A6. No observer retirement, gate relaxation, new boot argument
or TimeSync patch was used to make this fit.

## Four requested host checks

1. **Inactive carrier is permitted.** Pinned BSD-attachment code tests successful
   attachment, stack inactive state and `IOService::isInactive`, then re-registers
   after naming. It does not require link-active carrier or successful `enable`
   to select that branch. Registration still requires successful native attach.
2. **No driver-owned quiet-wait cycle.** Pinned TimeSync init allocates the
   delayed thread call; interface matching retains/enqueues/unlocks and returns.
   Delayed lookup calls platform quiet **before** acquiring its manager mutex.
   The adapter's worker is spawned after `net_init_run`, with no driver-held
   matching/command-gate locks across its waits. A6 quiet was received by host
   +50.678 s, versus init exec +43.808 s and observer INIT +42.790 s. These are
   chunk reception landmarks. Unrelated future busy work can still delay the
   native unlimited wait; no source audit promises live completion.
3. **Pinned ABI qualified.** Fresh KC-derived fixture: controller size `0x118`,
   400 authenticated vtable entries, sole abstract slot 362 implemented.
   All compiled inherited entries/targets and PAC attributes are checked.
   An additional **unlinked** interface witness validates 346 slots and size
   `0x148`, including the virtual-call layout used for interface state queries.
   Final emitted native-original branch and native data-alias targets are checked
   against the archive bindings, not only the standalone object.
4. **Hard layout limits honored.** All original gates and the actual fileset
   AES/header check pass with the values above. A failure would have rejected
   the candidate; nothing was retired or relaxed.

See `liuqin-r101-a7-host-checks.md` for pinned addresses, instructions, timing
evidence and the source-header/compiler inherited Dispatch correction.

## Exact behavior delta

Added `LiuqinIdentityEthernet : IOEthernetController`, with the native inherited
`IOEthernetInterface` factory/lifecycle. Fixed experiment MAC
`02:4c:51:10:00:01` is locally administered/unicast, not the Wi-Fi hardware MAC.
`configureInterface` calls native super, then installs six-byte OSData
`IOMACAddress` and OSBoolean-true `IOBuiltin` on the real interface. The
controller also reports builtin. The family supplies controller/provider,
prefix/unit and BSD naming; no literal `en0` or manually assigned BSD name.

Link remains valid-but-inactive. No transport, packet injection, fake carrier,
AVB/TSN/gPTP capability, offload, DHCP shim or traffic-success claim. Output
frees an accepted packet once and returns dropped. Administrative enable/disable
preserve inactive carrier. Mandatory filters have bounded no-receiver semantics.

Native stack naming can initially follow publication; TimeSync uses matched
notifications and receives actionable re-registration after BSD naming. The
worker now requires `BSD Name`, a native ifnet **and data-link registered state**,
then a post-attachment quiet check. A name alone is insufficient because native
code writes it before attachment completes. The prequiet, native-readiness and
postquiet waits are each bounded at 30 seconds. Driver diagnostics do not print
inside polling loops and remain outside existing snapshot checksums.

Only baseline kernel-source change is the worker-spawn hook in
`bsd/kern/bsd_init.c` after `net_init_run`. Existing device changes are the archive
recipe in board.toml, appended force-load in the staged defconfig and cumulative
kernel patch containing that hook. New adapter sources/headers, fixture and
builder are staged separately. Main repository build wiring is not changed.

## Verification and preserved attempts

- All 120 A6 manifest entries rehashed unchanged. Every existing A6 observer
  source is byte-identical. Runner, parser, guard and fault rules are unchanged.
- Exact 999-byte arguments, ADT and trust bundle match A6. Compiled Data seed is
  the same unique 74,048-byte sequence with SHA256
  `072eda49e3a55e5c7e762604cdf7406d9a2421e23a8d26ea557f6f6723c32505`;
  capacity remains 512 MiB. No display/Metal/SMP/EPSS or nTWE/nTWI change.
- Actual owned-class host tests pass MAC/bad-argument handling, configuration
  failures, partial-start cleanup, carrier semantics and exact packet ownership.
  These use fault-injectable lifecycle stubs and do not validate live IOKit.
- The first kernel link failed because configuration overrode the environment
  archive setting, omitting the worker definition. Corrected only in isolated
  defconfig. Original log is retained as `build-attempt1.log` and compressed
  `evidence/kernel-attempt1.log.gz`.
- The first successful packaged build is preserved in `evidence/a-first-link`.
  It was superseded before hardware acceptance to require data-link registered
  state as well as name/ifnet readiness. The corrected candidate above passes
  the same layout and actual fileset gates.
- A source/compiler projection named inherited slot 16 as a reserved panic
  method. The pinned controller/metaclass require `OSMetaClassBase::Dispatch`
  with diversity `0x8ee2`. The builder checks those exact two projections and
  rebinds them to native Dispatch; it never skips the inherited identity check.
  Original object hash and the correction are recorded in the archive report.

Reproducible tooling: `audit-host.py`, `prepare.py`, `build-identity-ethernet.py`,
`build.py`, `test-controller.py`, `check-interface-abi.py`, `verify.py`,
`check-layout.py`, `package.py`, `finalize.py`. `prepare.py` refuses an existing
prepared staging tree. Build/package/finalize do not boot. Host evidence and
candidate hashes are frozen in `evidence/host-manifest.json`.

## Hardware boundary

No claim yet that this adapter publishes successfully, that TimeSync's delayed
quiet wait returns, that clock-manager registration occurs, or that clocksyncd
or WindowServer advances. Apply the approved A7 decision matrix to a future
capture with unchanged A6 60/120/300 s snapshots and guards. Server allocation
alone does not prove listener resume/reply; absent carrier need not predict
whether Gate 3 clears. Metal abort remains a hypothesis pending exit evidence.

`native_reader_validated=false` remains. EL0 TRAP=0 does not mean zero faults.
No device command, flash, partition write, owner.key access, key rotation or
real-key signing was performed. The last recorded device state remains A6's
verified fastboot; it was not re-queried during this host-only step.
