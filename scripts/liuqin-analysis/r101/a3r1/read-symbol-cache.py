#!/usr/bin/env python3
"""Read only the leading Gob map[uint64]string of this ipsw .a2s format."""
from pathlib import Path
import argparse,json
p=argparse.ArgumentParser(description=__doc__);p.add_argument('cache',type=Path);p.add_argument('--output',type=Path,required=True);a=p.parse_args();b=a.cache.read_bytes()
def uint(data,pos):
 first=data[pos];pos+=1
 if first<128:return first,pos
 n=256-first
 if not 1<=n<=8 or pos+n>len(data):raise ValueError('invalid Gob unsigned integer')
 return int.from_bytes(data[pos:pos+n],'big'),pos+n
n,pos=uint(b,0);assert b[pos:pos+n]==bytes.fromhex('7f040102ff80000106010c0000'),'unexpected Gob map type';pos+=n
n,pos=uint(b,pos);payload=b[pos:pos+n];typeid,q=uint(payload,0);assert typeid==128 and payload[q]==0;q+=1;count,q=uint(payload,q);symbols={}
for _ in range(count):
 addr,q=uint(payload,q);length,q=uint(payload,q);assert q+length<=len(payload);name=payload[q:q+length].decode();q+=length;assert addr not in symbols;symbols[addr]=name
assert q==len(payload)
a.output.write_text(json.dumps({hex(k):v for k,v in sorted(symbols.items())},indent=2)+'\n')
for addr,name in sorted(symbols.items()):
 if any(x in name for x in ['[TSDDaemon init]','[TSDDaemon start]','[TSDDaemonService init]','[TSDDaemonServiceServer init]','[TSDDaemonServiceServerExported getSyncEntityManagerProxy','[TSDSyncEntityManager init]']):print(hex(addr),name)
