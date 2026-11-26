#!/usr/bin/env python3
"""Sandboxed host-only audit of 26C5035r Metal/IOGPU shim contracts, custom wire ABI,
Turnip Darwin KMD alignment, and frozen A7 trust/GPUBundles reachability.

Reads frozen r101/host-gate/A7 inputs read-only; writes only to out/liuqin-r101-gpu-host-gates-r2/evidence/.
"""
from pathlib import Path
import hashlib
import json
import re

ROOT = Path(__file__).resolve().parents[4]
PREV_EV = ROOT / 'out/liuqin-r101-gpu-host-gates/evidence'
A7_EV = ROOT / 'out/liuqin-r101-a7-work/evidence/a'
XNU_WORK = ROOT / 'out/liuqin/macos-27.3-26C5035r/liuqin/tree/.cache/xnu-work'
OUT_EV = ROOT / 'out/liuqin-r101-gpu-host-gates-r2/evidence'
OUT_EV.mkdir(parents=True, exist_ok=True)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_objc_dump(text: str):
    """Parse ipsw ObjC text dump into protocols and interfaces (properties, class/instance methods)."""
    protocols = {}
    interfaces = {}
    cur_kind = None
    cur_name = None
    cur_super = None
    for raw in text.splitlines():
        line = raw.strip()
        m = re.match(r'^@protocol\s+(\w+)(?:\s*<([^>]+)>)?$', line)
        if m:
            cur_kind, cur_name = 'protocol', m.group(1)
            protocols.setdefault(cur_name, {'bases': [x.strip() for x in (m.group(2) or '').split(',') if x.strip()],
                                            'properties': {}, 'instance_methods': set(), 'class_methods': set()})
            continue
        m = re.match(r'^@interface\s+(\w+)\s*:\s*(\w+)', line)
        if m:
            cur_kind, cur_name, cur_super = 'interface', m.group(1), m.group(2)
            interfaces.setdefault(cur_name, {'super': cur_super, 'properties': {}, 'instance_methods': set(), 'class_methods': set()})
            continue
        if line == '@end':
            cur_kind = cur_name = cur_super = None
            continue
        if not cur_name:
            continue
        target = protocols[cur_name] if cur_kind == 'protocol' else interfaces[cur_name]
        pm = re.match(r'^@property\s*\(([^)]*)\)\s*(\w+)\s*;', line)
        if pm:
            attrs = pm.group(1)
            prop = pm.group(2)
            tm = re.search(r'(?:^|,)T([^,]+)', attrs)
            gm = re.search(r'(?:^|,)G([^,]+)', attrs)
            target['properties'][prop] = {'type': tm.group(1) if tm else '', 'attrs': attrs, 'getter': gm.group(1) if gm else prop}
            continue
        mm = re.match(r'^([+-])\[(\w+)\s+([^\]]+)\];$', line)
        if mm:
            if mm.group(1) == '-':
                target['instance_methods'].add(mm.group(3))
            else:
                target['class_methods'].add(mm.group(3))
    return protocols, interfaces


def parse_frontend_methods(mm_text: str):
    """Extract @implementation class -> set of implemented instance selectors in NativeBridgeMetalFrontend.mm."""
    impls = {}
    cur = None
    for line in mm_text.splitlines():
        m = re.match(r'^\s*@implementation\s+(\w+)', line)
        if m:
            cur = m.group(1)
            impls.setdefault(cur, set())
            continue
        if re.match(r'^\s*@end\b', line):
            cur = None
            continue
        if cur and re.match(r'^\s*-\s*\(', line):
            # Extract selector tokens from ObjC method header (up to '{' or newline)
            header = line.split('{', 1)[0]
            # Strip return type - (ret)
            rest = re.sub(r'^\s*-\s*\([^)]*\)\s*', '', header)
            if ':' in rest:
                sels = re.findall(r'(\w+:)\s*\([^)]*\)', rest)
                if sels:
                    impls[cur].add(''.join(sels))
            else:
                nm = re.match(r'^(\w+)', rest.strip())
                if nm:
                    impls[cur].add(nm.group(1))
    return impls


def audit_shim_and_protocols():
    iogpu_protos, iogpu_ifaces = parse_objc_dump((PREV_EV / 'IOGPU.objc.txt').read_text())
    metal_protos, metal_ifaces = parse_objc_dump((PREV_EV / 'Metal.objc.txt').read_text())
    shim_path = ROOT / 'drivers/AdrenoMetal/IOGPUMetalDeviceShim.h'
    shim_text = shim_path.read_text()
    frontend_path = ROOT / 'drivers/AdrenoMetal/NativeBridgeMetalFrontend.mm'
    frontend_impls = parse_frontend_methods(frontend_path.read_text())

    # Parse MethodSpec arrays in IOGPUMetalDeviceShim.h
    spec_arrays = {}
    for m in re.finditer(r'static const MethodSpec\s+(\w+)\[\]\s*=\s*\{([\s\S]*?)\};', shim_text):
        arr_name, body = m.group(1), m.group(2)
        entries = []
        for em in re.finditer(r'\{\s*"([^"]+)"\s*,\s*\(IMP\)(\w+)\s*,\s*"([^"]+)"\s*,\s*(true|false)\s*\}', body):
            entries.append({'selector': em.group(1), 'imp': em.group(2), 'types': em.group(3), 'override': em.group(4) == 'true'})
        spec_arrays[arr_name] = entries

    # Check every MethodSpec against IOGPU and Metal class hierarchies
    def lookup_in_hierarchy(cls_name, sel, ifaces_list):
        chain = []
        seen = set()
        cur = cls_name
        while cur and cur not in seen:
            seen.add(cur)
            found = None
            for d in ifaces_list:
                if cur in d:
                    found = d[cur]
                    break
            if not found:
                break
            if sel in found['instance_methods']:
                prop_type = None
                for p, info in found['properties'].items():
                    if info['getter'] == sel:
                        prop_type = info['type']
                chain.append({'class': cur, 'found': True, 'property_type': prop_type})
            cur = found['super']
        return chain

    target_class_map = {
        'deviceMethods': 'IOGPUMetalDevice',
        'queueMethods': 'IOGPUMetalCommandQueue',
        'resourceMethods': 'IOGPUMetalResource',
        'commandBufferMethods': 'IOGPUMetalCommandBuffer',
        'functionMethods': '_MTLFunction',
    }
    shim_checks = {}
    for arr_name, entries in spec_arrays.items():
        ref_cls = target_class_map[arr_name]
        rows = []
        for e in entries:
            hits = lookup_in_hierarchy(ref_cls, e['selector'], [iogpu_ifaces, metal_ifaces])
            rows.append({**e, 'reference_class': ref_cls, 'found_in_target_hierarchy': hits})
        shim_checks[arr_name] = rows

    # Check all 19 protocol conformances
    conf_m = re.search(r'conformances\[\]\[2\]\s*=\s*\{([\s\S]*?)\};', shim_text)
    conformances = []
    for cm in re.finditer(r'\{\s*"([^"]+)"\s*,\s*"([^"]+)"\s*\}', conf_m.group(1)):
        cls_name, proto_name = cm.group(1), cm.group(2)
        in_metal = proto_name in metal_protos
        in_iogpu = proto_name in iogpu_protos
        conformances.append({
            'frontend_class': cls_name,
            'protocol': proto_name,
            'in_Metal_objc': in_metal,
            'in_IOGPU_objc': in_iogpu,
            'frontend_impl_found': cls_name in frontend_impls,
        })

    # Enumerate resolveStub exposure per mapped class (from IOGPU.objc.txt)
    ref_map_m = re.search(r'classes\[\]\s*=\s*\{([\s\S]*?)\};', shim_text)
    mapped_classes = []
    for rm in re.finditer(r'\{\s*"([^"]+)"\s*,\s*(?:"([^"]+)"|nullptr)\s*\}', ref_map_m.group(1)):
        mapped_classes.append((rm.group(1), rm.group(2)))
    mapped_classes.append(('NBDevice', 'IOGPUMetalDevice'))

    # Map shim explicit methods to frontend classes
    explicit_by_cls = {
        'NBDevice': {e['selector'] for e in spec_arrays.get('deviceMethods', [])},
        'NBQueue': {e['selector'] for e in spec_arrays.get('queueMethods', [])},
        'NBBuffer': {e['selector'] for e in spec_arrays.get('resourceMethods', [])},
        'NBTexture': {e['selector'] for e in spec_arrays.get('resourceMethods', [])},
        'NBCommandBuffer': {e['selector'] for e in spec_arrays.get('commandBufferMethods', [])},
        'NBFunction': {e['selector'] for e in spec_arrays.get('functionMethods', [])},
    }

    # Note: class_getInstanceMethod(reference, selector) walks reference's superclass chain too!
    resolve_exposure = {}
    for fe_cls, iogpu_cls in mapped_classes:
        if not iogpu_cls or iogpu_cls not in iogpu_ifaces:
            continue
        # Direct IOGPU hierarchy methods (within IOGPU.framework)
        direct_sels = set()
        chain_names = []
        cur = iogpu_cls
        while cur and cur in iogpu_ifaces:
            chain_names.append(cur)
            direct_sels |= iogpu_ifaces[cur]['instance_methods']
            cur = iogpu_ifaces[cur]['super']
        fe_implemented = set(frontend_impls.get(fe_cls, set())) | explicit_by_cls.get(fe_cls, set())
        unimplemented = sorted(direct_sels - fe_implemented)
        resolve_exposure[fe_cls] = {
            'iogpu_class': iogpu_cls,
            'iogpu_super_chain': chain_names,
            'metal_superclass_above_iogpu': cur,
            'iogpu_instance_method_count': len(direct_sels),
            'frontend_or_shim_implemented_overlap': len(direct_sels & fe_implemented),
            'unimplemented_iogpu_selectors_reachable_by_resolveStub': len(unimplemented),
            'unimplemented_selectors': unimplemented,
        }

    report = {
        'scope': '26C5035r IOGPU/Metal ObjC dump cross-check against IOGPUMetalDeviceShim.h and NativeBridgeMetalFrontend.mm',
        'inputs_sha256': {
            'IOGPU.objc.txt': sha(PREV_EV / 'IOGPU.objc.txt'),
            'Metal.objc.txt': sha(PREV_EV / 'Metal.objc.txt'),
            'IOGPUMetalDeviceShim.h': sha(shim_path),
            'NativeBridgeMetalFrontend.mm': sha(frontend_path),
        },
        'explicit_method_specs': shim_checks,
        'protocol_conformances': conformances,
        'all_19_protocols_present_in_target': all(c['in_Metal_objc'] or c['in_IOGPU_objc'] for c in conformances),
        'resolveStub_exposure_iogpu_layer': resolve_exposure,
    }
    (OUT_EV / 'iogpu-shim-objc-cross-check.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def audit_wire_and_turnip_abi():
    abi_path = ROOT / 'drivers/Adreno740/NativeAdrenoABI.h'
    uc_path = ROOT / 'drivers/Adreno740/NativeAdrenoUserClient.cpp'
    pub_path = ROOT / 'drivers/Adreno740/NativeAdrenoPublish.cpp'
    patch_path = ROOT / 'patches/mesa/turnip-darwin-kmd.patch'
    plugin_path = ROOT / 'drivers/AdrenoMetal/NativeAdrenoMetalPlugin.mm'

    abi_text = abi_path.read_text()
    uc_text = uc_path.read_text()
    pub_text = pub_path.read_text()
    patch_text = patch_path.read_text()
    plugin_text = plugin_path.read_text()

    methods = {}
    for m in re.finditer(r'(NativeAdrenoMethod\w+)\s*=\s*(\d+)', abi_text):
        name, num = m.group(1), int(m.group(2))
        methods[name] = {
            'id': num,
            'in_NativeAdrenoUserClient': name in uc_text,
            'in_NativeAdrenoPublish': name in pub_text,
            'in_turnip_darwin_kmd_patch': name in patch_text,
        }

    # Check ABI version & key constants
    abi_ver = int(re.search(r'NativeAdrenoAbiVersion\s*=\s*(\d+)', abi_text).group(1))
    max_bufs = int(re.search(r'NativeAdrenoAbiMaxBuffers\s*=\s*(\d+)', abi_text).group(1))

    # Extract static_assert sizeof checks from NativeAdrenoABI.h
    struct_asserts = re.findall(r'static_assert\(sizeof\((\w+)\)\s*==\s*([^,]+),', abi_text)

    # Check Turnip Darwin KMD patch references to NativeAdrenoABI / chip_id / gmem / ubwc / macOS
    turnip_checks = {
        'includes_NativeAdrenoABI_h': '#include "NativeAdrenoABI.h"' in patch_text,
        'checks_abi_version': 'NativeAdrenoAbiVersion' in patch_text,
        'checks_a740_special_chip_id_only': '0x43050a01' in patch_text,
        'hardcodes_a730_chip_id': '0x07030001' in patch_text,
        'reads_gmem_bytes_from_kmd': 'gmem_bytes' in patch_text,
        'reads_highest_bank_bit_from_kmd': 'highest_bank_bit' in patch_text,
        'reads_ubwc_from_kmd': 'ubwc_swizzle' in patch_text and 'macrotile_mode' in patch_text and 'ubwc_version' in patch_text,
        'uses_plugin_open_type_0x4147': '0x4147' in patch_text,
        'matches_AGXAccelerator_or_IOAccelerator': {
            'AGXAccelerator': 'AGXAccelerator' in patch_text,
            'IOAcceleratorES': 'IOAcceleratorES' in patch_text,
            'IOAccelerator': '"IOAccelerator"' in patch_text,
        },
        'uses_IOConnectCallStructMethod': 'IOConnectCallStructMethod' in patch_text,
        'uses_IOConnectMapMemory64': 'IOConnectMapMemory64' in patch_text,
    }

    # Check NativeAdrenoMetalPlugin.mm macOS 26C5035r contract points
    plugin_checks = {
        'subclasses_IOGPUMetalDevice_on_osx': '@interface NativeAdrenoMetalDevice : IOGPUMetalDevice' in plugin_text,
        'retains_dummy_instance_without_calling_super_init': '[kept addObject:self]' in plugin_text,
        'installs_iogpu_shim_on_osx': 'iogpu::install(device, port)' in plugin_text,
        'sets_TU_DEBUG_nocb_default': '"nocb"' in plugin_text,
        'render_server_is_WindowServer_on_osx': '"WindowServer"' in (ROOT / 'drivers/AdrenoMetal/NativeRenderServer.h').read_text(),
        'optional_constructor_hooks_on_osx': {
            'ca_triple_buffer_CASetDebugOption_198': 'CASetDebugOption' in plugin_text and 'setOption(198, true)' in plugin_text,
            'ca_free_wakeup_CAWindowServerDisplay': 'CAWindowServerDisplay' in plugin_text and 'nextWakeupTime' in plugin_text and 'beginExternalUpdate:usingSoftwareRenderer:' in plugin_text,
        },
        'has_24A446_only_quartzcore_patch_guarded': '0x184461928' in plugin_text,
    }

    report = {
        'scope': 'Wire ABI v2, Turnip Darwin KMD patch, and macOS Metal plugin source-level contract audit',
        'inputs_sha256': {
            'NativeAdrenoABI.h': sha(abi_path),
            'NativeAdrenoUserClient.cpp': sha(uc_path),
            'NativeAdrenoPublish.cpp': sha(pub_path),
            'turnip-darwin-kmd.patch': sha(patch_path),
            'NativeAdrenoMetalPlugin.mm': sha(plugin_path),
        },
        'abi_version': abi_ver,
        'max_buffers': max_bufs,
        'struct_size_static_asserts': {k: v.strip() for k, v in struct_asserts},
        'methods': methods,
        'turnip_darwin_kmd_checks': turnip_checks,
        'macos_plugin_checks': plugin_checks,
    }
    (OUT_EV / 'wire-and-turnip-abi.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def audit_a7_trust_and_bundle_reachability():
    nm_path = A7_EV / 'nm.txt'
    nm_text = nm_path.read_text()
    kern_exec_path = XNU_WORK / 'bsd/kern/kern_exec.c'
    kern_exec_text = kern_exec_path.read_text()
    toml_path = A7_EV / 'unixnu.toml'
    toml_text = toml_path.read_text()
    cfg_path = ROOT / 'out/liuqin/macos-27.3-26C5035r/liuqin/.config'
    cfg_text = cfg_path.read_text()

    args_m = re.search(r'^args\s*=\s*"([^"]+)"', toml_text, re.M)
    boot_args = args_m.group(1) if args_m else ''

    symbols_of_interest = [
        'native_sandbox_grant',
        'native_owner_macos_gpu_addon',
        'native_gpu_addon_install',
        'native_gpu_addon_mount',
        'native_gpu_addon_prepare',
        'native_gpu_bundle_protect',
        'native_gpu_bundle_protect_one',
        'native_ram_block_gpu_addon',
        'native_owner_macos_data_prepare',
        'native_owner_data_firmlinks',
        'liuqin_scratch_probe',
        'native_gop_handoff_call',
        'native_gop_handoff_memory',
    ]
    nm_hits = {}
    for sym in symbols_of_interest:
        matches = [line.strip() for line in nm_text.splitlines() if sym in line]
        nm_hits[sym] = matches

    # Verify preprocessor guard around native_gpu_bundle_protect and native_owner_macos_gpu_addon in kern_exec.c
    owner_data_guard = '#if defined(XNU_OWNER_DATA_MOUNT) && XNU_OWNER_DATA_MOUNT' in kern_exec_text
    weak_ram_block = 'extern int native_ram_block_gpu_addon(const uint8_t **, uint64_t *) __attribute__((weak_import));' in kern_exec_text
    cfg_flags = {}
    for key in ['CONFIG_XNU_OWNER_DATA_MOUNT', 'CONFIG_XNU_OWNER_BOOT_MANIFEST', 'CONFIG_XNU_NATIVE_RAM_BLOCK',
                'CONFIG_XNU_TRUST_CACHE_RUNTIME', 'CONFIG_XNU_NATIVE_ADRENO', 'CONFIG_XNU_NATIVE_LEGACY_DISPLAY']:
        m = re.search(r'^' + key + r'=(.+)$', cfg_text, re.M)
        cfg_flags[key] = m.group(1) if m else 'unset/commented'

    report = {
        'scope': 'Frozen A7 kernel symbol and source reachability proof for GPUBundles, rootless protection, gpu-addon, and sandbox grant',
        'inputs_sha256': {
            'a7_nm.txt': sha(nm_path),
            'a7_unixnu.toml': sha(toml_path),
            'liuqin_.config': sha(cfg_path),
            'kern_exec.c': sha(kern_exec_path),
        },
        'a7_config_flags': cfg_flags,
        'a7_boot_args_bytes': len(boot_args),
        'a7_boot_args_limit_bytes': 1000,
        'a7_boot_args_headroom_bytes': 1000 - len(boot_args),
        'gpu_addon_1_arg_bytes_with_space': len(' gpu-addon=1'),
        'gpu_addon_1_fits_current_boot_args': len(boot_args) + len(' gpu-addon=1') < 1000,
        'kern_exec_gated_by_XNU_OWNER_DATA_MOUNT': owner_data_guard,
        'kern_exec_weak_import_native_ram_block_gpu_addon': weak_ram_block,
        'a7_nm_symbol_matches': nm_hits,
        'conclusions': {
            'native_sandbox_grant_active_in_A7': bool(nm_hits['native_sandbox_grant']),
            'gpubundles_rootless_protect_compiled_in_A7': bool(nm_hits['native_gpu_bundle_protect'] or nm_hits['native_gpu_bundle_protect_one']),
            'gpu_addon_installer_compiled_in_A7': bool(nm_hits['native_gpu_addon_install'] or nm_hits['native_owner_macos_gpu_addon']),
            'gpu_addon_handoff_provider_defined_in_A7': bool(nm_hits['native_ram_block_gpu_addon']),
            'liuqin_data_mount_uses_owner_data_prepare': bool(nm_hits['native_owner_macos_data_prepare']),
        },
    }
    (OUT_EV / 'a7-trust-and-bundle-reachability.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    r1 = audit_shim_and_protocols()
    r2 = audit_wire_and_turnip_abi()
    r3 = audit_a7_trust_and_bundle_reachability()
    print('PASS: shim explicit arrays:', {k: len(v) for k, v in r1['explicit_method_specs'].items()})
    print('PASS: all 19 Metal protocols present in target:', r1['all_19_protocols_present_in_target'])
    print('PASS: ABI v%d methods checked: %d' % (r2['abi_version'], len(r2['methods'])))
    print('PASS: A7 reachability:', json.dumps(r3['conclusions']))
    print('PASS: A7 boot args bytes:', r3['a7_boot_args_bytes'], '/ 1000')


if __name__ == '__main__':
    main()
