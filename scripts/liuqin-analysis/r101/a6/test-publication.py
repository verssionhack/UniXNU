#!/usr/bin/env python3
from pathlib import Path
import copy,importlib.util
H=Path(__file__).resolve().parent;s=importlib.util.spec_from_file_location('pub',H/'publication.py');m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
def fixture():
 p=[{'cls':c,'rid':hex(i+1),'state':'6' if i else '0','registered':'1' if i else '0','matched':'1' if i else '0','inactive':'0','source':'IOService'} for i,c in enumerate(m.CLASSES)]
 q=[{'rid':'0x1','key':k,'present':'0','type':'none','decoded':'0','bits':'0','value':'0'} for k in m.KEYS];return p,q
def run(p,q):return m.classify(60,p,q,'clock_pending')
p,q=fixture();assert run(p,q)['outcome']=='attached_unregistered_no_clock_ID'
p,q=fixture();p[0].update(state='6',registered='1',matched='1');assert run(p,q)['outcome']=='registered_matched_but_userspace_clock_pending'
p,q=fixture();p[1].update(state='0',registered='0',matched='0');assert run(p,q)['outcome']=='unknown' and not run(p,q)['positive_control']
p,q=fixture();q[0].update(present='1',type='OSNumber',decoded='1',bits='64',value='0');assert run(p,q)['outcome']=='unknown' # real numeric zero is present
p,q=fixture();q[0].update(present='1',type='OSString',decoded='0');assert run(p,q)['outcome']=='unknown'
p,q=fixture();p[0]['registered']='1';assert not run(p,q)['protocol_complete']
p,q=fixture();p[1]['rid']=p[0]['rid'];assert not run(p,q)['protocol_complete']
p,q=fixture();q.pop();assert not run(p,q)['protocol_complete']
p,q=fixture();q.append(copy.deepcopy(q[0]));assert not run(p,q)['protocol_complete']
p,q=fixture();q[0].update(decoded='1');assert not run(p,q)['protocol_complete']
p,q=fixture();p[0].update(state='1',inactive='1');assert run(p,q)['outcome']=='unknown'
print('PASS: 11 publication branches/controls/type/zero/missing/bit-integrity cases')
