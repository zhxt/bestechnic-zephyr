# SPDX-License-Identifier: Apache-2.0
import re
import struct
from check_bth_layout import symbols
from pack_m55_payload import parse_load_segments, run_readelf

def audit_m55(elf, cross):
    segments=parse_load_segments(run_readelf(elf)); syms=symbols(elf,cross)
    if syms.get('_vector_start')!=0xa0000 or syms.get('dual_shared')!=0x2015e100:
        raise ValueError('M55 vector/shared ABI address')
    ranges=[]
    for s in segments:
        v,n,lma,data=(s[k] for k in ('vaddr','memsz','paddr','filesz'))
        if data>n or not any(lo<=v and n<=hi-v for lo,hi in
                [(0xa0000,0xe0000),(0x200c0000,0x2015c000),(0x2015e100,0x2015e180)]):
            raise ValueError(f'M55 VMA crosses allocation: {s}')
        if data and not 0xa0000<=lma<lma+data<=0xe0000:
            raise ValueError(f'M55 LMA outside ITCM: {s}')
        for lo,hi in ranges:
            if v<hi and lo<v+n:raise ValueError('M55 overlapping VMA')
        if n:ranges.append((v,v+n))
    # SDK TCM selector indices: ITCM ascending, DTCM reversed in banks 0..15.
    itcm=set(range((0xa0000-0x40000)//0x20000,(0xe0000-0x40000)//0x20000))
    dtcm={15-i for i in range(0xc0000//0x20000,0x160000//0x20000)}
    if itcm & dtcm:raise ValueError('physical TCM bank overlap')
    return dict(segments=segments,itcm_selector_banks=sorted(itcm),dtcm_selector_banks=sorted(dtcm),
        physical_note='M55 TCM maps SYS RAM0/1 below 0x20400000; BTH uses dedicated 0x20500000..0x2055ffff, no BTH shared extension',
        ipc_reserved=[0x2015c000,0x2015e000],trampoline=[0x2015e000,0x2015e100],
        diagnostic=[0x2015e100,0x2015e180],boot_trace=[0x2015e180,0x2015e200],
        doorbell_diagnostic=[0x2015e200,0x2015e280],mailbox=[0x2015ffe0,0x20160000])

def audit_doorbell(elf, cross, bth, duration, mode):
    """Inspect linked vectors and generated DTS, not just source declarations."""
    syms=symbols(elf,cross);segments=parse_load_segments(run_readelf(elf));blob=elf.read_bytes()
    def read(address,size):
        for seg in segments:
            delta=address-seg['vaddr']
            if 0<=delta and delta+size<=seg['filesz']:
                return blob[seg['offset']+delta:seg['offset']+delta+size]
        raise ValueError('doorbell vector not file backed')
    irq_map={'rx_isr':39 if bth else 41,'tx_isr':37 if bth else 39}
    devices=[]
    for handler,irq in irq_map.items():
        param,fn=struct.unpack('<II',read(syms['_sw_isr_table']+8*irq,8))
        if fn!=(syms[handler]|1) or param not in [v for k,v in syms.items() if k.startswith('__device_dts_ord_')]:
            raise ValueError(f'incorrect {handler} binding for IRQ {irq}')
        devices.append(param)
    if devices[0]!=devices[1]:raise ValueError('IRQ handlers refer to different mailbox devices')
    conf=(elf.parent/'.config').read_text().splitlines()
    for required in ('CONFIG_MBOX=y','CONFIG_MBOX_BES2700=y',f'CONFIG_DUAL_IPC_SECONDS={duration}',f'CONFIG_DUAL_MSG_MODE={mode}'):
        if required not in conf:raise ValueError('missing '+required)
    dts=re.sub(r'/\*.*?\*/','',(elf.parent/'zephyr.dts').read_text(),flags=re.S)
    node=re.search(r'mbox_peer: mailbox@500000a0\s*{([^}]+)}',dts)[1]
    if ('endpoint-bth;' in node)!=bth:raise ValueError('wrong mailbox endpoint')
    for key,expected in [('reg',[0x500000a0,8,0x40000134,8]),
                         ('interrupts',[irq_map['rx_isr'],3,irq_map['tx_isr'],3])]:
        value=re.search(r'\b'+key+r'\s*=([^;]+);',node)[1]
        if [int(x,0) for x in re.findall(r'0x[0-9a-f]+|[0-9]+',value)]!=expected:
            raise ValueError('mailbox '+key+' mismatch')
    if bth and f'CONFIG_DUAL_DURATION_SECONDS={duration+10 if mode==2 else 600}' not in conf:raise ValueError('wrong heartbeat duration')
    return dict(irq=irq_map,device=hex(devices[0]),endpoint='bth' if bth else 'sys',duration=duration)
