#!/usr/bin/env python3
"""Compile the dormant A2 native reader/candidate branch without changing build objects."""
from pathlib import Path
import json,subprocess
R=Path(__file__).resolve().parents[3];W=R/'out/liuqin-r101-work'
O=R/'out/liuqin/macos-27.3-26C5035r/liuqin/tree/build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837'
j=json.loads((O/'osfmk/DEVELOPMENT/thread.o.json').read_text().strip().rstrip(','));args=j['arguments'];cmd=[];i=0
while i<len(args):
    if args[i] in ['-MJ','-MF','-MT']:i+=2;continue
    if args[i]=='-o':cmd+=['-o',str(W/'thread-candidates-check.o')];i+=2;continue
    cmd.append(args[i]);i+=1
cmd+=['-DR101_CAPTURE_CANDIDATES=1']
r=subprocess.run(cmd,cwd=j['directory'],capture_output=True,text=True)
(W/'compile-candidates.log').write_text(r.stdout+r.stderr)
print(json.dumps({'exit':r.returncode,'candidate_mode':True,'build_objects_changed':False,'log':str(W/'compile-candidates.log')}));raise SystemExit(r.returncode)
