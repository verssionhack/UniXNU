#!/usr/bin/env python3
"""Supplemental exact suffix recovery; never changes raw log or runner verdict."""
from pathlib import Path
import argparse,hashlib,importlib.util,json,re
H=Path(__file__).resolve().parent
p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder',type=Path);a=p.parse_args();f=a.folder.resolve();raw=(f/'usb.log').read_bytes();lines=raw.decode('utf8',errors='strict').splitlines();recovered=[];derived=[];offset=0
row=re.compile(r'LQ102 BLK_WRITER: t_ms=\d+ pid=-?\d+ comm=[A-Za-z0-9_.-]+ bytes=\d+ writes=\d+ legacy_bytes=\d+ legacy_writes=\d+ context=block-submitter path=unknown')
trap=re.compile(r'TRAP [0-9a-f]+ esr [0-9a-f]+ far [0-9a-f]+ pc [0-9a-f]+ rec \d+ lr [0-9a-f]+')
for no,line in enumerate(lines,1):
 matches=list(re.finditer(r'LQ10[12] ',line))
 if matches and matches[0].start():
  assert len(matches)==1,'ambiguous embedded observers';pos=matches[0].start();prefix,suffix=line[:pos],line[pos:]
  assert trap.fullmatch(prefix) and row.fullmatch(suffix),'unsupported framing: never guess'
  recovered.append({'line':no,'byte_offset_in_line':pos,'prefix':prefix,'observer_suffix':suffix,'raw_physical_line_bytes_with_LF':len(line.encode())+1,'recovered_observer_record_bytes_with_LF':len(suffix.encode())+1});derived.extend([prefix,suffix])
 else:derived.append(line)
s=importlib.util.spec_from_file_location('blockcoverage',H.parent/'a2/block-coverage.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
windows=m.block_windows(derived);report={'raw_log_sha256':hashlib.sha256(raw).hexdigest(),'raw_log_modified':False,'original_runner_status_unchanged':json.loads((f/'boot-record.json').read_text())['capture_status'],'framing_rule':'Only a complete TRAP prefix immediately followed by a complete strictly matched BLK_WRITER suffix; split once for supplemental block analysis. No inferred field values or bytes.','recoveries':recovered,'recovered_windows':len(windows),'all_block_windows_accounted_after_exact_suffix_recovery':bool(windows) and all(w['complete'] and w['legacy_breakdown_complete'] for w in windows),'previously_failed_windows_after_recovery':[w for w in windows if any(f't_ms={w["t_ms"]} ' in r['observer_suffix'] for r in recovered)],'limits':'This does not repair target framing, change pre-frozen rules, establish absence of every possible logging defect, or convert exit5 to exit0. Snapshot hashes were verified directly from raw data.'}
(f/'block-framing-recovery.json').write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:report[k] for k in ['raw_log_modified','original_runner_status_unchanged','recoveries','recovered_windows','all_block_windows_accounted_after_exact_suffix_recovery']},indent=2))
