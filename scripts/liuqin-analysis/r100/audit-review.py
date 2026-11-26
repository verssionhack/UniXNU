#!/usr/bin/env python3
"""Recompute review evidence from immutable logs; preserve missing data as unknown."""
from pathlib import Path
from collections import Counter
import difflib, hashlib, importlib.util, json, re
R=Path(__file__).resolve().parents[3]
E=R/'out/liuqin-r100-work/evidence'
DEST=E/'review';DEST.mkdir(exist_ok=True)
PATHS={'r99p':R/'out/liuqin-r98-work/evidence/boot-r99p-20261119-122428/usb.log','r100b':E/'r100b/boot-r100b-20261120-155900/usb-combined.log'}
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def fields(s):
    return {k:int(v) if re.fullmatch(r'-?\d+',v) else v for k,v in re.findall(r'(\w+)=([^ ]+)',s)}
def first_quiescent_sample(samples, threshold=95):
    """Select the first qualifying row in capture order, across all supplied parts."""
    return next((sample for sample in samples if sample['idle_pct'] >= threshold), None)

def load(path):
    boundary = len((path.parent/'usb.log').read_text(errors='replace').splitlines()) if path.name=='usb-combined.log' else None
    lines=path.read_text(errors='replace').splitlines();windows=[];idle=[];data=[];faults=[];jetsam=[];vnodes=[];enospc=[];bins=Counter();current_bin=0;elapsed=0
    for no,line in enumerate(lines,1):
        if line.startswith('LIUQIN TASK_CPU_HDR:'):
            h=fields(line);windows.append({'header':h,'line':no,'rows':{}})
        elif line.startswith('LIUQIN TASK_CPU:') and windows:
            row=fields(line);windows[-1]['rows'][row['comm']]=row
        elif line.startswith('LIUQIN IDLE:'):
            row=fields(line);elapsed+=row['dt_ms'];current_bin+=1
            part = 'usb.log' if boundary is not None and no <= boundary else 'usb-follow.log' if boundary is not None else path.name
            local_line = no-boundary if boundary is not None and no > boundary else no
            idle.append(dict(row,line=no,capture_file=part,capture_line=local_line,relative_to_first_idle_ms=elapsed))
        elif line.startswith('LIUQIN DATA_STATFS:'):
            row=fields(line);row.update(line=no,preceding_idle_relative_ms=elapsed,free_bytes=row['bfree']*row['bsize'],total_bytes=row['blocks']*row['bsize']);data.append(row)
        elif line.startswith('LIUQIN EL0_FAULT:'):faults.append(dict(fields(line),line=no))
        elif line.startswith('LIUQIN JETSAM:'):jetsam.append(dict(fields(line),line=no))
        elif line.startswith('LIUQIN VNODES:'):vnodes.append(dict(fields(line),line=no))
        if re.match(r'fs_tx_enter_internal:\d+: .*: ENOSPC:',line):
            enospc.append({'line':no,'comm':re.match(r'fs_tx_enter_internal:\d+: \S+ (.*?): ENOSPC:',line).group(1),'text':line,'idle_bin':current_bin});bins[current_bin]+=1
    rates=[]
    # Use only intervals bounded by adjacent observed idle samples. The first and
    # last bins and the follow-up capture gap cannot supply rates.
    for i in range(1,len(idle)):
        dt=idle[i]['dt_ms'];idx=i
        if dt>=9000 and dt<=11000 and not (boundary is not None and idle[i-1]['line'] <= boundary < idle[i]['line']):
            rates.append({'idle_bin':idx,'dt_ms':dt,'printed_lines':bins[idx],'printed_lines_per_s':bins[idx]*1000/dt})
    return {'path':str(path.relative_to(R)),'sha256':sha(path),'windows':windows,'idle':idle,'data_statfs':data,'faults':faults,'jetsam':jetsam,'vnodes':vnodes,'apfs_enospc_prints':len(enospc),'apfs_enospc_writers':dict(Counter(x['comm'] for x in enospc)),'apfs_enospc_interval_rates':rates,'first_quiescent_sample':first_quiescent_sample(idle)}

def main():
    logs={k:load(p) for k,p in PATHS.items()}
    old=json.loads((R/'out/liuqin-r98-work/evidence/candidate/payload.json').read_text());new=json.loads((E/'r100b/validation-summary-r100b.json').read_text())
    args=lambda s:dict(x.split('=',1) if '=' in x else (x,None) for x in s.split())
    a=args(old['kernel_args']);b=args(new['kernel_args'])
    changes={k:{'r99p':a.get(k),'r100b':b.get(k)} for k in sorted(a.keys()|b.keys()) if k not in a or k not in b or a[k]!=b[k]}
    # Parse ADT without invoking the mutating package entry point.
    spec=importlib.util.spec_from_file_location('p',R/'scripts/liuqin-analysis/r100/package-r100b.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    def flatten(path):
        raw=path.read_bytes();node,end=m.parse(raw);assert end==len(raw)
        out={}
        def walk(n,parent=''):
            props,kids=n;name=dict(props).get(b'name',b'?').rstrip(b'\0').decode();here=parent+'/'+name if parent else '/'
            out[here]={k.decode():v for k,v in props}
            for k in kids:walk(k,here)
        walk(node);return out
    x=flatten(R/'out/liuqin-r98-work/evidence/candidate/kernel.macho.adt');y=flatten(E/'r100b/kernel.macho.adt')
    adt=[]
    for n in sorted(x.keys()|y.keys()):
        for key in sorted(x.get(n,{}).keys()|y.get(n,{}).keys()):
            v=x.get(n,{}).get(key);w=y.get(n,{}).get(key)
            if v!=w:adt.append({'node':n,'property':key,'old_hex':v.hex() if v is not None and key!='random-seed' else None,'new_hex':w.hex() if w is not None and key!='random-seed' else None,'old_sha256':hashlib.sha256(v).hexdigest() if v is not None else None,'new_sha256':hashlib.sha256(w).hexdigest() if w is not None else None})
    # Device snapshot hashes describe present staged inputs, not an invented
    # complete immutable source snapshot of the old build.
    def index(p):
        return {str(f.relative_to(p)):sha(f) for d in ['board.toml','configs','patches','drivers','scripts','package','dts'] for f in ([p/d] if (p/d).is_file() else (p/d).rglob('*')) if f.is_file() and '__pycache__' not in str(f)}
    da=index(R/'out/liuqin-r98-work/device');db=index(R/'out/liuqin-r100-work/device')
    source_delta={k:{'r99_staged_sha256':da.get(k),'r100_staged_sha256':db.get(k)} for k in sorted(da.keys()|db.keys()) if da.get(k)!=db.get(k)}
    cpu=[]
    for i in [0,1,2]:
        wa=logs['r99p']['windows'][i];wb=logs['r100b']['windows'][i]
        rows=[]
        for name in sorted(wa['rows'].keys()|wb['rows'].keys()):
            ra=wa['rows'].get(name);rb=wb['rows'].get(name)
            rows.append({'comm':name,'r99p_win_ms':ra['win_ms'] if ra else None,'r100b_win_ms':rb['win_ms'] if rb else None,'delta_ms':rb['win_ms']-ra['win_ms'] if ra and rb else None})
        rows.sort(key=lambda x:abs(x['delta_ms']) if x['delta_ms'] is not None else -1,reverse=True)
        cpu.append({'window_index':i,'r99p_header':wa['header'],'r100b_header':wb['header'],'rows':rows,'limitation':'top 10 plus pinned only; absent rows unknown, not zero; first window has dt=0 and is cumulative'})
    report={'first150_r100b':load(E/'r100b/boot-r100b-20261120-155900/usb.log'),'logs':logs,'argument_delta':changes,'adt_delta':adt,'staged_source_delta':source_delta,'cpu_window_comparisons':cpu,'kernel_sha256':{'r99p':old['kernel_sha256'],'r100b':new['kernel_sha256']},'trust_bundle_equal':old['trust_cache_sha256']==new['trust_cache_sha256'],'scratch_logical_bytes':536870912}
    (DEST/'review-audit.json').write_text(json.dumps(report,indent=2)+'\n')
    md=['# r99p versus r100b: captured CPU windows','', 'Units: CPU milliseconds. Differences are r100b minus r99p. Missing entries mean not logged. Existing telemetry exposes top 10 plus pinned tasks, so a top-15 reconstruction is unavailable.','']
    for w in cpu:
        md += [f"## Window {w['window_index']}: dt {w['r99p_header']['dt_ms']} / {w['r100b_header']['dt_ms']} ms",'', '| Process | r99p | r100b | Delta |','| --- | ---: | ---: | ---: |']
        for row in w['rows']:md.append('| '+ ' | '.join(str(row[k]) if row[k] is not None else 'unknown' for k in ['comm','r99p_win_ms','r100b_win_ms','delta_ms'])+' |')
        md.append('')
    (DEST/'cpu-window-diff.md').write_text('\n'.join(md)+'\n')
    print(json.dumps({'argument_delta':changes,'adt_delta':[dict(t,old_hex='[256-byte seed]',new_hex='[256-byte seed]') if t['property']=='random-seed' else t for t in adt],'cpu_50s':cpu[1],'quiescence':{k:v['first_quiescent_sample'] for k,v in logs.items()},'ENOSPC':{k:{'printed_lines':v['apfs_enospc_prints'],'writers':v['apfs_enospc_writers'],'max_interval_printed_lines_per_s':max((z['printed_lines_per_s'] for z in v['apfs_enospc_interval_rates']),default=0)} for k,v in logs.items()}},indent=2))
if __name__=='__main__':main()
