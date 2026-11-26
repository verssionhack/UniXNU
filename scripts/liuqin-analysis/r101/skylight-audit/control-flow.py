#!/usr/bin/env python3
"""Conservative intraprocedural return reachability from saved pinned assembly."""
from pathlib import Path
import collections,json,re
R=Path(__file__).resolve().parents[4];E=R/'out/liuqin-r101-skylight-audit/evidence'
def analyze(file,cut):
    rows={}
    for line in file.read_text().splitlines():
        m=re.match(r'0x([0-9a-f]+):\s+(?:[0-9a-f]{2} ){4}\s*(\S+)\s*(.*)',line)
        if m:rows[int(m[1],16)]=(m[2],m[3])
    entry=min(rows);edges={};returns=[];unknown=[]
    for pc,(op,args) in rows.items():
        nxt=pc+4;targets=[]
        if op.startswith('ret'):returns.append(pc)
        elif op in ['br','braa','brab','braaz','brabz']:unknown.append(pc)
        elif op=='b' or op.startswith('b.') or op in ['cbz','cbnz','tbz','tbnz']:
            match=re.search(r'loc_([0-9a-f]+)',args) or re.search(r'0x([0-9a-f]+)',args)
            target=int(match[1],16) if match else None
            if target in rows:targets.append(target)
            elif op=='b':unknown.append(pc)
            if op!='b' and nxt in rows:targets.append(nxt)
        elif nxt in rows:targets.append(nxt)
        edges[pc]=targets
    def reach(blocked=None):
        seen=set();q=collections.deque([entry])
        while q:
            x=q.popleft()
            if x in seen or x==blocked:continue
            seen.add(x);q.extend(edges.get(x,[]))
        return seen
    before=reach();after=reach(cut)
    return {'entry':hex(entry),'cut_instruction':hex(cut),'cut_assembly':rows[cut],'normal_returns':[hex(x) for x in returns],'returns_reachable':[hex(x) for x in returns if x in before],'returns_reachable_without_cut':[hex(x) for x in returns if x in after],'unresolved_tail_or_indirect_branch':[hex(x) for x in unknown],'cut_dominates_all_normal_returns':bool(returns) and all(x in before and x not in after for x in returns),'limits':'Direct intra-function CFG only; conditional outcomes unconstrained, calls assumed to return. Blocking, exceptions, callbacks, and nonreturning callees are not modeled.'}
r={'WSInitialize':analyze(E/'WSInitialize.asm.txt',0x182a8fca8),'CGXInitializeGL':analyze(E/'display-check.asm.txt',0x1828d424c)}
assert not any(x['unresolved_tail_or_indirect_branch'] for x in r.values())
(E/'normal-return-dominators.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r,indent=2))
