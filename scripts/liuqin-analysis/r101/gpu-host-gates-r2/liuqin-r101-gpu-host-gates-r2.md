# r101 GPU host gates r2: full reference KMD link/placement and 26C5035r ABI/trust audit

Date: 2026-11-21. **Host-only isolated revision (`gpu-host-gates-r2`).**
No A730/XNU driver edits, no boot image or payload emitted, no device command,
no flash/partition write, no key access, no real-key signing. Accepted M1, A7,
layout, SkyLight and r1 host-gate artifacts remain immutable.
Labels: **host-measured**, **source-verified**, **inference**, **(verify)**.
Evidence root: `out/liuqin-r101-gpu-host-gates-r2/evidence/`.

## Gate disposition

| Gate | r1 status | r2 status | What remains |
| --- | --- | --- | --- |
| KMD footprint / link / placement | Partial `.o` sums (3 Sm8550Platform compile failures; no link) | **Reference closure linked, prelinked & validated** (`-Werror`, 0 warnings; `Layout.validate()`, `emit_prelink.py`, `aes_fileset_gate.py`, `AGXAccelerator` stubs & read-only A730 firmware in `__DATA_CONST` all pass; **tight margins exposed**: const-VMA margin **384 B**, `__DATA` slack **16 KiB**) | Resolve 3 weak-import board hooks & 4 A7 legacy-display duplicate stubs in future real A730 integration; budget const-VMA / `__DATA` (or Tier-1 observer retirement) before adding board power/probe code; runtime RAM headroom remains separate |
| 26C5035r Metal / IOGPU / Turnip ABI | Selected contracts & symbol presence; full gate open | **Static ObjC/wire/plugin contracts audited; full gate still OPEN** (concrete shim mismatches & `resolveStub` AAPCS hazards pinpointed) | Fix 2 `MethodSpec` type-encoding mismatches & 2 `resolveStub` ARM64 AAPCS return hazards (`minLOD` float, `compressionMetadata` 16 B struct) before adoption; **blocked on Linux host** by missing Apple macOS 27 (`26C5035r`) userspace SDK, real `codesign`, Rust `1.98.0` `arm64e-apple-darwin` (`rust-src`), `glslangValidator`, and local patched Mesa/metal2vulkan checkouts |
| Bundle trust & `/Library/GPUBundles` reachability | Unestablished in frozen A7 | **Closed as NOT reachable in frozen A7** (`native_sandbox_grant` is active; `native_owner_macos_gpu_addon`, `native_gpu_bundle_protect`, `native_gpu_addon_install` are compiled out; `native_ram_block_gpu_addon` undefined; boot args 999/1,000 B) | Requires an explicit liuqin Data-staging + `com.apple.rootless`/`SF_RESTRICTED` + non-bootarg activation design when graphics integration is later authorized |
| HFI queue count & strict GMU parser | Closed in r1 | Carried forward unchanged from frozen r1 | Driver integration remains held |
| Read-only platform discovery | Design ready; held | Remains held pending owner review of r1/r2 gates and explicit hold resolution | No probe coded or booted |

---

## 1. Full reference KMD closure: generation, `-Werror` compile, real `ld64` link & fileset placement

### 1.1 Unmodified source closure and zero-fabrication header generation

**Host-measured:** local matching checkouts were staged read-only into
`out/liuqin-r101-gpu-host-gates-r2/stage/`:

- `UniXNU-sheng` at `6bc0ce1e8c3a3733110a80dd80ddfb2a1ca46555` (`package/ShengGmuVotes.c`,
  `package/audit-adreno-platform.py`, and the three unmodified generators
  `prepare-sheng-gmu.py`, `prepare-sheng-gpu-smmu.py`, `prepare-sheng-gmu-votes.py`).
- `UniXNU-sm8550-common` at `97665e28578483082b674e8375a8fa65f4cf49cf` (`kits/Sm8550Platform`).
- Local `drivers/Adreno740` (`08a32b56e1b9e9d0e9d2ee0644d1c5825e8215fe`),
  `kits/AdrenoFirmware`, `kits/AdrenoPM4`, `kits/ArmSmmu4K`.
- `fetch-reference-inputs.py` fetched and verified **28 SHA-pinned Adreno inputs**
  (1,211,915 B) and **39 pinned SM8550 DTS/binding files** (`fetched-reference-inputs.json`).

All three unmodified sheng generators passed and produced the four real generated headers
without fabrication:

- `ShengGmuSource.h` (3,077 B, SHA256 `fe2e077a...be9e0`)
- `ShengGmuVotesSource.h` (1,076 B, SHA256 `d8a2cfc8...4d4e5`)
- `ShengGmuCommandDbSource.h` (157 B, SHA256 `d5a27e57...d8f1d7`)
- `ShengGpuSmmuSource.h` (283 B, SHA256 `3b1ae037...44fe682`)

### 1.2 `-Werror` compilation with actual 26C5035r arm64e kernel toolchain

**Host-measured (`reference-closure-link-placement.json`):** using the actual A7
`bsd_init.o.json` and `IOPlatformExpert.cpo.json` compile records and
`/opt/unixnu-linux/llvm/bin/clang` with `-Wall -Wextra -Werror` (no `-Wno-everything`),
all **46 objects** compiled cleanly with **0 warnings and 0 errors**, including:

- `NativeAdrenoService.cpp` with `NATIVE_ADRENO_HAVE_GMU_RULES=1`,
  `NATIVE_ADRENO_HAVE_GMU_VOTES=1`, and `NATIVE_ADRENO_HAVE_COMMAND_DB=1` enabled;
- the exact `build-adreno740-kits.py` archive membership (`ShengGmu.c`,
  `ShengGmuCommandDb.c`, `ShengGmuVotes.c`, `AdrenoFirmware`, `ArmSmmu4K`,
  `AdrenoPM4`, and all `NativeAdreno*.cpp` excluding `NativeAdrenoClient.cpp`);
- `ShengGpuSmmu.c` compiled separately (note: `build-adreno740-kits.py` omits
  `ShengGpuSmmu.c` from `libAdreno740.a`; r2 measures both without and with it);
- staged `NativeAdrenoAccelerator.cpp` (`__DATA,__mod_init_func` removed and
  `__GLOBAL__sub_I_NativeAdrenoAccelerator.cpp` globalized via `llvm-objcopy`) plus
  `bti c; b *.original` stubs and collection addresses against
  `scripts/data/ioaccelerator-base-abi-26C5035r.json`;
- strong firmware symbols in `__DATA_CONST,__const` (4 KiB aligned + 8-byte size symbols)
  for both pinned sheng blobs (159,552 B) and pinned A730 blobs (146,784 B).

### 1.3 Real `ld64` standalone link findings against frozen A7

Linking the full archive into A7's exact `.LDFLAGS` + `link.filelist` + `version.o` +
`lastkernelconstructor.o` + `lastkerneldataconst.o` + `linkarchives` first reproduced A7's
baseline standalone Mach-O with **0-byte delta across every segment**
(`__TEXT 0x1cc000`, `__DATA_CONST 0x140000`, `__TEXT_EXEC 0x9a8000`, `__DATA 0x27c000`,
`__LASTDATA_CONST 0x4000`, `first_const_vma 0xfffffff007005fe0`).

Unmodified linking of the full closure revealed **two concrete link-integration defects**
that were invisible in per-object measurements:

1. **Three `__attribute__((weak_import))` board hooks rejected by `ld64 -static -kernel`**:
   - `_boot_log_export_put` (`NativeAdrenoPublish.cpp:73`)
   - `_native_gpu_dcvs` (`volatile uint32_t[15]`, `NativeAdrenoSubmit.cpp:77`)
   - `_native_pmap_user_mappings` (`NativeAdrenoMemory.cpp:354`)
2. **Four duplicate symbols against frozen A7's `libNativeLegacyDisplay.late.a(LegacyDisplaySupport27.o)`**:
   - `_native_adreno_fences`, `_native_adreno_fences_detail`, `_native_gpu_trace_record`,
     `_native_gpu_trace_enabled`
   - **Source-verified:** `out/liuqin-r101-a7-work/device-a/scripts/build-liuqin-legacy-display.py:345-348`
     emits strong non-Adreno stubs for these four symbols. Any future Adreno-enabled liuqin
     kernel must drop or weaken those stubs in the legacy display support object.

To measure exact aligned linked placement without altering A7, `build-and-link-closure.py`
linked isolated `/tmp` binaries using a measurement-only 3-symbol stub object
(`volatile uint32_t native_gpu_dcvs[15]` + 2 trivial functions) and a `/tmp` copy of
`libNativeLegacyDisplay.late.a` with only the four colliding symbols weakened:

| Linked standalone variant | `__TEXT` (slack / cap `0x1d8000`) | `__DATA_CONST` (`Δ` vs A7) | `__TEXT_EXEC` (`Δ` vs A7) | `__DATA` (slack / cap `0x284000`) | First `__TEXT,__const` VMA (margin vs `0xfffffff007005900`) | `const_tail` -> AppleARMPlatform | `KLD` -> `__DATA` | `Layout.validate()` |
| --- | --- | --- | --- | --- | --- | ---: | ---: | --- |
| A7 baseline repro | `0x1cc000` (49,152 B) | `0x140000` (0) | `0x9a8000` (0) | `0x27c000` (32,768 B) | `0xfffffff007005fe0` (1,760 B) | 567,912 B | 6,127,616 B | PASS |
| Full sheng closure (A740 blobs) | `0x1cc000` (49,152 B) | `0x16c000` (+180,224 B) | `0x9d4000` (+180,224 B) | `0x280000` (16,384 B) | `0xfffffff007005a80` (**384 B**) | 387,688 B | 5,947,392 B | PASS |
| Full closure (A730 blobs) | `0x1cc000` (49,152 B) | `0x168000` (+163,840 B) | `0x9d4000` (+180,224 B) | `0x280000` (16,384 B) | `0xfffffff007005a80` (**384 B**) | 404,072 B | 5,947,392 B | PASS |
| Full closure (A730 blobs + `ShengGpuSmmu.c`) | `0x1cc000` (49,152 B) | `0x168000` (+163,840 B) | `0x9d4000` (+180,224 B) | `0x280000` (16,384 B) | `0xfffffff007005a80` (**384 B**) | 404,072 B | 5,947,392 B | PASS |

### 1.4 Full `emit_prelink.py` + `aes_fileset_gate.py` dry-run verification

**Host-measured (`prelink-and-aes-gate.json`, `aes-fileset-gate-a730blobs-plus-smmu.json`):**
running `kits/XnuPrelink/emit_prelink.py` on the `a730blobs_plus_smmu` standalone link
against pinned 26C5035r `kernelcache.decompressed` (85-entry A7 closure, `/tmp` scratch
deleted immediately after verification, no boot image emitted) passed every prelink and
ABI gate:

- `emit_prelink.py`: exit 0, `3430 functions, 287 data of 3856 kext-facing targets; 0 conflicts; unresolved closure references: 0; stubbed functions: 0`, emitted size 142,573,568 B (`sha256 ca76d1f8...379bed6`).
- `aes_fileset_gate.py`: exit 0 (`PASS: 22 bindings, 8 transfers, 8 inherited pointers, 285 vtable slots, delta 0x45c8000`).
- Emitted native header gap: **640 B** (`header_end 0x199800`, `first_backed_section 0x199a80`); root header slack: **26,024 B**.
- `AGXAccelerator` original-binding stubs retargeted cleanly in emitted kernel:
  - `__ZN13IOAcceleratorC2EPK11OSMetaClass` at `0xfffffff00c2bd064`: `bti c` (`0xd503245f`) + `b 0xfffffff00aae62e0` (exact match).
  - `__ZN13IOAcceleratorD2Ev` at `0xfffffff00c2bd06c`: `bti c` (`0xd503245f`) + `b 0xfffffff00aae6350` (exact match).
- All three embedded A730 firmware blobs (`_native_adreno_firmware_image` at `0xfffffff007ea4000`,
  `_native_adreno_sqe_firmware_image` at `0xfffffff007eb2000`, `_native_adreno_zap_image` at
  `0xfffffff007ec5000`) are 4 KiB aligned, inside `__DATA_CONST` (`initprot=1`, `maxprot=1`,
  read-only), and byte-for-byte SHA256-identical to the pinned A730 blobs.

**Critical layout warning:** adding the KMD closure drops standalone `first_const_vma`
margin from **1,760 B to 384 B** and `__DATA` policy slack from **32,768 B to 16,384 B**.
Adding SM8475 board power/clock/probe code on top of A7 without Tier-1 observer retirement
risks breaching `MIN_TEXT_CONST_VMA` or `DATA_CAP`. Furthermore, static link fit does **not**
prove runtime RAM headroom (A7 sampled 15.63 MiB minimum free RAM under WindowServer churn).

---

## 2. Pinned 26C5035r userspace ObjC ABI, wire ABI, and plugin audit

Typed Objective-C headers were extracted from the verified 26C5035r dyld shared cache via
`ipsw class-dump --class '.*'` for `IOGPU.framework` (47 classes), `Metal.framework`
(430 classes), `Metal.protocols.h`, and `QuartzCore`'s `CAWindowServerDisplay`.

### 2.1 `IOGPUMetalDeviceShim.h` explicit `MethodSpec` audit (`typed-objc-abi-audit.json`)

Of 39 explicit `MethodSpec` entries in `drivers/AdrenoMetal/IOGPUMetalDeviceShim.h`:

- **31 match** the pinned 26C5035r `IOGPU`/`Metal` class hierarchy in return and argument classes.
- **2 have concrete type-encoding mismatches** against 26C5035r:
  1. `-[IOGPUMetalDevice cmdBufArgsSize]`: target is `- (unsigned int)cmdBufArgsSize;` (`u32`, `I16@0:8`); shim declares `"Q16@0:8"` (`uint64_t`).
  2. `-[IOGPUMetalCommandQueue setGPUPriority:offset:]`: target is `- (_Bool)setGPUPriority:(unsigned long long)gpupriority offset:(unsigned short)offset;` (`u64, u16`); shim declares `"B32@0:8Q16Q24"` (`u64, u64`).
- **6 device selectors are absent from `IOGPUMetalDevice`/`_MTLDevice` in 26C5035r**:
  `kickCleanupQueue` and `updateResourcePoolPurgeability` (present on `MTLIOAccelDevice`,
  not `IOGPUMetalDevice`), plus `periodicUpdateResourcePoolPurgeability`,
  `cancelPeriodicUpdateResourcePoolPurgeability`, `gpuCoreCount`, and `featureProfile`
  (MPS/compiler private SPIs; harmless as added methods, not verified against MPSCore binary callers).

### 2.2 Exhaustive `resolveStub()` ARM64 AAPCS hazard catalog (`typed-objc-abi-audit.json`)

Because `resolveStub()` calls `class_getInstanceMethod(reference, selector)` (walking the
entire `IOGPUMetal*` -> `_MTL*` superclass chain) and binds `uint64_t stub(id, SEL) { return 0; }`,
auditing all 12 mapped `IOGPUMetal*` classes against `NativeBridgeMetalFrontend.mm` and
`IOGPUMetalDeviceShim.h` yields **exact ARM64 AAPCS return-ABI hazards**:

| Frontend class(es) | Selector | Defining class in 26C5035r | Target return type | ARM64 AAPCS hazard if hit |
| --- | --- | --- | --- | --- |
| `NBBuffer`, `NBTexture` | `minLOD` | `_MTLResource` | `float` | Returned in **`s0`**; `uint64_t(0)` writes `x0` and leaves `s0` garbage |
| `NBBuffer`, `NBTexture` | `compressionMetadata` | `_MTLResource` | `struct MTL4BufferRange { uint64_t x0; uint64_t x1; }` (16 B) | Returned in **`x0` + `x1`**; `uint64_t(0)` leaves `x1` garbage |
| `NBTexture` | `gpuResourceID` | `IOGPUMetalTexture` | `struct MTLResourceID { uint64_t x0; }` (8 B) | Single-word struct (fits `x0`, but struct-typed in ObjC encoding) |

No other unimplemented selector across the 12 mapped `IOGPUMetal*` -> `_MTL*` chains returns
a floating-point or aggregate struct type. (Numerous object/pointer-returning selectors return
`nil`/`NULL`, which remain semantic caller-tolerance risks.)

### 2.3 Protocol conformances, `QuartzCore` hooks, and Turnip wire ABI v2

- **Protocols (`shared-cache-protocols-and-ca.json`):** all **19** protocols referenced by
  `class_addProtocol` in `IOGPUMetalDeviceShim.h` exist in the pinned 26C5035r dyld shared
  cache protocol table. However, **5** (`MTLCommandQueue`, `MTLComputeCommandEncoder`,
  `MTLRenderCommandEncoder`, `MTLBlitCommandEncoder`, `MTLHeap`) are **not** defined by
  `Metal.framework` or `IOGPU.framework` themselves — they come from Apple's `AGXMetal*`,
  `MetalTools`, `CoreComposite`, `MPSCore`, `CoreML`, etc. Relying on `objc_getProtocol()`
  without referencing `@protocol(...)` should be verified in target processes.
- **`QuartzCore` swizzle targets:** pinned 26C5035r exports `_CASetDebugOption` at
  `0x18e19a4b4` and `CAWindowServerDisplay` implements `- (double)nextWakeupTime;` and
  `- (void)beginExternalUpdate:(void *)update usingSoftwareRenderer:(_Bool)renderer;`
  (note `NativeAdrenoMetalPlugin.mm:680` casts the `void`-returning original IMP as returning
  `uint64_t`).
- **Custom wire ABI v2 & Turnip KMD (`wire-and-turnip-abi.json`):** all 18 method IDs
  (`NativeAdrenoAbiVersion = 2`) and 16 `static_assert` struct layouts align between
  `NativeAdrenoABI.h`, `NativeAdrenoUserClient.cpp`, `NativeAdrenoPublish.cpp`, and
  `patches/mesa/turnip-darwin-kmd.patch`. Two macOS/A730 integration details were flagged:
  1. `turnip-darwin-kmd.patch:455` defaults `service_name` to `"IOAcceleratorES"` unless
     `TU_DARWIN_SERVICE` is set; `NativeAdrenoMetalPlugin.mm:331` sets
     `TU_DARWIN_SERVICE=AGXAccelerator`, whereas standalone helpers
     (`NativeAdrenoProbeDaemon.cpp:23`, `NativeTurnipSmoke.h:434`) still default to
     `"IOAcceleratorES"`.
  2. `turnip-darwin-kmd.patch:1859-1862` reads `highest_bank_bit`, `ubwc_swizzle`, and
     `macrotile_mode` from `NativeAdrenoAbiDeviceInfo`, so an A730 KMD must populate A730's
     real UBWC/GMEM parameters (`0x07030001`, 2 MiB GMEM, `highest_bank_bit=16`) rather than
     borrowing A740 values.

---

## 3. Frozen A7 trust & `/Library/GPUBundles` reachability proof

**Host-measured & source-verified (`a7-trust-and-bundle-reachability.json`):** inspecting
frozen A7's `nm.txt`, `unixnu.toml`, `.config`, and `kern_exec.c`:

- **Active in A7:** `native_sandbox_grant` (`__ZL20native_sandbox_grantP9IOService`) IS
  compiled into A7 at `0xfffffff00c1c0b30` and wired into `is_io_service_open_extended` and
  `is_io_registry_entry_set_properties`.
- **NOT compiled into A7:** `native_owner_macos_gpu_addon`, `native_gpu_addon_install`,
  `native_gpu_bundle_protect`, `native_gpu_bundle_protect_one`, and
  `native_owner_macos_data_prepare` have **zero symbols** in A7 `nm.txt` because they are
  guarded by `#if defined(XNU_OWNER_DATA_MOUNT) && XNU_OWNER_DATA_MOUNT` (`kern_exec.c:8587`),
  which is unset in liuqin's `.config` (liuqin mounts Data via `liuqin_scratch_probe` and
  its `r68-r71` Data patches).
- **Missing handoff provider:** `native_gpu_addon_install` depends on weak symbol
  `native_ram_block_gpu_addon` (`kern_exec.c:8672`), defined only in `drivers/RamBlock/NativeRamBlock.cpp:669`;
  `CONFIG_XNU_NATIVE_RAM_BLOCK` is disabled in liuqin, so the symbol is absent from A7.
- **Boot-arg ceiling:** frozen A7 `unixnu.toml` `args` is **999 bytes** (1 byte below the
  1,000-byte limit); appending ` gpu-addon=1` (12 bytes) overflows and is disallowed.

Therefore, **sheng's `gpu-addon=1` `/Library/GPUBundles` + `com.apple.rootless` +
`SF_RESTRICTED` staging path is NOT reachable in A7**. A future liuqin graphics design must
explicitly wire `/Library/GPUBundles` rootless protection and plugin staging into liuqin's
Data path without relying on `gpu-addon=1` boot args or `RamBlock`, alongside an ad-hoc
4 KiB-page CDHash trust module (still requiring no `owner.key` access).

---

## 4. Concrete Linux-host blockers for closing the remaining userspace ABI gate

**Host-measured (`userspace-build-blockers.json`):** closing the remaining macOS 27.3
(`26C5035r`) arm64e userspace build, import, PAC (`rust-pac-rewrite.py`), 4 KiB-page
`codesign`/CDHash, and runtime ABI checks is concretely blocked on this Linux host by:

1. **Missing Apple macOS 27 (`26C5035r`) userspace SDK:**
   `/opt/unixnu-linux/CommandLineTools/SDKs/MacOSX.sdk` contains `usr/include` only (cctools
   host headers). `Foundation`, `Metal`, `IOSurface`, `IOKit`, `CoreGraphics`, `QuartzCore`,
   `PrivateFrameworks/IOGPU.tbd`, and Darwin `libSystem`/`libobjc` TBDs are absent.
2. **Missing real Darwin `codesign`:** `scripts/linux/codesign` is an `exit 0` no-op shim
   for XNU SETUP host tools and cannot emit 4 KiB-page ad-hoc Mach-O code signatures/CDHashes.
3. **Missing Rust `1.98.0` + `rust-src` for `arm64e-apple-darwin`:** host `rustup` only has
   `stable`, `1.81.0`, and `1.96.0` for `x86_64-unknown-linux-gnu`; `build-adreno-metal-bridge.py`
   requires `cargo +1.98.0 -Z build-std=std,panic_unwind --target arm64e-apple-darwin`.
4. **Missing `glslangValidator`** (required by `build-turnip-darwin.py`).
5. **Missing local checkouts** of pinned Mesa (`85fda3b36405bcaea8bffc64aa4f2651dc90770d`)
   and `metal2vulkan` (`963f0e64f103d2e682cd0cc454a8fe50f52c8cbb`); patches exist locally
   (17 Mesa patches, 27 bridge patches), but cloning/building must target `/media/disk_4`
   (122 GiB free) or a macOS build host, **never `/home`** (~2.3 GiB free).

## 5. Summary of holds and next decision boundary

- **Holds preserved:** A730/XNU driver edits, graphics hardware boots, display/input deep
  extraction, flashing/partition writes, and `owner.key` / real-key signing remain held.
- **What is now proven on host:** the full reference KMD + staged `AGXAccelerator` +
  read-only A730 firmware closure compiles cleanly with `-Werror`, links against A7, passes
  `Layout.validate()`, `emit_prelink.py`, `aes_fileset_gate.py`, and exact `IOAccelerator`
  branch-retargeting checks — with two concrete integration items to clean up (3 weak-import
  board hooks, 4 A7 legacy-display duplicate stubs) and two tight margins to watch (**384 B**
  const-VMA margin, **16 KiB** `__DATA` slack).
- **What requires owner decision / external input next:**
  1. Review r1 + r2 host-gate reports and decide whether to supply a macOS build host/runner
     (or Apple macOS 27 SDK + cross-build tools on `/media/disk_4`) to close the userspace
     Turnip/metal2vulkan/plugin build gate before lifting holds, **or**
  2. Explicitly authorize implementing the reviewed strictly read-only platform-input
     discovery probe (`liuqin-r101-platform-discovery-plan.md`) — taking into account A7's
     tight 1,760 B const-VMA / 384 B post-KMD margin and optional Tier-1 observer retirement.
