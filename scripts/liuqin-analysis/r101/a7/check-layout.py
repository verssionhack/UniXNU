#!/usr/bin/env python3
"""Hard A6 layout limits. Failure records rejection; never packages or boots."""
from pathlib import Path
import importlib.util,json,sys
R=Path(__file__).resolve().parents[4];W=R/'out/liuqin-r101-a7-work';e=W/'evidence/a';e.mkdir(parents=True,exist_ok=True)
p=R/'scripts/liuqin-analysis/r100/package.py';s=importlib.util.spec_from_file_location('a7_layout',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
candidate=e/'standalone.macho'
if not candidate.is_file():candidate=R/'out/liuqin/macos-27.3-26C5035r/liuqin/tree/build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837.unstripped.noctf'
segments,sections=m.parse_macho_segments(candidate)
checks={'TEXT':segments['__TEXT']['vmsize']<=m.TEXT_CAP,'DATA':segments['__DATA']['vmsize']<=m.DATA_CAP,'const_VMA':sections['__TEXT,__const']>=m.MIN_TEXT_CONST_VMA}
r={'status':'PASS' if all(checks.values()) else 'REJECTED-layout-gate','checks':checks,'segments':{k:hex(segments[k]['vmsize']) for k in ['__TEXT','__DATA','__TEXT_EXEC']},'text_const_vma':hex(sections['__TEXT,__const']),'const_margin_bytes':sections['__TEXT,__const']-m.MIN_TEXT_CONST_VMA,'caps':{'TEXT':hex(m.TEXT_CAP),'DATA':hex(m.DATA_CAP),'const_floor':hex(m.MIN_TEXT_CONST_VMA)},'hardware_boots':0,'observer_retirement':False,'caps_relaxed':False}
(e/'layout-gate.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2));sys.exit(0 if all(checks.values()) else 2)
