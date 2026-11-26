#!/usr/bin/env python3
"""Build libLiuqinWireless.a (WcnPower + WCN6855 Bluetooth + WCN6855 ath11k/mac80211/cfg80211 Wi-Fi)."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
import os
import re
import shlex
import shutil
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path('/home/kurumin/github/UniXNU')
SRC_DIR = Path(__file__).resolve().parent
INPUT_DIR = ROOT / 'scripts/liuqin-analysis/r103-input'
QCA_BT = Path(os.environ.get('LIUQIN_QCA_BT_DIR', '/media/disk_4/unixnu_workspace/liuqin-bt-sources/QcaBluetooth'))
ATH_WIFI = Path(os.environ.get('LIUQIN_ATH_WIFI_DIR', '/media/disk_4/unixnu_workspace/liuqin-wifi-sources/Ath12kWifi'))
LINUX_REPO = Path('/tmp/linux-liuqin-check')
CLANG_BIN = Path('/opt/unixnu-linux/llvm/bin/clang')
LLVM_NM = shutil.which('llvm-nm') or '/usr/bin/llvm-nm'
LLVM_OBJCOPY = shutil.which('llvm-objcopy') or '/usr/bin/llvm-objcopy'
LLVM_AR = os.environ.get('LLVM_AR', shutil.which('llvm-ar') or 'llvm-ar')

ATH11K_SRCS = [
    'core.c', 'hal.c', 'hal_tx.c', 'hal_rx.c', 'wmi.c', 'mac.c', 'reg.c',
    'htc.c', 'qmi.c', 'dp.c', 'dp_tx.c', 'dp_rx.c', 'ce.c',
    'peer.c', 'dbring.c', 'hw.c', 'pcic.c', 'fw.c', 'p2p.c', 'mhi.c', 'pci.c',
]

NW_KEEP_SYMS = {
    '_nw_wifi_start', '_nw_wifi_step', '_nw_wifi_stop', '_nw_wifi_stats', '_nw_wifi_set_events',
    '_nw_wifi_scan', '_nw_wifi_bss_count', '_nw_wifi_bss_get', '_nw_wifi_connect', '_nw_wifi_disconnect',
    '_nw_wifi_tx', '_nw_wifi_status_get', '_nw_wifi_where', '_nw_wifi_power', '_nw_wifi_tx_packet',
    '_nw_wifi_link_state', '_nw_wifi_tx_reasons', '_nw_wifi_buffer_stats_get',
    '_nw_wifi_buffer_pool_configure', '_nw_wifi_buffer_pool_trim', '_nw_wifi_irq_mode',
    '_nw_wifi_irq_pending', '_nw_wifi_wait_ms', '_nw_wifi_poll',
    '_nw_wifi_control_transport_set', '_nw_wifi_control_attach', '_nw_wifi_control_detach',
    '_nw_wifi_control_receive', '_nw_wifi_control_writable', '_nw_wifi_control_stats_get',
    '_nw_wifi_set_platform',
}

# Move Wi-Fi const/cstring/data/bss out of capped __TEXT (0x1d8000) and __DATA (0x284000)
# into uncapped __DATA_CONST (read-only) and __BOOTDATA (read-write).
SEC_REMAP = {
    ('__TEXT', '__const'): ('__DATA_CONST', '__const'),
    ('__TEXT', '__cstring'): ('__DATA_CONST', '__wifi_cstr'),
    ('__TEXT', '__literal4'): ('__DATA_CONST', '__wifi_lit4'),
    ('__TEXT', '__literal8'): ('__DATA_CONST', '__wifi_lit8'),
    ('__TEXT', '__literal16'): ('__DATA_CONST', '__wifi_lit16'),
    ('__DATA', '__data'): ('__BOOTDATA', '__wifi_data'),
    ('__DATA', '__bss'): ('__BOOTDATA', '__wifi_bss'),
    ('__DATA', '__common'): ('__BOOTDATA', '__wifi_comm'),
}


def load_mod(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def remap_macho_sections(obj_path: Path) -> None:
    """In-place Mach-O section_64 (segname, sectname) remap so Wi-Fi stays out of capped __TEXT/__DATA."""
    buf = bytearray(obj_path.read_bytes())
    magic, _, _, _, ncmds, _, _, _ = struct.unpack_from('<IIIIIIII', buf, 0)
    assert magic == 0xfeedfacf, f'Not 64-bit Mach-O: {obj_path}'
    off = 32
    changed = False
    for _ in range(ncmds):
        cmd, cmdsize = struct.unpack_from('<II', buf, off)
        if cmd == 0x19:  # LC_SEGMENT_64
            nsects = struct.unpack_from('<I', buf, off + 64)[0]
            for i in range(nsects):
                at = off + 72 + i * 80
                sect = buf[at:at + 16].split(b'\0', 1)[0].decode('ascii', errors='replace')
                seg = buf[at + 16:at + 32].split(b'\0', 1)[0].decode('ascii', errors='replace')
                target = SEC_REMAP.get((seg, sect))
                if target is not None:
                    new_seg, new_sect = target
                    buf[at:at + 16] = new_sect.encode('ascii').ljust(16, b'\0')[:16]
                    buf[at + 16:at + 32] = new_seg.encode('ascii').ljust(16, b'\0')[:16]
                    changed = True
        off += cmdsize
    if changed:
        obj_path.write_bytes(buf)


def stage_btqca() -> Path:
    """Stage btqca.c and btqca.h from local Linux checkout into QcaBluetooth/out/linux."""
    out = QCA_BT / 'out/linux'
    out.mkdir(parents=True, exist_ok=True)
    for name in ('btqca.c', 'btqca.h'):
        dst = out / name
        if not dst.is_file():
            raw = subprocess.check_output(
                ['git', '-C', str(LINUX_REPO), 'show', f'origin/liuqin-6.17:drivers/bluetooth/{name}']
            )
            dst.write_bytes(raw)
    return out


def prepare_wifi_tree() -> None:
    """Prepare Ath12kWifi/out/{pinned,mhi-src,os-src,mac80211,cfg80211,crypto,ath11k-src,cfg80211-native-*.c}."""
    mod = ATH_WIFI
    linux = mod / 'deps/linux'
    assert (linux / 'drivers/net/wireless/ath/ath11k/pci.c').is_file(), f'Missing linux v7.0.14 in {linux}'
    assert (mod / 'deps/wpa_supplicant-2.12/src/crypto/aes-ccm.c').is_file(), 'Missing wpa_supplicant-2.12'

    # 1. Pinned Linux public headers
    subprocess.run(['bash', str(mod / 'tools/pin-headers.sh')], check=True)

    # 2. MHI + OS-patched qmi_interface.c / mhi-init.c
    mhi_src = mod / 'out/mhi-src'
    os_src = mod / 'out/os-src'
    mhi_src.mkdir(parents=True, exist_ok=True)
    os_src.mkdir(parents=True, exist_ok=True)
    h_dir = linux / 'drivers/bus/mhi/host'
    for f in sorted(h_dir.glob('*.c')) + [h_dir / 'internal.h']:
        dst = mhi_src / f.name
        if dst.is_symlink() or dst.exists():
            dst.unlink()
        dst.symlink_to(f)
    shutil.copy2(mod / 'shim/mhi/trace.h', mhi_src / 'trace.h')
    # Stock Linux mhi/host/boot.c (WCN6855 ath11k programs MHI contexts in READY state, not before BHI)
    common_link = mod / 'out/common.h'
    common_link.unlink(missing_ok=True)
    common_link.symlink_to(linux / 'drivers/bus/mhi/common.h')

    # Apply completion workqueue patch to qmi_interface.c and mhi-init.c
    qmi_c = os_src / 'qmi_interface.c'
    mhi_init_c = os_src / 'mhi-init.c'
    qmi_c.write_bytes((linux / 'drivers/soc/qcom/qmi_interface.c').read_bytes())
    mhi_init_c.write_bytes((linux / 'drivers/bus/mhi/host/init.c').read_bytes())
    subprocess.run(
        ['patch', '--batch', '--forward', '--fuzz=0', '--no-backup-if-mismatch', '-p1',
         '-i', str(mod / 'tools/patches/linux-completion-workqueues.patch')],
        cwd=os_src, check=True, stdout=subprocess.DEVNULL,
    )
    (mhi_src / 'init.c').unlink(missing_ok=True)
    (mhi_src / 'init.c').symlink_to(mhi_init_c)
    (os_src / 'qmi_encdec.c').unlink(missing_ok=True)
    (os_src / 'qmi_encdec.c').symlink_to(linux / 'drivers/soc/qcom/qmi_encdec.c')

    # 3. mac80211 & cfg80211 (strip tracing)
    for subsys, rel in (('mac80211', 'net/mac80211'), ('cfg80211', 'net/wireless')):
        out_dir = mod / 'out' / subsys
        out_dir.mkdir(parents=True, exist_ok=True)
        paths = sorted((linux / rel).glob('*.[ch]'))
        traces: set[str] = set()
        for p in paths:
            if p.name in ('trace.h', 'trace_msg.h'):
                continue
            dst = out_dir / p.name
            if dst.is_symlink() or dst.exists():
                dst.unlink()
            dst.symlink_to(p)
            traces.update(re.findall(r'\b(trace_[a-zA-Z0-9_]+)\s*\(', p.read_text()))
        trace_hdr = '/* Tracing disabled */\n' + '\n'.join(f'#define {t}(...) ((void)0)' for t in sorted(traces)) + '\n'
        (out_dir / 'trace.h').write_text(trace_hdr)
        (out_dir / 'trace_msg.h').write_text(trace_hdr)

    # 4. Portable AES crypto sources from wpa_supplicant-2.12
    crypto_out = mod / 'out/crypto'
    crypto_out.mkdir(parents=True, exist_ok=True)
    lock = json.loads((mod / 'tools/source-lock.json').read_text())['supplicant']
    for name in lock['required']:
        if not name.startswith('src/crypto/'):
            continue
        src = mod / 'deps' / lock['directory'] / name
        dst = crypto_out / src.name
        if dst.is_symlink() or dst.exists():
            dst.unlink()
        dst.symlink_to(src)

    # 5. Generated cfg80211-native-protocol.c, mac80211-fils-protocol.inc, cfg80211-native-events.c
    sys.path.insert(0, str(mod / 'tools'))
    from source_fragments import function  # type: ignore

    frags = []
    for fname, names in (
        ('nl80211.c', ['cfg80211_check_station_change', 'cfg80211_free_coalesce']),
        ('pmsr.c', ['cfg80211_pmsr_process_abort', 'cfg80211_pmsr_free_wk', 'cfg80211_pmsr_wdev_down', 'cfg80211_release_pmsr']),
    ):
        txt = (linux / 'net/wireless' / fname).read_text()
        for n in names:
            frags.append(function(txt, n))
    (mod / 'out/cfg80211-native-protocol.c').write_text(
        '/* SPDX-License-Identifier: GPL-2.0-only */\n'
        '#include "lx_pci.h"\n#include <net/cfg80211.h>\n'
        '#include "cfg80211/core.h"\n#include "cfg80211/rdev-ops.h"\n'
        '#include "cfg80211/nl80211.h"\n#include "cfg80211/trace.h"\n'
        + '\n'.join(frags)
    )
    fils_txt = (linux / 'net/mac80211/fils_aead.c').read_text()
    fils_code = '\n'.join(function(fils_txt, n) for n in ('fils_encrypt_assoc_req', 'fils_decrypt_assoc_resp'))
    (mod / 'out/mac80211-fils-protocol.inc').write_text('/* FILS protocol bodies */\n' + fils_code)

    nl_txt = (linux / 'net/wireless/nl80211.c').read_text()
    ev_names = """
    nl80211hdr_put
    cfg80211_assoc_comeback cfg80211_bss_color_notify cfg80211_ch_switch_notify cfg80211_ch_switch_started_notify
    cfg80211_cqm_beacon_loss_notify cfg80211_cqm_pktloss_notify cfg80211_cqm_rssi_notify cfg80211_cqm_rssi_notify_work
    cfg80211_del_sta_sinfo cfg80211_epcs_changed cfg80211_gtk_rekey_notify cfg80211_links_removed cfg80211_mgmt_tx_status_ext
    cfg80211_nan_func_terminated cfg80211_nan_match cfg80211_new_sta cfg80211_probe_status cfg80211_ready_on_channel
    cfg80211_remain_on_channel_expired cfg80211_report_obss_beacon_khz cfg80211_rx_spurious_frame
    cfg80211_rx_unexpected_4addr_frame cfg80211_rx_unprot_mlme_mgmt cfg80211_schedule_channels_check
    cfg80211_sta_opmode_change_notify cfg80211_tdls_oper_request cfg80211_tx_mgmt_expired
    nl80211_common_reg_change_event nl80211_michael_mic_failure nl80211_mlo_reconf_add_done nl80211_radar_notify
    nl80211_send_ap_stopped nl80211_send_beacon_hint_event nl80211_send_connect_result nl80211_send_ibss_bssid
    nl80211_send_mgmt nl80211_send_port_authorized nl80211_send_roamed nl80211_send_sched_scan
    """.split()
    ev_frags: dict[str, str] = {}

    def visit(fn: str) -> None:
        if fn in ev_frags:
            return
        try:
            code = function(nl_txt, fn)
        except ValueError:
            return
        ev_frags[fn] = code
        for child in re.findall(r'\b((?:__)?(?:nl80211|cfg80211)_[a-zA-Z0-9_]+)\s*\(', code):
            visit(child)

    for n in ev_names:
        visit(n)
    ev_types = []
    for tname in sorted(set(re.findall(r'\bstruct (nl80211_[a-zA-Z0-9_]+)\b', '\n'.join(ev_frags.values())))):
        m = re.search(r'\bstruct ' + tname + r'\s*\{', nl_txt)
        if m:
            ev_types.append(nl_txt[m.start():nl_txt.index('};', m.end()) + 2] + '\n')
    ev_protos = [c[:c.index('{')].strip() + ';\n' for c in ev_frags.values()]
    (mod / 'out/cfg80211-native-events.c').write_text(
        '/* SPDX-License-Identifier: GPL-2.0-only */\n'
        '#include "lx_pci.h"\n#include <net/genetlink.h>\n#include <net/cfg80211.h>\n#include <linux/nospec.h>\n'
        '#include "cfg80211/core.h"\n#include "cfg80211/rdev-ops.h"\n#include "cfg80211/nl80211.h"\n'
        '#include "cfg80211/reg.h"\n#include "cfg80211/trace.h"\n'
        'static struct genl_family nl80211_fam = { .id = 0x13, .version = 1 };\n'
        'enum nl80211_multicast_groups { NL80211_MCGRP_CONFIG, NL80211_MCGRP_SCAN, '
        'NL80211_MCGRP_REGULATORY, NL80211_MCGRP_MLME, NL80211_MCGRP_VENDOR, NL80211_MCGRP_NAN, '
        'NL80211_MCGRP_TESTMODE };\n'
        + '\n'.join(ev_types + ev_protos + list(ev_frags.values()))
    )

    # 6. Stage ath11k-src with trace stub + XNU adaptations
    a_src = linux / 'drivers/net/wireless/ath/ath11k'
    a_out = mod / 'out/ath11k-src'
    a_out.mkdir(parents=True, exist_ok=True)
    a_traces: set[str] = set()
    for f in sorted(a_src.glob('*.[ch]')):
        if f.name == 'trace.h':
            continue
        dst = a_out / f.name
        if dst.is_symlink() or dst.exists():
            dst.unlink()
        dst.symlink_to(f)
        a_traces.update(re.findall(r'\b(trace_ath11k_[a-zA-Z0-9_]+)\s*\(', f.read_text()))
    (a_out / 'trace.h').write_text(
        '#ifndef LX_ATH11K_TRACE_H\n#define LX_ATH11K_TRACE_H\n'
        + '\n'.join(
            f'#define {t}(...) (0)' if t.endswith('_enabled') else f'#define {t}(...) ((void)0)'
            for t in sorted(a_traces)
        )
        + '\n#endif\n'
    )

    # Use stock Linux dp.h ring sizes (128 MiB SMMU DMA arena holds full 4096-entry RXDMA rings)

    # Patch pci.c to export ath11k_pci_init / ath11k_pci_exit and keep ASPM disabled (avoids L1/M2 stall)
    pci_c = (a_src / 'pci.c').read_text()
    assert 'static int ath11k_pci_init(void)' in pci_c and 'static void ath11k_pci_exit(void)' in pci_c
    pci_c = pci_c.replace('static int ath11k_pci_init(void)', 'int ath11k_pci_init(void)', 1)
    pci_c = pci_c.replace('static void ath11k_pci_exit(void)', 'void ath11k_pci_exit(void)', 1)
    aspm_old = '\tif (test_bit(ATH11K_FLAG_MULTI_MSI_VECTORS, &ab->dev_flags))\n\t\tath11k_pci_aspm_restore(ab_pci);'
    assert aspm_old in pci_c
    pci_c = pci_c.replace(aspm_old, '\tif (0 && test_bit(ATH11K_FLAG_MULTI_MSI_VECTORS, &ab->dev_flags))\n\t\tath11k_pci_aspm_restore(ab_pci);', 1)
    (a_out / 'pci.c').unlink(missing_ok=True)
    (a_out / 'pci.c').write_text(pci_c)

    # Patch mac.c to fall back to nw_board_mac() when firmware reports invalid/default MAC
    mac_c = (a_src / 'mac.c').read_text()
    mac_anchor = '\t\t\tar->mac_addr[4] += i;\n\t\t}\n'
    assert mac_c.count(mac_anchor) == 1, 'Expected mac_addr anchor in ath11k/mac.c'
    mac_c = mac_c.replace('#include "mac.h"\n', '#include "mac.h"\nvoid nw_board_mac(u8 *a);\n', 1)
    mac_c = mac_c.replace(
        mac_anchor,
        mac_anchor
        + '\t\tif (!is_valid_ether_addr(ar->mac_addr) ||\n'
        + '\t\t    (!ar->mac_addr[0] && ar->mac_addr[1] == 0x03 && ar->mac_addr[2] == 0x7f)) {\n'
        + '\t\t\tnw_board_mac(ar->mac_addr);\n'
        + '\t\t\tar->mac_addr[4] += i;\n'
        + '\t\t}\n',
        1,
    )
    (a_out / 'mac.c').unlink(missing_ok=True)
    (a_out / 'mac.c').write_text(mac_c)

    # Patch reg.c so channel_update_work only waits when a 11d scan is actually RUNNING
    # (not PREPARING after add_interface, which would block the cooperative dispatcher for 20s before first scan)
    reg_c = (a_src / 'reg.c').read_text()
    reg_anchor = '\t\tif (ar->state_11d != ATH11K_11D_IDLE) {\n'
    assert reg_c.count(reg_anchor) == 1, 'Expected state_11d anchor in ath11k/reg.c'
    reg_c = reg_c.replace(reg_anchor, '\t\tif (ar->state_11d == ATH11K_11D_RUNNING) {\n', 1)
    (a_out / 'reg.c').unlink(missing_ok=True)
    (a_out / 'reg.c').write_text(reg_c)

    # Small compat headers for ath11k helpers not used by ath12k
    shim_inc = mod / 'out/ath11k-shim'
    (shim_inc / 'linux/soc/qcom').mkdir(parents=True, exist_ok=True)
    for rel_h, body in {
        'linux/suspend.h': '#ifndef LX_SUSPEND_H\n#define LX_SUSPEND_H\n#define pm_suspend_target_state 0\n#define PM_SUSPEND_MEM 3\n#define PM_SUSPEND_ON 0\n#endif\n',
        'linux/sysfs.h': '#ifndef LX_SYSFS_H\n#define LX_SYSFS_H\n#endif\n',
        'linux/property.h': '#ifndef LX_PROPERTY_H\n#define LX_PROPERTY_H\nstatic inline bool device_property_read_bool(struct device *d, const char *n) { (void)d; (void)n; return false; }\n#endif\n',
        'linux/of_irq.h': '#ifndef LX_OF_IRQ_H\n#define LX_OF_IRQ_H\n#endif\n',
        'linux/iommu.h': '#ifndef LX_IOMMU_H\n#define LX_IOMMU_H\nstruct iommu_domain { int unused; };\nstatic inline struct iommu_domain *iommu_get_domain_for_dev(struct device *d) { (void)d; return NULL; }\n#endif\n',
        'linux/soc/qcom/smem.h': '#ifndef LX_QCOM_SMEM_H\n#define LX_QCOM_SMEM_H\n#define QCOM_SMEM_HOST_ANY -1\nstatic inline void *qcom_smem_get(unsigned h, unsigned id, size_t *sz) { (void)h; (void)id; (void)sz; return ERR_PTR(-ENOENT); }\n#endif\n',
        'linux/hwmon.h': '#ifndef LX_HWMON_H\n#define LX_HWMON_H\n#endif\n',
        'linux/hwmon-sysfs.h': '#ifndef LX_HWMON_SYSFS_H\n#define LX_HWMON_SYSFS_H\n#endif\n',
        'linux/thermal.h': '#ifndef LX_THERMAL_H\n#define LX_THERMAL_H\n#endif\n',
        'linux/relay.h': '#ifndef LX_RELAY_H\n#define LX_RELAY_H\n#endif\n',
    }.items():
        (shim_inc / rel_h).write_text(body)

    spec_link = mod / 'out/spectral_common.h'
    spec_link.unlink(missing_ok=True)
    spec_link.symlink_to(linux / 'drivers/net/wireless/ath/spectral_common.h')

    (a_out / 'ath11k_compat.h').write_text(
        '#ifndef LX_ATH11K_COMPAT_H\n#define LX_ATH11K_COMPAT_H\n'
        'typedef unsigned long kernel_ulong_t;\n'
        '#ifndef swab16\n#define swab16(x) __builtin_bswap16((u16)(x))\n#endif\n'
        '#ifndef swab32\n#define swab32(x) __builtin_bswap32((u32)(x))\n#endif\n'
        '#ifndef swab64\n#define swab64(x) __builtin_bswap64((u64)(x))\n#endif\n'
        '#ifndef DMI_BOARD_VENDOR\n'
        '#define DMI_NONE 0\n#define DMI_BIOS_VENDOR 1\n#define DMI_BIOS_VERSION 2\n#define DMI_SYS_VENDOR 4\n'
        '#define DMI_PRODUCT_NAME 5\n#define DMI_PRODUCT_VERSION 6\n#define DMI_PRODUCT_SKU 8\n'
        '#define DMI_PRODUCT_FAMILY 9\n#define DMI_BOARD_VENDOR 10\n#define DMI_BOARD_NAME 11\n'
        '#define DMI_CHASSIS_VENDOR 13\n'
        'struct dmi_strmatch { unsigned char slot:7; unsigned char exact_match:1; char substr[79]; };\n'
        'struct dmi_system_id { int (*callback)(const struct dmi_system_id *d); const char *ident; struct dmi_strmatch matches[4]; void *driver_data; };\n'
        '#define DMI_MATCH(a, b) { .slot = a, .substr = b }\n'
        '#define DMI_EXACT_MATCH(a, b) { .slot = a, .exact_match = 1, .substr = b }\n'
        'static inline const struct dmi_system_id *dmi_first_match(const struct dmi_system_id *list) { (void)list; return NULL; }\n'
        '#endif\n'
        '#ifndef PM_SUSPEND_PREPARE\n'
        '#define PM_HIBERNATION_PREPARE 0x0001\n#define PM_POST_HIBERNATION 0x0002\n'
        '#define PM_SUSPEND_PREPARE 0x0003\n#define PM_POST_SUSPEND 0x0004\n'
        '#define unregister_pm_notifier(n) (0)\n'
        '#endif\n'
        'static inline void prefetch(const void *x) { (void)x; }\n'
        'static inline void *memset32(u32 *s, u32 v, size_t count) { for (size_t i = 0; i < count; ++i) s[i] = v; return s; }\n'
        'static inline struct device_node *of_find_node_by_type(struct device_node *from, const char *type) { (void)from; (void)type; return NULL; }\n'
        'static inline bool of_machine_is_compatible(const char *compat) { (void)compat; return false; }\n'
        'static inline bool of_property_present(const struct device_node *np, const char *prop) { (void)np; (void)prop; return false; }\n'
        'static inline int of_reserved_mem_region_to_resource(const struct device_node *np, int idx, struct resource *res) { (void)np; (void)idx; (void)res; return -ENOENT; }\n'
        'static inline int device_get_mac_address(struct device *d, char *a) { (void)d; (void)a; return -ENOENT; }\n'
        'static inline phys_addr_t resource_size(const struct resource *res) { return res->end - res->start + 1; }\n'
        'static inline void *devm_ioremap(struct device *d, phys_addr_t pa, size_t sz) { (void)d; return ioremap(pa, sz); }\n'
        '#ifndef dma_alloc_noncoherent\n'
        '#define dma_alloc_noncoherent(dev, size, dma, dir, gfp) dma_alloc_coherent((dev), (size), (dma), (gfp))\n'
        '#endif\n'
        '#ifndef dma_free_noncoherent\n'
        '#define dma_free_noncoherent(dev, size, vaddr, dma, dir) dma_free_coherent((dev), (size), (vaddr), (dma))\n'
        '#endif\n'
        '#ifndef PCI_IRQ_ALL_TYPES\n#define PCI_IRQ_ALL_TYPES (PCI_IRQ_MSI)\n#endif\n'
        '#ifndef PCI_IRQ_LEGACY\n#define PCI_IRQ_LEGACY 0\n#endif\n'
        '#endif\n'
    )


def build_ath11k_objects(src_dir: Path, out: Path) -> list[Path]:
    """Compile ath11k + mac80211 + cfg80211 + mhi + qmi + crypto + Ath12kWifi adapter objects."""
    prepare_wifi_tree()
    mod = ATH_WIFI
    wifi_out = out / 'wifi-objs'
    raw_dir = wifi_out / 'raw'
    wifi_out.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    clang = str(CLANG_BIN)
    resource = subprocess.check_output([clang, '-print-resource-dir'], text=True).strip() + '/include'
    flags = [
        '-target', 'arm64e-apple-ios17.0', '-mkernel', '-O2', '-g0',
        '-ffreestanding', '-fno-builtin', '-fno-common', '-fno-strict-aliasing', '-fwrapv',
        '-fno-stack-protector', '-Wno-incompatible-pointer-types', '-Wno-error',
        '-fno-delete-null-pointer-checks', '-mgeneral-regs-only', '-momit-leaf-frame-pointer',
        '-std=gnu11', '-w',
        '-DCONFIG_ATH11K_DEBUG', '-DCONFIG_CFG80211=1', '-DCONFIG_MAC80211=1',
        '-DCONFIG_MAC80211_STA_HASH_MAX_SIZE=0', '-DCONFIG_MAC80211_RC_DEFAULT=""',
        '-nostdinc', '-isystem', str(mod / 'shim/libc'), '-isystem', resource,
        '-include', 'lx_pci.h',
        '-I', str(mod / 'shim/include'),
        '-I', str(mod / 'include'),
        '-I', str(mod / 'out/pinned'),
        '-I', str(mod / 'src'),
        '-I', str(mod / 'out'),
    ]
    trees = {
        'ath11k': ['-I', str(mod / 'out/ath11k-shim'), '-I', str(mod / 'out/ath11k-src')],
        'mhi': ['-I', str(mod / 'out/mhi-src')],
        'qmi': ['-I', str(mod / 'out/os-src')],
        'mac80211': ['-I', str(mod / 'out/mac80211')],
        'cfg80211': ['-I', str(mod / 'out/cfg80211')],
        'generated': ['-I', str(mod / 'out/cfg80211')],
        'crypto': ['-I', str(mod / 'shim/crypto'), '-I', str(mod / 'out/crypto')],
    }

    jobs: list[tuple[Path, Path, list[str]]] = []
    for line in (mod / 'tools/sources.txt').read_text().splitlines():
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        tree, _, name = line.partition(':') if ':' in line else ('', '', line)
        if tree == 'ath12k':
            continue
        if name == 'src/nw_wifi.c':
            src = src_dir / 'nw_wifi_ath11k.c'
            obj = wifi_out / 'nw_wifi_ath11k.o'
            jobs.append((src, obj, trees['ath11k']))
            continue
        if name == 'src/nw_debug.c':
            src = src_dir / 'nw_debug_ath11k.c'
            obj = wifi_out / 'nw_debug_ath11k.o'
            jobs.append((src, obj, trees['ath11k']))
            continue
        if tree == 'mhi':
            src = mod / 'out/mhi-src' / name
        elif tree == 'qmi':
            src = mod / 'out/os-src' / name
        elif tree in ('mac80211', 'cfg80211', 'crypto'):
            src = mod / 'out' / tree / name
        elif tree == 'generated':
            src = mod / 'out' / name
        else:
            src = mod / name
        obj = wifi_out / ((tree + '_' if tree else '') + src.stem + '.o')
        extra = trees.get(tree, trees['ath11k'] if name.startswith('src/') else [])
        if name.startswith('src/nw_cfg80211_'):
            extra = trees['cfg80211']
        elif name == 'src/nw_fils.c':
            extra = trees['mac80211']
        elif name == 'src/nw_crypto_mac80211.c':
            extra = trees['crypto'] + trees['mac80211']
        elif tree == 'crypto' and name == 'aes-siv.c':
            extra = [*extra, '-Daes_siv_encrypt=nw_aes_siv_encrypt', '-Daes_siv_decrypt=nw_aes_siv_decrypt']
        jobs.append((src, obj, extra))

    for name in ATH11K_SRCS:
        src = mod / 'out/ath11k-src' / name
        obj = wifi_out / ('ath11k_' + src.stem + '.o')
        jobs.append((src, obj, trees['ath11k']))

    def compile_job(job: tuple[Path, Path, list[str]]) -> Path:
        src, obj, extra = job
        raw_obj = raw_dir / obj.name
        dep = raw_obj.with_suffix('.d')
        ident = raw_obj.with_suffix('.inputs.json')
        post = ['-include', 'ath11k_compat.h'] if str(mod / 'out/ath11k-src') in extra else []
        cmd = [clang, '-c', *extra, *flags, *post, '-MD', '-MF', str(dep), str(src), '-o', str(raw_obj)]
        if raw_obj.exists() and ident.exists():
            rec = json.loads(ident.read_text())
            if (
                rec.get('command') == cmd
                and rec.get('obj_sha') == hashlib.sha256(raw_obj.read_bytes()).hexdigest()
                and all(Path(p).is_file() and hashlib.sha256(Path(p).read_bytes()).hexdigest() == h
                        for p, h in rec.get('deps', {}).items())
            ):
                return raw_obj
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode:
            return (src, r.stderr[-2500:])
        hdrs = shlex.split(dep.read_text().replace('\\\n', '').partition(':')[2])
        ident.write_text(json.dumps({
            'command': cmd,
            'obj_sha': hashlib.sha256(raw_obj.read_bytes()).hexdigest(),
            'deps': {str(Path(p).absolute()): hashlib.sha256(Path(p).read_bytes()).hexdigest() for p in hdrs},
        }) + '\n')
        return raw_obj

    with ThreadPoolExecutor(8) as pool:
        results = list(pool.map(compile_job, jobs))
    errs = [x for x in results if isinstance(x, tuple)]
    if errs:
        for src, msg in errs:
            sys.stderr.write(f'=== FAILED {src.name} ===\n{msg}\n')
        raise SystemExit(1)
    raw_objs = results

    names: set[str] = set()
    for o in raw_objs:
        nm_out = subprocess.check_output([LLVM_NM, '-g', '--defined-only', str(o)], text=True)
        for line in nm_out.splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[2] not in NW_KEEP_SYMS:
                names.add(parts[2])
    mapping = wifi_out / 'rename.txt'
    mapping.write_text(''.join(f'{n} _nwk{n}\n' for n in sorted(names)))

    final_objs = [obj for _, obj, _ in jobs]

    def finalize_obj(obj: Path) -> Path:
        shutil.copyfile(raw_dir / obj.name, obj)
        subprocess.run([LLVM_OBJCOPY, f'--redefine-syms={mapping}', str(obj)], check=True)
        remap_macho_sections(obj)
        return obj

    with ThreadPoolExecutor(8) as pool:
        list(pool.map(finalize_obj, final_objs))
    print(f'Built {len(final_objs)} ath11k/mac80211/cfg80211 objects (symbols prefixed _nwk, sections remapped)', flush=True)
    return final_objs


def main() -> None:
    tree = Path(os.environ.get('UNIXNU_TREE', str(Path.cwd()))).resolve()
    if not (tree / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837').is_dir():
        tree = (ROOT / 'out/liuqin/macos-27.3-26C5035r/liuqin/tree').resolve()
    objroot = tree / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837'
    out = tree / 'build/liuqin-wireless'
    out.mkdir(parents=True, exist_ok=True)

    dev_env = os.environ.get('UNIXNU_DEVICE')
    src_dir = (Path(dev_env) / 'drivers/LiuqinWireless') if dev_env and (Path(dev_env) / 'drivers/LiuqinWireless').is_dir() else SRC_DIR

    builder = load_mod('lq_gpu_builder', ROOT / 'scripts/liuqin-analysis/r102-gpu/build-liuqin-adreno730.py')
    cpp_recipe = json.loads((objroot / 'iokit/DEVELOPMENT/IOPlatformExpert.cpo.json').read_text().strip().rstrip(','))
    c_recipe = json.loads((objroot / 'bsd/DEVELOPMENT/bsd_init.o.json').read_text().strip().rstrip(','))

    linux_out = stage_btqca()
    common_inc = [
        '-I', str(src_dir),
        '-I', str(INPUT_DIR),
        '-I', str(QCA_BT / 'include'),
        '-I', str(QCA_BT / 'src'),
        '-I', str(QCA_BT / 'shim'),
        '-I', str(linux_out),
        '-I', str(ATH_WIFI / 'include'),
        '-I', str(tree / '.cache/xnu-work/osfmk'),
        '-Wno-unused-parameter',
        '-Wno-sign-compare',
        '-Wno-deprecated-declarations',
        '-Wno-c99-designator',
        '-Wno-reorder-init-list',
        '-Wno-overriding-option',
        '-Wno-missing-designated-field-initializers',
    ]

    objs: list[Path] = []

    def compile_one(src: Path, extra: list[str] | None = None, remap: bool = False) -> None:
        is_c = src.suffix == '.c'
        recipe = c_recipe if is_c else cpp_recipe
        obj = out / (src.stem + '.o')
        cmd = builder.make_cmd(recipe, src, obj, common_inc + (extra or []))
        r = subprocess.run(cmd, cwd=recipe['directory'], capture_output=True, text=True)
        (out / (src.stem + '.log')).write_text(r.stdout + r.stderr)
        if r.returncode:
            sys.stderr.write(f'FAILED {src}:\n{r.stdout}\n{r.stderr}\n')
            raise SystemExit(r.returncode)
        if remap:
            remap_macho_sections(obj)
        objs.append(obj)

    compile_one(src_dir / 'LiuqinWcnPower.cpp')
    compile_one(src_dir / 'LiuqinBluetooth.cpp')
    compile_one(src_dir / 'LiuqinWifiFirmware.c', remap=True)
    compile_one(src_dir / 'LiuqinWifiNet.cpp', remap=True)
    compile_one(src_dir / 'LiuqinWifiPcie.cpp', remap=True)

    # QcaBluetooth core + macOS /dev/cu.BLTH TTY front-end + mainline btqca.c (WCN6855)
    qbt_core_wcn6855 = out / 'qbt_core_wcn6855.c'
    qbt_core_src = (QCA_BT / 'src/qbt_core.c').read_text()
    core_needle = '        if (!q->wait_event && n >= 5 && e[0] == 0x0e)\n            match = (e[3] | (unsigned)e[4] << 8) == q->wait_opcode;\n        else if (q->wait_event == e[0]) match = true;'
    core_repl = '        if (n >= 5 && e[0] == 0x0e && (e[3] | (unsigned)e[4] << 8) == q->wait_opcode)\n            match = true;\n        else if (q->wait_event && q->wait_event == e[0]) match = true;'
    assert qbt_core_src.count(core_needle) == 1
    qbt_core_wcn6855.write_text(qbt_core_src.replace(core_needle, core_repl))
    compile_one(qbt_core_wcn6855)
    compile_one(QCA_BT / 'src/qbt_geni.c')
    compile_one(QCA_BT / 'src/qbt_tty.c')
    qbt_linux_wcn6855 = out / 'qbt_linux_wcn6855.c'
    qbt_linux_src = (QCA_BT / 'src/qbt_linux.c').read_text()
    assert qbt_linux_src.count('QCA_WCN7850') == 2
    qbt_linux_src = qbt_linux_src.replace('QCA_WCN7850', 'QCA_WCN6855')
    ibs_needle = '        q->ibs=true;q->tx_state=QBT_ASLEEP;q->rx_awake=false;\n        bdaddr_t local;for(unsigned i=0;i<6;i++)local.b[i]=address[5-i];e=qca_set_bdaddr(&h,&local);'
    ibs_repl = '        bdaddr_t local;for(unsigned i=0;i<6;i++)local.b[i]=address[5-i];e=qca_set_bdaddr(&h,&local);\n        if(!e){q->ibs=true;q->tx_state=QBT_AWAKE;q->rx_awake=true;q->idle_at=q->ops.now_ns(q->ops.context)+100000000ULL;}'
    assert qbt_linux_src.count(ibs_needle) == 1
    qbt_linux_wcn6855.write_text(qbt_linux_src.replace(ibs_needle, ibs_repl))
    compile_one(qbt_linux_wcn6855)
    compile_one(linux_out / 'btqca.c', ['-DHCI_OP_RESET=0x0c03'])

    # Full WCN6855 ath11k + mac80211 + cfg80211 + mhi + qmi + crypto stack
    objs.extend(build_ath11k_objects(src_dir, out))

    archive = out / 'libLiuqinWireless.a'
    archive.unlink(missing_ok=True)
    subprocess.run([LLVM_AR, 'rcs', str(archive), *[str(o) for o in objs]], check=True)
    print(f'Built {archive} ({len(objs)} objects)', flush=True)


if __name__ == '__main__':
    main()
