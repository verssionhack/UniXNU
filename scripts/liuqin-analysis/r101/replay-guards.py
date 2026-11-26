#!/usr/bin/env python3
"""Replay existing guards and proposed print-rate guard; mark missing timing evidence."""
from pathlib import Path
import importlib.util,json,re,hashlib
R=Path(__file__).resolve().parents[3]
def module(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
runner=module('r100',R/'scripts/liuqin-analysis/r100/run-r100.py')
g=module('g',Path(__file__).with_name('guards.py'))
log=R/'out/liuqin-r100-work/evidence/r100b/boot-r100b-20261120-155900/usb-combined.log'
lines=log.read_bytes().splitlines();runs=[]
for first_perf_seconds in [15,30,45]:
    old=runner.AbortMonitor(max_si=20,si_window=120);new=g.EnospcPrintGuard();first_ticks=None;now=0;events=[]
    for i,line in enumerate(lines,1):
        perf=re.match(rb'LIUQIN PERF: ticks=(\d+) frq=(\d+)',line)
        idle=re.match(rb'LIUQIN IDLE: dt_ms=(\d+)',line)
        if perf:
            ticks,frq=map(int,perf.groups())
            if first_ticks is None:first_ticks=ticks
            now=max(now,first_perf_seconds+(ticks-first_ticks)/frq)
        elif idle and first_ticks is not None:now+=int(idle[1])/1000
        reason=old.feed_chunk(line+b'\n',now);print_reason=new.feed_line(line,now)
        if (reason or print_reason) and not events:events.append({'line':i,'estimated_seconds':now,'original_guard':reason,'enospc_guard':print_reason})
    new.tick(now)
    runs.append({'assumed_first_perf_seconds':first_perf_seconds,'original_abort_reason':old.abort_reason,'enospc_abort_reason':new.abort_reason,'first_trigger':events,'max_si':old.max_si_seen,'max_pid':old.max_pid_seen,'max_print_rate':max((w['rate'] for w in new.windows),default=0)})
# Necessary checks for a prospective abort mechanism: rate threshold, sustained
# requirement, recovery after an empty window, and monotonic-clock rejection.
for counts,expected in [([160,160],False),([161,161],True),([161,0,161],False)]:
    guard=g.EnospcPrintGuard()
    for i,count in enumerate(counts):
        for _ in range(count):guard.feed_line(b'fs_tx_enter_internal:1: disk1 launchd: ENOSPC: test',i*10+1)
        guard.tick((i+1)*10)
    assert bool(guard.abort_reason)==expected,(counts,guard.abort_reason)
try:
    g.EnospcPrintGuard().tick(-1)
except ValueError:
    pass
else:
    raise AssertionError('Guard accepted non-monotonic time')
report={'log_sha256':hashlib.sha256(log.read_bytes()).hexdigest(),'policy':g.ENOSPC_POLICY,'runs':runs,'guard_checks':'PASS','limitation':'Original USB capture has no per-chunk arrival timestamps. Replay uses a synthetic monotonic time from PERF/IDLE anchors and three first-anchor assumptions. It cannot certify exact original wall-clock guard behavior, especially near the capture gap. Runtime validation still required; do not equate APFS diagnostic prints with all errno-28 returns.'}
out=R/'out/liuqin-r100-work/evidence/review/guard-replay.json';out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
