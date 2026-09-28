# SPDX-License-Identifier: Apache-2.0
import ctypes
import json
import re
import struct
import subprocess
from check_bth_layout import symbols
from pack_m55_payload import parse_load_segments, run_readelf

def service_validator(root, generated, restart):
    """Compile the same validator linked into BTH, with its selected layout."""
    generated.mkdir(parents=True, exist_ok=True)
    wrapper = generated / 'service_validator.c'
    wrapper.write_text('''/* Generated audit harness; never part of the firmware. */
#include <bes2700_dual_boot.h>
uint32_t check(uint32_t entry)
{
    struct dual_service service = {
        .magic = DUAL_SERVICE_MAGIC, .layout = DUAL_LAYOUT, .dispatch = entry,
        .itcm = DUAL_ITCM, .itcm_size = 0x40000U,
        .dtcm = DUAL_DTCM, .dtcm_size = 0xa0000U, .mailbox = DUAL_MAILBOX,
    };
    return dual_service_validate(&service);
}
''')
    library = generated / 'service_validator.so'
    options = ['-DCONFIG_BES2700_M55_RESTART=1'] if restart else []
    subprocess.run(['cc', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror', *options,
                    '-I', str(root / 'include/bestechnic/bes2700yp'), str(wrapper),
                    str(root / 'platforms/bes2700yp/boot/service_contract.c'),
                    '-o', str(library)], check=True)
    check = ctypes.CDLL(str(library)).check
    check.argtypes = [ctypes.c_uint32]
    check.restype = ctypes.c_uint32
    return check


def audit_service_entry(elf, bth, cross, root, generated, restart):
    """Validate the linked service VMA, not its flash load/programming alias."""
    syms = symbols(elf, cross)
    address = syms.get('dual_dispatch')
    if address is None:
        raise ValueError('missing bootstrap service entry')
    entry = address | 1
    code = entry & ~1
    check = service_validator(root, generated, restart)
    errors = check(entry)
    if errors:
        raise ValueError(f'bootstrap entry {entry:#010x} rejected by BTH: errors={errors:#x}')
    if not check(code) or not check(0x34000001):
        raise ValueError('service validator accepts a non-Thumb or flash data address')
    segments = parse_load_segments(run_readelf(elf))
    if not any('E' in segment['flags'] and segment['vaddr'] <= code and
               code + 2 <= segment['vaddr'] + segment['filesz'] for segment in segments):
        raise ValueError('bootstrap service is not backed by executable ELF bytes')
    if 'dual_service_validate' not in symbols(bth, cross):
        raise ValueError('BTH has no shared service validator')
    caller = 'bes2700_lifecycle_validate' if restart else 'main'
    disassembly = subprocess.check_output(
        [cross + 'objdump', '-d', '--disassemble=' + caller, str(bth)], text=True)
    if not re.search(r'\bbl(?:\.w)?\s+[0-9a-f]+ <dual_service_validate>', disassembly):
        raise ValueError('BTH entry does not call the audited service validator')
    return dict(dispatch=f'{entry:#010x}', code=f'{code:#010x}', caller=caller,
                actual_firmware_validator='pass', executable_segment='pass',
                bth_calls_validator='pass')


def check_resource_contract(root):
    resources = json.loads((root / 'platforms/bes2700yp/resources.json').read_text())
    if resources['schema'] != 1 or resources['chip'] != 'bes2700yp':
        raise ValueError('unsupported resource contract')
    observation = resources.get('observation')
    if observation != dict(version=1, short_ms=60000, long_ms=600000, limit_ms=660000):
        raise ValueError('observation resource contract')
    observation_header = (root / 'include/bestechnic/bes2700yp/bes2700_observation.h').read_text()
    for key, macro in [('version', 'VERSION'), ('short_ms', 'SHORT_MS'),
                       ('long_ms', 'LONG_MS'), ('limit_ms', 'LIMIT_MS')]:
        match = re.search(r'^#define BES_OBSERVATION_' + macro + r' (\d+)U$', observation_header, re.M)
        if not match or int(match[1]) != observation[key]:
            raise ValueError('observation header/manifest mismatch: ' + key)
    regions = resources['regions']
    names = [r['name'] for r in regions]
    if len(set(names)) != len(names):
        raise ValueError('duplicate resource region')
    previous = 0x2015c000
    for region in regions:
        if region['start'] != previous or region['end'] <= region['start'] or not region['owner']:
            raise ValueError('resource gap/overlap/owner')
        previous = region['end']
    if previous != 0x20160000:
        raise ValueError('shared resource end')
    bounds = {r['name']: [r['start'], r['end']] for r in regions}
    expected = dict(message=[0x2015c000, 0x2015e000], trampoline=[0x2015e000, 0x2015e100],
                    heartbeat=[0x2015e100, 0x2015e180], trace=[0x2015e180, 0x2015e200],
                    doorbell=[0x2015e200, 0x2015e280], lifecycle=[0x2015e280, 0x2015e300],
                    unallocated=[0x2015e300, 0x2015ffe0], mailbox=[0x2015ffe0, 0x20160000])
    if bounds != expected:
        raise ValueError('resource memory ABI')
    header = (root / 'include/bestechnic/bes2700yp/bes2700_lifecycle.h').read_text()
    macros = {'layout': 'LAYOUT', 'address': 'ADDR', 'rounds': 'ROUNDS', 'target': 'TARGET',
              'observe_seconds': 'OBSERVE_SECONDS', 'ready_ms': 'READY_MS',
              'message_ms': 'MESSAGE_MS', 'quiesce_ms': 'QUIESCE_MS', 'reset_ms': 'RESET_MS'}
    for key, macro in macros.items():
        match = re.search(r'^#define BES_LIFECYCLE_' + macro + r'\s+(0x[0-9a-fA-F]+|\d+)U?$', header, re.M)
        if not match or int(match[1], 0) != resources['lifecycle'][key]:
            raise ValueError('lifecycle header/manifest mismatch: ' + key)
    if resources['lifecycle']['bytes'] != 128:
        raise ValueError('lifecycle control size')
    if resources.get('reset_diagnostic') != dict(version=1, address=0x2055c1a0,
                                                bytes=80, read_attempts=32, poll_limit=1024):
        raise ValueError('reset diagnostic contract')
    if resources.get('repark_diagnostic') != dict(version=1, address=0x2055c800, bytes=100,
            bank=9, selector_mask=7<<27, physical_words=[0x20320000,0x20320004,0x20330000],
            expected_words=[0x2015ffe0,0x200c0009,0xe7fdbf30]):
        raise ValueError('repark diagnostic contract')
    for name, value in dict(BES_RESET_DIAG_ADDR=0x2055c1a0, BES_RESET_DIAG_VERSION=1,
                            BES_RESET_READ_ATTEMPTS=32, BES_RESET_POLL_LIMIT=1024,
                            BES_REPARK_DIAG_ADDR=0x2055c800, BES_REPARK_DIAG_VERSION=1).items():
        found = re.search(r'^#define ' + name + r'\s+(0x[0-9a-fA-F]+|\d+)U?$', header, re.M)
        if not found or int(found[1], 0) != value:
            raise ValueError('reset diagnostic header/manifest mismatch: ' + name)
    boot = (root / 'include/bestechnic/bes2700yp/bes2700_dual_boot.h').read_text()
    for macro, expected_address in {'DUAL_SHARED_ADDR': 0x2015e100, 'DUAL_TRACE_ADDR': 0x2015e180,
                                   'DUAL_TRAMPOLINE': 0x2015e000, 'DUAL_MAILBOX': 0x2015ffe0,
                                   'DUAL_DTCM_END': 0x2015c000}.items():
        match = re.search(r'^#define ' + macro + r'\s+(0x[0-9a-fA-F]+)U?$', boot, re.M)
        if not match or int(match[1], 0) != expected_address:
            raise ValueError('boot/resource contract: ' + macro)
    return resources


def audit_reset_timer(elf, cross, resources):
    """Check the entire reset wait and the non-inlined tight reader in the final ELF."""
    syms = symbols(elf, cross)
    segments = parse_load_segments(run_readelf(elf))
    sizes = {}
    for row in subprocess.check_output([cross + 'nm', '-S', str(elf)], text=True).splitlines():
        fields = row.split()
        if len(fields) == 4:
            sizes[fields[3]] = int(fields[1], 16)
    bodies = {}
    for name in ('bes_reset_timer_read', 'hold_cpu_reset'):
        address, size = syms.get(name, 0), sizes.get(name, 0)
        if not (size and 0x00500000 <= syms['__boot_text_sram_start__'] <= address <
                address + size <= syms['__boot_text_sram_end__'] <= 0x00510000):
            raise ValueError('reset timing code outside boot SRAM: ' + name)
        if not any('E' in s['flags'] and s['vaddr'] <= address and
                   address + size <= s['vaddr'] + s['filesz'] for s in segments):
            raise ValueError('reset timing code not file backed: ' + name)
        bodies[name] = subprocess.check_output(
            [cross + 'objdump', '-d', '--disassemble=' + name, str(elf)], text=True)
    reader = bodies['bes_reset_timer_read']
    pair = (r'\bmrs\s+(\w+),\s*PRIMASK\s*\n[^\n]*\bcpsid\s+i\s*\n'
            r'[^\n]*\bldr(?:\.w)?\s+\w+,\s*(\[[^\]]+\])\s*\n'
            r'[^\n]*\bldr(?:\.w)?\s+\w+,\s*\2\s*\n'
            r'[^\n]*\bmsr\s+PRIMASK,\s*\1\b')
    if not re.search(pair, reader):
        raise ValueError('reset timer lacks adjacent reads and PRIMASK preservation')
    # No out-of-line Flash helper may enter the timing-sensitive sampler.
    if re.search(r'\bblx?(?:\.w)?\s', reader):
        raise ValueError('reset timer reader calls another function')
    wait = bodies['hold_cpu_reset']
    if len(re.findall(r'\bbl(?:\.w)?\s+[0-9a-f]+ <bes_reset_timer_read>', wait)) < 2:
        raise ValueError('reset wait does not use audited SRAM reader')
    if '<bth_ticks>' in wait:
        raise ValueError('reset wait still uses the Flash timer reader')
    dispatch = subprocess.check_output(
        [cross + 'objdump', '-d', '--disassemble=dual_dispatch', str(elf)], text=True)
    if not re.search(r'\b(?:bl|b\.w)\s+[0-9a-f]+ <[^>]*hold_cpu_reset[^>]*>', dispatch):
        raise ValueError('service does not call SRAM reset wait')
    low = resources['reset_diagnostic']['address']
    high = low + resources['reset_diagnostic']['bytes']
    if not 0x2055c1a0 <= low < high <= 0x2055c200:
        raise ValueError('reset diagnostic allocation overlaps logger/profile')
    if any(s['memsz'] and s['vaddr'] < high and low < s['vaddr'] + s['memsz']
           for s in segments):
        raise ValueError('adapter allocates reset diagnostic reservation')
    return dict(sampler=syms['bes_reset_timer_read'] | 1, wait=syms['hold_cpu_reset'],
                ram_placement='pass', protected_reader='pass', wait_calls_reader='pass',
                diagnostic=[low, high])


def audit_repark(elf, cross):
    syms = symbols(elf, cross)
    names = ('repark_cpu', 'bes2700yp_m55_repark_prepare')
    if any(name not in syms for name in names):
        raise ValueError('missing dedicated HAL repark path')
    bodies = {name: subprocess.check_output(
        [cross+'objdump', '-d', '--disassemble='+name, str(elf)], text=True)
        for name in (*names, 'dual_dispatch')}
    if '<bes2700yp_m55_repark_prepare>' not in bodies['repark_cpu']:
        raise ValueError('repark bypasses HAL preparation')
    if not re.search(r'\b(?:bl|b\.w)\s+[0-9a-f]+ <repark_cpu>', bodies['dual_dispatch']):
        raise ValueError('dispatch bypasses repark bridge')
    if re.search(r'<(?:bes2700yp_m55_(?:prepare|start)|hal_(?:psc|cmu)_[^>]+)>',
                 bodies['bes2700yp_m55_repark_prepare']):
        raise ValueError('repark HAL changes CPU/power beyond bank preparation')
    return dict(bridge=syms[names[0]], prepare=syms[names[1]],
                dispatch_calls_bridge='pass', bridge_calls_hal='pass',
                preparation_does_not_release='pass')


def audit_lifecycle(elfs, cross, resources):
    bounds = {r['name']: (r['start'], r['end']) for r in resources['regions']}
    # Includes memsz, therefore BSS and NOLOAD allocations cannot silently grow
    # into another publisher's control words or the unused shared tail.
    forbidden = [bounds[n] for n in ('message', 'trace', 'doorbell', 'lifecycle', 'unallocated', 'mailbox')]
    diagnostic = resources['reset_diagnostic']
    low, high = diagnostic['address'], diagnostic['address'] + diagnostic['bytes']
    forbidden += [(low, high), (low - 0x20000000, high - 0x20000000)]
    diagnostic = resources['repark_diagnostic']
    low, high = diagnostic['address'], diagnostic['address'] + diagnostic['bytes']
    forbidden += [(low, high), (low - 0x20000000, high - 0x20000000)]
    for elf in elfs:
        for segment in parse_load_segments(run_readelf(elf)):
            low, size = segment['vaddr'], segment['memsz']
            if size and any(low < high and start < low + size for start, high in forbidden):
                raise ValueError('ELF overlaps shared reservation: ' + str(elf))
        if elf.name == 'zephyr.elf':
            dts = re.sub(r'/\*.*?\*/', '', (elf.parent / 'zephyr.dts').read_text(), flags=re.S)
            node = re.search(r'lifecycle_control: memory@2015e280\s*{([^}]+)}', dts)
            if not node or [int(x, 0) for x in re.findall(r'0x[0-9a-f]+', node[1])] != [0x2015e280, 128]:
                raise ValueError('lifecycle DTS reservation: ' + str(elf))
    m55 = elfs[1]
    syms = symbols(m55, cross)
    if (syms.get('__bes2700_m55_shared_start') != bounds['heartbeat'][0] or
            syms.get('__bes2700_m55_shared_end', 0xffffffff) > bounds['heartbeat'][1]):
        raise ValueError('heartbeat linker bounds')
    return {'control': list(bounds['lifecycle']), 'bytes': 128, 'elf_reservations': 'pass',
            'heartbeat_linker_bounds': 'pass'}

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

def audit_doorbell(elf, cross, bth, duration, mode, restart=False):
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
    if ('CONFIG_BES2700_M55_RESTART=y' in conf) != restart:
        raise ValueError('lifecycle configuration mismatch')
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
