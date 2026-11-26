#!/usr/bin/env python3
"""Verify saved assembly against pinned bytes and freeze this host-only audit."""
from pathlib import Path
import contextlib,datetime,hashlib,io,json,re
R=Path(__file__).resolve().parents[4];H=Path(__file__).resolve().parent;W=R/'out/liuqin-r101-skylight-audit';E=W/'evidence'
dest=E/'audit-manifest.json';assert not dest.exists(),'preserve frozen audit'
def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
checked={}
parents=[R/'out/liuqin-r101-a7-work/evidence/result-manifest.json',R/'out/liuqin-r101-a7-work/evidence/host-manifest.json',R/'out/liuqin-r101-a6-work/evidence/result-manifest.json']
for p in parents:
    data=json.loads(p.read_text())
    for n,digest in data['files'].items():assert sha(R/n)==digest,n
    checked[str(p.relative_to(R))]={'entries':len(data['files']),'manifest_sha256':sha(p)}
with contextlib.redirect_stdout(io.StringIO()):import scan
primary=scan.C/'dyld_shared_cache_arm64e'
assert sha(primary)=='f4aefea64cb86bf2f82a0af1e0f6fde7f56b2ef67eaeba9ff3ae0cdfc1e1c36f'
for p,entry in json.loads((E/'data-inputs.json').read_text()).items():assert sha(Path(p))==entry['sha256']
counts={}
for p in E.glob('*.asm.txt'):
    count=0
    for line in p.read_text().splitlines():
        m=re.match(r'^(?:0x|=>)([0-9a-f]+):\s+((?:[0-9a-f]{2}[ \t]+){3}[0-9a-f]{2})',line)
        if not m:continue
        pc=int(m[1],16);raw=bytes.fromhex(m[2]);assert scan.reader.read(pc,4)==raw,(p,hex(pc));count+=1
    assert count,p;counts[p.name]=count
dom=json.loads((E/'normal-return-dominators.json').read_text());assert all(x['cut_dominates_all_normal_returns'] and not x['unresolved_tail_or_indirect_branch'] for x in dom.values())
assert json.loads((E/'A6-history-gate.json').read_text())['future_required_lossless_history_exit']==0
assert json.loads((E/'A7-history-gate.json').read_text())['future_required_lossless_history_exit']==5
proof={'status':'PASS','assembly_instruction_bytes_checked':sum(counts.values()),'by_file':counts,'root_cache_sha256':sha(primary),'prior_manifests_verified':checked,'device_actions':0,'candidate_builds':0}
(E/'opcode-verification.json').write_text(json.dumps(proof,indent=2)+'\n')
paths=[p for p in E.rglob('*') if p.is_file()]+[p for p in H.iterdir() if p.is_file()]+[p for p in W.glob('*.log')]
manifest={'time':datetime.datetime.now().astimezone().isoformat(),'status':'offline-audit-complete; no qualified non-Metal startup selector; hardware hold retained','device_actions':0,'candidate_builds':0,'SkyLight_UUID':'331822b11c9f367badd2310ddeeff7c9','prior_manifests_verified':checked,'assembly_instruction_bytes_checked':sum(counts.values()),'files':{str(p.relative_to(R)):sha(p) for p in sorted(set(paths))}}
dest.write_text(json.dumps(manifest,indent=2)+'\n');print('PASS:',sum(counts.values()),'instructions verified;',len(paths),'artifacts frozen; no build or device action. Manifest SHA256:',sha(dest))
