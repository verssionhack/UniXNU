#!/usr/bin/env python3
"""UUID-pinned offline register symbolication and instruction checks; no backtrace claim."""
from pathlib import Path
import hashlib,importlib.util,json,struct,subprocess
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
R=Path(__file__).resolve().parents[3];W=R/'out/liuqin-r101-work';E=W/'evidence/review-A1';cache=Path('/media/disk_4/unixnu_workspace/ramdisk_dir/liuqin-r101-host-cache/dyld_shared_cache_arm64e');tool=Path('/media/disk_4/unixnu_workspace/ramdisk_dir/tools/ipsw')
manifest=json.loads((E/'host-cache-manifest.json').read_text());main=next(x for x in manifest if x['path'].endswith('/dyld_shared_cache_arm64e'));code=next(x for x in manifest if x['path'].endswith('/dyld_shared_cache_arm64e.01'))
for entry in [main,code]:
 with (R/entry['path']).open('rb') as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==entry['sha256']
assert main['uuid']=='8b1e17c672d6301791a4916022e3612e'
slide=0xbcdc000;rows=[]
for tag,tid,kind,raw,qualified in [('windowserver-pc',676,'PC',0x18c224c20,True),('windowserver-lr',676,'LR',0x18c237964,True),('workqueue-pc',951,'PC',0x18c2269ec,True),('workqueue-lr',951,'LR',0x18c265fcc,True),('reportcrash-wfe-pc-assuming-common-slide',275,'PC',0x19128b518,False),('locationd-pc-assuming-common-slide',81,'PC',0x1f9300180,False)]:
 result=subprocess.run([tool,'dyld','a2s','--image','--mapping','--cache',E/'cache-symbols.a2s',cache,hex(raw-slide)],capture_output=True,text=True,check=True)
 (E/(tag+'-symbol.txt')).write_text(result.stdout+result.stderr)
 rows.append({'tag':tag,'tid':tid,'register':kind,'raw':hex(raw),'unslid':hex(raw-slide),'task_slide_recorded':qualified,'symbol_output':result.stdout})
with cache.open('rb') as stream:
 header=stream.read(104);off,n=struct.unpack_from('<II',header,16);stream.seek(off);mappings=[struct.unpack('<QQQII',stream.read(32)) for i in range(n)]
assert mappings[0][0]==0x180000000
instructions=[]
with (R/code['path']).open('rb') as stream:
 head=stream.read(104);off,n=struct.unpack_from('<II',head,16);stream.seek(off);maps=[struct.unpack('<QQQII',stream.read(32)) for i in range(n)]
 for pc in [0x180548c18,0x18055b950,0x1855af50c]:
  for base,size,fileoff,_,prot in maps:
   if base<=pc<base+size:
    stream.seek(fileoff+pc-base);data=stream.read(32)
    instructions += [{'address':hex(i.address),'bytes':i.bytes.hex(),'mnemonic':i.mnemonic,'operands':i.op_str} for i in Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN).disasm(data,pc)]
assert any(i['address']=='0x1855af518' and i['bytes']=='5f2003d5' and i['mnemonic']=='wfe' for i in instructions)
assert any(i['address']=='0x18055b960' and i['mnemonic']=='bl' and i['operands']=='#0x180548c18' for i in instructions)
spec=importlib.util.spec_from_file_location('validate',Path(__file__).with_name('validate-user-frames.py'));v=importlib.util.module_from_spec(spec);spec.loader.exec_module(v)
entries=[{**x,'path':str(R/x['path'])} for x in [main,code]];caches=[v.Cache(x) for x in entries]
record={'va_bits':39,'map_min':0x1001aa000,'map_max':1<<39,'slide':slide,'cache_uuid':main['uuid'],'invalid_address_read_failed':False,'frames':[{'tid':676,'depth':0,'lr_raw':0x18c237964,'source':'saved-LR-register'},{'tid':951,'depth':0,'lr_raw':0x18c265fcc,'source':'saved-LR-register'}]}
try:profile=v.validate(record,caches)
finally:
 for c in caches:c.data.close()
assert all(f['status']=='callsite-plausible' for f in profile['frames'])
assert profile['callsite_validation_passed'] is False and profile['native_reader_validated'] is False
result={'cache_uuid':main['uuid'],'shared_region_unslid_base':'0x180000000','main_sha256':main['sha256'],'text_subcache_sha256':code['sha256'],'rows':rows,'instructions':instructions,'saved_register_callsite_profile':profile,'note':'Two registers per thread; no validated unwind/backtrace. ReportCrash/locationd use common-slide hypothesis, not a recorded fault-task slide.'}
(E/'offline-symbolication.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps({'cache_uuid':main['uuid'],'base':'0x180000000','WindowServer_PC':'_mach_msg2_trap + 8','WindowServer_LR':'_mach_msg2_internal + 76','WFE_word_confirmed':True,'saved_LR_callsites_plausible':True,'native_reader_validated':False}))
