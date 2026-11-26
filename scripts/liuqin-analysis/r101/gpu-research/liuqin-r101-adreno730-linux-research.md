# Adreno 730: local Linux implementation and UniXNU adaptation

Date: 2026-11-21. Host-only research; no candidate build or device operation.
External workspace: `/media/disk_4/xiaomi_pad_pro6_linux_workspace`.
Labels: **source-verified**, **host-measured**, **reported**, **inference**, **(verify)**.

## Finding

**Source-verified:** a substantive Adreno 730 kernel implementation is present
in `linux-sm8450-liuqin/drivers/gpu/drm/msm/adreno`. It includes GPU bring-up,
GMU firmware/HFI, command submission, interrupts, recovery and preemption.
The A730 implementation lives largely in files named **a6xx**, including
`a6xx_gpu.c`, `a6xx_gmu.c`, `a6xx_hfi.c`, `a6xx_preempt.c` and `a6xx_catalog.c`.
Looking only for an `a730.c` or `a7xx_gpu.c` would miss it.

**Reported:** the companion `xiaomipad-6pro-mainline/README.md:71` lists
Adreno 730 / Freedreno / Mesa desktop acceleration as working, with application
workarounds. Its Waydroid guide also reports hardware acceleration. These are
project claims, not a fresh GPU execution test performed in this research.

The useful next engineering task is an A730/SM8475 adaptation of existing
UniXNU GPU and Metal components. Linux acceleration supplies real hardware
reference code; it does not itself provide a macOS Metal device.

## Source identity and limits

- Local kernel HEAD: `e6ed309612463f1c891d58b0c357b79a8be640e8`.
- Companion HEAD: `0ea1508088ea83936c34a9a04ab1c02482e2a84a`.
- Companion `kernel/source.json` selects **a different kernel commit**:
  `fe81794b5e1b8a3f11a165f3acbfdb8fa671dbb3`, branch
  `release/v0.6.0-dp-fingerprint`, upstream base
  `a19585977c11fa662435b607cb9ff4ac7133092e`.

Do not equate the inspected checkout with the release-selected source or
assume either matches the reported accelerated run. A full kernel `git status`
encountered disk I/O errors in unrelated ARM DTS files and was stopped; clean
working-tree status is unverified. Selected readable inputs are hashed in the
research manifest. No exhaustive Mesa source inventory or runtime trace was
established; Turnip/A730 compiler support in the exact Darwin build remains a
separate verification item.

## Concrete implementation map

All Linux paths below are relative to `linux-sm8450-liuqin/`.

| Layer | Source | Verified content |
| --- | --- | --- |
| A730 identity | `drivers/gpu/drm/msm/adreno/a6xx_catalog.c:1370` | Chip `0x07030001`, `ADRENO_7XX_GEN1`, 2 MiB GMEM, cached-coherent/HW-APRIV/preemption quirks; A730 clock-gating and protection tables |
| CP and GPU | `drivers/gpu/drm/msm/adreno/a6xx_gpu.c` | `a7xx_submit` at 347, `a7xx_cp_init` at 832, `hw_init` at 1064, A7xx function table at 2444 |
| GMU | `drivers/gpu/drm/msm/adreno/a6xx_gmu.c:1055` | Runtime power, clock rates, bus quota, IRQ enable, cold/warm boot, firmware start and HFI startup |
| Firmware authentication | `drivers/gpu/drm/msm/adreno/adreno_gpu.c:30` | Device-specific ZAP filename, reserved-memory loading, `qcom_mdt_load`, `qcom_scm_pas_auth_and_reset` |
| Registers/packets | `drivers/gpu/drm/msm/registers/adreno/` | A6xx/A7xx register and packet XML; generation-specific differences must be respected |
| SoC resources | `arch/arm64/boot/dts/qcom/sm8450.dtsi` | GPU/GMU/GPUCC/SMMU resources, clocks, power domains and reserved ZAP memory |
| Board activation | `arch/arm64/boot/dts/qcom/sm8475-xiaomi-liuqin.dts:645` | GPU enabled; board-specific `qcom/sm8475/liuqin/a730_zap.mbn` |
| SM8475 differences | `arch/arm64/boot/dts/qcom/sm8475.dtsi` | SM8475 GPUCC compatible; its displayed alternative GPU OPP table is commented out, not active configuration |

**Source-verified:** resource anchors inherited by Liuqin include:

- GPU `0x03d00000`, length `0x40000`; CX memory `0x03d9e000`, length
  `0x1000`; CX debug `0x03d61000`, length `0x800`; GPU interrupt GIC SPI 300.
- GMU `0x03d6a000`/`0x35000`, RSCC `0x03d50000`/`0x10000`, GMU PDC
  `0x0b290000`/`0x10000`; HFI/GMU interrupts SPI 304/305.
- GPUCC `0x03d90000`; Adreno SMMU `0x03da0000`.
- GPU IOMMU specifiers `<0 0x400>` and `<1 0x400>`; GMU `<5 0x400>`.
  These are Linux binding inputs, not complete XNU context-bank programming.
- GMU uses CX/GX power domains, AOSS/QMP and seven named clocks. SMMU has its
  own clock/power dependencies. Linux enables `CONFIG_SM_GPUCC_8450=y`,
  `CONFIG_QCOM_LLCC=y`, and `CONFIG_DRM_MSM=y` in the board configuration.

The GMU resume code explicitly selects a 150 MHz hub rate for non-A740-family
devices versus 200 MHz for A740-family. This is one concrete reason not to
substitute A730 firmware into an unchanged A740 backend.

## Firmware already available

**Host-measured:** all three files exist under the companion's
`device/firmware/usr/lib/firmware` and their SHA256 hashes match its
`tools/build-liuqin-firmware-prep.sh:77` pins:

| Relative filename | SHA256 |
| --- | --- |
| `updates/qcom/a730_sqe.fw` | `e67d1829f57fc8326d806234b932dc3b78e28a9940df34c70752f17d5f38b7aa` |
| `updates/qcom/gmu_gen70000.bin` | `b2d3f0e2a98fd6259ab9ffef16df63265542e6cc9a970d53d476e823d432042a` |
| `qcom/sm8475/liuqin/a730_zap.mbn` | `36296b019753fbb2a4733450a2d0a94e307238227297a747d0ff2811364f5d5f` |

The catalog's fallback name `a730_zap.mdt` is overridden by the board DTS's
`.mbn` path. Preserve that board-specific identity. ZAP loading uses existing
signed firmware and secure-monitor services; this is distinct from owner-key
signing. No owner key was accessed. Do not treat manual SECVID fallback as a
validated Liuqin path: the driver explicitly warns of faults if the secure
configuration is wrong.

## Existing UniXNU code changes the scope

**Source-verified:** `docs/porting/gpu.md`, `components.toml`, and the local
`drivers/Adreno740` / `drivers/AdrenoMetal` READMEs document an existing path:

`Metal → AdrenoMetal → metal2vulkan → Turnip → Darwin KMD → GPU backend`.

The current backend is A740/SM8550, with `Sm8550Platform`, `AdrenoFirmware`,
`AdrenoPM4` and `ArmSmmu4K`. `NativeAdrenoService.cpp` uses board-specific
`SHENG_GMU_VOTES_CHIP_ID` and `NativeAdrenoPwrupList::buildA740`; this is not
a generic A730-ready service. The frontend README also identifies a macOS
IOGPUMetalDevice entry, so macOS integration has existing reference code.
That does not establish compatibility with pinned macOS 26C5035r.

**Inference:** reuse the transport, buffer/fence abstractions, frontend and
compiler infrastructure where their contracts match. Implement an explicit
A730 backend/profile and SM8475/Liuqin platform inputs. Do not enable the
A740 component by changing only a device ID or publish an empty accelerator.
Retain source license and authorship notices when deriving code.

## Next implementation milestones (not executed)

1. Pin a readable reference snapshot, resolve checkout/release mismatch, and
   compare A730 with A740: MMIO tables, GMEM, CP power-up/preemption records,
   GMU memory/HFI protocol, firmware, clocks, RPMh votes and secure loading.
   Verify the exact Darwin Turnip tree's A730 device/compiler and KMD support.
2. Define A730 component and SM8475 platform interfaces using existing
   `NativeAdrenoTransport`/VM/fence contracts. Host-test tables, firmware parsing,
   HFI encoding, packet sequences, failure cleanup and address ownership.
3. Qualify bounded hardware power/GMU/HFI/SMMU bring-up before CP submission.
   Then prove ring progress, fence completion, safe teardown and known-image
   readback independently of WindowServer. Each future hardware step needs a
   concrete design consistent with the current hold; none is proposed as a boot now.
4. Only after those gates, integrate the matching macOS Metal frontend,
   AIR→SPIR-V→NIR→IR3 pipeline, IOSurface and user-client ABI, trust/sandbox
   packaging, then test device discovery and real rendering. Display presentation
   remains a separate ownership/cache/fence problem from successful GPU rendering.

A full GPU backend is not assumed to fit A7's 48 KiB TEXT / 32 KiB DATA slack.
Link footprint and prelink placement require explicit measurement/design;
all segment, const-floor, header/payload and AES gates remain binding. Any
addon/signing requirement must be addressed separately without touching the
held real owner key.

A7 remains unchanged: nTWE=1/nTWI=0, identity Ethernet, 512 MiB Data,
`native_reader_validated=false`, EL0 TRAP caveat. No graphics boot, flash,
partition write, source-driver edit or candidate build occurred in this research.
