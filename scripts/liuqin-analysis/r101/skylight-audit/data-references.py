#!/usr/bin/env python3
"""Bounded ADRP provenance candidates for compositor mode globals; no execution."""
import json,struct
from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
from capstone.arm64_const import ARM64_OP_MEM,ARM64_OP_REG,ARM64_OP_IMM
import scan
cs=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN);cs.detail=True
targets={0x1eb1b6f64:'active_compositor',0x1eb1b6fa8:'default_once',0x1eb1b6fb0:'default_to_metal',0x1eb1b7638:'metal_lovin',0x1eb1b7640:'metal_once',0x1eb1b64aa:'safe_mode',0x1eb1b64ab:'virtual_console_only'}
found={}
def norm(name):return 'x'+name[1:] if name.startswith('w') else name
for page in scan.pages:
    pc=int(page['pc'],16);start=pc-scan.start;owner=page['owner'];next_func=min((a for a in scan.addrs if a>pc),default=scan.start+len(scan.code));end=min(start+4*512,next_func-scan.start)
    regs={f'x{page["register"]}':int(page['page'],16)}
    for ins in cs.disasm(scan.code[start+4:end],pc+4):
        ops=ins.operands;put={}
        for op in ops:
            if op.type==ARM64_OP_MEM:
                base=norm(ins.reg_name(op.mem.base));address=regs.get(base)
                if address is not None and not op.mem.index:
                    address+=op.mem.disp
                    if address in targets:
                        found[(ins.address,address)]={'pc':hex(ins.address),'global':hex(address),'name':targets[address],'instruction':ins.mnemonic+' '+ins.op_str,'owner':owner,'provenance_adrp':page['pc']}
        if ins.mnemonic=='add' and len(ops)==3 and ops[0].type==ARM64_OP_REG and ops[1].type==ARM64_OP_REG and ops[2].type==ARM64_OP_IMM:
            b=norm(ins.reg_name(ops[1].reg))
            if b in regs:put[norm(ins.reg_name(ops[0].reg))]=regs[b]+ops[2].imm
        elif ins.mnemonic=='mov' and len(ops)==2 and all(o.type==ARM64_OP_REG for o in ops):
            b=norm(ins.reg_name(ops[1].reg))
            if b in regs:put[norm(ins.reg_name(ops[0].reg))]=regs[b]
        _,writes=ins.regs_access()
        for w in writes:regs.pop(norm(ins.reg_name(w)),None)
        regs.update(put)
        if ins.mnemonic.startswith('bl'):
            for i in range(19):regs.pop('x'+str(i),None)
        if not regs:break
rows=sorted(found.values(),key=lambda r:int(r['pc'],16))
(scan.E/'compositor-global-references.json').write_text(json.dumps({'limits':'Up to 512 instructions following each relevant ADRP, bounded by next symbol. Linear register provenance across conditional paths yields candidates, not an exhaustive alias-aware writer proof; instructions manually checked in full functions.','references':rows},indent=2)+'\n')
for r in rows:
    if r['name'] in ['default_to_metal','active_compositor']:print(r)
