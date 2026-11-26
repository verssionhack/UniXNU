#!/usr/bin/env python3
from pathlib import Path
import importlib.util,json,re
H=Path(__file__).resolve().parent
def load(name,p):
 s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def assess(folder):
 result=load('previous_assessment',H.parent/'a2r1/assessment.py').assess(folder)
 target=load('target_export',H/'target-frames.py');raw=(folder/'usb.log').read_bytes();checks={};records=[]
 for t in [60,120,300]:
  for name in ['WindowServer','clocksyncd']:
   key=f'{name}_{t}'
   try:
    r=target.export(raw,t,name);records.append(r);checks[key]=bool(r['waits'] and r['frames'] and r['main_image']['status']=='ok' and r['invalid_address_read_failed'])
   except (ValueError,KeyError) as exc:checks[key]=False
 lines=raw.decode(errors='replace').splitlines();sweeps=[target.fields(l) for l in lines if l.startswith('LQ102 TIMESYNC_COVERAGE:')]
 checks['registry_sweeps_complete']=len(sweeps)==3 and all(r.get('valid')=='1' and r.get('visit_truncated')=='0' and r.get('hit_truncated')=='0' for r in sweeps)
 result['target_contract']=checks;result['target_records']=records;result['registry_coverage']=sweeps
 if not all(checks.values()):result['status']='incomplete-target-observer-capture';result['exit_code']=5
 return result
