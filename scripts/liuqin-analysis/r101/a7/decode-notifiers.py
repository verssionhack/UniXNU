#!/usr/bin/env python3
"""Supplement A5r1's server-first decoder with its same qualified count rules.

The frozen decoder intentionally returns after a typed server; raw notifier
words are nevertheless present. No target reads or frozen-parser changes.
"""
from pathlib import Path
import argparse,copy,json
def decode(state,record):
    result={'target_s':state['target_s'],'status':'unknown','notifiers':{},'racy':True}
    try:
        assert state['outcome']=='created_resumed_server_init' and not state['failed_reads']
        words={r['key']:r for r in state['raw_words']};base=int(state['raw_begin'][0]['main'],16);slide=int(state['raw_begin'][0]['shared_slide'],16)
        def get(k,addr=None):
            w=words[k];assert w['rc']=='0'
            if addr is not None:assert int(w['addr'],16)==addr
            return int(w['a'],16),int(w['b'],16)
        def pointer(p):return record['map_min']<=p<record['map_max'] and not p&7
        def isa(v):return v&0x00007ffffffffff8 if v&1 else v
        assert get('ISAM',slide+0x180447ba8)==(0x00007ffffffffff8,1) and get('ISAV',slide+0x180447bb8)[0]==1
        assert get('ARRIV',slide+0x1eb1deb78)[0]>>32==16 and get('SETIV',slide+0x1eb1dee90)[0]>>32==16
        for prefix,key,endkey,off in [('CN','CLKY','CLKY_END',0x6e1a0),('GN','GPTY','GPTY_END',0x6e180)]:
            cell=get(key,base+off);assert cell==get(endkey,base+off)
            notifier,singleton=cell;assert pointer(notifier) and pointer(singleton)
            n0=get(prefix+'0',notifier);n1=get(prefix+'1',notifier+16);n2=get(prefix+'2',notifier+32);n3=get(prefix+'3',notifier+40)
            assert isa(n0[0])==base+0x6ce28 and n2[1]==n3[0]
            matched,pending=n1[1],n2[1];assert pointer(matched) and pointer(pending)
            s0=get(prefix+'S0',matched);s1=get(prefix+'S1',matched+16);a0=get(prefix+'A0',pending);a2=get(prefix+'A2',pending+32)
            assert isa(s0[0])==slide+0x1ed9533f8 and isa(a0[0])==slide+0x1ed954668
            result['notifiers'][prefix]={'notifier':hex(notifier),'singleton':hex(singleton),'matched_count':s1[1]>>32&0x3ffffff,'pending_count':a2[0]>>32&0xffffffff}
        result['status']='qualified-counts'
    except (KeyError,ValueError,AssertionError) as exc:
        result['status']='unknown';result['reason']='identity/address/read/stability qualification failed: '+str(exc)
    return result
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('folder',type=Path);args=p.parse_args();f=args.folder
    assessment=json.loads((f/'capture-assessment.json').read_text());rows=[]
    for state in assessment['state_outcomes']:
        record=json.loads((f/f'frames-clocksyncd-{state["target_s"]}.json').read_text());row=decode(state,record);rows.append(row)
        # Negative controls: unavailable reads and wrong class ISA stay unknown.
        bad=copy.deepcopy(state);next(x for x in bad['raw_words'] if x['key']=='CNS1')['rc']='14';assert decode(bad,record)['status']=='unknown'
        bad=copy.deepcopy(state);next(x for x in bad['raw_words'] if x['key']=='CNS0')['a']='0';assert decode(bad,record)['status']=='unknown'
    (f/'notifier-supplement.json').write_text(json.dumps({'qualification':'same pinned local notifier/count layout as A5r1; supplementary postprocessing only','negative_controls':'PASS: read failure and wrong ISA remain unknown','outcomes':rows},indent=2)+'\n');print(json.dumps(rows,indent=2))
