#!/usr/bin/env python3
"""Export one complete raw-candidate snapshot for UUID-pinned host validation."""
import argparse,hashlib,importlib.util,json,re
from pathlib import Path
H=Path(__file__).resolve().parent
spec=importlib.util.spec_from_file_location('checks',H/'coverage.py');checks=importlib.util.module_from_spec(spec);spec.loader.exec_module(checks)
def export(raw,target):
    lines=raw.decode('utf-8',errors='strict').splitlines()
    snapshots=[s for s in checks.snapshot_coverage(lines) if s['target_s']==target]
    if len(snapshots)!=1 or not snapshots[0]['complete']:raise ValueError('require exactly one complete snapshot with verified checksum')
    snap=snapshots[0];rows=lines[snap['begin_line']:snap['end_line']-1]
    def fields(line):return dict(re.findall(r'(\w+)=([^ ]+)',line))
    maps=[fields(l) for l in rows if l.startswith('LQ101 USER_MAP:')];shared=[fields(l) for l in rows if l.startswith('LQ101 SHARED_REGION:')]
    if len(maps)!=1 or len(shared)!=1:raise ValueError('missing/unambiguous geometry or shared region required')
    va=maps[0];sr=shared[0]
    if va.get('source')!='BCM2837-native-4k-TTBR0' or int(va['machine_max'],16)!=1<<int(va['va_bits']):raise ValueError('unqualified VA geometry')
    frames=[fields(l) for l in rows if l.startswith('LQ101 FRAME:')]
    if not frames:raise ValueError('snapshot has no raw candidate frames; A1 is gated')
    validations={int(f['tid']):f for l in rows if l.startswith('LQ101 WALK_VALIDATION:') for f in [fields(l)] if 'tid' in f}
    tids={int(f['tid']) for f in frames}
    invalid_ok=all(tid in validations and int(validations[tid].get('invalid_rc','0'))!=0 and validations[tid].get('mode')=='raw-host-callsite-pending' for tid in tids)
    return {'log_sha256':hashlib.sha256(raw).hexdigest(),'target_s':target,'va_bits':int(va['va_bits']),
      'map_min':int(va['min'],16),'map_max':int(va['max'],16),'slide':int(sr['slide'],16),'cache_uuid':sr['uuid'],
      'invalid_address_read_failed':invalid_ok,'frames':[{'tid':int(f['tid']),'depth':int(f['depth']),'lr_raw':int(f['lr_raw'],16),'fp_raw':int(f['fp_raw'],16)} for f in frames]}
def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('log',type=Path);p.add_argument('--target',type=int,choices=[60,120,300],required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    a.output.write_text(json.dumps(export(a.log.read_bytes(),a.target),indent=2)+'\n')
if __name__=='__main__':main()
