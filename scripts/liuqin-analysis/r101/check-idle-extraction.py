#!/usr/bin/env python3
"""Regression checks for the r100 initial/follow-up idle-sample selection error."""
from pathlib import Path
import importlib.util,json
R=Path(__file__).resolve().parents[3]
p=R/'scripts/liuqin-analysis/r100/audit-review.py'
s=importlib.util.spec_from_file_location('audit',p);audit=importlib.util.module_from_spec(s);s.loader.exec_module(audit)
b=R/'out/liuqin-r100-work/evidence/r100b/boot-r100b-20261120-155900'
old=audit.load(R/'out/liuqin-r98-work/evidence/boot-r99p-20261119-122428/usb.log')
initial=audit.load(b/'usb.log');follow=audit.load(b/'usb-follow.log');combined=audit.load(b/'usb-combined.log')
assert old['first_quiescent_sample']['tot']==596005
assert initial['first_quiescent_sample']['tot']==595963
assert initial['first_quiescent_sample']['capture_line']==5095
assert follow['first_quiescent_sample']['tot']==994386
assert follow['first_quiescent_sample']['capture_line']==392
assert combined['first_quiescent_sample']['tot']==595963
assert combined['first_quiescent_sample']['capture_file']=='usb.log'
assert audit.first_quiescent_sample(initial['idle']+follow['idle'])['tot']==595963
assert audit.first_quiescent_sample([{'idle_pct':94}]) is None
assert audit.first_quiescent_sample([{'idle_pct':94},{'idle_pct':95},{'idle_pct':99}])['idle_pct']==95
assert audit.first_quiescent_sample([]) is None
report={'status':'PASS','explanation':'994386 is the first qualifying sample in follow-up alone, not the full boot. The full chronological extraction selects initial usb.log:5095, tot=595963.','r99p':old['first_quiescent_sample'],'r100b':combined['first_quiescent_sample'],'superseded_follow_only':follow['first_quiescent_sample']}
out=R/'out/liuqin-r100-work/evidence/review/idle-extraction-regression.json';out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
