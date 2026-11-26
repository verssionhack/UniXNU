"""Conservative host coverage checks; no inferred APFS/syscall correlation."""
import re

def snapshot_coverage(lines):
    active=None;results=[]
    for no,line in enumerate(lines,1):
        if line.startswith('LQ101 SNAPSHOT_BEGIN:'):
            if active:results.append({**active,'complete':False,'reason':'missing end before next begin'})
            match=re.search(r'target_s=(\d+)',line)
            if not match:
                results.append({'target_s':None,'begin_line':no,'complete':False,'reason':'malformed begin marker'});active=None;continue
            target=int(match[1])
            active={'target_s':target,'begin_line':no,'lines':0,'hash_value':14695981039346656037}
        elif line.startswith('LQ101 SNAPSHOT_END:'):
            f=dict(re.findall(r'(\w+)=([^ ]+)',line))
            try:
                target=int(f['target_s']);complete=int(f['complete']);count=int(f['lines']);checksum=int(f['hash'],16)
            except (KeyError,ValueError):
                results.append({**(active or {'target_s':None}),'end_line':no,'complete':False,'reason':'malformed end marker'});active=None;continue
            if active is None:
                results.append({'target_s':target,'complete':False,'reason':'end without begin'});continue
            ok=(target==active['target_s'] and complete==1 and count==active['lines'] and checksum==active['hash_value'])
            results.append({**active,'end_line':no,'complete':ok,'reason':'count/hash and emitter status verified' if ok else 'count/hash/target/emitter mismatch'})
            active=None
        elif active and line.startswith('LQ101 ') and not line.startswith('LQ101 CPU_TIME:'):
            # Transport must preserve LF bytes. A replacement character or a
            # missing/duplicated line changes this end-to-end checksum.
            for b in (line+'\n').encode():active['hash_value']=((active['hash_value']^b)*1099511628211)&((1<<64)-1)
            active['lines']+=1
    if active:results.append({**active,'complete':False,'reason':'capture ended inside snapshot'})
    targets=[r['target_s'] for r in results if r['target_s'] is not None]
    for result in results:
        if result['target_s'] is not None and targets.count(result['target_s'])>1:
            result['complete']=False;result['reason']='duplicate snapshot target'
    return results

def apfs_coverage(lines):
    prints=[{'line':i,'text':line} for i,line in enumerate(lines,1)
            if re.match(r'fs_tx_enter_internal:\d+: .*: ENOSPC:',line)]
    # The APFS lines contain comm but no pid/tid, request id or kernel timestamp.
    # Bounded syscall exemplars cannot prove a one-to-one association. Equal
    # process names or nearby serial lines are candidates, never matches.
    return {'apfs_enospc_print_lines':len(prints),'matched_to_syscall_event':0,
            'apfs_enospc_print_lines_not_matched_to_syscall_event':len(prints),
            'print_signature':'fs_tx_enter_internal:<line>: ...: ENOSPC:',
            'matching_available':False,'unmatched_is_async_claim':False,
            'reason':'No shared correlation id/pid/tid; path events are rate bounded. All printed lines remain unmatchable.',
            'additive_with_syscall_or_block_counts':False,'lines':prints}
