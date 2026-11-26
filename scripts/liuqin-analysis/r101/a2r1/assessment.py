#!/usr/bin/env python3
"""Host capture acceptance; missing evidence cannot turn runner exit 0 into success."""
from pathlib import Path
import argparse,hashlib,importlib.util,json
H=Path(__file__).resolve().parent
INCOMPLETE_EXIT=5

def decision(report,terminal_disconnect):
 checks={k:v for k,v in report['a2_contract'].items() if isinstance(v,bool)}
 complete=bool(checks) and all(checks.values()) and report['observer_budget_ok'] and not report['overlong_observer_lines'] and report['status']=='captured-observers; blocked-object attribution requires review' and not terminal_disconnect
 return {'status':'complete-observer-capture' if complete else 'incomplete-observer-capture','exit_code':0 if complete else INCOMPLETE_EXIT,'failed_contracts':[k for k,v in checks.items() if not v],'terminal_USB_disconnect':terminal_disconnect,'analyzer_status':report['status'],'limits':'No guard trigger or exit 0 substitutes for target evidence. Physical recovery needs an explicit owner record; USB disappearance alone does not prove a kernel panic.'}

def assess(folder):
 folder=Path(folder).resolve();path=H.parent/'a2/analyze-a2.py';spec=importlib.util.spec_from_file_location('a2_acceptance_analyzer',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.W=folder.parents[2]
 report=m.analyze(folder);events=[json.loads(l) for l in (folder/'guard-trace.jsonl').read_text().splitlines()];last_data=max((e['mono_ns'] for e in events if e['event']=='monitor' and e['length']),default=-1);last_disconnect=max((e['mono_ns'] for e in events if e['event']=='serial_disconnect'),default=-1)
 result=decision(report,last_disconnect>=last_data and last_disconnect>=0);result['analysis_source_sha256']=hashlib.sha256(path.read_bytes()).hexdigest();result['assessment_source_sha256']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest();result['analysis']=report;return result
if __name__=='__main__':
 p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args();result=assess(a.folder);a.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k!='analysis'},indent=2));raise SystemExit(result['exit_code'])
