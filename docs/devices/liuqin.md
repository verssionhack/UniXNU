# Xiaomi Pad 6 Pro (liuqin)

Xiaomi Pad 6 Pro (liuqin) is a SM8475 device. The port below is an independent community project. The UniXNU organization does not maintain it.

| Repository | Maintainer |
| --- | --- |
| [UniXNU-liuqin](https://github.com/1696108518/UniXNU-liuqin) | [1696108518](https://github.com/1696108518) |
| [UniXNU-liuqin](https://github.com/boomoodxf/UniXNU-liuqin) | [boomoodxf](https://github.com/boomoodxf) |

## State

The repository has the board file, defconfig and a kernel USB debug port. The UEFI integration is the next step.

## Maintenance

The maintainer owns the repository and its release decisions. UniXNU documentation lists the port and its state; it does not take over maintenance.

## Local macOS bring-up

The local macOS 27.3 (26C5035r) experiment uses
`scripts/liuqin-analysis/r102-gpu/prepare-and-build-gpu.py`. Its landscape
desktop baseline is commit `797da65`. The r103 input sources add the Liuqin
WN8030 keyboard bridge, touchpad pointer reports and the NT36532 touchscreen
pointer. The keyboard uses QUP1 SE5 at `0xa94000`; touch uses QUP0 SE4 at
`0x990000`. Both share the TLMM summary interrupt. The input build checks
the shipped IOHIDDevice vtable and pointer authentication discriminators.

The optional persistent Data recipe uses the space after the authenticated
root image in userdata, leaving a 64 MiB tail reservation. It verifies the
initial APFS seed by reading it back, preserves populated Data on subsequent
boots, and installs an on-device APFS container growth job. USB debugging stays
enabled for host verification; kernel matrix/status painting is disabled. The
tablet reached the desktop and the user confirmed touchscreen operation.
APFS grew to 213964931072 bytes (199.27 GiB), and a subsequent boot reused
the completed Data store with the expanded container and seed marker intact.
The signed helper reuse fix subsequently booted to the desktop with
`USER PREPARE` and `ADAPTER PREPARE` both returning zero. In that later boot
the user reported that neither the cover nor touchscreen responded; USB
debug was also absent after capture. Enabling I2C master status generation
alone did not resolve its timeout. A further boot with Linux engine clock/output
initialization restored touchscreen operation: 164 frames reached HID without
errors, confirmed by the user. The cover still timed out and generated no
interrupts; touchpad operation remains unverified.

Subsequent `--with-input --with-wireless` builds added GPU Write-Combining,
GPU DCVS scaling, DPU double-buffering with 120/144/60 Hz display modes,
backlight/button/Hall helpers, desktop idle CPU/thermal mitigations (`no-lc=1`,
denylist, `disabled.501.plist`), WCN6855 Bluetooth (GENI UART20 at 3.2 Mbps
with macOS 27.3 `bluetoothd`/`BlueTool`/`QcaBTType0.dylib`), and WCN6855 Wi-Fi
(SM8475 PCIe0 RC + QMP V6 PHY + 128 MiB Apps SMMU `cb73` + MHI/QMI + Linux
`v7.0.14` `ath11k`/`mac80211`/`cfg80211` + `en0` + `unixnu-wpa_supplicant` +
`wpa_cli`). In clean capture `boot-gpu-20261125-012843` (`--stay-up`), both
radios ran simultaneously on the 120 Hz desktop (`BT STAT` active at 3.2 Mbps;
`WIFI_READY` 102 channels, `en0` attached, `unixnu-wpa_supplicant` connected,
live over-the-air scan finding 19 APs — 25 APs across 2.4/5 GHz in
`boot-gpu-20261125-012145`). Live WPA2 association/DHCP remains to be tested.
See `scripts/liuqin-analysis/r103-storage/README.md` for the recipe and
evidence paths.

## Sources

- [Board configuration: 1696108518/UniXNU-liuqin](https://github.com/1696108518/UniXNU-liuqin/blob/907b8e91c88e71f698292abfd8db49ba90492dc4/board.toml)
