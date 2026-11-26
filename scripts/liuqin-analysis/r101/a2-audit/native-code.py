#!/usr/bin/env python3
"""Disassemble preserved native functions; do not read target memory."""
from pathlib import Path
import re,struct,subprocess
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
R=Path(__file__).resolve().parents[4];E=R/'out/liuqin-r101-a2-offline-audit'
for tag,base in [('A1','out/liuqin-r101-work'),('A2','out/liuqin-r101-a2-work')]:
 p=R/base/'evidence/a/standalone.macho';data=p.read_bytes();nm=subprocess.check_output(['llvm-nm','-an',str(p)],text=True);segments=[];off=32
 for _ in range(struct.unpack_from('<I',data,16)[0]):
  cmd,n=struct.unpack_from('<II',data,off)
  if cmd==0x19:segments.append(struct.unpack_from('<QQQQ',data,off+24))
  off+=n
 output=[]
 for name,size in [('__ZN6ArmCpu11startThreadEPvi',192),('_cpu_init',512),('_liuqin_r102_cpu_readback',160)]:
  m=re.search(r'^([0-9a-f]+) [Ss] '+re.escape(name)+r'$',nm,re.M)
  if not m:continue
  start=int(m[1],16)
  for va,vsz,fo,fsz in segments:
   if va<=start and start+size<=va+fsz:
    code=data[fo+start-va:fo+start-va+size];break
  else:raise RuntimeError(name)
  output.append(name+':')
  for i in Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN).disasm(code,start):output.append(f'{i.address:#x} {i.bytes.hex()} {i.mnemonic} {i.op_str}')
 (E/f'{tag}-CPU-functions.asm.txt').write_text('\n'.join(output)+'\n')
