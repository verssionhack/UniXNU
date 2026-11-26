#!/usr/bin/env python3
"""Build and sign macOS 27.3 Bluetooth userspace (bluetoothd, BlueTool, QcaBTType0.dylib)
on Linux and pack a combined NGPUADD2 addon (Metal GPU + Bluetooth + WCN6855 firmware).
"""
from __future__ import annotations

import hashlib
import json
import os
import plistlib
import re
import shlex
import shutil
import struct
import subprocess
import sys
import tarfile
import zlib
from pathlib import Path

ROOT = Path('/home/kurumin/github/UniXNU')
CROSS = Path('/media/disk_4/unixnu_workspace/macos27-cross')
CLANG = CROSS / 'bin/macos27-clang'
RCODESIGN = CROSS / 'bin/rcodesign'
QCA_BT = Path('/media/disk_4/unixnu_workspace/liuqin-bt-sources/QcaBluetooth')
EXTRACTED_BTD = Path('/media/disk_4/unixnu_workspace/liuqin-bt-sources/extracted/bluetoothd.arm64e')
ATH_WIFI = Path('/media/disk_4/unixnu_workspace/liuqin-wifi-sources/Ath12kWifi')
WIFI_FW = Path('/media/disk_4/unixnu_workspace/liuqin-wifi-sources/firmware/WCN6855/hw2.0')
GPU_PLUGIN_DIR = CROSS / 'build/adreno-metal-plugin-macos27'
OUT = CROSS / 'build/bluetooth-macos27'

STOCK_QCA_FW = Path('/media/disk_4/xiaomi_pad_pro6_linux_workspace/xiaomipad-6pro-mainline/device/firmware/usr/lib/firmware/qca')
LINUX_QCA_FW = Path('/home/kurumin/Codes/Github/linux-firmware/qca')


def run(cmd, **kw):
    print('+', ' '.join(str(x) for x in cmd), flush=True)
    return subprocess.run([str(x) for x in cmd], check=True, **kw)


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def extract_macho_entitlements(macho_path: Path) -> bytes:
    """Extract raw CSSLOT_ENTITLEMENTS XML plist bytes directly from Mach-O LC_CODE_SIGNATURE."""
    data = macho_path.read_bytes()
    magic, _, _, _, ncmds, _, _, _ = struct.unpack_from('<IIIIIIII', data, 0)
    assert magic == 0xfeedfacf, f'Not 64-bit Mach-O: {hex(magic)}'
    off = 32
    cs_off = cs_size = 0
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from('<II', data, off)
        if cmd == 0x1d:  # LC_CODE_SIGNATURE
            cs_off, cs_size = struct.unpack_from('<II', data, off + 8)
            break
        off += cmdsize
    assert cs_off and cs_size, 'No LC_CODE_SIGNATURE found'
    sb = data[cs_off:cs_off + cs_size]
    sb_magic, sb_len, sb_count = struct.unpack_from('>III', sb, 0)
    assert sb_magic == 0xfade0cc0, f'Bad superblob magic {hex(sb_magic)}'
    for i in range(sb_count):
        btype, boff = struct.unpack_from('>II', sb, 12 + i * 8)
        bmagic, blen = struct.unpack_from('>II', sb, boff)
        if bmagic == 0xfade7171:  # CSMAGIC_EMBEDDED_ENTITLEMENTS
            return sb[boff + 8:boff + blen]
    raise RuntimeError('No embedded entitlements blob found in Mach-O')


def parse_cdhash_and_check_4k(binary: Path) -> str:
    """Return 40-hex SHA-256 truncated CDHash and assert 4 KiB code signature page size."""
    out = subprocess.run(
        [str(RCODESIGN), 'extract', 'code-directory', str(binary)],
        check=True, capture_output=True, text=True,
    ).stdout
    m_ps = re.search(r'page_size:\s*(\d+)', out)
    assert m_ps and int(m_ps.group(1)) == 4096, f'{binary.name}: expected 4096-byte CS page_size, got:\n{out[:500]}'
    raw_cd = subprocess.run(
        [str(RCODESIGN), 'extract', 'code-directory-raw', str(binary)],
        check=True, capture_output=True,
    ).stdout
    return hashlib.sha256(raw_cd).hexdigest()[:40]


def pad8(data: bytes) -> bytes:
    return data + bytes(-len(data) % 8)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    build = OUT / 'build'
    sbin = OUT / 'sbin'
    lib = OUT / 'lib'
    fw_qca = OUT / 'firmware/qca'
    for d in (build, sbin, lib, fw_qca):
        d.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(QCA_BT / 'tools'))
    import native_macos27  # type: ignore

    assert EXTRACTED_BTD.is_file(), f'Missing {EXTRACTED_BTD}'
    assert sha256_file(EXTRACTED_BTD) == native_macos27.ORIGINAL_SHA256, 'bluetoothd.arm64e SHA-256 mismatch'

    # 1. Build & 4K ad-hoc sign BlueTool
    bluetool_bin = sbin / 'BlueTool'
    run([
        CLANG, '-O2', '-Wall', '-Wextra', '-Werror',
        '-fblocks', '-fstack-protector-strong',
        QCA_BT / 'userland/BlueTool.c', '-o', bluetool_bin,
    ])
    bt_ent = build / 'BlueTool.entitlements.plist'
    bt_ent.write_bytes(plistlib.dumps({'com.apple.private.security.no-container': True}, fmt=plistlib.FMT_XML))
    run([
        RCODESIGN, 'sign',
        '--binary-identifier', 'org.unixnu.bluetooth.BlueTool',
        '--entitlements-xml-file', bt_ent,
        bluetool_bin,
    ])
    bluetool_bin.chmod(0o755)
    bluetool_cdhash = parse_cdhash_and_check_4k(bluetool_bin)
    print(f'BlueTool CDHash: {bluetool_cdhash}', flush=True)

    # 2. Build & 4K ad-hoc sign QcaBTType0.dylib
    layout_hdr = build / 'qbt_macos27_layout.h'
    layout_hdr.write_text(native_macos27.layout_header())
    type0_bin = lib / 'QcaBTType0.dylib'
    run([
        CLANG, '-dynamiclib',
        '-install_name', native_macos27.NATIVE_DYLIB.decode(),
        '-O2', '-Wall', '-Wextra', '-Werror',
        '-fvisibility=hidden', '-fstack-protector-strong',
        '-I', build,
        '-DQBT_LAYOUT_HEADER="qbt_macos27_layout.h"',
        QCA_BT / 'userland/Type0.c', '-o', type0_bin,
    ])
    run([
        RCODESIGN, 'sign',
        '--binary-identifier', 'org.unixnu.bluetooth.Type0',
        type0_bin,
    ])
    type0_bin.chmod(0o755)
    type0_cdhash = parse_cdhash_and_check_4k(type0_bin)
    print(f'QcaBTType0.dylib CDHash: {type0_cdhash}', flush=True)

    # 3. Patch & 4K ad-hoc sign macOS 27.3 bluetoothd (preserving original identifier & entitlements)
    orig_ent_xml = extract_macho_entitlements(EXTRACTED_BTD)
    btd_ent = build / 'bluetoothd.entitlements.plist'
    btd_ent.write_bytes(orig_ent_xml)
    orig_ent_dict = plistlib.loads(orig_ent_xml)

    image = native_macos27.NativeImage(EXTRACTED_BTD)
    patched = image.vendor_routing().volatile_root_keys().h4_shutdown().capability_adapter()
    btd_bin = sbin / 'bluetoothd'
    btd_bin.write_bytes(patched.data)
    btd_bin.chmod(0o755)
    run([
        RCODESIGN, 'sign',
        '--binary-identifier', 'com.apple.bluetoothd',
        '--entitlements-xml-file', btd_ent,
        btd_bin,
    ])
    btd_cdhash = parse_cdhash_and_check_4k(btd_bin)
    new_ent_dict = plistlib.loads(extract_macho_entitlements(btd_bin))
    assert new_ent_dict == orig_ent_dict, 'bluetoothd entitlements mismatch after signing'
    assert btd_bin.read_bytes().count(native_macos27.NATIVE_DYLIB + b'\0') == 1, 'Missing QcaBTType0.dylib LC_LOAD_DYLIB'
    print(f'bluetoothd CDHash: {btd_cdhash} (entitlements={len(new_ent_dict)})', flush=True)

    # 4. Write runtime marker
    marker = {
        'native_input_sha256': native_macos27.ORIGINAL_SHA256,
        'files': {
            'sbin/bluetoothd': sha256_file(btd_bin),
            'sbin/BlueTool': sha256_file(bluetool_bin),
            'lib/QcaBTType0.dylib': sha256_file(type0_bin),
        },
    }
    (sbin / 'QcaBluetooth.runtime').write_text(json.dumps(marker, sort_keys=True) + '\n')

    # 5. Stage WCN6855 firmware (prefer stock liuqin dir, fill remaining hpnv21* from linux-firmware)
    for old in fw_qca.glob('*'):
        if old.is_file():
            old.unlink()
    staged_fw = {}
    for src_dir in (LINUX_QCA_FW, STOCK_QCA_FW):
        if not src_dir.is_dir():
            continue
        for p in sorted(src_dir.iterdir()):
            if not p.is_file():
                continue
            if re.fullmatch(r'hpbtfw2[01]\.tlv|hpnv2[01]g?\.(bin|b[0-9a-f]{2,4}|30[0-9a-f])', p.name):
                shutil.copyfile(p, fw_qca / p.name)
                staged_fw[p.name] = {'bytes': p.stat().st_size, 'sha256': sha256_file(p), 'src': str(p)}
    assert 'hpbtfw21.tlv' in staged_fw and 'hpnv21.bin' in staged_fw, f'Missing WCN6855 BT fw: {sorted(staged_fw)}'
    print(f'Staged {len(staged_fw)} WCN6855 BT firmware files in {fw_qca}', flush=True)

    # 5B. Cross-build & 4K ad-hoc sign unixnu-wpa_supplicant + wpa_cli for macOS 27.3
    wpa_tar = ATH_WIFI / 'deps/wpa_supplicant-2.12.tar.gz'
    assert wpa_tar.is_file(), f'Missing {wpa_tar}'
    wpa_src = OUT / 'wpa-src'
    wpa_obj = OUT / 'wpa-macos27'
    wpa_src.mkdir(parents=True, exist_ok=True)
    wpa_obj.mkdir(parents=True, exist_ok=True)
    staged_wpa: dict[str, bytes] = {}
    with tarfile.open(wpa_tar) as arc:
        for m in arc.getmembers():
            rel = Path(m.name).relative_to('wpa_supplicant-2.12')
            dst = wpa_src / rel
            if m.isdir():
                dst.mkdir(parents=True, exist_ok=True)
            elif m.isfile():
                dst.parent.mkdir(parents=True, exist_ok=True)
                staged_wpa[str(rel)] = arc.extractfile(m).read()

    def wpa_replace(rel: str, old: str, new: str) -> None:
        txt = staged_wpa[rel].decode()
        assert txt.count(old) == 1, f'wpa_supplicant patch anchor mismatch in {rel}'
        staged_wpa[rel] = txt.replace(old, new).encode()

    wpa_replace('src/drivers/drivers.mak', '##### COMMON DRIVERS\n', """##### COMMON DRIVERS

ifdef CONFIG_DRIVER_SHENG
DRV_CFLAGS += -DCONFIG_DRIVER_SHENG
DRV_OBJS += ../src/drivers/driver_sheng.o
DRV_OBJS += ../src/drivers/nw_control_client.o
DRV_OBJS += ../src/drivers/nw_control_wire.o
DRV_OBJS += ../src/drivers/nw_supplicant_frontend.o
DRV_OBJS += ../src/drivers/nw_wireless_event.o
NEED_SME=y
endif
""")
    wpa_replace('src/drivers/drivers.c', 'const struct wpa_driver_ops *const wpa_drivers[] =',
                'extern const struct wpa_driver_ops wpa_driver_sheng_ops;\n\nconst struct wpa_driver_ops *const wpa_drivers[] =')
    wpa_replace('src/drivers/drivers.c', '#ifdef CONFIG_DRIVER_NL80211\n',
                '#ifdef CONFIG_DRIVER_SHENG\n\t&wpa_driver_sheng_ops,\n#endif\n#ifdef CONFIG_DRIVER_NL80211\n')
    wpa_replace('wpa_supplicant/wpa_supplicant.c', '\tssid->auth_failures++;',
                '#ifdef CONFIG_DRIVER_SHENG\n\tnw_supplicant_auth_failed(wpa_s, reason);\n#endif\n\n\tssid->auth_failures++;')
    wpa_replace('wpa_supplicant/wpa_supplicant.c', '#include "ctrl_iface.h"',
                '#include "ctrl_iface.h"\n#ifdef CONFIG_DRIVER_SHENG\n#include "nw_supplicant_frontend.h"\n#endif')
    for rel, data in staged_wpa.items():
        p = wpa_src / rel
        if not p.exists() or p.read_bytes() != data:
            p.write_bytes(data)
    for rel, src_rel in {
        'src/drivers/driver_sheng.c': 'userspace/driver_sheng.c',
        'src/drivers/nw_control_client.c': 'userspace/nw_control_client.c',
        'src/drivers/nw_control_wire.c': 'src/nw_control_wire.c',
        'src/drivers/nw_supplicant_frontend.c': 'userspace/nw_supplicant_frontend.c',
        'src/drivers/nw_wireless_event.c': 'userspace/nw_wireless_event.c',
        'src/l2_packet/l2_packet_sheng.c': 'userspace/l2_packet_sheng.c',
        'wpa_supplicant/.config': 'userspace/supplicant.config',
    }.items():
        dst = wpa_src / rel
        if dst.is_symlink() or dst.exists():
            dst.unlink()
        dst.symlink_to(ATH_WIFI / src_rel)

    wpa_flags = [
        '-O2', '-g0', '-Wall', '-MMD', '-Werror=implicit-function-declaration',
        '-I' + str(ATH_WIFI / 'include'),
        '-I' + str(ATH_WIFI / 'userspace'),
        '-I' + str(wpa_src / 'wpa_supplicant'),
    ]
    run([
        'make', '-j8', 'wpa_supplicant', 'wpa_cli', 'V=1',
        f'CC={CLANG}',
        f'BUILDDIR={wpa_obj}',
        f'EXTRA_CFLAGS={shlex.join(wpa_flags)}',
        'LDFLAGS=',
    ], cwd=wpa_src / 'wpa_supplicant')

    wifi_bin_dir = OUT / 'bin'
    wifi_bin_dir.mkdir(parents=True, exist_ok=True)
    supplicant_bin = wifi_bin_dir / 'unixnu-wpa_supplicant'
    wpa_cli_bin = sbin / 'wpa_cli'
    shutil.copy2(wpa_src / 'wpa_supplicant/wpa_supplicant', supplicant_bin)
    shutil.copy2(wpa_src / 'wpa_supplicant/wpa_cli', wpa_cli_bin)
    supplicant_bin.chmod(0o755)
    wpa_cli_bin.chmod(0o755)
    run([RCODESIGN, 'sign', '--binary-identifier', 'org.unixnu.wifi.supplicant', supplicant_bin])
    run([RCODESIGN, 'sign', '--binary-identifier', 'org.unixnu.wifi.wpa_cli', wpa_cli_bin])
    supplicant_cdhash = parse_cdhash_and_check_4k(supplicant_bin)
    wpa_cli_cdhash = parse_cdhash_and_check_4k(wpa_cli_bin)
    print(f'unixnu-wpa_supplicant CDHash: {supplicant_cdhash}', flush=True)
    print(f'wpa_cli CDHash: {wpa_cli_cdhash}', flush=True)

    wpa_conf_bytes = (
        b'# Networks arrive from the native Wi-Fi control channel or wpa_cli.\n'
        b'ctrl_interface=/var/run/wpa_supplicant\n'
        b'ap_scan=1\n'
    )
    wpa_job_bytes = plistlib.dumps({
        'Label': 'org.unixnu.wifi.supplicant',
        'ProgramArguments': [
            '/private/var/ngpu/bin/unixnu-wpa_supplicant',
            '-Dsheng', '-ien0',
            '-c/private/var/ngpu/etc/wifi/wpa_supplicant.conf',
            '-q', '-s',
        ],
        'RunAtLoad': True,
        'KeepAlive': True,
        'ThrottleInterval': 3,
        'UserName': 'root',
        'Umask': 0o77,
        'ProcessType': 'Interactive',
    }, fmt=plistlib.FMT_XML)

    # 5C. Verify WCN6855 Wi-Fi firmware
    wifi_fw_names = ('amss.bin', 'board-2.bin', 'm3.bin', 'regdb.bin')
    for fn in wifi_fw_names:
        assert (WIFI_FW / fn).is_file(), f'Missing WCN6855 Wi-Fi firmware {WIFI_FW / fn}'

    # 6. Pack combined NGPUADD2 addon (GPU Metal bundle + BT + Wi-Fi userland + WCN6855 BT & Wi-Fi firmware)
    gpu_trust = json.loads((GPU_PLUGIN_DIR / 'trust.json').read_text())
    bundle = GPU_PLUGIN_DIR / 'NativeAdrenoMetal.bundle'
    assert (bundle / 'Contents/MacOS/NativeAdrenoMetal').is_file(), 'Missing NativeAdrenoMetal.bundle'

    files: list[tuple[str, int, bytes]] = []
    for p in sorted(x for x in bundle.rglob('*') if x.is_file()):
        mode = 0o755 if p.name in ('NativeAdrenoMetal', 'libvulkan_freedreno.dylib') else 0o644
        files.append(('GPUBundles/NativeAdrenoMetal.bundle/' + p.relative_to(bundle).as_posix(), mode, p.read_bytes()))
    files.append(('GPUBundles/NativeAdrenoMetal.publish', 0o644, b'1\n'))
    files.append(('sbin/bluetoothd', 0o755, btd_bin.read_bytes()))
    files.append(('sbin/BlueTool', 0o755, bluetool_bin.read_bytes()))
    files.append(('sbin/QcaBluetooth.runtime', 0o644, (sbin / 'QcaBluetooth.runtime').read_bytes()))
    files.append(('sbin/wpa_cli', 0o755, wpa_cli_bin.read_bytes()))
    files.append(('lib/QcaBTType0.dylib', 0o755, type0_bin.read_bytes()))
    files.append(('bin/unixnu-wpa_supplicant', 0o755, supplicant_bin.read_bytes()))
    files.append(('etc/wifi/wpa_supplicant.conf', 0o644, wpa_conf_bytes))
    files.append(('LaunchDaemons/org.unixnu.wifi.supplicant.plist', 0o644, wpa_job_bytes))
    for p in sorted(fw_qca.iterdir()):
        if p.is_file():
            files.append((f'firmware/qca/{p.name}', 0o644, p.read_bytes()))
    for fn in wifi_fw_names:
        files.append((f'firmware/ath11k/WCN6855/hw2.0/{fn}', 0o644, (WIFI_FW / fn).read_bytes()))

    body = bytearray()
    for name, mode, data in files:
        enc = name.encode('ascii') + b'\0'
        assert len(enc) <= 160
        packed = zlib.compress(data, 9)
        body += struct.pack('<IIQQ', len(enc), mode, len(data), len(packed))
        body += pad8(enc) + pad8(packed)
    blob = b'NGPUADD2' + struct.pack('<IIQ', len(files), 0, 24 + len(body)) + bytes(body)
    addon_out = OUT / 'kernel.macho.gpuaddon'
    addon_out.write_bytes(blob)

    trust = dict(gpu_trust)
    trust.update({
        'bluetoothd_cdhash': btd_cdhash,
        'bluetool_cdhash': bluetool_cdhash,
        'type0_cdhash': type0_cdhash,
        'supplicant_cdhash': supplicant_cdhash,
        'wpa_cli_cdhash': wpa_cli_cdhash,
        'extra_cdhashes': [btd_cdhash, bluetool_cdhash, type0_cdhash, supplicant_cdhash, wpa_cli_cdhash],
        'bt_firmware_count': len(staged_fw),
        'wifi_firmware_count': len(wifi_fw_names),
        'addon_path': str(addon_out),
        'addon_bytes': len(blob),
        'addon_sha256': sha256_file(addon_out),
    })
    (OUT / 'trust.json').write_text(json.dumps(trust, indent=2) + '\n')
    print(f'PASS: packed {addon_out} ({len(files)} files, {len(blob)} bytes)')
    print(json.dumps(trust, indent=2))


if __name__ == '__main__':
    main()
