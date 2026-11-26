#!/usr/bin/env python3
"""Replay every recorded r101 guard call, including empty polls, without device access."""
from pathlib import Path
import argparse,hashlib,importlib.util,json
H=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('runner',H/'run-r101.py');runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)
def replay(folder,verify_sources=True):
    record=json.loads((folder/'boot-record.json').read_text());raw=(folder/'usb.log').read_bytes();trace=(folder/'guard-trace.jsonl').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=record['log_sha256']:raise ValueError('USB log hash mismatch')
    if hashlib.sha256(trace).hexdigest()!=record['trace_sha256']:raise ValueError('Trace hash mismatch')
    if verify_sources:
        for rel,digest in record['source_sha256'].items():
            if runner.sha(runner.R/rel)!=digest:raise ValueError('Guard source changed: '+rel)
    monitor=runner.Monitor();offset=0;steps=0;end=None
    for event in [json.loads(x) for x in trace.splitlines()]:
        if event['event']=='monitor':
            if event['offset']!=offset:raise ValueError('Non-contiguous recorded chunk offsets')
            data=raw[offset:offset+event['length']]
            if len(data)!=event['length'] or hashlib.sha256(data).hexdigest()!=event['chunk_sha256']:raise ValueError('Chunk differs from trace')
            result=monitor.step(event['elapsed'],data)
            if result!=event['result']:raise ValueError(f'Guard decision mismatch at event {steps}')
            offset+=len(data);steps+=1
        elif event['event']=='capture_end':end=event
    if offset!=len(raw) or end is None or end['bytes']!=len(raw):raise ValueError('Incomplete capture trace')
    if monitor.summary()!=end['result']:raise ValueError('Final guard state differs')
    return {'status':'PASS','timing':'exact-recorded-calls','steps':steps,'bytes':offset,'result':monitor.summary()}
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder',type=Path);a=p.parse_args();print(json.dumps(replay(a.folder),indent=2))
