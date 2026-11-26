# Liuqin r103 input and persistent Data

Resumed from Antigravity session `4a72f19e-7e62-4781-b6fa-f0da88c7bb3f`.
The baseline desktop milestone was already committed as `797da65`.

## Behavior

- USB debugging is enabled by default (`liuqin_usb=1`) for host verification.
  `--no-usb-debug` disables the gadget and mutes the console mirror; the boot
  runner then requires `--stay-up` because a USB reboot is unavailable.
- The desktop kernel's framebuffer row helper returns NULL, suppressing
  matrix, status and debug painters throughout boot. The USB console mirror
  remains enabled unless `--no-usb-debug` is explicitly selected.
- `liuqin-input=1` registers the source-built HID device after IOHIDFamily
  loads, then starts the Liuqin keyboard and touch workers.
- The cover uses I2C13 at `0xa94000`, address `0x4c`, 100 kHz; GPIO50 is
  data-ready, GPIO83 reset, GPIO42 wake, GPIO62 power, GPIO46 status.
  The bridge runs its onboard firmware. Its fixed 68-byte packets can contain
  multiple reports. Keyboard, consumer and mouse reports are decoded;
  touchpad reports become relative pointer and two-finger scroll reports.
- Touch uses SPI4 at `0x990000`, QUP wrapper `0x9c0000`, 9.6 MHz, CS0,
  GPIO16..19 and IRQ GPIO21. The NT36532 CSOT firmware uses ordinary contact
  reports. The first contact becomes an absolute pointer and click, with
  the inverse of the landscape display transform. Pen and native macOS
  multitouch gestures are not implemented.
- Both input workers share TLMM's SPI 208. The keyboard uses FIFO mode.
  Touch uses SE DMA when firmware disables its FIFO, with contiguous buffers,
  explicit cache maintenance and apps-SMMU stream `0x5a3`.

## Persistent Data

`--persistent-data init` adds `liuqin-data=2`. The kernel parses the existing
GPT and SHNGROOT manifest, keeps a 128 MiB gap after the root image, reserves
a metadata area, and uses the remaining userdata space except the last 64 MiB
for Data. For the live userdata layout observed over USB, Data starts at
partition-relative byte `17670602752`, with capacity `213964931072` bytes,
approximately 199.27 GiB.
The actual allocation is calculated from the device's GPT at boot.

Initialization requires an empty metadata block or a matching incomplete
`LQDATA03` record. Unknown or corrupt records are refused. A completed record
is reused without erasing Data, including when booted with mode 2 again.
`--persistent-data reuse` selects mode 1, which requires an existing completed
record. Mode 0 or no argument retains the original RAM fixture.

`--persistent-data format` selects mode 3 for the first installation in this
allocated extent when its metadata block contains older non-Data content.
It can replace that content, but reuses an existing completed Data record.
It still refuses a corrupt or mismatched `LQDATA03` record. The live tablet
had pre-existing JSON and HTML bytes in candidate locations, so its first
installation uses this explicit format mode; later builds can use `reuse`.

First initialization materializes the 512 MiB APFS seed on UFS, flushes it,
reads the entire seed back and checks its logical SHA-256 before committing
its metadata record. The block device advertises the full Data extent.
`local.unixnu.liuqin.data-grow` runs Apple's diskutil on-device to expand the
APFS container from its seed size. A failed growth is retried; success writes
`/private/var/db/.liuqin-data-grown`. On the tablet, diskutil exited successfully and the container reached
52237532 blocks of 4096 bytes, or 213964931072 bytes. The kernel does not modify the GPT or
OS/SystemOS/App windows. Persistent Data writes are real flash writes.

A second marker, `/private/var/db/.liuqin-seeded`, avoids repeating template
population and replacing the account/preferences on subsequent boots.
Cache flushes issue SCSI SYNCHRONIZE CACHE. Data uses bounded READ/WRITE(10)
requests and a shared transport mutex. Sub-4K writes preserve adjacent bytes.
UNMAP is not advertised for persistent Data. A timed-out write stops further
commands from reusing the outstanding descriptor.

## Sources

Hardware and Linux protocol references:
`/media/disk_4/xiaomi_pad_pro6_linux_workspace/linux-sm8450-liuqin`:
`arch/arm64/boot/dts/qcom/sm8475-xiaomi-liuqin.dts`, `sm8450.dtsi`,
`drivers/clk/qcom/gcc-sm8450.c`, `drivers/pinctrl/qcom/pinctrl-sm8450.c`,
`drivers/hid/hid-nanosic.c`, and `drivers/input/touchscreen/nt36523/`.
Firmware is the workspace's `novatek_nt36532_m81_fw_csot.bin`.

The keyboard HID device and codecs derive from UniXNU-sheng's BSD licensed
`KeyboardCover.cpp`, `Wn8030.c/.h` and `GeniI2c.c/.h`. Liuqin's geometry and
transport are local adaptations. The generic SPI implementation is QcomGeniSpi.
The Novatek protocol comes from ShengNovatekTouch commit
`4d6133c374c4980a1fa82879ad25b5ef2ae47896`. Public IOHIDFamily headers are pinned
to `e31e90a24c27ad6cbe981650d12a1a4124065b03`.
Both external checkouts live in
`/media/disk_4/unixnu_workspace/liuqin-input-sources/`.

The HID builder checks the kernelcache hash, base instance size, all 334 vtable
slots, inherited IOService identities and PAC diversities. It applies the
same narrowly checked class/metaclass Dispatch projection as A7's Ethernet
builder before stripping the deferred class initializer.

## Build and verification

From the UniXNU checkout:

```sh
python3 scripts/liuqin-analysis/r103-storage/check-transport.py
python3 scripts/liuqin-analysis/r103-storage/check-scsi.py
python3 scripts/liuqin-analysis/r103-storage/check-grow.py
python3 scripts/liuqin-analysis/r103-storage/check-probe.py
python3 scripts/liuqin-analysis/r102-gpu/prepare-and-build-gpu.py \
  --with-input --persistent-data reuse \
  --gpu-addon /media/disk_4/unixnu_workspace/macos27-cross/build/adreno-metal-plugin-macos27/kernel.macho.gpuaddon \
  --trust-json /media/disk_4/unixnu_workspace/macos27-cross/build/adreno-metal-plugin-macos27/trust.json
```

`--build-only` rebuilds the existing isolated device. A fresh build regenerates
it from frozen A7 inputs. `--repack-only` updates only the existing payload;
its input/storage switches must match the compiled kernel. The boot arguments
remain below the 1023-byte limit. Large outputs remain on disk_4.

Evidence: `/media/disk_4/unixnu_workspace/r102-gpu/`:
`build-r103-usb-debug.log`, `evidence/validation-summary.json`,
`evidence/aes-fileset-gate.json`, `evidence/boot.img`.
The HID ABI report is in
`out/liuqin/macos-27.3-26C5035r/liuqin/tree/build/liuqin-input/build-report.json`.

Host checks cover allocation bounds, partial-block preservation, request
encoding and DMA directions, SCSI errors, corrupt metadata, seed identity,
reopen behavior and the growth job's retry/name checks. The generated signed
helper installer is also exercised under ASAN/UBSAN: first creation, reuse
without writes, hash/size/ownership/permissions checks, mount/type rejection,
and the original nonpersistent EEXIST behavior. These use simulated hardware;
recorded tablet results follow below.

Boot and capture with the existing volatile runner:

```sh
python3 scripts/liuqin-analysis/r102-gpu/run-gpu-boot.py --desktop --duration 240 --stay-up
```

This sends `fastboot boot`; the persistent kernel can initialize its allocated
Data region during boot. The USB console supports capture and reboot commands.
On-device validation should check input, `df -h
/System/Volumes/Data`, the growth log and a file surviving reboot. A successful
fastboot command alone does not establish that macOS reached the desktop.

## Recorded hardware results

The 2026-11-23 `boot-gpu-20261123-004054/usb.log` capture records a
verified persistent seed, a read/write Data mount, successful diskutil growth,
and an APFS container of 52237532 blocks. The user confirmed the desktop
appeared and the touchscreen worked; the cover keyboard did not respond.
Touchpad operation is unconfirmed.

`boot-gpu-20261123-004949/usb.log` records `existing=1 state=2 mode=1`,
`state=reuse`, the same expanded APFS size, and skipped template/account
seeding. This proves that the completed store, expanded container and marker
survived reboot. That boot stopped at `LIUQIN USER PREPARE: err=17` because
the signed helper installer used exclusive creation on the persistent file.
The generated patch now reopens existing helpers only for persistent Data,
without rewriting them, and verifies their mount, type, size, SHA-256, root
ownership and 0755 permissions before accepting them.

The cover's initial I2C read timed out while the serial engine's status output
was disabled. The latest image enables `GENI_SE_M_IRQ_EN` while retaining
polling with the GIC serial-engine interrupt masked. This keyboard fix and the
helper reuse fix passed the kernel layout and AES gates in
`build-r103-reuse-helper.log`. Image SHA-256:
`eafe68fcc5c66bedeb70b35a6b50795a1d8575b9d5d1d3c567426113cca4c78c`.
The `boot-gpu-20261123-212527` capture verified the helper fix on hardware:
`USER PREPARE` and `ADAPTER PREPARE` both returned zero, and the user confirmed
the desktop appeared with reused Data. The keyboard still timed out with no
status; enabling master IRQ output alone was insufficient. The user reported
that all input was unresponsive, including touch, which worked in the earlier
boot. The USB debug port was absent after capture. This boot therefore does
not qualify the split HID device change. The next diagnostic build adds
Linux's GENI clock/output initialization and touch IRQ/HID counters.
Its build log is `build-r103-engine-init.log`. Use `--persistent-data reuse` for subsequent
boots of this tablet. USB debugging remains enabled and framebuffer debug
painting remains disabled.

`boot-gpu-20261123-213137` tested the Linux engine initialization. The
signed helper and adapter again prepared successfully. The user confirmed
that touchscreen operation returned; its counters recorded 164 frames and
164 accepted HID reports with no errors. USB reboot to fastboot worked after
capture. The cover still produced no IRQ, and the I2C write stalled waiting
for completion (`status=41`, `m=0`, `io=0`, `sw=2`). The following build adds
local TLMM ownership on eGPIO-capable pads, matching Linux's
`msm_pinmux_set_mux`, and logs pad configuration and I/O state. Evidence is
`build-r103-pad-ownership.log`.

## Performance, 120/144 Hz Display, Thermal Fix, Bluetooth & Wi-Fi (r103-wireless)

Subsequent hardware-verified iterations on the same macOS 27.3 (`26C5035r`)
persistent-Data desktop baseline (`--persistent-data reuse --with-input --with-wireless`)
added:

- **Performance & display**: GPU Write-Combining (`wc=1`), GPU DCVS scaling
  (`dcvs=1` idle), DPU hardware double-buffering (`DPU_DB ready pipes=2`,
  `frame_us=8349`), 120 Hz default with 144 Hz / 60 Hz display modes
  (`vsync=120`, `setDigitalOutMode` verified across 120/144/60 Hz), and daily
  hardware helpers (display backlight, volume/power buttons, and Hall cover
  sensor).
- **Idle CPU / thermal fix**: Root-caused post-desktop heat to background
  launchd/daemon churn; mitigated via `no-lc=1`, daemon denylist
  (`deny-exec=...`), and `/private/var/db/com.apple.xpc.launchd/disabled.501.plist`.
- **WCN6855 Bluetooth** (`scripts/liuqin-analysis/r103-wireless/`): Shared
  `LiuqinWcnPower` PMU/RPMh rail manager + GENI UART20 (`0x00894000`, 3.2 Mbps,
  Apps SMMU bypass SID `0x483`) + mainline `btqca.c` + `/dev/cu.BLTH` +
  cross-compiled/4K-signed macOS 27.3 `bluetoothd`, `BlueTool`,
  `QcaBTType0.dylib`, and 114 WCN6855 BT firmware files (`hpbtfw21.tlv`,
  `hpnv21.bin`) packed into `kernel.macho.gpuaddon`.
- **WCN6855 Wi-Fi** (`scripts/liuqin-analysis/r103-wireless/`): SM8475 PCIe0 RC
  + QMP V6 Gen3x1 PHY + BDF->SID hash (`0x100 -> 0x1c01`) + 128 MiB Apps SMMU
  Stage-1 DMA window (`cb73`, `iova=0x20000000..0x27ffffff`) + DesignWare iMSI
  (SPI 141) + MHI/QMI + Linux `v7.0.14` `ath11k` / `mac80211` / `cfg80211`
  (stock `dp.h` ring sizes; `reg.c` `channel_update_work` waits only on
  `ATH11K_11D_RUNNING` so `add_interface` does not stall the cooperative
  dispatcher) + `en0` bridge (`LiuqinWifiNet.cpp`) + `org.unixnu.wifi.control`
  + cross-compiled/4K-signed `unixnu-wpa_supplicant` and `wpa_cli` + WCN6855
  Wi-Fi firmware (`amss.bin`, `board-2.bin`, `m3.bin`, `regdb.bin`).

Build command with combined GPU + Bluetooth + Wi-Fi addon:

```sh
python3 scripts/liuqin-analysis/r103-wireless/build-bluetooth-userland-linux.py
python3 scripts/liuqin-analysis/r102-gpu/prepare-and-build-gpu.py \
  --persistent-data reuse --with-input --with-wireless \
  --gpu-addon /media/disk_4/unixnu_workspace/macos27-cross/build/bluetooth-macos27/kernel.macho.gpuaddon \
  --trust-json /media/disk_4/unixnu_workspace/macos27-cross/build/bluetooth-macos27/trust.json
```

Clean verification capture (`boot-gpu-20261125-012843`, `--desktop --duration 75 --stay-up`,
`boot_sha256=c51b19d95c21a8eb772eacb74ac99dfaefa6b4587c6955da25a61563c7699bbc`,
`kernel_sha256=5f2e7f2d1bb47476d43f2213a151b1040a9bf7db5f7a78a98bf748baf06b67fb`,
`__TEXT=0x1d0000`, `__DATA=0x280000`, `__TEXT,__const=0xfffffff007006280`,
`aes_gate=PASS`):

- `ADDON files=132 written=132 failed=0 err=0 prot=6 prot_err=0`
- `DPU_DB ready pipes=2 ... frame_us=8349 hw_hz=120`; GPU `sub=256 ret=256 hang=0/0 dcvs=1/28/4% wc=1`
- `TOUCH ready spi=0x990000 irq=21` (`extent=18000x28800 ver=25`)
- `BT BOOT err=0 state=2 baud=3200000 ... fw=[BTFW.HSP.2.1.0-00570-PATCHZ-1]`;
  `BT TTY active=1`; `BT STAT pwr=1 svc=1 baud=3200000 tx=157358 rx=1521 host=864 deliv=1140 wake=2/0/17 irq=884`
- `WIFI_PCIE phy ready=1`, `link up=1 ms=12 lnksta=0xb0130008 ltssm=0x111`,
  `ep id=0x110317cb subsys=0x010817cb`, `WIFI_SMMU ok bank=73 slot=2 asid=73 iova=0x20000000 sz=0x8000000`
- `WIFI_READY mac=d2:fa:11:a5:c8:71 chans=102`, `wifi-net: attached to en0 ... ifnet=ready`,
  `WIFI_CTL connected session=1 unit=1`
- Live over-the-air AP scan: `wifi-net: scan done (19 APs)` (`25 APs` across 2.4 GHz
  and 5 GHz in `boot-gpu-20261125-012145`), `WIFI_STAT stage=4 scans=1 bss=19 msi=924(bits=0xc007c) dma=57944/131072K ctl(sess=1 rx=30 tx=35)`
- Note: Over-the-air WPA2-PSK association / DHCP throughput via `wpa_cli` has not yet been tested end-to-end on hardware.
