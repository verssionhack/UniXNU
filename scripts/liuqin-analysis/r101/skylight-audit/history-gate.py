#!/usr/bin/env python3
"""Proposed future host history gate; do not change frozen capture statuses."""
from pathlib import Path
import argparse,json,re
def assess(raw):
    rows=[];malformed=[]
    for n,line in enumerate(raw.decode(errors='replace').splitlines(),1):
        if 'LQ101 LOSS:' not in line:continue
        if not line.startswith('LQ101 LOSS:'):malformed.append(n);continue
        fields=dict(re.findall(r'(\w+)=(\d+)(?:\s|$)',line))
        required=['ring_drop','history_overwrite','payload_trunc','saturated','writer_overflow']
        if any(k not in fields for k in required):malformed.append(n);continue
        rows.append({'line':n,**{k:int(fields[k]) for k in required}})
    available=bool(rows) and not malformed
    lossless=available and all(r['ring_drop']==0 for r in rows)
    return {'status':'hook-ring-lossless' if lossless else 'hook-history-loss-or-unknown','LOSS_rows':len(rows),'malformed_LOSS_lines':malformed,'ring_drop_max':max((r['ring_drop'] for r in rows),default=None),'payload_trunc_max':max((r['payload_trunc'] for r in rows),default=None),'history_overwrite_max':max((r['history_overwrite'] for r in rows),default=None),'counter_saturation_max':max((r['saturated'] for r in rows),default=None),'writer_overflow_max':max((r['writer_overflow'] for r in rows),default=None),'hook_ring_lossless':lossless,'future_required_lossless_history_exit':0 if lossless else 5,'current_frozen_runner_exit_unchanged':True,'absence_claim_permitted':False,'limits':'A zero ring-drop count does not undo bounded-history eviction, undecoded IPC, prefix caps or filtering. This is an offline proposed gate, not an installed runner/abort-policy change.'}
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder',type=Path);p.add_argument('--output',type=Path,required=True);args=p.parse_args()
    # Meaningful null and positive-drop controls; missing evidence never passes.
    assert assess(b'')['future_required_lossless_history_exit']==5
    assert assess(b'LQ101 LOSS: ring_drop=1 history_overwrite=0 payload_trunc=0 saturated=0 writer_overflow=0\n')['future_required_lossless_history_exit']==5
    assert assess(b'prefixLQ101 LOSS: ring_drop=0 history_overwrite=0 payload_trunc=0 saturated=0 writer_overflow=0\n')['future_required_lossless_history_exit']==5
    result=assess((args.folder/'usb.log').read_bytes());args.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
