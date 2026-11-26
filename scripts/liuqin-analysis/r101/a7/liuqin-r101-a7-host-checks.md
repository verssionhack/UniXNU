# r101 A7 — pre-build host checks

2026-11-21. Pinned KC SHA256
`d1003b5143ffd88439b4d45b6017f587171cfe6855660bed05370a2ea5db9fe9`.
This is host evidence, not hardware evidence. New artifacts are under
`out/liuqin-r101-a7-work/evidence/host/` and the shared generated build tree;
accepted A6 artifacts remain untouched. Candidate layout acceptance is separate.

## 1. Post-naming re-registration does not require carrier

**Host-verified:** pinned `IONetworkStack::attachNetworkInterfaceToBSD` tests the
data-link attachment return in `w21` at `...acad308`. Success branches to
`...acad3f8`, sets stack attached bit `0x10` at interface `+0xd8`, and tests the
previous stack state bit 0 (inactive) at `...acad400`. The next call at
`...acad408` is exported `IOService::isInactive` (`0xfffffe000c334808`). After
unlocking the stack mutex (`...acad414`), it tests that result and invokes
`registerService` at `...acad43c` when not inactive. The authenticated slot
`+0x5e0` resolves directly to `IOService::registerService` (`...c325634`).

No carrier/link-active property is tested in this branch. The earlier
`ifnet_ioctl(SIOCSIFFLAGS)` is not a condition on successful `enable()` here;
the attachment result controls the success branch. Thus valid-but-inactive
carrier does not suppress native re-registration, provided native BSD
attachment succeeds and termination has not begun. Actual attachment success
remains a runtime acceptance condition.

The public reference's `kInterfaceStateInactive=0x01`, attaching `0x08`, attached
`0x10` and matching branches agree with the pinned instructions; this is not an
assumption based solely on that older source tag.

## 2. Delayed lookup ownership and timing

**Host-verified:** clock-manager init constructs the authenticated function
pointer for `delayedClockIDLookup` at `...b1040c4`–`...40d4`, supplies `this` as
parameter 0, and calls `thread_call_allocate` at `...40dc`; the returned call is
stored at object `+0xc0`.

`interfaceMatched` checks BSD Name and exclusions, locks its own `+0xf8` mutex,
retains the manager, computes a one-second absolute deadline, queues that stored
call with `thread_call_enter_delayed` at `...b106680`, sets pending byte `+0xc8`,
and unlocks at `...b106690`. It does not synchronously invoke delayed lookup or
wait for its completion. The retain is object lifetime, not `adjustBusy`.

`delayedClockIDLookup` first obtains the platform and calls its quiet wait at
`...b1047e0`. Only **after** that returns does it acquire manager mutex `+0xf8`
at `...4804`–`...4808`, find the ID and publish. It releases that mutex before
registering the manager (`...4824`–`...4828`, then `...48ac`), or on the other
return paths. The separate native thread-call context can wait for interface
matching to finish without holding that manager mutex. The notification's
matching context can enqueue and return without depending on the delayed call.

**Implementation:** spawn the new worker immediately after `net_init_run` in
`bsd_init`. That hook performs no IOKit work synchronously. The worker checks
IOBSD with a 30-second wait, loads the family, waits for platform quiet with a
30-second timeout, then creates/starts the native controller. It holds no
service mutex, matching busy reference or workloop gate across these waits.
It polls native name/ifnet and `kIONetworkInterfaceRegisteredState` readiness
(the data-link-registered state, not carrier) for at most 30 seconds without printing
inside the loop, then checks platform quiet again. No wait is added to the
adapter's `start`, interface notification, or command-gate callback.

**Inference:** there is no driver-owned cyclic wait in this call graph. An
unrelated future busy service can still prevent the kext's unlimited quiet wait
from completing; that remains a runtime activation/order failure, not proof
against MAC eligibility. No busy-count manipulation or timesync flag is added.

**Measured host receipt times:** exact A6 guard trace maps root-quiet line 3662
to the chunk received by `+50.677847509 s`; first init exec line 1530 arrived by
`+43.808261159 s`; observer INIT line 744 by `+42.790475071 s`. Differences of
chunk receipt times are approximately 6.870 s after init exec and 7.887 s after
INIT. These are host reception landmarks, not exact on-target execution times.
They ground a 30-second quiet bound without treating “late” as a guarantee.

## 3. Complete pinned controller ABI

`audit-host.py` reads the KC's symbol tables and authenticated chained fixups,
not the sibling JSON. It derives 400 controller entries, each authenticated
IA/key 0 with address diversity, and all original target identities and
discriminators. Parent metaclass constructor instruction gives extent `0x118`.
The only pure slot is 362 (`getHardwareAddress`). The adapter's compile-time
parent-size assertion also passes.

The archive builder checks all 400 compiled entries, not only overrides. Every
retained-family inherited entry is bound to its pinned native target; every
IOService inherited entry must have the exact original symbol identity. Every
pure slot must be overridden. Object imports and qualified base calls are
resolved to pinned family targets through native-original branch stubs.

**Discovered and corrected:** source-header/compiler vtables project inherited
slot 16 as `_RESERVEDOSMetaClassBase3`, whose native source implementation panics.
The pinned controller and metaclass both use `OSMetaClassBase::Dispatch` there,
with discriminator `0x8ee2`. The builder refuses any projection other than those
two exact slots, verifies pinned identities/discriminator, then renames that
undefined binding to native `Dispatch`. It does not accept the panic target or
skip the slot check. The report records the unadjusted object hash and correction.
No baseline header/kernel method is modified.

The qualified archive's retained-family imports are enumerated in its build report. Overrides:
start/stop 190/191; outputPacket 273; getFeatures 274; enable/disable 316/317;
configureInterface 321; hardware address 362; multicast mode/list 364/365;
promiscuous mode 366, plus owned destructors/metaclass getter. Medium queries,
packet freeing and remaining feature/filter operations inherit verified native
implementations. No native pure target remains callable through this vtable.

`test-controller.py` compiles the actual owned class with fault-injectable host
stubs. It passes MAC format/bytes, bad pointer handling, configuration failures,
partial-start cleanup, valid-inactive carrier and exact single-free/drop packet
ownership. This does not validate live native lifecycle or notification delivery.
Header source is IONetworkingFamily-188 commit
`bb910e2b458939f6b1f53c0fa6907f258b431ea4`, qualified by compiled-slot checks
rather than presumed binary equivalence.

## 4. Hard layout acceptance

`check-layout.py` records actual candidate TEXT, DATA and const-VMA values and
returns nonzero on any original gate failure. `package.py` retains the original
r101 gates and actual emitted-fileset AES/header-vs-payload check before making
a boot image. No caps are relaxed and no A6 observer is retired. A host build is
not acceptance until all of those checks pass. Any failure leaves A7 unaccepted
and prevents progression to a volatile boot.

Keep native-reader validation false, nTWE=1/nTWI=0, 512 MiB Data, exact 999-byte
arguments, unchanged A6 guard/parser sources and snapshots. EL0 TRAP=0 does not
mean zero faults. No flash, private-key access, real-key signing or device action
is part of this host implementation/verification step.
