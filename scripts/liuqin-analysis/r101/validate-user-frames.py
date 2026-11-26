#!/usr/bin/env python3
"""Check raw r101 LRs against pinned dyld cache code; does not enable native walking.

Input JSON: va_bits, map_min, map_max, slide (integers), cache_uuid (hex),
invalid_address_read_failed (bool), frames [{tid,depth,lr_raw (integer)}].
Cache-set manifest: [{path,sha256,uuid}] with main cache first. Supply all code
subcaches explicitly. UUIDs/geometry must come from the target and pinned cache
inventory, never from trial masks or a search for plausible instructions.
"""
from pathlib import Path
import argparse,hashlib,json,mmap,struct

def is_call(word,pc):
    from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
    instructions=list(Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN).disasm(word,pc,count=1))
    return instructions[0].mnemonic if len(instructions)==1 and instructions[0].mnemonic in {'bl','blr','blraa','blrab','blraaz','blrabz'} else None

class Cache:
    def __init__(self,entry):
        self.path=Path(entry['path'])
        with self.path.open('rb') as stream:
            if hashlib.file_digest(stream,'sha256').hexdigest()!=entry['sha256']:raise ValueError('cache SHA mismatch')
            self.data=mmap.mmap(stream.fileno(),0,access=mmap.ACCESS_READ)
        try:self._parse(entry)
        except Exception:
            self.data.close();raise
    def _parse(self,entry):
        if not self.data[:16].startswith(b'dyld_v1') or b'arm64' not in self.data[:16]:raise ValueError('unsupported cache magic/architecture')
        self.uuid=self.data[88:104].hex()
        if self.uuid!=entry['uuid'].replace('-','').lower():raise ValueError('cache UUID mismatch')
        off,count=struct.unpack_from('<II',self.data,16)
        if count==0 or count>1024 or off<104 or off+count*32>len(self.data):raise ValueError('invalid mapping table')
        self.mappings=[]
        for i in range(count):
            address,size,fileoff,maxprot,initprot=struct.unpack_from('<QQQII',self.data,off+i*32)
            if fileoff+size>len(self.data) or size==0:raise ValueError('mapping outside cache file')
            self.mappings.append((address,size,fileoff,initprot))
    def instruction(self,address):
        found=[]
        for base,size,off,prot in self.mappings:
            if base<=address and address+4<=base+size and prot&4:found.append(self.data[off+address-base:off+address-base+4])
        return found

def validate(record,caches):
    bits=record['va_bits'];low=record['map_min'];high=record['map_max'];slide=record['slide']
    if not 32<=bits<=52 or not 0<=low<high<=1<<bits or not 0<=slide<1<<bits:raise ValueError('invalid authoritative user VA geometry')
    if not caches or caches[0].uuid!=record['cache_uuid'].replace('-','').lower():raise ValueError('target/cache UUID mismatch')
    rows=[]
    for f in record['frames']:
        raw=f['lr_raw']
        if not isinstance(raw,int) or not 0<=raw<1<<64:raise ValueError('invalid raw 64-bit LR')
        lr=raw&((1<<bits)-1);row={**f,'lr_normalized':lr,'mask_source':'explicit target VA geometry','callsite_unslid':None,'call':None}
        if not low<=lr<high or lr&3 or lr<slide+4:row['status']='invalid-return-address'
        else:
            pc=lr-slide-4;row['callsite_unslid']=pc
            words=[word for c in caches for word in c.instruction(pc)]
            if len(words)!=1:row['status']='outside-or-ambiguous-executable-cache-mapping'
            else:
                row['call']=is_call(words[0],pc);row['status']='callsite-plausible' if row['call'] else 'not-after-call'
        rows.append(row)
    ok=bool(rows) and record.get('invalid_address_read_failed') is True and all(r['status']=='callsite-plausible' for r in rows)
    return {'callsite_validation_passed':ok,'frames':rows,'native_reader_validated':False,'walker_enable_authorized':False,
      'limits':'Callsite plausibility is not independent proof of correct copyin/stack. Main-executable and nonresident frames can remain unresolved. No guessed VA mask; raw LR retained.'}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('record',type=Path);p.add_argument('cache_manifest',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    caches=[]
    try:
        for entry in json.loads(a.cache_manifest.read_text()):caches.append(Cache(entry))
        result=validate(json.loads(a.record.read_text()),caches);a.output.write_text(json.dumps(result,indent=2)+'\n')
    finally:
        for cache in caches:cache.data.close()
    print(json.dumps({'callsite_validation_passed':result['callsite_validation_passed'],'native_reader_validated':False,'output':str(a.output)}))
    return 0 if result['callsite_validation_passed'] else 1
if __name__=='__main__':raise SystemExit(main())
