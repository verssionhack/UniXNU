#!/usr/bin/env python3
from pathlib import Path
import importlib.util
H=Path(__file__).resolve().parent
def load(name,p):
 s=importlib.util.spec_from_file_location(name,p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
def assess(folder):
 r=load('a5r1_assessment',H.parent/'a5r1/assessment.py').assess(folder);publication=load('publication',H/'publication.py');raw=(folder/'usb.log').read_bytes();checks={};rows=[]
 for t in [60,120,300]:
  state=next((s.get('outcome') for s in r['state_outcomes'] if s['target_s']==t),None)
  try:
   p=publication.snapshot(raw,t,state);rows.append(p);checks[f'publication_protocol_{t}']=p['protocol_complete']
  except (ValueError,KeyError) as e:rows.append({'target_s':t,'outcome':'unknown','error':str(e)});checks[f'publication_protocol_{t}']=False
 r['publication_contract']=checks;r['publication_outcomes']=rows
 if not all(checks.values()):r['status']='incomplete-publication-observer-capture';r['exit_code']=5
 return r
