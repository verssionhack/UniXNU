#!/usr/bin/env python3
"""Sandboxed exact method-signature and ARM64 AAPCS stub-hazard audit against
ipsw class-dump typed headers of pinned 26C5035r IOGPU, Metal, and QuartzCore.

Reads only frozen/r2 evidence files; writes to out/liuqin-r101-gpu-host-gates-r2/evidence/.
"""
from pathlib import Path
import hashlib
import json
import re
import importlib.util

ROOT = Path(__file__).resolve().parents[4]
EV = ROOT / 'out/liuqin-r101-gpu-host-gates-r2/evidence'
PREV_EV = ROOT / 'out/liuqin-r101-gpu-host-gates/evidence'


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def parse_typed_headers(text: str):
    """Parse ipsw class-dump --class output into {class: {super, methods: {sel: {ret, params, raw}}}}."""
    classes = {}
    cur = None
    for raw in text.splitlines():
        line = raw.strip()
        m = re.match(r'^@interface\s+(\w+)\s*:\s*(\w+)', line)
        if m:
            cur = m.group(1)
            classes.setdefault(cur, {'super': m.group(2), 'methods': {}, 'class_methods': {}})
            continue
        if line == '@end':
            cur = None
            continue
        if not cur:
            continue
        if not (line.startswith('- (') or line.startswith('+ (')):
            continue
        kind = line[0]
        # Extract balanced return type inside first (...)
        idx = line.find('(')
        depth = 0
        end = -1
        for i in range(idx, len(line)):
            if line[i] == '(':
                depth += 1
            elif line[i] == ')':
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end < 0:
            continue
        ret_type = line[idx + 1:end].strip()
        rest = line[end + 1:].strip().rstrip(';').strip()
        # Parse selector and parameter types
        if ':' not in rest:
            sel = rest.split()[0]
            params = []
        else:
            sel_parts = []
            params = []
            pos = 0
            while pos < len(rest):
                colon = rest.find(':', pos)
                if colon < 0:
                    break
                # selector part is last whitespace-separated token before colon
                prefix = rest[pos:colon].strip()
                tok = prefix.split()[-1] if prefix else ''
                sel_parts.append(tok + ':')
                # next comes (paramType)paramName
                lp = rest.find('(', colon + 1)
                if lp < 0:
                    break
                d = 0
                rp = -1
                for j in range(lp, len(rest)):
                    if rest[j] == '(':
                        d += 1
                    elif rest[j] == ')':
                        d -= 1
                        if d == 0:
                            rp = j
                            break
                if rp < 0:
                    break
                params.append(rest[lp + 1:rp].strip())
                # Advance past paramName to next whitespace
                after = rest[rp + 1:].lstrip()
                sp = after.find(' ')
                if sp < 0:
                    pos = len(rest)
                else:
                    pos = len(rest) - len(after) + sp + 1
            sel = ''.join(sel_parts)
        bucket = classes[cur]['methods'] if kind == '-' else classes[cur]['class_methods']
        bucket[sel] = {'return_type': ret_type, 'param_types': params, 'declaration': line}
    return classes


def parse_protocols(text: str):
    protos = set()
    for line in text.splitlines():
        m = re.match(r'^@protocol\s+(\w+)', line.strip())
        if m:
            protos.add(m.group(1))
    return protos


def ctype_to_objc_return_class(ret: str):
    """Map C/ObjC return type string from class-dump to ARM64 AAPCS ABI class."""
    r = re.sub(r'\b(oneway|const|in|out|inout|bycopy|byref|__kindof|nullable|nonnull|_Nullable|_Nonnull)\b', '', ret).strip()
    if r == 'void':
        return 'void', 'v'
    if '*' in r or r in ('id', 'Class', 'SEL') or r.startswith('id<') or r.startswith('id '):
        if r.startswith('id') or r == 'Class' or r.endswith(' *') and not r.startswith(('void ', 'char ', 'unsigned ', 'int ', 'struct ', 'float ', 'double ')):
            return 'object_or_pointer', '@'
        return 'pointer', '^'
    if r in ('float', 'double', 'long double'):
        return 'hazard_float_or_double', ('f' if r == 'float' else 'd')
    if r.startswith('struct ') or r.startswith('union ') or '{' in r:
        return 'hazard_struct_aggregate', '{struct}'
    if r in ('_Bool', 'BOOL', 'bool'):
        return 'bool', 'B'
    if r in ('unsigned long long', 'unsigned long', 'uint64_t', 'NSUInteger', 'size_t'):
        return 'u64', 'Q'
    if r in ('long long', 'long', 'int64_t', 'NSInteger', 'ssize_t'):
        return 'i64', 'q'
    if r in ('unsigned int', 'uint32_t'):
        return 'u32', 'I'
    if r in ('int', 'int32_t'):
        return 'i32', 'i'
    if r in ('unsigned short', 'uint16_t'):
        return 'u16', 'S'
    if r in ('short', 'int16_t'):
        return 'i16', 's'
    if r in ('unsigned char', 'uint8_t'):
        return 'u8', 'C'
    if r in ('char', 'signed char', 'int8_t'):
        return 'i8', 'c'
    return 'other', r


def shim_enc_return_class(enc: str):
    s = enc.lstrip('rnNoORV')
    ch = s[0] if s else '?'
    return {
        'v': 'void', 'B': 'bool', 'c': 'bool_or_i8', 'C': 'u8',
        's': 'i16', 'S': 'u16', 'i': 'i32', 'I': 'u32',
        'q': 'i64', 'Q': 'u64', '@': 'object_or_pointer', '#': 'object_or_pointer',
        '^': 'pointer', '*': 'pointer', 'f': 'hazard_float_or_double', 'd': 'hazard_float_or_double',
        '{': 'hazard_struct_aggregate',
    }.get(ch, ch)


def parse_shim_arg_types(enc: str):
    """Extract parameter type codes (after self '@' and _cmd ':') from ObjC method type encoding."""
    # Remove digits
    no_digits = re.sub(r'\d+', '', enc)
    # Tokenize simple encodings
    toks = []
    i = 0
    while i < len(no_digits):
        if no_digits[i] == '^' and i + 1 < len(no_digits):
            toks.append(no_digits[i:i + 2])
            i += 2
        elif no_digits[i] == '{':
            d = 0
            start = i
            while i < len(no_digits):
                if no_digits[i] == '{':
                    d += 1
                elif no_digits[i] == '}':
                    d -= 1
                    if d == 0:
                        i += 1
                        break
                i += 1
            toks.append(no_digits[start:i])
        else:
            toks.append(no_digits[i])
            i += 1
    # toks[0] = ret, toks[1] = '@', toks[2] = ':', toks[3:] = params
    return toks[0] if toks else '', toks[3:]


def main():
    iogpu_path = EV / 'IOGPU.typed.h'
    metal_path = EV / 'Metal.typed.h'
    protos_path = EV / 'Metal.protocols.h'
    ca_path = EV / 'CAWindowServerDisplay.classdump.h'

    iogpu_cls = parse_typed_headers(iogpu_path.read_text())
    metal_cls = parse_typed_headers(metal_path.read_text())
    ca_cls = parse_typed_headers(ca_path.read_text())
    metal_protos = parse_protocols(protos_path.read_text())
    iogpu_protos = parse_protocols((PREV_EV / 'IOGPU.objc.txt').read_text())
    all_protos = metal_protos | iogpu_protos
    all_cls = {**metal_cls, **iogpu_cls}

    cross = json.loads((EV / 'iogpu-shim-objc-cross-check.json').read_text())

    # 1. Verify all 19 Metal protocols against Metal.protocols.h + IOGPU.objc.txt
    proto_checks = []
    for c in cross['protocol_conformances']:
        p = c['protocol']
        proto_checks.append({
            'frontend_class': c['frontend_class'],
            'protocol': p,
            'present_in_26C5035r_Metal_or_IOGPU': p in all_protos,
            'in_Metal_protocols_h': p in metal_protos,
            'in_IOGPU_objc': p in iogpu_protos,
        })

    # 2. Verify all 39 explicit MethodSpec entries in IOGPUMetalDeviceShim.h
    def find_typed_method(cls_name, sel):
        seen = set()
        cur = cls_name
        while cur and cur not in seen:
            seen.add(cur)
            info = all_cls.get(cur)
            if not info:
                break
            if sel in info['methods']:
                return cur, info['methods'][sel]
            cur = info['super']
        return None, None

    explicit_audit = {}
    mismatches = []
    not_in_hierarchy = []
    for arr_name, rows in cross['explicit_method_specs'].items():
        out_rows = []
        for r in rows:
            owner, minfo = find_typed_method(r['reference_class'], r['selector'])
            shim_ret_code, shim_params = parse_shim_arg_types(r['types'])
            shim_ret_cls = shim_enc_return_class(r['types'])
            if owner is None:
                # Check if selector exists anywhere in Metal/IOGPU (e.g., MPS/private extension or older macOS selector)
                anywhere = [c for c, ci in all_cls.items() if r['selector'] in ci['methods']]
                status = 'not_in_reference_hierarchy'
                not_in_hierarchy.append({
                    'array': arr_name, 'selector': r['selector'], 'shim_types': r['types'],
                    'found_on_other_classes': anywhere[:5],
                })
                out_rows.append({'selector': r['selector'], 'shim_types': r['types'], 'status': status,
                                 'found_on_other_classes': anywhere[:5]})
            else:
                tgt_ret_cls, tgt_ret_code = ctype_to_objc_return_class(minfo['return_type'])
                tgt_param_classes = [ctype_to_objc_return_class(pt)[0] for pt in minfo['param_types']]
                shim_param_classes = [shim_enc_return_class(pt) for pt in shim_params]
                ret_ok = (shim_ret_cls == tgt_ret_cls) or ({shim_ret_cls, tgt_ret_cls} <= {'object_or_pointer', 'pointer'})
                arity_ok = (len(shim_param_classes) == len(tgt_param_classes))
                params_ok = arity_ok and all(
                    (a == b) or ({a, b} <= {'object_or_pointer', 'pointer'}) or ({a, b} <= {'bool', 'bool_or_i8'})
                    for a, b in zip(shim_param_classes, tgt_param_classes)
                )
                status = 'match' if (ret_ok and params_ok) else 'MISMATCH'
                row = {
                    'selector': r['selector'],
                    'target_owner': owner,
                    'target_declaration': minfo['declaration'],
                    'shim_types': r['types'],
                    'shim_return_class': shim_ret_cls,
                    'target_return_class': tgt_ret_cls,
                    'shim_param_classes': shim_param_classes,
                    'target_param_classes': tgt_param_classes,
                    'status': status,
                }
                if status == 'MISMATCH':
                    mismatches.append(row)
                out_rows.append(row)
        explicit_audit[arr_name] = out_rows

    # 3. Enumerate ALL resolveStub-reachable methods & ARM64 AAPCS ABI hazards across all 12 mapped classes
    spec = importlib.util.spec_from_file_location('a7g', Path(__file__).with_name('audit-source-and-a7-gates.py'))
    a7g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(a7g)
    fe_impls = a7g.parse_frontend_methods((ROOT / 'drivers/AdrenoMetal/NativeBridgeMetalFrontend.mm').read_text())

    explicit_by_fe = {}
    arr_to_fe = {
        'deviceMethods': ['NBDevice'],
        'queueMethods': ['NBQueue'],
        'resourceMethods': ['NBBuffer', 'NBTexture'],
        'commandBufferMethods': ['NBCommandBuffer'],
        'functionMethods': ['NBFunction'],
    }
    for arr_name, rows in cross['explicit_method_specs'].items():
        for fe in arr_to_fe[arr_name]:
            explicit_by_fe.setdefault(fe, set()).update(r['selector'] for r in rows)

    stub_hazards = {}
    iogpu_layer_float = 0
    iogpu_layer_struct = 0
    total_chain_float = 0
    total_chain_struct = 0

    for fe_cls, info in cross['resolveStub_exposure_iogpu_layer'].items():
        iogpu_name = info['iogpu_class']
        chain_methods = {}
        chain_walked = []
        cur = iogpu_name
        seen = set()
        while cur and cur not in seen and cur in all_cls:
            seen.add(cur)
            chain_walked.append(cur)
            for sel, minfo in all_cls[cur]['methods'].items():
                chain_methods.setdefault(sel, {'owner': cur, **minfo})
            cur = all_cls[cur]['super']

        implemented = set(fe_impls.get(fe_cls, set())) | explicit_by_fe.get(fe_cls, set())
        if fe_cls != 'NBDevice':
            implemented |= fe_impls.get('NBObject', set())
        if fe_cls in ('NBRenderEncoder', 'NBComputeEncoder', 'NBBlitEncoder'):
            implemented |= fe_impls.get('NBEncoder', set())

        floats, structs, objs, ptrs, scalars, others = [], [], [], [], [], []
        iogpu_floats, iogpu_structs = [], []
        for sel, minfo in sorted(chain_methods.items()):
            if sel in implemented:
                continue
            # NBDevice subclasses _MTLDevice directly, so _MTLDevice methods are inherited natively, not stubbed!
            if fe_cls == 'NBDevice' and minfo['owner'] not in iogpu_cls:
                continue
            ret_cls, _ = ctype_to_objc_return_class(minfo['return_type'])
            item = {
                'selector': sel,
                'owner': minfo['owner'],
                'return_type': minfo['return_type'],
                'declaration': minfo['declaration'],
                'in_IOGPU_layer': minfo['owner'] in iogpu_cls,
            }
            if ret_cls == 'hazard_float_or_double':
                floats.append(item)
                if item['in_IOGPU_layer']:
                    iogpu_floats.append(item)
            elif ret_cls == 'hazard_struct_aggregate':
                structs.append(item)
                if item['in_IOGPU_layer']:
                    iogpu_structs.append(item)
            elif ret_cls == 'object_or_pointer':
                objs.append(item)
            elif ret_cls == 'pointer':
                ptrs.append(item)
            elif ret_cls in ('void', 'bool', 'u64', 'i64', 'u32', 'i32', 'u16', 'i16', 'u8', 'i8'):
                scalars.append(item)
            else:
                others.append(item)

        iogpu_layer_float += len(iogpu_floats)
        iogpu_layer_struct += len(iogpu_structs)
        total_chain_float += len(floats)
        total_chain_struct += len(structs)
        stub_hazards[fe_cls] = {
            'iogpu_class': iogpu_name,
            'hierarchy_walked': chain_walked,
            'counts': {
                'float_or_double_hazards': len(floats),
                'struct_aggregate_hazards': len(structs),
                'iogpu_layer_float_or_double': len(iogpu_floats),
                'iogpu_layer_struct_aggregate': len(iogpu_structs),
                'object_returns_returning_nil': len(objs),
                'pointer_returns_returning_null': len(ptrs),
                'safe_scalar_or_void': len(scalars),
                'other': len(others),
            },
            'float_or_double_hazards': floats,
            'struct_aggregate_hazards': structs,
            'other_returns': others,
        }

    # 4. Verify NativeAdrenoMetalPlugin.mm CAWindowServerDisplay swizzle targets
    ca_methods = ca_cls.get('CAWindowServerDisplay', {}).get('methods', {})
    ca_checks = {
        'nextWakeupTime': ca_methods.get('nextWakeupTime'),
        'beginExternalUpdate:usingSoftwareRenderer:': ca_methods.get('beginExternalUpdate:usingSoftwareRenderer:'),
    }

    report = {
        'scope': 'Typed ObjC method-signature and ARM64 AAPCS resolveStub hazard audit against pinned 26C5035r IOGPU, Metal, and QuartzCore',
        'inputs_sha256': {
            'IOGPU.typed.h': sha(iogpu_path),
            'Metal.typed.h': sha(metal_path),
            'Metal.protocols.h': sha(protos_path),
            'CAWindowServerDisplay.classdump.h': sha(ca_path),
        },
        'parsed_class_counts': {'IOGPU': len(iogpu_cls), 'Metal': len(metal_cls)},
        'protocol_conformance_checks': proto_checks,
        'all_19_protocols_present_in_26C5035r': all(x['present_in_26C5035r_Metal_or_IOGPU'] for x in proto_checks),
        'explicit_MethodSpec_checks': explicit_audit,
        'explicit_MethodSpec_mismatches': mismatches,
        'explicit_MethodSpec_not_in_reference_hierarchy': not_in_hierarchy,
        'resolveStub_aapcs_hazards_by_class': stub_hazards,
        'CAWindowServerDisplay_swizzle_targets': ca_checks,
        'summary': {
            'explicit_MethodSpec_total': sum(len(v) for v in explicit_audit.values()),
            'explicit_MethodSpec_mismatches': len(mismatches),
            'explicit_MethodSpec_not_in_reference_hierarchy': len(not_in_hierarchy),
            'resolveStub_iogpu_layer_float_double_hazards': iogpu_layer_float,
            'resolveStub_iogpu_layer_struct_aggregate_hazards': iogpu_layer_struct,
            'resolveStub_total_chain_float_double_hazards': total_chain_float,
            'resolveStub_total_chain_struct_aggregate_hazards': total_chain_struct,
        },
    }
    (EV / 'typed-objc-abi-audit.json').write_text(json.dumps(report, indent=2) + '\n')
    print('PASS: all 19 Metal protocols present in 26C5035r:', report['all_19_protocols_present_in_26C5035r'])
    print('Summary:', json.dumps(report['summary'], indent=2))
    if mismatches:
        print('EXPLICIT MISMATCHES:', json.dumps(mismatches, indent=2))
    if not_in_hierarchy:
        print('NOT IN REFERENCE HIERARCHY:', json.dumps(not_in_hierarchy, indent=2))


if __name__ == '__main__':
    main()
