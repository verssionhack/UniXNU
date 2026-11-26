#!/usr/bin/env python3
"""Validated incremental replacement of only this round's last observer patch."""
from pathlib import Path
import argparse,hashlib,json,subprocess
R=Path(__file__).resolve().parents[3];W=R/'out/liuqin-r101-work';work=R/'out/liuqin/macos-27.3-26C5035r/liuqin';source=work/'tree/.cache/xnu-work'
parser=argparse.ArgumentParser();parser.add_argument('--old',type=Path,required=True);args=parser.parse_args()
old=args.old.resolve();new=W/'observer.patch'
stamp=work/'xnu-inputs.json';j=json.loads(stamp.read_text());entries=[x for x in j['patches'] if x['path'].endswith('liuqin-r101.patch')]
assert len(entries)==1 and entries[0]['sha256']==hashlib.sha256(old.read_bytes()).hexdigest()
assert Path(entries[0]['path']).read_bytes()==new.read_bytes()
for args in [['--reverse','--check',old],['--reverse',old],['--check',new],[new]]:
    subprocess.run(['git','-C',str(source),'apply',*[str(x) for x in args]],check=True)
entries[0]['sha256']=hashlib.sha256(new.read_bytes()).hexdigest()
# All prior source/patch identities remain exactly unchanged. This avoids
# throwing away a validated source tree just because this final patch changed.
stamp.write_text(json.dumps(j,indent=2)+'\n')
print('Replaced exactly the final observer patch; earlier patch identities unchanged.')
