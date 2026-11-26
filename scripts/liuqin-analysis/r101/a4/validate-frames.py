#!/usr/bin/env python3
"""Check target-specific LRs against pinned cache and live-UUID-selected daemon."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,struct,subprocess
H=Path(__file__).resolve().parent;R=H.parents[3]
def load(name,path):
 spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
export=load('target_export',H/'target-frames.py');validator=load('native_callsite_checks',H.parent/'validate-user-frames.py')
def validate(folder,target,name):
 record=export.export((folder/'usb.log').read_bytes(),target,name);out=folder/f'frames-{name}-{target}.json';out.write_text(json.dumps(record,indent=2)+'\n')
 main=None;timesync=R/'out/liuqin-r101-a3r1-work/evidence/timesync'
 if name=='clocksyncd':main=export.MainImage(timesync/'clocksyncd',json.loads((timesync/'inputs.json').read_text()),record['main_image'])
 addresses=[]
 for frame in record['frames']:
  lr=frame['lr_raw']&((1<<record['va_bits'])-1)
  if main and main.contains_runtime(lr-4):continue
  addresses.append(lr-record['slide']-4)
 manifest=json.loads((R/'out/liuqin-r101-work/evidence/review-A1/host-cache-manifest.json').read_text());selected=[]
 for entry in manifest:
  file=R/entry['path']
  with file.open('rb') as stream:
   header=stream.read(104)
   if not header.startswith(b'dyld_v1'):continue
   offset,count=struct.unpack_from('<II',header,16)
   if count>1024:continue
   stream.seek(offset);maps=[struct.unpack('<QQQII',stream.read(32)) for _ in range(count)]
   if file.name=='dyld_shared_cache_arm64e' or any(prot&4 and any(base<=a and a+4<=base+size for a in addresses) for base,size,_,_,prot in maps):selected.append({**entry,'path':str(file)})
 selected.sort(key=lambda e:Path(e['path']).name!='dyld_shared_cache_arm64e');caches=[];rows=[]
 C=Path('/media/disk_4/unixnu_workspace/ramdisk_dir/liuqin-r101-host-cache/dyld_shared_cache_arm64e');tool=C.parent.parent/'tools/ipsw';symbolcache=R/'out/liuqin-r101-work/evidence/review-A1/cache-symbols.a2s';symbols={}
 main_symbols=json.loads((timesync/'clocksyncd-symbol-map.json').read_text())
 try:
  for entry in selected:caches.append(validator.Cache(entry))
  if caches[0].uuid!=record['cache_uuid']:raise ValueError('target cache UUID mismatch')
  for frame in record['frames']:
   lr=frame['lr_raw']&((1<<record['va_bits'])-1);is_main=bool(main and main.contains_runtime(lr-4));slide=main.slide if is_main else record['slide'];pc=lr-slide-4
   words=main.instruction(pc) if is_main else [w for c in caches for w in c.instruction(pc)]
   call=validator.is_call(words[0],pc) if len(words)==1 else None
   good=record['map_min']<=lr<record['map_max'] and not lr&3 and bool(call)
   row={**frame,'lr_normalized':lr,'image':'clocksyncd' if is_main else 'shared-cache','slide':hex(slide),'return_unslid':hex(lr-slide),'callsite_unslid':hex(pc),'call':call,'status':'callsite-plausible' if good else 'unresolved'}
   if good:
    key=(is_main,lr-slide)
    if key not in symbols:
     if is_main:
      # Address map applies only to the audited arm64e slice; another UUID stays unresolved.
      if main.uuid=='91f59f6a64c3321c88b00cc7a485ab1c':
       items=main_symbols.get('symbols',main_symbols) if isinstance(main_symbols,dict) else main_symbols
       candidates=[]
       if isinstance(items,dict):
        for a,n in items.items():
         try:address=int(a,0)
         except ValueError:continue
         if address<=lr-slide:candidates.append((address,n))
       if candidates:
        a,n=max(candidates);symbols[key]=f'{n} + {lr-slide-a:#x}'
       else:symbols[key]='see pinned executable symbol map'
      else:symbols[key]='different live slice; host symbol map not applicable'
     else:
      proc=subprocess.run([str(tool),'dyld','a2s','--image','--mapping','--cache',str(symbolcache),str(C),hex(lr-slide)],capture_output=True,text=True,check=True);symbols[key]=proc.stdout+proc.stderr
    row['symbolication']=symbols[key]
   rows.append(row)
 finally:
  for cache in caches:cache.data.close()
 result={'target_s':target,'name':name,'pid':record['pid'],'main_image':record['main_image'],'shared_region_slide':hex(record['slide']),'cache_uuid':record['cache_uuid'],'frames':rows,'raw_frame_count':len(rows),'plausible_frames':sum(r['status']=='callsite-plausible' for r in rows),'callsite_validation_passed':bool(rows) and record['invalid_address_read_failed'] and all(r['status']=='callsite-plausible' for r in rows),'native_reader_validated':False,'cache_inputs':selected,'limits':'Racy bounded frame candidates. Plausible callsites are not independent native-reader validation. Main executable uses its own live UUID and relocation; shared cache uses this target shared-region slide.'}
 (folder/f'frames-{name}-{target}-validation.json').write_text(json.dumps(result,indent=2)+'\n');return result
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder',type=Path);p.add_argument('--target',type=int,choices=[60,120,300],required=True);p.add_argument('--name',choices=['WindowServer','clocksyncd'],required=True);a=p.parse_args();r=validate(a.folder.resolve(),a.target,a.name);print(json.dumps({k:r[k] for k in ['target_s','name','raw_frame_count','plausible_frames','callsite_validation_passed','native_reader_validated']},indent=2))
