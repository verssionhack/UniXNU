#!/usr/bin/env python3
"""Prepare r100a work tree from r98/r99p: add GopFramebuffer (CPU-presented IOMobileFramebuffer) + LiuqinScratchDisk Internal protocol property."""
from pathlib import Path
import shutil

R = Path('/home/kurumin/github/UniXNU')
OLD = R / 'out/liuqin-r98-work'
W = R / 'out/liuqin-r100-work'
D = W / 'device'
SHENG = Path('/home/kurumin/Codes/Github/UniXNU-sheng')
HERE = Path(__file__).resolve().parent


def sub(path: Path, old: str, new: str) -> None:
    text = path.read_text()
    found = text.count(old)
    if found != 1:
        raise RuntimeError(f'{path}: expected 1 occurrence, found {found} for:\n{old[:200]}')
    path.write_text(text.replace(old, new, 1))


def main() -> None:
    assert (OLD / 'device').is_dir(), 'missing r98 device work dir'
    W.mkdir(parents=True, exist_ok=True)
    for name in ('device', 'helpers'):
        dst = W / name
        if dst.exists():
            shutil.rmtree(dst)
    shutil.copytree(OLD / 'device', D)
    if (OLD / 'helpers').exists():
        shutil.copytree(OLD / 'helpers', W / 'helpers')

    (D / 'scripts').mkdir(parents=True, exist_ok=True)
    (D / 'package').mkdir(parents=True, exist_ok=True)
    shutil.copy2(HERE / 'build-liuqin-legacy-display.py', D / 'scripts/build-liuqin-legacy-display.py')
    shutil.copy2(SHENG / 'scripts/legacy-display-26C5035r.json', D / 'scripts/legacy-display-26C5035r.json')
    shutil.copy2(SHENG / 'package/LegacyDisplayProbe.cpp', D / 'package/LegacyDisplayProbe.cpp')
    sub(D / 'package/LegacyDisplayProbe.cpp',
        'const uint32_t dotsPerInch=294;',
        'const uint32_t dotsPerInch=309;')

    # Free 48 KB of __DATA (lq_panic_tail 64K -> 16K) and 78 KB of __TEXT,__const (scratch_seed -> __BOOTDATA,__data).
    sub(D / 'patches/xnu/zzz-liuqin-panic-screen.patch',
        '+static char lq_panic_tail[1u << 16];',
        '+static char lq_panic_tail[1u << 14];')
    sub(D / 'patches/xnu/zzz-liuqin-zzz-switch-progress.patch',
        ' static char lq_panic_tail[1u << 16];',
        ' static char lq_panic_tail[1u << 14];')
    sub(D / 'drivers/LiuqinSourceStorage/ScratchSeed.inc',
        'static const unsigned char scratch_seed[] = {',
        'static const unsigned char scratch_seed[] __attribute__((section("__BOOTDATA,__data"))) = {')

    # Wire GopFramebuffer component + archive into board.toml and free 53 bytes of cmdline budget.
    board = D / 'board.toml'
    sub(board,
        'include = ["ArmDTPlatform", "ArmCpu", "SoftwareAES", "XnuPrelink", "DarwinBoot", "VerifiedRoot", "AppleKeyStoreState"]',
        'include = ["ArmDTPlatform", "ArmCpu", "SoftwareAES", "XnuPrelink", "DarwinBoot", "VerifiedRoot", "AppleKeyStoreState", "GopFramebuffer"]')
    sub(board,
        '  "build-liuqin-source-storage.py",\n]',
        '  "build-liuqin-source-storage.py",\n  "build-liuqin-legacy-display.py",\n]')
    sub(board,
        '  "debug=0x14e",\n  "startup_debug=1",\n  "kt_fixed_zones=120",\n  "armcpu-diagnostics=1",',
        '  "debug=0x14e",\n  "kt_fixed_zones=120",')
    sub(board, '  "liuqin_noroot=1",', '  "liuqin_noroot=0",')

    # Enable CONFIG_XNU_NATIVE_LEGACY_DISPLAY=y in liuqin_defconfig.
    defcfg = D / 'configs/liuqin_defconfig'
    sub(defcfg,
        '#   CONFIG_XNU_NATIVE_LEGACY_DISPLAY=y  GopFramebuffer component + libNativeLegacyDisplay.late.a\n',
        'CONFIG_XNU_NATIVE_LEGACY_DISPLAY=y\n')

    # Publish Protocol Characteristics -> Physical Interconnect Location = Internal on LiuqinScratchDisk
    # so applekeystored --init passes aks_apfs_get_disk_portability("/dev/disk4s1").
    scratch = D / 'drivers/LiuqinSourceStorage/LiuqinScratchDisk.cpp'
    sub(scratch,
        '  OSSafeReleaseNULL(mtype);\n  OSSafeReleaseNULL(chars);\n',
        '  OSSafeReleaseNULL(mtype);\n  OSSafeReleaseNULL(chars);\n'
        '  OSDictionary *proto = OSDictionary::withCapacity(1);\n'
        '  OSString *loc = OSString::withCString(kIOPropertyInternalKey);\n'
        '  if (proto && loc) {\n'
        '   proto->setObject(kIOPropertyPhysicalInterconnectLocationKey, loc);\n'
        '   setProperty(kIOPropertyProtocolCharacteristicsKey, proto);\n'
        '  }\n'
        '  OSSafeReleaseNULL(loc);\n'
        '  OSSafeReleaseNULL(proto);\n')

    (W / 'build-r100.py').write_text(
        "import sys\n"
        f"sys.path.insert(0, '{R / 'scripts'}')\n"
        "from unixnu import cli, feeds\n"
        "feeds.update_submodules = lambda ctx: None\n"
        f"D = '{D}'\n"
        "cli.main(['defconfig', 'liuqin_defconfig', '-D', D])\n"
        "cli.main(['build', 'kernel', '-D', D, '--jobs', '4', '--kernelcache', "
        "'/media/disk_4/unixnu_workspace/ramdisk_dir/unixnu/ipsw/26C5035r/kernelcache.decompressed'])\n"
    )
    print('Prepared r100a work tree at', D)


if __name__ == '__main__':
    main()
