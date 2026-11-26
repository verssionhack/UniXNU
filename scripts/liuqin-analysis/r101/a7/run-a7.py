#!/usr/bin/env python3
"""Launch frozen A6 capture code with only its evidence paths directed to A7.

No guard, parser, assessment, timing, device command or recovery-policy change.
Refuses another A7 capture directory: this authorization is for one boot.
"""
from pathlib import Path
import ast,hashlib,json,sys
R=Path(__file__).resolve().parents[4];H=Path(__file__).resolve().parent
W=R/'out/liuqin-r101-a7-work';E=W/'evidence'
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
for manifest in [E/'host-manifest.json',R/'out/liuqin-r101-a6-work/evidence/result-manifest.json']:
    for n,d in json.loads(manifest.read_text())['files'].items():
        if sha(R/n)!=d:raise RuntimeError('Frozen artifact mismatch: '+n)
p=R/'scripts/liuqin-analysis/r101/a6/run-a6.py';original=p.read_text()
old='out/liuqin-r101-a6-work';new='out/liuqin-r101-a7-work'
assert original.count(old)==2
effective=original.replace(old,new)
# Reversibility establishes that the two evidence-path constants are the only
# changes. The original __file__ retains original assessment/dependency loading.
assert effective.replace(new,old)==original
def monitor(s):
    return ast.dump(next(n for n in ast.parse(s).body if isinstance(n,ast.ClassDef) and n.name=='Monitor'),include_attributes=False)
assert monitor(original)==monitor(effective)
if '--check' not in sys.argv:
    if list((E/'a').glob('boot-A7-*')):raise RuntimeError('A7 capture already exists; no retry authorized by this launcher')
    if '--tag' not in sys.argv or sys.argv[sys.argv.index('--tag')+1]!='A7':raise RuntimeError('Use --tag A7')
    if '--seconds' not in sys.argv or sys.argv[sys.argv.index('--seconds')+1]!='480':raise RuntimeError('Use --seconds 480')
    launch=E/'launch-authorization.json'
    if launch.exists():raise RuntimeError('Launch already allocated; inspect evidence before any retry')
    (E/'effective-A6-runner.py.txt').write_text(effective)
    launch.write_text(json.dumps({'authorization':'User accepted A7 host qualification and explicitly cleared one volatile boot; standing no-separate-go authorization','boot_sha256':'ffdec111a73bdfafd5be42574dbf71d0542c0c78daffb8d98fde8942a91a3d5a','launcher_sha256':sha(Path(__file__)),'frozen_A6_runner_sha256':sha(p),'effective_runner_sha256':hashlib.sha256(effective.encode()).hexdigest(),'substitution':{'from':old,'to':new,'count':2},'Monitor_AST_equal':True,'assessment':'unmodified frozen A6 assessment and its original dependencies','cooldown_seconds':120,'capture_seconds':480,'boot_count_authorized':1,'flash':False,'private_key_access':False},indent=2)+'\n')
exec(compile(effective,str(p),'exec'),{'__file__':str(p),'__name__':'__main__'})
