# SPDX-License-Identifier: Apache-2.0
"""Check linkage and short guard primitives in the final resident ELF.

This does not claim a HAL-wide deadline. Reset and REPARK retain their
separate bounded-poll audits; host tests cover all dispatcher cleanup paths.
"""
import re
import subprocess
from audit_resources import check_control_flow
from check_bth_layout import symbols


def audit(elf,cross,probe):
    def body(name):
        text=subprocess.check_output([cross+'objdump','-d','--disassemble='+name,str(elf)],text=True)
        rows=[]
        for line in text.splitlines():
            m=re.match(r'\s*([0-9a-f]+):\s+(?:[0-9a-f]{4,8}\s+)+\s*(\S+)\s*(.*)',line)
            if m: rows.append((int(m[1],16),m[2],m[3]))
        return text,rows
    syms=symbols(elf,cross)
    state=syms.get('bes_arbitration_state',0)
    sizes={}
    for line in subprocess.check_output([cross+'nm','-S',str(elf)],text=True).splitlines():
        words=line.split()
        if len(words)==4: sizes[words[3]]=int(words[1],16)
    if (not state or sizes.get('bes_arbitration_state')!=64 or
            not syms.get('__bss_start__',0) <= state <= syms.get('__bss_end__',0)-64):
        raise ValueError('arbitration state is outside audited bootstrap BSS')
    frames={}
    for name in ('dual_dispatch','bes_arbitration_enter','bes_arbitration_leave','bes_arbitration_busy'):
        _,rows=body(name)
        frame=0
        for _,mnemonic,operands in rows:
            op=mnemonic.split('.')[0]
            if op.startswith('v') or re.search(r'\b(?:[sdq][0-9]+|fpscr)\b',operands):
                raise ValueError('non-integer arbitration instruction')
            if op=='push' or (op=='stmdb' and operands.startswith('sp!,')):
                frame+=4*len(operands.split('{')[1].split('}')[0].split(','))
            elif op in ('sub','subw') and operands.startswith('sp,'):
                amount=re.search(r'#(\d+)',operands)
                if not amount: raise ValueError('dynamic arbitration frame')
                frame+=int(amount[1])
        if frame>128: raise ValueError('arbitration local frame exceeds 128 bytes')
        frames[name]=frame
    dispatch,_=body('dual_dispatch')
    for name in ('bes_arbitration_enter','bes_arbitration_leave','bes_arbitration_busy'):
        if not re.search(r'\bbl(?:\.w)?\s+[0-9a-f]+ <'+name+r'>',dispatch):
            raise ValueError('lifecycle bypasses arbitration: '+name)
        code,rows=body(name)
        if not rows: raise ValueError('missing arbitration primitive: '+name)
        check_control_flow(rows,name)
        for _,mnemonic,operands in rows:
            op=mnemonic.split('.')[0]
            if op in ('bl','blx') or (op=='bx' and operands.strip()!='lr') or (op.startswith('ldr') and operands.startswith('pc,')):
                raise ValueError('arbitration primitive calls outside its short section')
            target=re.search(r'<([^>]+)>',operands)
            if op.startswith('b') and target and target[1].split('+')[0]!=name:
                raise ValueError('arbitration primitive leaves its short section')
    enter,_=body('bes_arbitration_enter')
    for register in ('IPSR','CONTROL','PRIMASK'):
        if not re.search(r'\bmrs\b[^\n]*'+register,enter,re.I):
            raise ValueError('arbitration context guard missing: '+register)
    for code in (enter,dispatch):
        if not re.search(r'\bcpsid\s+i',code) or not re.search(r'\bmsr\s+PRIMASK',code,re.I):
            raise ValueError('arbitration IRQ save/restore missing')
    injected,rows=body('arbitration_reentry_probe')
    if bool(rows)!=probe: raise ValueError('arbitration probe differs from profile')
    if probe and '<arbitration_reentry_probe>' not in dispatch:
        raise ValueError('arbitration probe is not called')
    return dict(version=1, state=state, local_frame_bytes=frames, single_attempt=True, polling=False,
                context='privileged BTH thread, PRIMASK=0', probe=probe,
                primitive_control_flow='acyclic', pending_stop='owner exit',
                hal_deadline_proven=False)
