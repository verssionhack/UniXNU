#!/usr/bin/env python3
from pathlib import Path
import importlib.util
H=Path(__file__).resolve().parent
def load(name,p):
 s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def assess(folder):
 result=load('prior_target_assessment',H.parent/'a4/assessment.py').assess(folder);decoder=load('a5r1_decoder',H/'decode-state.py');raw=(folder/'usb.log').read_bytes();checks={};states=[]
 for when in [60,120,300]:
  try:
   r=decoder.snapshot(raw,when);states.append(r);checks[f'state_protocol_{when}']=len(r['raw_begin'])==1 and len(r['raw_end'])==1 and r['raw_end'][0].get('status')=='recorded' and int(r['raw_end'][0].get('requests','65'))<=64 and r['raw_begin'][0].get('invalid_rc')=='14'
  except (ValueError,KeyError) as e:checks[f'state_protocol_{when}']=False;states.append({'target_s':when,'outcome':'unknown','error':str(e)})
 result['state_contract']=checks;result['state_outcomes']=states;result['state_classification_required_review']=True
 if not all(checks.values()):result['status']='incomplete-state-observer-capture';result['exit_code']=5
 return result
