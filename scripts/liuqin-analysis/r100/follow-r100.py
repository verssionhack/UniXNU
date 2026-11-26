#!/usr/bin/env python3
"""Extend one existing boot capture without resetting; preserve abort guard history."""
import argparse, datetime, hashlib, importlib.util, json, time
from pathlib import Path
p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder',type=Path);p.add_argument('--seconds',type=int,default=210);a=p.parse_args()
root=Path(__file__).resolve().parents[3]
ev=root/'out/liuqin-r100-work/evidence'
def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
runner=module('r100',ev/'run-r100.py');common=module('device',ev/'device_runner.py')
record=json.loads((a.folder/'boot-record.json').read_text())
origin=datetime.datetime.fromisoformat(record['start']).timestamp()
monitor=runner.AbortMonitor(record['max_si_limit'],record['si_window'])
# Historical timestamps do not exist per chunk. Feed only as pre-grace history;
# this preserves cumulative SI/exits counters without inventing 30s windows.
monitor.feed_chunk((a.folder/'usb.log').read_bytes(),0)
monitor.abort_reason=None
s=common.open_debug()
if s is None:raise SystemExit('Debug port absent; no reboot attempted')
start=time.monotonic();total=0;reason=None;fatal=None
meta={'start':datetime.datetime.now().astimezone().isoformat(),'boot_image_sha256':record['image_sha256'],'resets':0,'replay_requested':False,'historical_guard_timestamps':'not recorded; historical counters seeded at zero elapsed'}
path=a.folder/'usb-follow.log'
try:
    with s,path.open('xb',buffering=0) as f:
        s.dtr=True;s.rts=True
        while time.monotonic()-start<a.seconds:
            data=s.read(8192)
            if not data:continue
            f.write(data);total+=len(data)
            reason=monitor.feed_chunk(data,time.time()-origin)
            match=runner.FATAL.search(monitor.tail)
            if match:fatal=match.group().decode(errors='replace')
            if reason or fatal:break
finally:
    if s.is_open:s.close()
    meta.update(end=datetime.datetime.now().astimezone().isoformat(),captured_bytes=total,elapsed_seconds=time.monotonic()-start,abort_reason=reason,fatal=fatal,log_sha256=common.sha(path))
    (a.folder/'follow-record.json').write_text(json.dumps(meta,indent=2)+'\n')
    print(json.dumps(meta,indent=2))
