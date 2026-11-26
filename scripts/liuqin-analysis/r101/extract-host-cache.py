#!/usr/bin/env python3
"""Extract the UUID-checkable cache set from the read-only pinned SystemOS image.
Host helper uses apfs-fuse's reader/decompressor library, never mounts a volume.
"""
from pathlib import Path
import concurrent.futures,hashlib,json,re,shutil,subprocess
R=Path(__file__).resolve().parents[3];W=R/'out/liuqin-r101-work';E=W/'evidence/review-A1';H=W/'host-tools';local=W/'host-cache-apfs'
external=Path('/media/disk_4/unixnu_workspace/ramdisk_dir/liuqin-r101-host-cache');external.mkdir(exist_ok=True)
image=Path('/media/disk_4/unixnu_workspace/ramdisk_dir/unixnu/ipsw/26C5035r/141-22145-021.dmg')
entries=[]
for block in (E/'systemos-file-list.txt').read_text().split('\n\n'):
 fields=dict(line.split(' = ',1) for line in block.splitlines() if ' = ' in line)
 path=fields.get('Path','')
 if re.fullmatch(r'System/Library/dyld/dyld_shared_cache_arm64e(?:\.\d+(?:\.dyld\w+)?)?(?:\.symbols)?',path):entries.append((path,int(fields['Size'])))
for p in local.glob('dyld_shared_cache_arm64e*'):
 if p.is_symlink():continue
 target=external/p.name
 if target.exists():raise RuntimeError('Refuse replacement '+str(target))
 shutil.move(str(p),target);p.symlink_to(target)
def extract(entry):
 path,size=entry;target=external/Path(path).name
 if not target.exists():
  run=subprocess.run([H/'extract-apfs-file',image,path,target],capture_output=True,text=True)
  if run.returncode:raise RuntimeError(f'{path}: {run.stdout} {run.stderr}')
 if target.stat().st_size!=size:raise RuntimeError('Size mismatch '+path)
 link=local/target.name
 if not link.exists():link.symlink_to(target)
 with target.open('rb') as stream:
  header=stream.read(104);stream.seek(0);digest=hashlib.file_digest(stream,'sha256').hexdigest()
 if not header.startswith(b'dyld_v1'):raise RuntimeError('Cache magic mismatch '+path)
 return {'path':str(link.relative_to(R)),'size':size,'sha256':digest,'uuid':header[88:104].hex()}
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:rows=list(pool.map(extract,entries))
rows.sort(key=lambda r:(not r['path'].endswith('dyld_shared_cache_arm64e'),r['path']))
assert rows[0]['uuid']=='8b1e17c672d6301791a4916022e3612e'
(E/'host-cache-manifest.json').write_text(json.dumps(rows,indent=2)+'\n')
print(json.dumps({'files':len(rows),'bytes':sum(r['size'] for r in rows),'cache_uuid':rows[0]['uuid'],'read_only_source':str(image)}))
