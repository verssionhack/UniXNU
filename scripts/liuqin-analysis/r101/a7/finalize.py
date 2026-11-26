#!/usr/bin/env python3
"""Accept and freeze host qualification only; no device access."""
from pathlib import Path
import datetime,difflib,hashlib,json,sys
R=Path(__file__).resolve().parents[4];H=Path(__file__).resolve().parent;W=R/'out/liuqin-r101-a7-work';A=R/'out/liuqin-r101-a6-work';E=W/'evidence';e=E/'a'
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
manifest=E/'host-manifest.json';assert not manifest.exists(),'preserve frozen result'
parent=json.loads((A/'evidence/a/validation-summary.json').read_text());candidate=json.loads((e/'validation-summary.json').read_text())
for key in ['kernel_args','kernel_args_len','adt_sha256','trust_cache_sha256']:assert candidate[key]==parent[key],key
assert candidate['kernel_args_len']==999
assert sha(e/'boot.img')==candidate['boot_sha256'] and sha(e/'kernel.macho')==candidate['kernel_sha256']
assert json.loads((e/'layout-gate.json').read_text())['status']=='PASS'
assert json.loads((e/'aes-fileset-gate.json').read_text())['status']=='PASS'
assert json.loads((E/'host/interface-header-abi.json').read_text())['status']=='PASS'
sys.path.insert(0,str(R/'kits/XnuPrelink'))
from kc_image import Image
prelink=json.loads((e/'kernel.json').read_text());assert prelink['mapping_complete'] and not prelink['missing']
abi=json.loads((E/'archive/build-report.json').read_text());branches={x['symbol']:x for x in prelink['native_original_branches']};fix=Image((e/'kernel.macho').read_bytes()).fixups();data={};functions=0
for name,value in abi['bindings'].items():
    if name in branches:
        assert int(branches[name]['target'],16)==int(value,16),name;functions+=1
    else:
        assert name.endswith('10gMetaClassE') or name.startswith('__ZTV'),name
        sites=[hex(s) for s,p in fix.items() if p[0]==int(value,16)];assert sites,name;data[name]={'target':value,'sites':sites}
# The seed is an exact byte comparison with its accepted prior binary identity.
seed=(A/'evidence/a/standalone.macho').read_bytes()[0xde0000:0xde0000+74048]
assert hashlib.sha256(seed).hexdigest()=='072eda49e3a55e5c7e762604cdf7406d9a2421e23a8d26ea557f6f6723c32505'
raw=(e/'standalone.macho').read_bytes();assert raw.count(seed)==1
(E/'Data-seed-audit.json').write_text(json.dumps({'Data_seed_identical':True,'compiled_bytes':len(seed),'sha256':hashlib.sha256(seed).hexdigest(),'A6_offset':'0xde0000','A7_offset':hex(raw.find(seed)),'capacity_bytes':536870912},indent=2)+'\n')
changes=''
for n in ['board.toml','configs/liuqin_defconfig']:
    old=(A/'device-a'/n).read_text();new=(W/'device-a'/n).read_text()
    changes+=''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='A6/'+n,tofile='A7/'+n))
(E/'A6-to-A7-device-config.patch').write_text(changes)
old=json.loads((A/'evidence/result-manifest.json').read_text())['files']
for n,h in old.items():assert sha(R/n)==h,n
report=json.loads((E/'host-verification.json').read_text());report.update(status='PASS-host-qualified-no-boot',boot_sha256=candidate['boot_sha256'],kernel_sha256=candidate['kernel_sha256'],actual_fileset_AES_header_payload='PASS',interface_header_slots=346,native_original_function_bindings_verified=functions,native_data_aliases_verified=data,Data_seed_identical=True,args_ADT_trust_equal_A6=True,owned_class_tests='PASS; host stubs only; see test-controller.py',hardware_boots=0)
(E/'host-verification.json').write_text(json.dumps(report,indent=2)+'\n')
files=[p for p in E.rglob('*') if p.is_file()]+[p for p in H.iterdir() if p.is_file()]+[W/n for n in ['build.log','package.log','verification.log','preparation.json','observer.patch']]
files += [p for p in (W/'device-a/drivers/LiuqinIdentityEthernet').rglob('*') if p.is_file()]
files += [W/'device-a'/n for n in ['board.toml','configs/liuqin_defconfig','scripts/build-identity-ethernet.py','scripts/net-ether-26C5035r.json','scripts/controller-slots.json','scripts/metaclass-Dispatch.json']]
result={'time':datetime.datetime.now().astimezone().isoformat(),'status':'PASS-host-qualified-no-boot','hardware_boots':0,'parent_A6_manifest_entries_verified':len(old),'boot_sha256':candidate['boot_sha256'],'kernel_sha256':candidate['kernel_sha256'],'files':{str(p.relative_to(R)):sha(p) for p in sorted(set(files))}}
manifest.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k!='native_data_aliases_verified'},indent=2));print('Frozen artifacts:',len(result['files']))
