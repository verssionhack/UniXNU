#!/usr/bin/env python3
"""UUID/SHA-pinned callsite checks and offline symbolication of a verified snapshot."""
from pathlib import Path
import argparse,importlib.util,json,struct,subprocess
H=Path(__file__).resolve().parent;R=H.parents[3]
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder',type=Path);p.add_argument('--target',type=int,choices=[60,120,300],required=True);p.add_argument('--provisional',action='store_true');args=p.parse_args();folder=args.folder.resolve();suffix='-provisional' if args.provisional else ''
export=load('capture_frame_export',H.parent/'a2/frames-from-log.py');validator=load('native_callsite_checks',H.parent/'validate-user-frames.py');record=export.export.export((folder/'usb.log').read_bytes(),args.target)
out=folder/f'frames-{args.target}{suffix}.json';out.write_text(json.dumps(record,indent=2)+'\n')
manifest=json.loads((R/'out/liuqin-r101-work/evidence/review-A1/host-cache-manifest.json').read_text());addresses=[(f['lr_raw']&((1<<record['va_bits'])-1))-record['slide']-4 for f in record['frames']];selected=[]
for entry in manifest:
 file=R/entry['path']
 with file.open('rb') as stream:
  header=stream.read(104)
  if not header.startswith(b'dyld_v1'):continue
  offset,count=struct.unpack_from('<II',header,16)
  if count>1024:continue
  stream.seek(offset);maps=[struct.unpack('<QQQII',stream.read(32)) for _ in range(count)]
  if entry is manifest[0] or file.name=='dyld_shared_cache_arm64e' or any(prot&4 and any(base<=a and a+4<=base+size for a in addresses) for base,size,_,_,prot in maps):selected.append({**entry,'path':str(file)})
selected.sort(key=lambda e:Path(e['path']).name!='dyld_shared_cache_arm64e');caches=[]
try:
 for entry in selected:caches.append(validator.Cache(entry))
 result=validator.validate(record,caches)
finally:
 for cache in caches:cache.data.close()
C=Path('/media/disk_4/unixnu_workspace/ramdisk_dir/liuqin-r101-host-cache/dyld_shared_cache_arm64e');tool=C.parent.parent/'tools/ipsw';symbolcache=R/'out/liuqin-r101-work/evidence/review-A1/cache-symbols.a2s';symbols={}
for frame in result['frames']:
 if frame['status']!='callsite-plausible':continue
 lr=frame['lr_normalized']-record['slide'];key=hex(lr)
 if key not in symbols:
  proc=subprocess.run([str(tool),'dyld','a2s','--image','--mapping','--cache',str(symbolcache),str(C),key],capture_output=True,text=True,check=True);symbols[key]=proc.stdout+proc.stderr
 frame['symbolication']=symbols[key]
result['record_path']=out.name;result['cache_inputs']=selected;result['provisional']=args.provisional;result['target_s']=args.target;result['plausible_frames']=sum(f['status']=='callsite-plausible' for f in result['frames']);result['raw_frame_count']=len(result['frames']);result['limits']+=' Raw stack is racy and depth-limited; two idle thread stacks are not a service-owner trace.'
(folder/f'frames-{args.target}-validation{suffix}.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:result[k] for k in ['target_s','raw_frame_count','plausible_frames','callsite_validation_passed','native_reader_validated','provisional']},indent=2))
