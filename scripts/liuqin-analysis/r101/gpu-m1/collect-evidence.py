#!/usr/bin/env python3
"""Collect source-qualified excerpts and comparator inputs; no driver builds."""
from pathlib import Path
import hashlib
import json
import re
import shutil

ROOT = Path(__file__).resolve().parents[4]
B = ROOT / 'out/liuqin-r101-gpu-m1'
L = B / 'linux-release-clean'
E = B / 'evidence'

def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def blank(m):
    return ''.join('\n' if c == '\n' else ' ' for c in m[0])

def function(text, name):
    clean = re.sub(r'/\*.*?\*/|//[^\n]*|"(?:\\.|[^"\\])*"', blank, text, flags=re.S)
    m = re.search(r'\b' + re.escape(name) + r'\s*\([^;{}]*\)\s*\{', clean)
    assert m, name
    start = clean.rfind('\n', 0, m.start()) + 1
    # Include declaration's previous line if the return type is split.
    at = m.end() - 1
    level = 0
    for end in range(at, len(clean)):
        level += (clean[end] == '{') - (clean[end] == '}')
        if level == 0:
            return start, end + 1, text[start:end + 1]
    raise AssertionError(name)

targets = {
 'drivers/gpu/drm/msm/adreno/a6xx_gpu.c': ['a7xx_cp_init', 'a7xx_preempt_start', 'hw_init', 'a7xx_submit', 'a6xx_set_cp_protect', 'a6xx_set_ubwc_config', 'a7xx_llc_activate'],
 'drivers/gpu/drm/msm/adreno/a6xx_gmu.c': ['a6xx_gmu_resume', 'a6xx_gmu_fw_load', 'a6xx_gmu_fw_start', 'a6xx_gmu_rpmh_init', 'a6xx_rpmh_start', 'a6xx_gmu_shutdown', 'a6xx_gmu_stop', 'a6xx_gmu_rpmh_arc_votes_init', 'a6xx_gmu_acd_probe', 'a6xx_gmu_irq', 'a6xx_hfi_irq'],
 'drivers/gpu/drm/msm/adreno/a6xx_hfi.c': ['a730_build_bw_table', 'a740_build_bw_table', 'a6xx_hfi_init', 'a6xx_hfi_start', 'a6xx_hfi_send_msg'],
 'drivers/gpu/drm/msm/adreno/a6xx_preempt.c': ['a6xx_preempt_hw_init', 'preempt_init_ring', 'a6xx_preempt_init'],
 'drivers/iommu/arm/arm-smmu/arm-smmu-qcom.c': ['qcom_adreno_smmu_alloc_context_bank', 'qcom_adreno_smmu_init_context', 'qcom_adreno_smmu_set_ttbr0_cfg', 'qcom_adreno_smmu_write_sctlr'],
 'drivers/iommu/arm/arm-smmu/arm-smmu.c': ['arm_smmu_init_context_bank', 'arm_smmu_write_context_bank'],
 'drivers/firmware/qcom/qcom_scm.c': ['qcom_scm_pas_init_image', 'qcom_scm_pas_mem_setup', 'qcom_scm_pas_auth_and_reset'],
 'drivers/soc/qcom/mdt_loader.c': ['mdt_phdr_loadable', 'qcom_mdt_get_size', 'qcom_mdt_read_metadata', 'qcom_mdt_pas_init', '__qcom_mdt_load', 'qcom_mdt_load'],
 'drivers/clk/qcom/gpucc-sm8450.c': ['gpu_cc_sm8450_probe'],
}
excerpts = []
index = []
comparison = []
for path, names in targets.items():
    text = (L / path).read_text()
    for name in names:
        start, end, body = function(text, name)
        line = text.count('\n', 0, start) + 1
        final = text.count('\n', 0, end) + 1
        index.append({'path': path, 'function': name, 'start_line': line, 'end_line': final, 'sha256': hashlib.sha256(body.encode()).hexdigest()})
        excerpts.append(f'\n===== {path}:{line} {name} =====\n' + '\n'.join(f'{i}: {s}' for i, s in enumerate(body.splitlines(), line)))
        old = (B / 'linux-head' / path).read_text()
        _, _, previous = function(old, name)
        comparison.append({'path': path, 'function': name, 'head_equals_release': body == previous})
(E / 'source-excerpts.txt').write_text('\n'.join(excerpts) + '\n')
(E / 'source-excerpt-index.json').write_text(json.dumps(index, indent=2) + '\n')
(E / 'function-reconciliation.json').write_text(json.dumps(comparison, indent=2) + '\n')

source_paths = [ROOT / 'drivers/Adreno740', ROOT / 'drivers/AdrenoMetal', ROOT / 'kits/ArmSmmu4K', ROOT / 'kits/AdrenoFirmware', ROOT / 'kits/AdrenoPM4', B / 'sm8550-reference/kits/Sm8550Platform']
frozen = B / 'unixnu-comparator'
manifest = {}
for directory in source_paths:
    for p in sorted(directory.iterdir()):
        if not p.is_file() or p.name == '.git':
            continue
        dst = frozen / directory.name / p.name
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(p, dst)
        manifest[str(dst.relative_to(B))] = {'sha256': digest(dst), 'source': str(p)}
(E / 'unixnu-comparator-files.json').write_text(json.dumps(manifest, indent=2) + '\n')
print('extracted functions:', len(index), 'comparator files:', len(manifest))
print('changed functions:', [x['function'] for x in comparison if not x['head_equals_release']])
