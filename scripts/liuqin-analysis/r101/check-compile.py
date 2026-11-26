#!/usr/bin/env python3
"""Compile changed units with saved native commands before another complete build."""
from pathlib import Path
import concurrent.futures,json,subprocess
R=Path(__file__).resolve().parents[3];W=R/'out/liuqin-r101-work';O=R/'out/liuqin/macos-27.3-26C5035r/liuqin/tree/build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837'
def run(rel):
    p=O/rel;j=json.loads(p.read_text().strip().rstrip(','));args=j['arguments'];cmd=[];i=0
    while i<len(args):
        if args[i] in ['-MJ','-MF','-MT']:i+=2;continue
        cmd.append(args[i]);i+=1
    cmd+=['-w'];r=subprocess.run(cmd,cwd=j['directory'],capture_output=True,text=True)
    log=W/('compile-'+p.stem+'.log');log.write_text(r.stdout+r.stderr)
    return {'unit':rel,'exit':r.returncode,'log':str(log.relative_to(R)),'output':r.stderr[-5000:]}
units=['bsd/DEVELOPMENT/liuqin_perf.o.json','osfmk/DEVELOPMENT/thread.o.json','iokit/DEVELOPMENT/IOUserClient.cpo.json','osfmk/DEVELOPMENT/machine.o.json','osfmk/DEVELOPMENT/ipc_kmsg.o.json','osfmk/DEVELOPMENT/sleh.o.json']
with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(run,units))
(W/'compile-check.json').write_text(json.dumps(results,indent=2)+'\n')
for result in results:print(json.dumps(result))
raise SystemExit(any(x['exit'] for x in results))
