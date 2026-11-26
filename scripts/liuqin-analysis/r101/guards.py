#!/usr/bin/env python3
"""Host-side ENOSPC diagnostic-print guard for the planned r101 runner.

Counts APFS fs_tx_enter_internal ENOSPC lines, not capped LIUQIN errno details.
The threshold is a printed-line threshold, not the true errno-28 event rate.
Call tick() even when no serial data arrives; retain original r100 AbortMonitor.
"""
import re
APFS_ENOSPC=re.compile(rb'^fs_tx_enter_internal:\d+: .*: ENOSPC:')
ENOSPC_POLICY={'window_seconds':10.0,'printed_lines_per_second_limit':16.0,'consecutive_windows':2,'derivation':'r100b captured complete idle-bounded intervals peak 7.996 lines/s; round up 2x peak to 16; no true errno-rate inference'}
class EnospcPrintGuard:
    def __init__(self,start=0.0):
        self.start=start;self.count=0;self.streak=0;self.abort_reason=None;self.windows=[]
    def tick(self,now):
        if now<self.start:raise ValueError('non-monotonic time')
        while now-self.start>=ENOSPC_POLICY['window_seconds']:
            count=self.count;self.count=0
            rate=count/ENOSPC_POLICY['window_seconds']
            self.streak=self.streak+1 if rate>ENOSPC_POLICY['printed_lines_per_second_limit'] else 0
            self.windows.append({'end':self.start+10,'count':count,'rate':rate})
            self.start+=10
            if self.streak>=ENOSPC_POLICY['consecutive_windows'] and self.abort_reason is None:
                self.abort_reason=f'ENOSPC diagnostic-print guard: >16 lines/s in two consecutive 10s windows at {self.start:.1f}s'
        return self.abort_reason
    def feed_line(self,line,now):
        self.tick(now)
        if APFS_ENOSPC.match(line):self.count+=1
        return self.abort_reason
