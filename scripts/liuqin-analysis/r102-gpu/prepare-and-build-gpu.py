#!/usr/bin/env python3
"""Prepare, build, verify (layout + AES gate), and package r102-gpu (Adreno 730 KMD bring-up) volatile boot.img.

All large outputs go under /media/disk_4/unixnu_workspace/r102-gpu/ to protect /home free space.
Never touches frozen r101/A7/r2/r3 files or owner.key.
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import importlib.util
import json
import plistlib
import shutil
import struct
import subprocess
import sys
import tomllib
import uuid
from pathlib import Path

ROOT = Path('/home/kurumin/github/UniXNU')
A7_WORK = ROOT / 'out/liuqin-r101-a7-work'
R100_OLD = ROOT / 'out/liuqin-r100-work/evidence'
WORK = Path('/media/disk_4/unixnu_workspace/r102-gpu')
SCRIPT_DIR = Path(__file__).resolve().parent


def sha(p: Path) -> str:
    with p.open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def run(args) -> bytes:
    return subprocess.run([str(x) for x in args], check=True, capture_output=True).stdout


def load_mod(name: str, p: Path):
    spec = importlib.util.spec_from_file_location(name, p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def adt_add_gpu_addon(raw: bytes, add_gpu_addon: bool = True, add_bluetooth: bool = False) -> bytes:
    """Patch ADT for SM8475 DRAM range, sRGB LCD display profile, /chosen/memory-map/GpuAddon, and /arm-io/bluetooth."""

    def parse_node(buf: bytes, off: int):
        nprops, nchildren = struct.unpack_from('<II', buf, off)
        off += 8
        props = []
        for _ in range(nprops):
            name = buf[off:off + 32].split(b'\0', 1)[0].decode('ascii')
            plen = struct.unpack_from('<I', buf, off + 32)[0]
            val = buf[off + 36:off + 36 + plen]
            off += 36 + ((plen + 3) & ~3)
            props.append((name, val))
        children = []
        for _ in range(nchildren):
            child, off = parse_node(buf, off)
            children.append(child)
        return {'props': props, 'children': children}, off

    def encode_node(n) -> bytes:
        out = bytearray(struct.pack('<II', len(n['props']), len(n['children'])))
        for name, val in n['props']:
            nb = name.encode('ascii')
            assert len(nb) < 32
            out += nb.ljust(32, b'\0')
            out += struct.pack('<I', len(val))
            out += val
            if len(val) & 3:
                out += bytes(4 - (len(val) & 3))
        for ch in n['children']:
            out += encode_node(ch)
        return bytes(out)

    def node_name(n) -> str:
        for k, v in n['props']:
            if k == 'name':
                return v.rstrip(b'\0').decode('ascii', errors='replace')
        return ''

    root, end = parse_node(raw, 0)
    assert end == len(raw), f'ADT parse mismatch {end} != {len(raw)}'
    chosen = next(c for c in root['children'] if node_name(c) == 'chosen')
    # SM8475 liuqin RAM lives at 0x8_40004000..0x9_40004000 (above 33 GiB).
    # Original ADT had dram-base=0x80000000, dram-size=0x200000000 (ends at 0x2_80000000),
    # causing is_dram_addr(pa) to return FALSE for all RAM and demoting VM_WIMG_WCOMB to Device-GRE!
    chosen['props'] = [
        (k, struct.pack('<Q', 0xa_00000000) if k == 'dram-size' else v)
        for k, v in chosen['props']
    ]
    if add_gpu_addon:
        mmap = next(c for c in chosen['children'] if node_name(c) == 'memory-map')
        if not any(k == 'GpuAddon' for k, _ in mmap['props']):
            mmap['props'].append(('GpuAddon', bytes(16)))
    # Declare sRGB 8-bit IPS LCD panel (matching sheng) so QuartzCore selects uncompressed BGRA
    # rather than compressed wide-color '&w4a' / 'w40a'.
    product = next((c for c in root['children'] if node_name(c) == 'product'), None)
    if product is not None:
        overrides = {
            'artwork-display-gamut': b'sRGB\x00',
            'ideal-screen-colorspace': b'sRGB\x00',
            'oled-display': struct.pack('<I', 0),
        }
        product['props'] = [(k, overrides.get(k, v)) for k, v in product['props']]
    if add_bluetooth:
        arm_io = next((c for c in root['children'] if node_name(c) == 'arm-io'), None)
        if arm_io is not None and not any(node_name(c) == 'bluetooth' for c in arm_io['children']):
            arm_io['children'].append({
                'props': [
                    ('name', b'bluetooth\x00'),
                    ('device_type', b'bluetooth\x00'),
                    ('transport-encoding', struct.pack('<I', 1)),
                    ('transport-speed', struct.pack('<I', 3200000)),
                ],
                'children': [],
            })
        if arm_io is not None and not any(node_name(c) == 'wlan' for c in arm_io['children']):
            arm_io['children'].append({
                'props': [
                    ('name', b'wlan\x00'),
                    ('device_type', b'wlan\x00'),
                ],
                'children': [],
            })
    return encode_node(root)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--gpu-addon', type=Path, help='NGPUADD2 kernel.macho.gpuaddon file to stage into payload')
    ap.add_argument('--trust-json', type=Path, help='trust.json containing cdhash and turnip_cdhash to append to trustcache')
    ap.add_argument('--repack-only', action='store_true', help='Skip XNU compile/prelink and repack existing kernel.macho with updated addon/trustcache')
    ap.add_argument('--with-input', action='store_true', help='Build the Liuqin cover and NT36532 input port')
    ap.add_argument('--with-wireless', action='store_true', help='Build Liuqin WCN6855 power + Bluetooth (QcaBluetooth) port')
    ap.add_argument('--build-only', action='store_true', help='Build the existing isolated device without regenerating its sources')
    ap.add_argument('--no-usb-debug', dest='usb_debug', action='store_false', default=True,
                    help='Disable the USB debug gadget and console mirror (enabled by default)')
    ap.add_argument('--persistent-data', choices=('none', 'reuse', 'init', 'format'), default='none',
                    help='Use free userdata for UFS Data; init needs blank metadata, format permits replacing old non-Data content')
    cli_args = ap.parse_args()

    WORK.mkdir(parents=True, exist_ok=True)
    dev = WORK / 'device-gpu'
    ev = WORK / 'evidence'
    ev.mkdir(parents=True, exist_ok=True)
    sys.path.insert(0, str(ROOT / 'scripts'))
    from unixnu import cli, feeds
    feeds.update_submodules = lambda ctx: None
    if cli_args.repack_only:
        assert (ev / 'kernel.macho').is_file() and (ev / 'standalone.macho').is_file() and dev.is_dir(), 'Run full build first'
        layout = load_mod('layout', ROOT / 'scripts/liuqin-analysis/r100/package.py')
        segments, sections = layout.parse_macho_segments(ev / 'standalone.macho')
        gate_j = json.loads((ev / 'aes-fileset-gate.json').read_text())
        assert gate_j['status'] == 'PASS'
    elif not cli_args.build_only:
        if dev.exists():
            shutil.rmtree(dev)
        shutil.copytree(A7_WORK / 'device-a', dev, symlinks=True)

    if not cli_args.repack_only and not cli_args.build_only:
        # 1. Stage LiuqinAdreno730 driver & build script in isolated device-gpu
        drv_dir = dev / 'drivers/LiuqinAdreno730'
        (drv_dir / 'headers').mkdir(parents=True, exist_ok=True)
        for fn in ('LiuqinGpuBringup.cpp', 'LiuqinGpuPowerBoard.h', 'LiuqinA730HwInit.h', 'LiuqinGmuVotes.c', 'LiuqinGmu.c', 'LiuqinSmmu4KStreams.c'):
            shutil.copy2(SCRIPT_DIR / fn, drv_dir / fn)
        for fn in ('ShengGmuSource.h', 'ShengGmuCommandDbSource.h'):
            shutil.copy2(SCRIPT_DIR / 'headers' / fn, drv_dir / 'headers' / fn)
        shutil.copy2(SCRIPT_DIR / 'build-liuqin-adreno730.py', dev / 'scripts/build-liuqin-adreno730.py')

        # 2. Stage isolated NativeLegacyDisplay.cpp under LiuqinAdreno730 (never shadows tree/drivers/GopFramebuffer)
        #    and remove the 4 non-Adreno placeholder stubs from isolated build-liuqin-legacy-display.py
        nld_staged = drv_dir / 'NativeLegacyDisplay.cpp'
        shutil.copy2(SCRIPT_DIR / 'NativeLegacyDisplay.cpp', nld_staged)

        ld_script = dev / 'scripts/build-liuqin-legacy-display.py'
        lds = ld_script.read_text()
        dup_block = (
            'bool native_adreno_fences(uint32_t *,uint32_t *) {return false;}\n'
            'bool native_adreno_fences_detail(uint32_t *,uint32_t *,uint32_t *) {return false;}\n'
            'int native_gpu_trace_enabled(void) {return 0;}\n'
            'void native_gpu_trace_record(uint32_t,uint32_t,const uint64_t *,uint32_t) {}\n'
        )
        assert lds.count(dup_block) == 1, 'Expected exact 4-stub block in isolated build-liuqin-legacy-display.py'
        lds = lds.replace(dup_block, '')
        nld_call = "print(run(['python3', ROOT / 'scripts/build-arm-driver.py', 'NativeLegacyDisplay'], text=True), end='')"
        assert lds.count(nld_call) == 1, 'Expected exact NativeLegacyDisplay build call'
        nld_override = (
            f"nld_src = Path({str(nld_staged)!r})\n"
            "r_nld = json.loads((ROOT / 'build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/iokit/DEVELOPMENT/IOPlatformExpert.cpo.json').read_text().strip().rstrip(','))\n"
            "cmd_nld, args_nld, idx_nld = [], r_nld['arguments'], 0\n"
            "while idx_nld < len(args_nld):\n"
            "    v = args_nld[idx_nld]\n"
            "    if v == r_nld['file']: cmd_nld.append(str(nld_src))\n"
            "    elif v == '-o': cmd_nld += ['-o', str(OUT / 'NativeLegacyDisplay.o')]; idx_nld += 1\n"
            "    elif v in ('-MF', '-MT', '-MJ'): idx_nld += 1\n"
            "    elif v == '-Xclang' and args_nld[idx_nld + 1].startswith('-W'): idx_nld += 1\n"
            "    elif not v.startswith('-W'): cmd_nld.append(v)\n"
            "    idx_nld += 1\n"
            "cmd_nld += ['-Wall', '-Wextra', '-Werror', '-Wno-unused-parameter', '-Wno-unnecessary-virtual-specifier', '-Wno-c99-designator',\n"
            "            '-Wno-reorder-init-list', '-Wno-deprecated-enum-enum-conversion', '-Wno-overriding-option',\n"
            "            '-Wno-missing-designated-field-initializers', '-Wno-unused-but-set-variable', '-Wno-unused-but-set-global',\n"
            "            '-I', str(ROOT / '.cache/xnu-work/osfmk'), '-I', str(OUT), '-I', str(ROOT / 'drivers/GopFramebuffer')]\n"
            "run(cmd_nld, cwd=r_nld['directory'])\n"
        )
        lds = lds.replace(nld_call, nld_override)
        ld_script.write_text(lds)

        # 3. Wire into isolated device-gpu/board.toml and device-gpu/configs/liuqin_defconfig
        bt = dev / 'board.toml'
        bts = bt.read_text()
        needle_bt = '  "build-identity-ethernet.py",'
        assert bts.count(needle_bt) == 1
        bt.write_text(bts.replace(needle_bt, needle_bt + '\n  "build-liuqin-adreno730.py",'))

        dc = dev / 'configs/liuqin_defconfig'
        dcs = dc.read_text()
        needle_dc = '-Wl,-force_load,{tree}/build/liuqin-identity-ethernet/libLiuqinIdentityEthernet.a"'
        assert dcs.count(needle_dc) == 1
        dc.write_text(
            dcs.replace(
                needle_dc,
                needle_dc[:-1] + ' -Wl,-force_load,{tree}/build/liuqin-adreno730/libLiuqinAdreno730.a"',
            )
        )

        # 4. Extend isolated device-gpu's xnu patch with post-ethernet GPU bringup spawn hook
        staged_bsd = (A7_WORK / 'staged-sources/bsd/kern/bsd_init.c').read_text()
        hook_needle = '\tliuqin_identity_ethernet_start();\n'
        assert staged_bsd.count(hook_needle) == 1
        new_bsd = staged_bsd.replace(
            hook_needle,
            hook_needle
            + '\t/* r102-gpu: SM8475 / Adreno 730.1 KMD bring-up worker. */\n'
            + '\textern void liuqin_gpu_bringup_start(void);\n'
            + '\tliuqin_gpu_bringup_start();\n',
        )
        if cli_args.with_input:
            input_sources = SCRIPT_DIR.parent / 'r103-input'
            input_driver = dev / 'drivers/LiuqinInput'
            input_driver.mkdir(parents=True, exist_ok=True)
            for source in input_sources.iterdir():
                if source.suffix in ('.c', '.cpp', '.h', '.json'):
                    shutil.copy2(source, input_driver / source.name)
            shutil.copy2(input_sources / 'build-liuqin-input.py', dev / 'scripts/build-liuqin-input.py')
            text = bt.read_text()
            bt.write_text(text.replace(needle_bt, needle_bt + '\n  "build-liuqin-input.py",'))
            text = dc.read_text()
            library = '-Wl,-force_load,{tree}/build/liuqin-adreno730/libLiuqinAdreno730.a'
            assert text.count(library) == 1
            dc.write_text(text.replace(library, library + ' -Wl,-force_load,{tree}/build/liuqin-input/libLiuqinInput.a'))
            new_bsd = new_bsd.replace(hook_needle, hook_needle + '\textern void liuqin_input_start(void);\n\tliuqin_input_start();\n')
        if cli_args.with_wireless:
            # Bridge LiuqinIdentityEthernet (en0) to WifiNet without altering IOEthernetController's vtable.
            eth_cpp = dev / 'drivers/LiuqinIdentityEthernet/LiuqinIdentityEthernet.cpp'
            eth_src = eth_cpp.read_text()
            eth_src = eth_src.replace(
                '#include <IOKit/IOPlatformExpert.h>\n',
                '#include <IOKit/IOPlatformExpert.h>\n#include <IOKit/IODeviceTreeSupport.h>\n',
                1,
            )
            eth_src = eth_src.replace(
                'static constexpr UInt8 address[6]={0x02,0x4c,0x51,0x10,0x00,0x01};\n',
                'static int (*volatile gWifiOutput)(mbuf_t);\n'
                'static volatile bool gWifiLink;\n'
                'static void liuqinRadioAddress(UInt8 m[6]) {\n'
                '    UInt8 fallback[6]={0x02,0x4c,0x51,0x10,0x00,0x01};\n'
                '    memcpy(m,fallback,6);\n'
                '    IORegistryEntry *chosen=IORegistryEntry::fromPath("/chosen",gIODTPlane);\n'
                '    OSData *id=chosen?OSDynamicCast(OSData,chosen->getProperty("unique-chip-id")):nullptr;\n'
                '    uint64_t seed=0;\n'
                '    if(id && id->getLength()>=sizeof(seed))memcpy(&seed,id->getBytesNoCopy(),sizeof(seed));\n'
                '    OSSafeReleaseNULL(chosen);\n'
                '    if(!seed)return;\n'
                '    uint64_t h=0xcbf29ce484222325ull;\n'
                '    for(unsigned i=0;i<8;++i)h=(h^((seed>>(8*i))&0xff))*0x100000001b3ull;\n'
                '    for(unsigned i=0;i<6;++i)m[i]=(UInt8)(h>>(8*i));\n'
                '    m[0]=(UInt8)((m[0]&0xfe)|0x02);\n'
                '}\n',
                1,
            )
            eth_src = eth_src.replace(
                '    IOEthernetInterface *interface=nullptr;\n',
                '    IOEthernetInterface *interface=nullptr;\n'
                '    const IONetworkMedium *medium=nullptr;\n'
                '    UInt8 address[6]={};\n'
                '    bool enabled=false;\n',
                1,
            )
            eth_src = eth_src.replace(
                '        if(!IOEthernetController::start(provider))return false;\n'
                '        OSDictionary *dict=OSDictionary::withCapacity(1);\n'
                '        IONetworkMedium *medium=IONetworkMedium::medium(kIOMediumEthernetAuto,0);\n'
                '        bool ok=dict && medium && IONetworkMedium::addMedium(dict,medium) && publishMediumDictionary(dict);\n'
                '        OSSafeReleaseNULL(medium);OSSafeReleaseNULL(dict);\n',
                '        liuqinRadioAddress(address);\n'
                '        if(!IOEthernetController::start(provider))return false;\n'
                '        OSDictionary *dict=OSDictionary::withCapacity(1);\n'
                '        IONetworkMedium *m=IONetworkMedium::medium(IOMediumType(kIOMediumEthernetAuto)|IOMediumType(kIOMediumOptionFullDuplex),1000ULL*1000*1000);\n'
                '        bool ok=dict && m && IONetworkMedium::addMedium(dict,m) && publishMediumDictionary(dict);\n'
                '        medium=ok?IONetworkMedium::getMediumWithType(getMediumDictionary(),m->getType()):nullptr;\n'
                '        OSSafeReleaseNULL(m);OSSafeReleaseNULL(dict);\n',
                1,
            )
            eth_src = eth_src.replace(
                '    IOReturn enable(IONetworkInterface *) override {setLinkStatus(kIONetworkLinkValid,nullptr);return kIOReturnSuccess;}\n'
                '    IOReturn disable(IONetworkInterface *) override {setLinkStatus(kIONetworkLinkValid,nullptr);return kIOReturnSuccess;}\n'
                '    UInt32 outputPacket(mbuf_t packet,void *) override {\n'
                '        if(packet)freePacket(packet);\n'
                '        return kIOReturnOutputDropped;\n'
                '    }\n',
                '    void wifiLink(bool up) {\n'
                '        if(up && medium)setLinkStatus(kIONetworkLinkValid|kIONetworkLinkActive,medium,1000ULL*1000*1000);\n'
                '        else setLinkStatus(kIONetworkLinkValid,nullptr);\n'
                '    }\n'
                '    bool isEnabled() const {return enabled;}\n'
                '    IOReturn enable(IONetworkInterface *) override {enabled=true;wifiLink(gWifiLink);return kIOReturnSuccess;}\n'
                '    IOReturn disable(IONetworkInterface *) override {enabled=false;setLinkStatus(kIONetworkLinkValid,nullptr);return kIOReturnSuccess;}\n'
                '    UInt32 outputPacket(mbuf_t packet,void *) override {\n'
                '        if(int (*out)(mbuf_t)=gWifiOutput){out(packet);return kIOReturnOutputSuccess;}\n'
                '        if(packet)freePacket(packet);\n'
                '        return kIOReturnOutputDropped;\n'
                '    }\n',
                1,
            )
            eth_src += (
                '\nextern "C" bool sheng_ethernet_wifi_attach(int (*output)(mbuf_t)) {\n'
                '    LiuqinIdentityEthernet *c=liveController;\n'
                '    if(!c || !output)return false;\n'
                '    gWifiLink=false; gWifiOutput=output;\n'
                '    if(c->isEnabled())c->wifiLink(false);\n'
                '    return true;\n'
                '}\n'
                'extern "C" void sheng_ethernet_wifi_link(bool up) {\n'
                '    gWifiLink=up;\n'
                '    LiuqinIdentityEthernet *c=liveController;\n'
                '    if(c && c->isEnabled())c->wifiLink(up);\n'
                '}\n'
                'extern "C" ifnet_t sheng_ethernet_ifnet(void) {\n'
                '    LiuqinIdentityEthernet *c=liveController;\n'
                '    IOEthernetInterface *i=c?c->getIdentityInterface():nullptr;\n'
                '    return i?i->getIfnet():nullptr;\n'
                '}\n'
            )
            eth_cpp.write_text(eth_src)
            wl_sources = SCRIPT_DIR.parent / 'r103-wireless'
            wl_driver = dev / 'drivers/LiuqinWireless'
            wl_driver.mkdir(parents=True, exist_ok=True)
            for source in wl_sources.iterdir():
                if source.suffix in ('.c', '.cpp', '.h'):
                    shutil.copy2(source, wl_driver / source.name)
            shutil.copy2(wl_sources / 'build-liuqin-wireless.py', dev / 'scripts/build-liuqin-wireless.py')
            text = bt.read_text()
            bt.write_text(text.replace(needle_bt, needle_bt + '\n  "build-liuqin-wireless.py",'))
            text = dc.read_text()
            library = '-Wl,-force_load,{tree}/build/liuqin-adreno730/libLiuqinAdreno730.a'
            assert text.count(library) == 1
            dc.write_text(text.replace(library, library + ' -Wl,-force_load,{tree}/build/liuqin-wireless/libLiuqinWireless.a'))
            new_bsd = new_bsd.replace(hook_needle, hook_needle + '\textern void liuqin_bluetooth_start(void);\n\tliuqin_bluetooth_start();\n\textern void liuqin_wifi_pcie_start(void);\n\tliuqin_wifi_pcie_start();\n')

        prep = json.loads((A7_WORK / 'preparation.json').read_text())
        patch_chunks = []
        for rel in prep['changed_kernel_files']:
            orig_p = A7_WORK / 'frozen-r100b-source' / rel
            original = orig_p.read_text() if orig_p.exists() else ''
            text = new_bsd if rel == 'bsd/kern/bsd_init.c' else (A7_WORK / 'staged-sources' / rel).read_text()
            patch_chunks.append(
                ''.join(
                    difflib.unified_diff(
                        original.splitlines(True),
                        text.splitlines(True),
                        fromfile='a/' + rel if original else '/dev/null',
                        tofile='b/' + rel,
                    )
                )
            )
        patch_file = next((dev / 'patches/xnu').glob('*liuqin-r101.patch'))
        patch_file.write_text(''.join(patch_chunks))

        # 4B. Wire self-contained liuqin_gpu_addon_install() via bsd/kern/liuqin_gpu_addon.h + 2 tiny hunks in kern_exec.c
        addon_patch_name = 'zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz-liuqin-r102-gpu-addon.patch'
        addon_hdr = r'''/* Self-contained NGPUADD2 unpacker for liuqin macOS 27.3 /Library/GPUBundles. */
#include <libkern/zlib.h>
#include <sys/xattr.h>
extern int native_ram_block_gpu_addon(const uint8_t **, uint64_t *) __attribute__((weak_import));
volatile int liuqin_addon_ready = 0;
static voidpf lq_addon_zalloc(voidpf opaque __unused, uInt items, uInt size) {
	size_t bytes = (size_t)items * size + 16;
	uint8_t *blk = kalloc_data(bytes, Z_WAITOK | Z_ZERO);
	if (!blk) return Z_NULL;
	memcpy(blk, &bytes, sizeof(bytes));
	return blk + 16;
}
static void lq_addon_zfree(voidpf opaque __unused, voidpf addr) {
	uint8_t *blk = (uint8_t *)addr - 16;
	size_t bytes = 0;
	memcpy(&bytes, blk, sizeof(bytes));
	kfree_data(blk, bytes);
}
static int lq_addon_inflate(const uint8_t *packed, uint64_t packed_sz, uint8_t *data, uint64_t sz) {
	z_stream s;
	memset(&s, 0, sizeof(s));
	s.zalloc = lq_addon_zalloc; s.zfree = lq_addon_zfree;
	s.next_in = (Bytef *)(uintptr_t)packed; s.avail_in = (uInt)packed_sz;
	s.next_out = data; s.avail_out = (uInt)sz;
	if (inflateInit(&s) != Z_OK) return ENOMEM;
	int r = inflate(&s, Z_FINISH);
	inflateEnd(&s);
	return (r == Z_STREAM_END && s.total_out == sz && !s.avail_in) ? 0 : EINVAL;
}
static int lq_addon_protect_one(const char *path) {
	static const char cls[] = "KernelExtensionManagement";
	vfs_context_t ctx = vfs_context_kernel();
	vnode_t vp = NULLVP;
	int err = vnode_lookup(path, VNODE_LOOKUP_NOFOLLOW, &vp, ctx);
	if (err) return err;
	uio_t auio = uio_create(1, 0, UIO_SYSSPACE, UIO_WRITE);
	if (!auio) { vnode_put(vp); return ENOMEM; }
	uio_addiov(auio, CAST_USER_ADDR_T(cls), sizeof(cls) - 1);
	err = vn_setxattr(vp, "com.apple.rootless", auio, XATTR_NOSECURITY, ctx);
	uio_free(auio);
	if (!err) {
		struct vnode_attr va;
		VATTR_INIT(&va); VATTR_WANTED(&va, va_flags);
		err = vnode_getattr(vp, &va, ctx);
		if (!err && !(va.va_flags & SF_RESTRICTED)) {
			uint32_t fl = va.va_flags | SF_RESTRICTED;
			VATTR_INIT(&va); VATTR_SET(&va, va_flags, fl);
			err = vnode_setattr(vp, &va, ctx);
		}
	}
	vnode_put(vp);
	return err;
}
static int lq_addon_protect(const char *path) {
	char part[192];
	strlcpy(part, path, sizeof(part));
	int first = 0;
	for (size_t i = sizeof("/Library/GPUBundles/") - 1; part[i]; ++i) {
		if (part[i] != '/') continue;
		part[i] = 0;
		int e = lq_addon_protect_one(part);
		part[i] = '/';
		if (e && !first) first = e;
	}
	int e = lq_addon_protect_one(part);
	return first ? first : e;
}
static void liuqin_gpu_addon_install(proc_t p, user_addr_t scratch) {
	const uint8_t *addon = NULL;
	uint64_t bytes = 0;
	if (!native_ram_block_gpu_addon || !native_ram_block_gpu_addon(&addon, &bytes)) {
		printf("LQ102GPU ADDON none\n");
		return;
	}
	uint32_t count = 0; uint64_t total = 0;
	if (bytes < 24 || memcmp(addon, "NGPUADD2", 8)) { printf("LQ102GPU ADDON bad_hdr\n"); return; }
	memcpy(&count, addon + 8, 4); memcpy(&total, addon + 16, 8);
	if (total != bytes || !count || count > 4096) { printf("LQ102GPU ADDON bad_meta\n"); return; }
	int written = 0, failed = 0, last_err = 0, prot_ok = 0, prot_err = 0;
	vfs_context_t kctx = vfs_context_kernel();
	uint64_t at = 24;
	for (uint32_t i = 0; i < count; ++i) {
		uint32_t nb = 0, mode = 0; uint64_t sz = 0, packed = 0;
		if (bytes - at < 24) { failed++; last_err = EINVAL; break; }
		memcpy(&nb, addon + at, 4); memcpy(&mode, addon + at + 4, 4);
		memcpy(&sz, addon + at + 8, 8); memcpy(&packed, addon + at + 16, 8);
		at += 24;
		const char *name = (const char *)(addon + at);
		uint64_t npad = (nb + 7) & ~7ULL, ppad = (packed + 7) & ~7ULL;
		if (nb < 2 || nb > 160 || bytes - at < npad + ppad || name[nb - 1]) { failed++; last_err = EINVAL; break; }
		at += npad;
		bool is_bundle = !strncmp(name, "GPUBundles/", 11);
		bool is_library = is_bundle || !strncmp(name, "LaunchDaemons/", 14);
		char path[192];
		snprintf(path, sizeof(path), is_library ? "/Library/%s" : "/private/var/ngpu/%s", name);
		char dir[192]; strlcpy(dir, path, sizeof(dir));
		for (size_t k = (is_library ? 9 : 1); dir[k]; ++k) {
			if (dir[k] != '/') continue;
			dir[k] = 0; (void)lq_mkdir_p(dir, p, scratch); dir[k] = '/';
		}
		uint8_t *buf = kalloc_data(sz ? sz : 1, Z_WAITOK);
		int err = buf ? lq_addon_inflate(addon + at, packed, buf, sz) : ENOMEM;
		if (!err) {
			vnode_t vp = NULLVP;
			err = vnode_open(path, O_CREAT | O_TRUNC | FWRITE | O_NOFOLLOW, (int)mode, 0, &vp, kctx);
			if (!err) {
				int resid = 0;
				err = vn_rdwr(UIO_WRITE, vp, (caddr_t)buf, (int)sz, 0, UIO_SYSSPACE, IO_NOAUTH | IO_UNIT, vfs_context_ucred(kctx), &resid, p);
				if (!err && resid) err = EIO;
				if (!err) {
					struct vnode_attr va; VATTR_INIT(&va);
					VATTR_SET(&va, va_uid, 0); VATTR_SET(&va, va_gid, 0);
					VATTR_SET(&va, va_mode, (int)mode); VATTR_SET(&va, va_data_size, sz);
					err = vnode_setattr(vp, &va, kctx);
				}
				if (!err) err = VNOP_FSYNC(vp, MNT_WAIT, kctx);
				int ce = vnode_close(vp, FWRITE, kctx);
				if (!err) err = ce;
			}
		}
		if (buf) kfree_data(buf, sz ? sz : 1);
		if (!err) {
			written++;
			if (is_bundle) {
				int pe = lq_addon_protect(path);
				if (pe) prot_err = pe; else prot_ok++;
			}
		} else { failed++; last_err = err; }
		at += ppad;
	}
	printf("LQ102GPU ADDON files=%u written=%d failed=%d err=%d prot=%d prot_err=%d\n",
	    count, written, failed, last_err, prot_ok, prot_err);
	{
		extern volatile int native_bindfs_boot_mount;
		static const struct {
			const char *src, *dst, *lower, *upper;
		} kBtMounts[2] = {
			{ "/private/var/ngpu/lib", "/usr/lib", "/usr/lib/dyld", "/usr/lib/QcaBTType0.dylib" },
			{ "/private/var/ngpu/sbin", "/usr/sbin", "/usr/sbin/notifyd", "/usr/sbin/QcaBluetooth.runtime" },
		};
		int st[2] = { 0, 0 }, err[2] = { -1, -1 };
		for (int mi = 0; mi < 2; ++mi) {
			if (mi == 1 && (st[0] != 5 || err[0] != 0)) break;
			vnode_t probe = NULLVP;
			st[mi] = 1;
			int e = vnode_lookup(kBtMounts[mi].src, 0, &probe, vfs_context_current());
			if (e) { err[mi] = e; continue; }
			vnode_put(probe); probe = NULLVP;
			st[mi] = 2;
			struct mount_args req = {
				.type = scratch + 0x600,
				.path = scratch + 0x620,
				.flags = MNT_RDONLY | MNT_UNION,
				.data = scratch + 0x700,
			};
			int32_t res = 0;
			if ((e = copyout("bindfs", req.type, 7)) ||
			    (e = copyout(kBtMounts[mi].dst, req.path, strlen(kBtMounts[mi].dst) + 1)) ||
			    (e = copyout(kBtMounts[mi].src, req.data, strlen(kBtMounts[mi].src) + 1))) {
				err[mi] = e; continue;
			}
			native_bindfs_boot_mount = 1;
			e = mount(p, &req, &res);
			native_bindfs_boot_mount = 0;
			if (e) { err[mi] = e; continue; }
			st[mi] = 3;
			e = vnode_lookup(kBtMounts[mi].lower, 0, &probe, vfs_context_current());
			if (!e) {
				vnode_put(probe); probe = NULLVP;
				st[mi] = 4;
				e = vnode_lookup(kBtMounts[mi].upper, 0, &probe, vfs_context_current());
				if (!e) { vnode_put(probe); probe = NULLVP; st[mi] = 5; }
			}
			err[mi] = e;
		}
		printf("LQ103 BT_RUNTIME lib=%d/%d sbin=%d/%d\n", st[0], err[0], st[1], err[1]);
	}
	__atomic_store_n(&liuqin_addon_ready, 1, __ATOMIC_RELEASE);
}
'''
        # Generate macOS 27.3 desktop skip-setup + auto-login seed data (matches scripts/make-macos-data-seed.py)
        def c_bytes(name: str, data: bytes) -> str:
            body = ','.join(str(b) for b in data) if data else '0'
            return (
                f'static const uint8_t {name}[{max(1, len(data))}] '
                f'__attribute__((section("__BOOTDATA,__data"))) = {{{body}}};\n'
                f'static const uint32_t {name}_len = {len(data)}u;\n'
            )

        skip_items = [
            'Accessibility', 'AdditionalPrivacySettings', 'Appearance', 'AppleID', 'AppStore',
            'Biometric', 'Diagnostics', 'DisplayTone', 'EnableLockdownMode', 'FileVault',
            'iCloudDiagnostics', 'iCloudStorage', 'Intelligence', 'Location', 'OSShowcase',
            'Privacy', 'Restore', 'Safety', 'ScreenTime', 'Siri', 'SoftwareUpdate',
            'TermsOfAddress', 'TextSize', 'TOS', 'TouchIDPrompt', 'UnlockWithWatch',
            'Wallpaper', 'Welcome',
        ]
        setup_skip_plist = plistlib.dumps({'SkipSetupItems': skip_items}, fmt=plistlib.FMT_XML)
        salt = hashlib.sha256(b'liuqin-unixnu-salt-v1').digest()
        iterations = 50000
        entropy = hashlib.pbkdf2_hmac('sha512', b'unixnu', salt, iterations, 128)
        shadow = plistlib.dumps(
            {'SALTED-SHA512-PBKDF2': {'entropy': entropy, 'iterations': iterations, 'salt': salt}},
            fmt=plistlib.FMT_BINARY,
        )
        user_guid = str(uuid.uuid5(uuid.NAMESPACE_DNS, 'unixnu.liuqin.local')).upper()
        user_plist = plistlib.dumps({
            'name': ['unixnu'], 'realname': ['UniXNU'], 'uid': ['501'], 'gid': ['20'],
            'home': ['/Users/unixnu'], 'shell': ['/bin/zsh'], 'generateduid': [user_guid],
            'passwd': ['********'],
            'authentication_authority': [';ShadowHash;HASHLIST:<SALTED-SHA512-PBKDF2>'],
            'ShadowHashData': [shadow],
            '_writers_passwd': ['unixnu'], '_writers_realname': ['unixnu'], '_writers_hint': ['unixnu'],
        }, fmt=plistlib.FMT_BINARY)
        login_plist = plistlib.dumps({'autoLoginUser': 'unixnu'}, fmt=plistlib.FMT_BINARY)
        kc_key = bytes.fromhex('7d895223d2bcddeaa3b91f')
        kc_plain = b'unixnu\x00'
        kc_plain += bytes(-len(kc_plain) % 12)
        kc_data = bytes(b ^ kc_key[i % len(kc_key)] for i, b in enumerate(kc_plain))
        tu_debug_data = b'sysmem,nocb\n'
        disabled_plist = plistlib.dumps({
            'com.apple.mobileactivationd': True,
            'com.apple.watchdogd': True,
            'com.apple.logd_helper': True,
            'com.apple.analyticsd': True,
            'com.apple.coresymbolicationd': True,
            'com.apple.PerfPowerServices': True,
            'com.apple.symptomsd-diag': True,
            'com.apple.triald.system': True,
            'com.apple.SubmitDiagInfo': True,
            'com.apple.spindump': True,
            'com.apple.tailspind': True,
            'com.apple.ReportCrash': True,
            'com.apple.ReportCrash.Root': True,
            'com.apple.osanalytics.osanalyticshelper': True,
            'com.apple.photoanalysisd': True,
            'com.apple.mediaanalysisd': True,
            'com.apple.softwareupdated': True,
            'com.apple.mobileassetd.v2': True,
            'com.apple.mobileassetd': True,
        }, fmt=plistlib.FMT_XML)
        disabled_user_plist = plistlib.dumps({
            'com.apple.chronod': True,
            'com.apple.contextstored': True,
            'com.apple.ContextStoreAgent': True,
            'com.apple.imagent': True,
            'com.apple.callservicesd': True,
            'com.apple.identityservicesd': True,
            'com.apple.BiomeAgent': True,
            'com.apple.biomesyncd': True,
            'com.apple.bird': True,
            'com.apple.cloudd': True,
            'com.apple.itunescloudd': True,
            'com.apple.corespotlightd': True,
            'com.apple.spotlightknowledged': True,
            'com.apple.donotdisturbd': True,
            'com.apple.homed': True,
            'com.apple.routined': True,
            'com.apple.duetexpertd': True,
            'com.apple.knowledge-agent': True,
            'com.apple.ReportCrash': True,
            'com.apple.photoanalysisd': True,
            'com.apple.mediaanalysisd': True,
            'com.apple.photolibraryd': True,
            'com.apple.corespeechd': True,
            'com.apple.localspeechrecognition': True,
            'com.apple.assistantd': True,
            'com.apple.siriinferenced': True,
            'com.apple.siriknowledged': True,
            'com.apple.generativeexperiencesd': True,
            'com.apple.intelligenceplatformd': True,
            'com.apple.intelligenceflowd': True,
            'com.apple.modelcatalogd': True,
            'com.apple.SetStoreUpdateService': True,
            'com.apple.ScreenTimeAgent': True,
        }, fmt=plistlib.FMT_XML)

        desktop_seed_c = (
            c_bytes('lq_seed_setup_skip', setup_skip_plist)
            + c_bytes('lq_seed_user_plist', user_plist)
            + c_bytes('lq_seed_login_plist', login_plist)
            + c_bytes('lq_seed_kcpassword', kc_data)
            + c_bytes('lq_seed_tu_debug', tu_debug_data)
            + c_bytes('lq_seed_disabled_plist', disabled_plist)
            + c_bytes('lq_seed_disabled_user_plist', disabled_user_plist)
            + r'''
static int lq_write_owned(proc_t p, user_addr_t scratch, const char *path, const uint8_t *data, uint32_t sz, int mode, uint32_t uid, uint32_t gid) {
	vfs_context_t kctx = vfs_context_kernel();
	char dir[192]; strlcpy(dir, path, sizeof(dir));
	for (size_t k = 1; dir[k]; ++k) {
		if (dir[k] != '/') continue;
		dir[k] = 0; (void)lq_mkdir_p(dir, p, scratch); dir[k] = '/';
	}
	vnode_t vp = NULLVP;
	int err = vnode_open(path, O_CREAT | O_TRUNC | FWRITE | O_NOFOLLOW, mode, 0, &vp, kctx);
	if (err) return err;
	if (sz) {
		int resid = 0;
		err = vn_rdwr(UIO_WRITE, vp, (caddr_t)(uintptr_t)data, (int)sz, 0, UIO_SYSSPACE, IO_NOAUTH | IO_UNIT, vfs_context_ucred(kctx), &resid, p);
		if (!err && resid) err = EIO;
	}
	if (!err) {
		struct vnode_attr va; VATTR_INIT(&va);
		VATTR_SET(&va, va_uid, uid); VATTR_SET(&va, va_gid, gid);
		VATTR_SET(&va, va_mode, mode); VATTR_SET(&va, va_data_size, sz);
		err = vnode_setattr(vp, &va, kctx);
	}
	if (!err) err = VNOP_FSYNC(vp, MNT_WAIT, kctx);
	int ce = vnode_close(vp, FWRITE, kctx);
	return err ? err : ce;
}
static int lq_mkdir_owned(proc_t p, user_addr_t scratch, const char *path, int mode, uint32_t uid, uint32_t gid) {
	int err = lq_mkdir_p(path, p, scratch);
	if (err && err != EEXIST) return err;
	vfs_context_t kctx = vfs_context_kernel();
	vnode_t vp = NULLVP;
	err = vnode_lookup(path, VNODE_LOOKUP_NOFOLLOW, &vp, kctx);
	if (err) return err;
	struct vnode_attr va; VATTR_INIT(&va);
	VATTR_SET(&va, va_uid, uid); VATTR_SET(&va, va_gid, gid); VATTR_SET(&va, va_mode, mode);
	err = vnode_setattr(vp, &va, kctx);
	vnode_put(vp);
	return err;
}
static void liuqin_desktop_seed_install(proc_t p, user_addr_t scratch) {
	int ok = 0, fail = 0, last_err = 0, e = 0;
	static const uint8_t empty[1] = {0};
	e = lq_write_owned(p, scratch, "/private/var/ngpu/tu_debug", lq_seed_tu_debug, lq_seed_tu_debug_len, 0644, 0, 0);
	if (e) { fail++; last_err = e; } else ok++;
	e = lq_write_owned(p, scratch, "/private/var/db/com.apple.xpc.launchd/disabled.plist", lq_seed_disabled_plist, lq_seed_disabled_plist_len, 0644, 0, 0);
	if (e) { fail++; last_err = e; } else ok++;
	e = lq_write_owned(p, scratch, "/private/var/db/com.apple.xpc.launchd/disabled.501.plist", lq_seed_disabled_user_plist, lq_seed_disabled_user_plist_len, 0644, 0, 0);
	if (e) { fail++; last_err = e; } else ok++;
	e = lq_write_owned(p, scratch, "/private/var/db/.AppleSetupDone", empty, 0, 0644, 0, 0);
	if (e) { fail++; last_err = e; } else ok++;
	e = lq_write_owned(p, scratch, "/Library/Managed Preferences/com.apple.SetupAssistant.managed.plist", lq_seed_setup_skip, lq_seed_setup_skip_len, 0644, 0, 0);
	if (e) { fail++; last_err = e; } else ok++;
	e = lq_write_owned(p, scratch, "/private/var/db/dslocal/nodes/Default/users/unixnu.plist", lq_seed_user_plist, lq_seed_user_plist_len, 0600, 0, 0);
	if (e) { fail++; last_err = e; } else ok++;
	e = lq_write_owned(p, scratch, "/Library/Preferences/com.apple.loginwindow.plist", lq_seed_login_plist, lq_seed_login_plist_len, 0644, 0, 0);
	if (e) { fail++; last_err = e; } else ok++;
	e = lq_write_owned(p, scratch, "/private/etc/kcpassword", lq_seed_kcpassword, lq_seed_kcpassword_len, 0600, 0, 0);
	if (e) { fail++; last_err = e; } else ok++;
	static const char *const hdirs[] = {
		"/Users/unixnu", "/Users/unixnu/Desktop", "/Users/unixnu/Documents", "/Users/unixnu/Downloads",
		"/Users/unixnu/Library", "/Users/unixnu/Library/Preferences", "/Users/unixnu/Library/Caches",
		"/Users/unixnu/Library/Application Support", "/Users/unixnu/Movies", "/Users/unixnu/Music",
		"/Users/unixnu/Pictures", "/Users/unixnu/Public",
	};
	for (unsigned i = 0; i < sizeof(hdirs) / sizeof(hdirs[0]); ++i) {
		int m = (i == 0) ? 0750 : (i == 11 ? 0755 : 0700);
		e = lq_mkdir_owned(p, scratch, hdirs[i], m, 501, 20);
		if (e) { fail++; last_err = e; } else ok++;
	}
	e = lq_write_owned(p, scratch, "/Users/unixnu/.skipbuddy", empty, 0, 0644, 501, 20);
	if (e) { fail++; last_err = e; } else ok++;
	printf("LQ102GPU DESKTOP_SEED ok=%d fail=%d err=%d\n", ok, fail, last_err);
}
'''
        )
        addon_hdr = addon_hdr + desktop_seed_c
        hdr_diff = ''.join(difflib.unified_diff([], addon_hdr.splitlines(True), fromfile='/dev/null', tofile='b/bsd/kern/liuqin_gpu_addon.h'))
        kern_exec_diff = (
            '--- a/bsd/kern/kern_exec.c\n'
            '+++ b/bsd/kern/kern_exec.c\n'
            '@@ -7853,6 +7853,19 @@\n'
            ' \t\t\tbreak;\n'
            ' \t\t}\n'
            ' \t}\n'
            '+\tif (!denied && have_path) {\n'
            '+\t\tconst char *lq_b = path;\n'
            '+\t\tfor (const char *lq_p = path; *lq_p; lq_p++) {\n'
            '+\t\t\tif (*lq_p == \'/\') lq_b = lq_p + 1;\n'
            '+\t\t}\n'
            '+\t\tif (strcmp(lq_b, "coresymbolicationd") == 0 ||\n'
            '+\t\t    strcmp(lq_b, "analyticsd") == 0 ||\n'
            '+\t\t    strcmp(lq_b, "PerfPowerServices") == 0 ||\n'
            '+\t\t    strcmp(lq_b, "com.apple.geod") == 0 ||\n'
            '+\t\t    strcmp(lq_b, "logd_helper") == 0) {\n'
            '+\t\t\tdenied = true;\n'
            '+\t\t}\n'
            '+\t}\n'
            ' \tzfree(ZV_NAMEI, path);\n'
            ' \treturn denied;\n'
            ' }\n'
            '@@ -10011,4 +10024,5 @@\n'
            ' #include "liuqin_data_populate.h"\n'
            ' #include "liuqin_data_layout.h"\n'
            '+#include "liuqin_gpu_addon.h"\n'
            ' #include "liuqin_mount_probe.h"\n'
            ' #include "liuqin_mount_adapter.h"\n'
            '@@ -10247,6 +10261,10 @@\n'
            ' \t\tunsigned layout=0;\n'
            ' \t\tif (!probe_error && populate==1 && PE_parse_boot_argn("liuqin-data-layout",&layout,sizeof(layout)) && layout==1)\n'
            ' \t\t\tprobe_error=liuqin_data_layout(p,(user_addr_t)scratch_addr);\n'
            '+\t\tif (!probe_error && layout==1) {\n'
            '+\t\t\tliuqin_gpu_addon_install(p,(user_addr_t)scratch_addr);\n'
            '+\t\t\tliuqin_desktop_seed_install(p,(user_addr_t)scratch_addr);\n'
            '+\t\t}\n'
            ' \t\tprintf("LIUQIN SCRATCH RESULT: err=%d volatile=1 userspace_started=0\\n",probe_error);\n'
            ' \t\tunsigned user_probe=0;\n'
            ' \t\tif (!probe_error && layout==1 && PE_parse_boot_argn("liuqin-mount-probe",&user_probe,sizeof(user_probe)) && user_probe==1) {\n'
        )
        # The desktop build keeps diagnostics in the USB ring. Disable the
        # matrix/status painters from boot, including callers which bypass
        # the scrolling console's suspend flag.
        orig_dbg = (A7_WORK / 'staged-sources/bsd/dev/liuqin_debug.c').read_text()
        dbg_target = (
            'static volatile uint32_t *\n'
            'lq_fb_io_row(unsigned row)\n'
            '{\n'
        )
        assert orig_dbg.count(dbg_target) == 1
        new_dbg = orig_dbg.replace(
            dbg_target,
            'static int lq_fb_suspended;\n\n' + dbg_target + '\treturn NULL; /* Desktop: debug painters disabled. */\n',
        )
        assert new_dbg.count('volatile int liuqin_debug_mute;') == 1
        if not cli_args.usb_debug:
            new_dbg = new_dbg.replace('volatile int liuqin_debug_mute;',
                                      'volatile int liuqin_debug_mute = 1; /* USB mirror explicitly disabled. */')
        new_dbg = new_dbg.replace('liuqin_debug_at_line_start(void)\n{\n',
                                  'liuqin_debug_at_line_start(void)\n{\n\tif (liuqin_debug_mute) return 1;\n')
        assert new_dbg.count('static int lq_fb_suspended;\n') == 2
        new_dbg = new_dbg.replace(
            'static int lq_fb_suspended;\nstatic vm_map_t lq_init_map;\n',
            'static vm_map_t lq_init_map;\n',
        )
        dbg_diff = ''.join(difflib.unified_diff(
            orig_dbg.splitlines(True), new_dbg.splitlines(True),
            fromfile='a/bsd/dev/liuqin_debug.c', tofile='b/bsd/dev/liuqin_debug.c',
        ))
        # On Qualcomm SM8475, changing a page's cache attribute from Write-Back to Write-Combining
        # (VM_WIMG_WCOMB) in pmap_batch_set_cache_attributes_internal() does not flush dirty lines
        # of the VM's cacheable zero-fill. Without pmap_sync_wimg(), stale zero-fill lines evict
        # over WC GPU BOs in DRAM and trip the WC audit / GPU hang (matching UniXNU-sheng's fix
        # in osfmk/arm/pmap/pmap.c — the pmap compiled by DEVELOPMENT_ARM64_BCM2837).
        pmap_diff = (
            '--- a/osfmk/arm/pmap/pmap.c\n'
            '+++ b/osfmk/arm/pmap/pmap.c\n'
            '@@ -6027,7 +6027,7 @@\n'
            ' \t\tpte |= ARM_PTE_NX | ARM_PTE_PNX;\n'
            ' \t\tbreak;\n'
            ' \tcase VM_WIMG_RT:\n'
            '-\t\tif (is_dram_addr(pa)) {\n'
            '+\t\tif (is_dram_addr(pa) || pa_valid(pa)) {\n'
            ' \t\t\tpte = ARM_PTE_ATTRINDX(CACHE_ATTRINDX_RT);\n'
            ' \t\t} else {\n'
            ' #if HAS_FEAT_XS\n'
            '@@ -6067,7 +6067,7 @@\n'
            ' \t\tpte |= ARM_PTE_NX | ARM_PTE_PNX;\n'
            ' \t\tbreak;\n'
            ' \tcase VM_WIMG_WCOMB:\n'
            '-\t\tif (is_dram_addr(pa)) {\n'
            '+\t\tif (is_dram_addr(pa) || pa_valid(pa)) {\n'
            ' \t\t\tpte = ARM_PTE_ATTRINDX(CACHE_ATTRINDX_WRITECOMB);\n'
            ' \t\t} else {\n'
            ' #if HAS_FEAT_XS\n'
            '@@ -10979,6 +10979,10 @@\n'
            ' \t\t\t}\n'
            ' \n'
            ' \t\t\tpvh_unlock(pai);\n'
            '+\n'
            '+\t\t\tif (wimg_bits_new != wimg_bits_prev && wimg_bits_new != VM_WIMG_RT) {\n'
            '+\t\t\t\tpmap_sync_wimg(pn, wimg_bits_prev, wimg_bits_new);\n'
            '+\t\t\t}\n'
            ' \n'
            ' \t\t\tpage_index++;\n'
            ' \n'
        )
        (dev / 'patches/xnu' / addon_patch_name).write_text(hdr_diff + kern_exec_diff + dbg_diff + pmap_diff)
        series_p = dev / 'patches/xnu/series'
        series_txt = series_p.read_text()
        if addon_patch_name not in series_txt:
            series_p.write_text(series_txt.rstrip('\n') + '\n' + addon_patch_name + '\n')
        if cli_args.persistent_data != 'none':
            storage = load_mod('liuqin_persistent_storage', SCRIPT_DIR.parent / 'r103-storage/stage-storage.py')
            storage.stage(dev, addon_hdr)

    if not cli_args.repack_only:
        # 5. Build kernel via UniXNU CLI (reuses warm tree)
        sys.path.insert(0, str(ROOT / 'scripts'))
        from unixnu import cli, feeds
        feeds.update_submodules = lambda ctx: None
        cli.main(['defconfig', 'liuqin_defconfig', '-D', str(dev)])
        cli.main([
            'build', 'kernel', '-D', str(dev), '--jobs', '4',
            '--kernelcache', '/media/disk_4/unixnu_workspace/ramdisk_dir/unixnu/ipsw/26C5035r/kernelcache.decompressed',
        ])

        ev = WORK / 'evidence'
        ev.mkdir(parents=True, exist_ok=True)
        xnu_out = ROOT / 'out/liuqin/macos-27.3-26C5035r/liuqin'
        for name in ('kernel.macho', 'kernel.json', 'kernel.map.json'):
            shutil.copy2(xnu_out / 'kernel' / name, ev / name)
        shutil.copy2(
            xnu_out / 'tree/build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837.unstripped.noctf',
            ev / 'standalone.macho',
        )

        # 6. Verify layout caps + AES fileset gate
        layout = load_mod('layout', ROOT / 'scripts/liuqin-analysis/r100/package.py')
        segments, sections = layout.parse_macho_segments(ev / 'standalone.macho')
        print(
            f"Layout: __TEXT={segments['__TEXT']['vmsize']:#x} (cap {layout.TEXT_CAP:#x}), "
            f"__DATA={segments['__DATA']['vmsize']:#x} (cap {layout.DATA_CAP:#x}), "
            f"__TEXT,__const={sections['__TEXT,__const']:#x} (floor {layout.MIN_TEXT_CONST_VMA:#x})",
            flush=True,
        )
        assert segments['__TEXT']['vmsize'] <= layout.TEXT_CAP, 'TEXT cap exceeded'
        assert segments['__DATA']['vmsize'] <= layout.DATA_CAP, 'DATA cap exceeded'
        assert sections['__TEXT,__const'] >= layout.MIN_TEXT_CONST_VMA, 'TEXT const VMA floor violated'

        nm = ev / 'nm.txt'
        with nm.open('wb') as f:
            subprocess.run(['llvm-nm', '-n', str(ev / 'kernel.macho')], check=True, stdout=f)
        gate = ev / 'aes-fileset-gate.json'
        run([
            'python3', ROOT / 'scripts/liuqin-analysis/aes_fileset_gate.py',
            '--kernel', ev / 'kernel.macho',
            '--standalone', ev / 'standalone.macho',
            '--nm', nm,
            '--bindings', R100_OLD / 'original-bindings.S',
            '--report', gate,
        ])
        gate_j = json.loads(gate.read_text())
        assert gate_j['status'] == 'PASS', f'AES gate failed: {gate_j}'

    # 7. Package volatile boot.img on /media/disk_4
    fat = ev / 'payload.img'
    ref_fat = ROOT / 'out/liuqin/macos-27.3-26C5035r/liuqin/payload/payload.img'
    shutil.copyfile(ref_fat, fat)
    a7_val = json.loads((A7_WORK / 'evidence/a/validation-summary.json').read_text())
    args = a7_val['kernel_args']
    assert args.split().count('liuqin_usb=1') == 1, 'Expected enabled USB debug in A7 baseline'
    if not cli_args.usb_debug:
        args = args.replace('liuqin_usb=1', 'liuqin_usb=0')
    # Drop redundant liuqin_caches=1 (default is already 1); logd_helper is already denied in kern_exec.c,
    # keeping kernel_args comfortably under 1023 bytes for vsync=120 and input/data/wireless switches.
    args = args.replace(' liuqin_caches=1', '')
    if cli_args.with_wireless:
        args = args.replace(',/usr/sbin/bluetoothd', '')
    for extra_arg in ('vsync=120', 'no-lc=1'):
        if extra_arg.split('=')[0] + '=' not in args:
            args = args + ' ' + extra_arg
    if cli_args.with_input:
        # This baseline flag only rewrites a plist already installed by the
        # desktop seed. Reuse its command-line space for the input switch.
        args = args.replace(' liuqin-disable-daemons=1', '')
        args += ' liuqin-input=1'
    if cli_args.persistent_data != 'none':
        args += ' liuqin-data=' + {'reuse': '1', 'init': '2', 'format': '3'}[cli_args.persistent_data]
    assert len(args) < 1023, f'kernel_args too long ({len(args)} >= 1023)'
    raw_adt = (A7_WORK / 'evidence/a/kernel.macho.adt').read_bytes()
    raw_adt = adt_add_gpu_addon(raw_adt, add_gpu_addon=bool(cli_args.gpu_addon), add_bluetooth=bool(cli_args.with_wireless))
    config = run(['mtype', '-i', fat, '::/EFI/UniXNU/unixnu.toml']).decode()
    current = tomllib.loads(config)['entry'][0]['args']
    config = config.replace(current, args)
    (ev / 'unixnu.toml').write_text(config)
    (ev / 'kernel.macho.adt').write_bytes(raw_adt)
    copies = [
        (ev / 'kernel.macho', '::/EFI/UniXNU/Payloads/kernel.macho'),
        (ev / 'kernel.macho.adt', '::/EFI/UniXNU/Payloads/kernel.macho.adt'),
        (ev / 'unixnu.toml', '::/EFI/UniXNU/unixnu.toml'),
    ]
    if cli_args.gpu_addon:
        addon_dst = ev / 'kernel.macho.gpuaddon'
        shutil.copy2(cli_args.gpu_addon, addon_dst)
        copies.append((addon_dst, '::/EFI/UniXNU/Payloads/kernel.macho.gpuaddon'))
    if cli_args.trust_json:
        tj = json.loads(cli_args.trust_json.read_text())
        orig_tc = ev / 'kernel.macho.trustcache.orig'
        new_tc = ev / 'kernel.macho.trustcache'
        orig_tc.write_bytes(run(['mtype', '-i', fat, '::/EFI/UniXNU/Payloads/kernel.macho.trustcache']))
        cdhashes = [tj['cdhash'], tj['turnip_cdhash']] + list(tj.get('extra_cdhashes', []))
        run(['python3', ROOT / 'scripts/trust-append-module.py', orig_tc, new_tc, *cdhashes])
        copies.append((new_tc, '::/EFI/UniXNU/Payloads/kernel.macho.trustcache'))
    for src, dest in copies:
        run(['mcopy', '-o', '-i', fat, src, dest])
        assert hashlib.sha256(run(['mtype', '-i', fat, dest])).hexdigest() == sha(src)
    trust_sha = hashlib.sha256(run(['mtype', '-i', fat, '::/EFI/UniXNU/Payloads/kernel.macho.trustcache'])).hexdigest()
    if not cli_args.trust_json:
        assert trust_sha == a7_val['trust_cache_sha256']

    run(['python3', dev / 'scripts/wrap-payload-mbr.py', fat, ev / 'payload-mbr.img'])
    pkg_out = WORK / 'package-out'
    pkg_out.mkdir(exist_ok=True)
    cli.main([
        'bootimg', '-D', str(dev), '--out', str(pkg_out),
        '--uefi', '/home/kurumin/Codes/Github/uefi-sheng',
        '--fd', str(R100_OLD / 'SILICIUM_UEFI.fd'),
        '--dtb', str(dev / 'dts/liuqin-cape.dtb'),
        '--ramdisk', str(ev / 'payload-mbr.img'),
        '--output', str(ev / 'boot.img'),
    ])

    summary = {
        'status': 'PASS',
        'profile': 'r102-gpu-adreno730-kmd-bringup',
        'boot_img': str(ev / 'boot.img'),
        'boot_sha256': sha(ev / 'boot.img'),
        'kernel_sha256': sha(ev / 'kernel.macho'),
        'segments': {k: hex(segments[k]['vmsize']) for k in ('__TEXT', '__DATA', '__TEXT_EXEC')},
        'text_const_vma': hex(sections['__TEXT,__const']),
        'aes_gate': gate_j['status'],
        'trust_cache_sha256': trust_sha,
        'kernel_args': args,
        'usb_debug': cli_args.usb_debug,
        'input_port': cli_args.with_input,
        'persistent_data_mode': cli_args.persistent_data,
        'hardware_verified': False,
    }
    (ev / 'validation-summary.json').write_text(json.dumps(summary, indent=2) + '\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
