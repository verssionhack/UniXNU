# r101 GPU host gates after Linux parity acceptance

Scope: unmodified reference-source compilation, pinned-binary inspection,
firmware analysis and design. No A730/XNU driver edits, kernel candidate link,
boot image, hardware action, signing, flash, partition write or key access.
Accepted M1/A7 artifacts remain immutable. Labels: **host-measured**,
**source-verified**, **inference**, **(verify)**.

## Gate disposition

| Gate | Result | What remains |
| --- | --- | --- |
| KMD footprint / placement | Partial measurement; concrete placement strategy established | Full enabled reference closure, generated board inputs, correct archive membership, final link and existing gates |
| 26C5035r Metal / Turnip ABI | Pinned discovery contract and selected ABI facts verified; full gate **open** | Complete SDK/patched Mesa build, symbol/type/PAC/user-client checks and later runtime evidence |
| HFI queue count | **Initializer contract closed:** firmware accepts both valid two- and three-queue tables | No operational/wakeup/coherence claim from initialization alone |
| Strict GMU parser design | Host contract passes actual image and seven malformed controls | Driver integration remains held |
| Read-only platform discovery | Design documented separately | No probe implementation or boot authorized by this report |

This report does not mark all remaining Milestone 1 gates passed. Missing
inputs are named below rather than replaced with dummy board headers, firmware
ACKs, fabricated SDK declarations or optimistic link-size estimates.

## 1. What was compiled and measured

`measure-reference.py` compiles frozen M1 comparator sources using the existing
26C5035r source-kernel compilation record and its actual arm64e toolchain.
Warnings are suppressed for diagnostic size measurement; this is not the
reference recipe's Werror qualification. Source hashes, commands, logs, return
codes and every Mach-O section size are preserved in `compiled-reference.json`.
Of 50 attempted objects, 47 compile: all 30 selected Adreno740 objects, four
AdrenoFirmware, five AdrenoPM4 and eight ArmSmmu4K objects. Three Sm8550Platform
objects fail on missing generated source headers.

The actual XNU linker rules in `MakeInc.def` rename `__TEXT,__text` to
`__TEXT_EXEC,__text`; `__DATA,__const`, init functions and authenticated pointers
move to `__DATA_CONST`. Debug sections are not runtime capacity. Applying those
rules to the successfully compiled diagnostic inventory gives:

| Group | TEXT_EXEC bytes | TEXT bytes | DATA_CONST bytes | DATA bytes |
| --- | ---: | ---: | ---: | ---: |
| Adreno740 | 141,116 | 3,965 | 19,432 | 20,364 |
| AdrenoFirmware | 8,672 | 0 | 0 | 0 |
| AdrenoPM4 | 7,028 | 16 | 0 | 0 |
| ArmSmmu4K | 27,404 | 84 | 0 | 0 |
| Total successful inventory | **184,220** | **4,065** | **19,432** | **20,364** |

These are exact **object-section sums**, not aligned linked sizes. They are
neither a complete closure nor a mathematically safe lower/upper bound on the
future driver: the inventory includes some sources the board recipe excludes,
while missing generated feature headers compile out other service branches.
In particular, the original recipe excludes NativeAdrenoClient and stages the
accelerator separately; a blanket archive of this inventory is not accepted.

The pinned documented board recipe was retrieved at sheng commit
`516a780473a2ac59c8b438e132bb60204dda9e22` and saved with URL/hash provenance.
It also requires `kits/sheng/ShengGmuVotes.c`, generated `ShengGmuSource.h`,
`ShengGmuCommandDbSource.h`, `ShengGpuSmmuSource.h`, vote policy and firmware
inputs. The local platform snapshot does not contain those generated headers;
the board-specific votes source is not in the selected component kit.
No placeholders were manufactured. This recipe is a documented reference,
not a claim that its revision equals every local comparator revision.

## 2. Placement strategy, without relaxing a wall

The existing native driver is linked through `-force_load` into the standalone
kernel. That archive is not a separately placed fileset kext. The actual
fileset layout places native executable code after retained kext executable
code, checks native constants against the first retained constants, and keeps
native writable DATA below Libm.

**Host-measured:** read-only reconstruction of frozen A7 placement establishes:

- Existing TEXT policy slack: 49,152 B; DATA policy slack: 32,768 B.
- Native code/KLD end to native DATA start: **6,127,616 B**. This is the
  relevant measured physical window for additional TEXT_EXEC, subject to all
  layout validations; code does not consume the 48 KiB TEXT allowance.
- DATA_CONST ends at collection VA `0xfffffe0007f04000`; LASTDATA_CONST ends
  at `0xfffffe0007f08000`. First retained constants are AppleARMPlatform at
  `0xfffffe0007f92a68`, leaving **567,912 B after the const tail**.

`additional-placement-windows.json` retains exact intervals. Its generic
"next retained" TEXT_EXEC row is not a code-growth permission: the stricter
native DATA boundary and `Layout.validate()` remain binding.

**Source-verified firmware staging:** the documented recipe emits strong image
symbols into **`__DATA_CONST,__const`**, with 4 KiB alignment per image and an
8-byte size symbol. It does not embed firmware in writable standalone DATA.
Known A730 blobs are GMU 57,272 B, SQE 74,676 B and ZAP 11,608 B, total
143,556 B. Applying that recipe's exact ordering/alignment gives **146,784 B**
from a 4 KiB-aligned origin, recorded in `firmware-staging-layout.json`.
This consumes const-window capacity; it is not free space and is distinct from
runtime GMU allocations. ZAP remains vendor-signed; no owner key is involved.

**Proposed placement:** use the existing separately placed native TEXT_EXEC,
read-only DATA_CONST firmware section and ordinary DATA, with exact archive
membership and staged accelerator initialization. Do not introduce a new
fileset kext solely because the raw code exceeds 48 KiB. Do not put these blobs
in writable DATA. Preserve strong-over-weak firmware symbol resolution and
verify the emitted sections, hashes and permissions after linking.

Tier-1 observer retirement may recover space, but no retirement was implemented
or saving credited here. Final acceptance requires the complete generated
profile, real link, 16 KiB alignment, const floor, neighbor checks, native/root
headers, original-call/PAC bindings and AES gate. The measured inventory and
firmware are compatible with a plausible strategy; **they do not prove fit**.
Also keep runtime allocation separate: the reference GMU icache reservation
alone is almost 16 MiB, comparable to A7's minimum free-RAM sample under churn.
Static placement does not establish runtime memory headroom.

## 3. Pinned 26C5035r ABI audit

IOGPU, Metal and IOSurface image metadata, Objective-C declarations and symbol
inventories were extracted from the accepted host cache. `verify-target.py`
checks used cache UUID/SHA256 identities and **501 saved instruction words**
against pinned bytes. No earlier audit script with output-writing import side
effects was imported. A new disposable ipsw symbol cache was used; it is not
part of the frozen evidence manifest.

Concrete target facts:

- IOGPU UUID `f4f1377aec8d3a2d8ff1586823d6c92d`, source version 163.1.4,
  target macOS 27.3. Other exact image IDs are in `target-abi-verification.json`.
- `IOGPUMetalDevice` inherits `_MTLDevice`. Its `acceleratorPort` property is
  32-bit unsigned, matching the adapter's port type.
- At `0x1940b8630`, `+[IOGPUMetalDevice registerAcceleratorService:]` reads
  CFString `MetalPluginName`, calls `gpu_bundle_find_trusted`, resolves optional
  `MetalPluginClassName` or the principal class, checks `isSubclassOfClass:`,
  calls `initWithAcceleratorPort:`, associates service/device and calls
  `MTLAddDevice` for a non-nil result. Selector stubs were checked separately.
- `-[IOGPUMetalDevice cmdBufArgsSize]` at `0x1940b91f8` returns **48**,
  matching the shim. `_setAcceleratorService:` retains its argument and stores
  it in the target ivar; the frontend supplies its own compatible selector.
- The target's original `initWithAcceleratorPort:options:` calls
  `IOGPUDeviceCreateWithOptions`. The native plugin deliberately avoids that
  initializer and retains the temporary subclass instance, returning its own
  frontend object. This makes the shim/lifetime path an essential ABI seam,
  not a proof that a normal original IOGPU user client was instantiated.
- All **17 IOSurface function names** called in the two audited frontend
  sources are present in the target symbol inventory. This is symbol presence,
  not proof of matching call types, surface ownership, import coherency or PAC.
- Kernel accelerator metadata has a recorded 26C5035r IOAccelerator base
  fixture: 136-byte instance, 272 entries, original constructor/destructor
  bindings and Dispatch caveat. Full subclass dispatch, authenticated pointers,
  staged metaclass initialization and the custom ABI-v2 external method path
  still need qualification in the actual selected build.

**Specific qualification gaps:** the local SDK is the minimal kernel toolchain
SDK and lacks Metal.framework and private IOGPU.framework. The patched Darwin
Mesa source/build and resulting dylib/plugin are absent. Therefore no complete
macOS frontend build/import check or runtime ABI test was performed. The
existing build entry has a macos27 target, but its existence is not a build
result. The shim's generic uint64-zero missing-selector fallback is not a
type-correct universal replacement for floating-point/aggregate-return methods;
method-encoding-specific handling must be audited before calling it qualified.
No such adapter code was changed here.

## 4. Trust registration without owner.key

The source build script uses **ad-hoc** `codesign --sign - --pagesize 4096`
for the Turnip dylib and bundle, then records their CDHashes. The wording
"owner-signed" in its introduction must not be confused with using owner.key.
`make-owner-trust-bundle.py` constructs a version-2 CDHash module and packages
it with original modules; it has no private-key operation. A future exact
build can therefore be registered through a reviewed extra trust module
without reading owner.key or exercising the offline real-key signing flow.
No trust bundle or signed executable was generated/activated in this audit.

AMFI trust and IOGPU's trusted-bundle-location check are **separate** gates.
The addon packaging supports GPUBundles prefix, and source kern_exec code
stages `/Library/GPUBundles`, applies `com.apple.rootless` storage class
`KernelExtensionManagement` and SF_RESTRICTED. Both the code CDHashes and
bundle/directory protection must be verified in the future exact image;
a raw trust-cache module alone does not prove `gpu_bundle_find_trusted` passes.
Source support is not evidence that these routines are active/reachable in
frozen A7. Its emitted symbol survey did not establish that. Nor may a new
`gpu-addon=1` simply be appended to the already 999-byte argument string.
Packaging activation needs a reviewed existing/non-arg path or another explicit
configuration design under the 1,000-byte limit.

## 5. HFI count audit: a real firmware result

The pinned A730 GMU firmware's bounded Thumb initializer at **CM3 VA 0x8cd0**
was decoded from its mapped firmware block, independently of the broad linear
candidate scan. `audit-hfi-init.py` asserts 17 exact instruction predicates.
The caller at 0x8fa4 calls it at 0x8fb0 and publishes ready/error.

- It waits for HFI table-info, loads the table pointer, reads first-header
  offset from table+8 in dwords, and reads queue count as u16 at table+16.
- `cmp r0,#0x14; bls` accepts count <=20; larger counts return `0x70`.
- It strides headers by **48 bytes**, loads queue ID from low byte at header+8
  and requires ID<count. It copies each header's ring size/base into internal
  descriptors and returns zero after the loop.
- CM3 table-info literal `0x1807e610` agrees with Linux GMU register offset
  `0x5184` plus the independently known GPU/GMU aperture displacement.

Thus Linux `(count=2, types a00/a01)` and native `(count=3, types a00/a01/a02)`
both satisfy the **actual binary initializer**. Models of count 21 and ID equal
to count correctly follow the error predicate. **The firmware does not strictly
require two queues at this initialization boundary.** This closes the narrow
queue-count rejection hypothesis without running CM3. It does not establish
all later queue uses, debug-queue behavior, IRQ/coherence or operational HFI.
Keep the Linux two-queue layout as the conservative first-profile design unless
there is a measured reason to select three; no wire implementation changed.

The host strict-parser prototype validates all 15 real headers/four data blocks
and rejects seven malformed controls: truncated payload, partial trailing header,
unaligned address, unknown metadata, cross-region payload, 32-bit wrap and
overlapping data. It checks subtraction-based file/region bounds, alignment,
metadata policy, count cap, data nonoverlap and full pinned digest. It performs
no MMIO, SMC, DMA or firmware execution. Runtime adoption still requires memory
ownership and stopped-GMU preconditions; malformed control results are not
hardware fault injection.

## 6. Next boundary

The separate discovery plan is ready for review. No probe should be coded or
booted on the assumption that all host gates have passed. Remaining concrete
host inputs are the complete board-generated closure and target userspace SDK/
patched Mesa build; the final link/import/ABI checks depend on them. The HFI
initializer and parser work can be carried forward without reopening firmware
hunting. Graphics boots, A730 driver edits, display/input work and real-key
operations stay held.
