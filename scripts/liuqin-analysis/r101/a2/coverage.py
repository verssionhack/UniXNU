"""A2 adds LQ102 evidence to the existing end-to-end snapshot checksum contract."""
from pathlib import Path
p=Path(__file__).resolve().parent.parent/'coverage.py';source=p.read_text()
old="line.startswith('LQ101 ')";assert source.count(old)==1
source=source.replace(old,"line.startswith(('LQ101 ','LQ102 '))")
exec(compile(source,str(p),'exec'),globals())

def history_references(lines):
    import re
    valid={s['target_s'] for s in snapshot_coverage(lines) if s['complete']}
    current=None;records={};result=[]
    for no,line in enumerate(lines,1):
        if line.startswith('LQ101 SNAPSHOT_BEGIN:'):
            match=re.search(r'target_s=(\d+)',line);current=int(match[1]) if match else None
        elif line.startswith('LQ101 SNAPSHOT_END:'):current=None
        elif current is not None and line.startswith('LQ102 HISTORY:'):
            fields=dict(re.findall(r'(\w+)=([^ ]+)',line))
            try:record={'target_s':current,'kind':fields['kind'],'n':int(fields['n']),'revision':int(fields['rev']),'reuse_s':int(fields['reuse_s']),'rows':0,'line':no}
            except (KeyError,ValueError):
                result.append({'target_s':current,'complete':False,'reason':'malformed history marker'});continue
            records[(current,record['kind'])]=record
        elif current is not None:
            kind='open' if line.startswith('LQ101 EVENT: scope=last50-open ') else 'ipc' if line.startswith('LQ101 IPC: scope=last50-ipc ') else None
            if kind and (current,kind) in records:records[(current,kind)]['rows']+=1
    for (target,kind),record in sorted(records.items()):
        if not record['reuse_s']:
            complete=target in valid and record['rows']==min(record['n'],50)
        else:
            source=records.get((record['reuse_s'],kind))
            complete=bool(target in valid and source and source['target_s'] in valid and source['target_s']<target and not source['reuse_s'] and source['rows']==min(source['n'],50) and source['revision']==record['revision'] and source['n']==record['n'] and record['rows']==0)
        result.append({**record,'complete':complete})
    return result
