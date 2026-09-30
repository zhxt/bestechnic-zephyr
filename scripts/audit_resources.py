# SPDX-License-Identifier: Apache-2.0
"""Audit the resource descriptor and the complete read-only dispatch call graph."""
import ctypes
import re
import struct
import subprocess
from pack_m55_payload import parse_load_segments, run_readelf
from check_bth_layout import symbols

ALLOWED = {'bes_resource_dispatch', 'bes_resource_buffer_valid', 'dual_service_phase',
           'bes_arbitration_busy',
           'bes2700yp_snapshot', 'bes2700yp_clocks_are_24m',
           'hal_cmu_axi_sys_get_freq', 'hal_cmu_sys_get_freq', 'hal_cmu_get_crystal_freq'}


def file_span(segments, address, size, executable=False):
    for seg in segments:
        if (size > 0 and seg['vaddr'] <= address and
                address + size <= seg['vaddr'] + seg['filesz'] and
                ('E' in seg['flags'] if executable else 'W' not in seg['flags'])):
            return seg['offset'] + address - seg['vaddr']
    raise ValueError('resource symbol is not wholly file-backed with required permissions')


def check_control_flow(rows, name):
    """Reject cycles, while permitting backward jumps to a shared return."""
    graph = {}
    branches = re.compile(r'b(?:eq|ne|cs|cc|mi|pl|vs|vc|hi|ls|ge|lt|gt|le)?$|cbn?z$')
    for i, (pc, mnemonic, operands) in enumerate(rows):
        op = mnemonic.split('.')[0]
        edges = []
        destination = re.search(r'([0-9a-f]+) <([^>]+)>', operands)
        if branches.fullmatch(op) and destination and destination[2].split('+')[0] == name:
            edges.append(int(destination[1], 16))
        terminal = (op in ('b', 'bx') or (op in ('pop', 'ldmia') and 'pc' in operands) or
                    (op.startswith('ldr') and operands.startswith('pc,')))
        if not terminal and i+1 < len(rows):
            edges.append(rows[i+1][0])
        graph[pc] = edges
    active, done = set(), set()

    def visit(pc):
        if pc in active:
            raise ValueError('resource service contains a control-flow cycle: ' + name)
        if pc in done or pc not in graph:
            return
        active.add(pc)
        for dest in graph[pc]:
            visit(dest)
        active.remove(pc); done.add(pc)
    if rows:
        visit(rows[0][0])


def check_gpio_irq_scope(rows, name):
    """Prove the supported GPIO call sites cannot run under local CPSID.

    GPIO dispatch rejects IRQ-masked entry. Its final MSR restores that zero
    entry mask; the only nested mask manipulation is RAM arbitration bookkeeping.
    HAL callees must not mask interrupts themselves.
    """
    if name.startswith('bes2700yp_gpio') or name == 'gpio_masked':
        if any(op.split('.')[0] in ('cpsid', 'msr') for _, op, _ in rows):
            raise ValueError('GPIO HAL changes interrupt masking: ' + name)
    if name != 'bes_gpio_dispatch' or not rows:
        return
    by_pc = {pc: i for i, (pc, _, _) in enumerate(rows)}
    pending, seen = [(rows[0][0], False)], set()
    while pending:
        pc, masked = pending.pop()
        if (pc, masked) in seen or pc not in by_pc:
            continue
        seen.add((pc, masked))
        i = by_pc[pc]
        _, mnemonic, operands = rows[i]
        op = mnemonic.split('.')[0]
        if op == 'cpsid':
            masked = True
        elif op == 'cpsie' or (op == 'msr' and 'PRIMASK' in operands.upper()):
            masked = False
        destination = re.search(r'([0-9a-f]+) <([^>]+)>', operands)
        if destination:
            target = destination[2].split('+')[0]
            if 'bes2700yp_gpio_' in target and masked:
                raise ValueError('GPIO hardware call under PRIMASK')
            if (op not in ('bl', 'blx') and
                    (op.startswith('b') or op in ('cbz', 'cbnz')) and target == name):
                pending.append((int(destination[1], 16), masked))
        terminal = (op in ('b', 'bx') or (op in ('pop', 'ldmia') and 'pc' in operands) or
                    (op.startswith('ldr') and operands.startswith('pc,')))
        if not terminal and i+1 < len(rows):
            pending.append((rows[i+1][0], masked))


def audit(elf, bth, cross, root, generated, uart=False, arbitration=False, gpio=False, gpio_api=False):
    prefix = 'bes_gpio' if gpio else 'bes_arbitration' if arbitration else 'bes_uart_resource' if uart else 'bes_resource'
    descriptor = prefix + '_service'
    dispatch = prefix + '_dispatch'
    allowed = ALLOWED | {dispatch} | ({'bes2700yp_uart0_read'} if uart else set())
    if gpio:
        allowed |= {'bes2700yp_gpio_access', 'bes2700yp_gpio_sample', 'gpio_masked', 'bes_arbitration_enter', 'bes_arbitration_leave'}
    library = generated / 'resource_validator.so'
    subprocess.run(['cc', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                    '-I', str(root / 'include/bestechnic/bes2700yp'),
                    str(root / 'platforms/bes2700yp/resources/contract.c'),
                    str(root / 'platforms/bes2700yp/resources/uart_contract.c'),
                    str(root / 'platforms/bes2700yp/resources/arbitration_contract.c'),
                    str(root / 'platforms/bes2700yp/resources/gpio_contract.c'), '-o', str(library)], check=True)
    validator = ctypes.CDLL(str(library))
    validate_descriptor = getattr(validator, prefix + '_descriptor_valid')
    validate_descriptor.argtypes = [ctypes.POINTER(ctypes.c_uint32)]
    validator.bes_resource_descriptor_address_valid.argtypes = [ctypes.c_uint32]
    syms = symbols(elf, cross)
    sizes = {}
    for line in subprocess.check_output([cross+'nm', '-S', str(elf)], text=True).splitlines():
        words = line.split()
        if len(words) == 4:
            sizes[words[3]] = int(words[1], 16)
    segments = parse_load_segments(run_readelf(elf))
    data = elf.read_bytes()
    address = syms.get(descriptor, 0)
    if sizes.get(descriptor) != 32 or not validator.bes_resource_descriptor_address_valid(address):
        raise ValueError('resource descriptor placement/size')
    offset = file_span(segments, address, 32)
    words = struct.unpack_from('<8I', data, offset)
    if not validate_descriptor((ctypes.c_uint32 * 8)(*words)):
        raise ValueError('resource descriptor rejected by actual client validator')
    if words[4] != syms.get(dispatch, 0) | 1:
        raise ValueError('resource descriptor points to a different dispatch')
    disassembly = subprocess.check_output([cross+'objdump', '-d', str(elf)], text=True)
    functions = {}
    current = None
    for line in disassembly.splitlines():
        match = re.match(r'^([0-9a-f]+) <([^>]+)>:', line)
        if match:
            current = match[2]; functions[current] = []
        elif current:
            match = re.match(r'\s*([0-9a-f]+):\s+(?:[0-9a-f]{4,8}\s+)+\s*(\S+)\s*(.*)', line)
            if match:
                functions[current].append((int(match[1], 16), match[2], match[3]))
    seen, active, frames = set(), set(), {}

    def walk(name):
        if name in active:
            raise ValueError('recursive resource service call')
        veneer = name.startswith('__') and name.endswith('_veneer')
        target = name[2:-7] if veneer else None
        if name not in allowed and not (veneer and target in allowed):
            raise ValueError('unaudited resource callee: ' + name)
        if name in seen:
            return frames[name]
        active.add(name)
        code, size = syms.get(name, 0), sizes.get(name, 0)
        file_span(segments, code, size, executable=True)
        rows = functions.get(name, [])
        if not rows:
            raise ValueError('missing resource disassembly: ' + name)
        check_control_flow(rows, name)
        if gpio:
            check_gpio_irq_scope(rows, name)
        own, children = 0, []
        for pc, mnemonic, operands in rows:
            op = mnemonic.split('.')[0]
            if op.startswith('v') or re.search(r'\b(?:[sdq][0-9]+|fpscr)\b', operands):
                raise ValueError('floating-point/SIMD resource instruction')
            if op == 'blx' or (op == 'bx' and operands.strip() != 'lr' and not veneer):
                raise ValueError('indirect resource call')
            if op == 'push' or (op == 'stmdb' and operands.startswith('sp!,')):
                registers = operands[operands.index('{')+1:operands.index('}')]
                own += 4 * len(registers.split(','))
            elif op in ('sub', 'subw') and operands.startswith('sp,'):
                amount = re.search(r'#(\d+)', operands)
                if not amount:
                    raise ValueError('dynamic resource stack allocation')
                own += int(amount[1])
            if op.startswith('b') or op in ('cbz', 'cbnz'):
                destination = re.search(r'([0-9a-f]+) <([^>]+)>', operands)
                if destination:
                    callee = destination[2].split('+')[0]
                    if callee != name:
                        children.append(walk(callee))
            if op.startswith('ldr') and operands.startswith('pc,'):
                if not veneer:
                    raise ValueError('unexpected resource indirect jump')
        if veneer:
            # GNU Thumb veneers have a literal target, not a runtime callback.
            off = file_span(segments, code, size, executable=True)
            prefixes = {8: 'dff800f0', 16: '01b40248844601bc604700bf'}
            prefix = bytes.fromhex(prefixes[size]) if size in prefixes else b''
            if (not prefix or data[off:off+len(prefix)] != prefix or
                    struct.unpack_from('<I', data, off+len(prefix))[0] != syms[target] | 1):
                raise ValueError('resource veneer target mismatch')
            children.append(walk(target))
        frames[name] = own + max(children, default=0)
        active.remove(name); seen.add(name)
        return frames[name]

    stack = walk(dispatch)
    if stack > 256:
        raise ValueError('resource dispatch exceeds 256-byte stack budget')
    bsyms = symbols(bth, cross)
    if gpio:
        fault = syms.get('gpio_fault', 0)
        if (not fault or sizes.get('gpio_fault') != 4 or
                not syms.get('__bss_start__', 0) <= fault <= syms.get('__bss_end__', 0)-4):
            raise ValueError('GPIO fault latch is outside audited bootstrap BSS')
        consumers = ['bes_gpio_connect', 'bes_gpio_call', 'bes_gpio_descriptor_valid']
        calls = {'bes_gpio_connect': ('dual_service_validate', 'bes_resource_descriptor_address_valid',
                                     'bes_gpio_descriptor_valid')}
        if gpio_api:
            consumers += ['bes_gpio_api', 'gpio_bes_init', 'gpio_bes_pin_configure',
                          'gpio_bes_port_get_raw', 'gpio_bes_port_set_masked_raw',
                          'gpio_bes_port_set_bits_raw', 'gpio_bes_port_clear_bits_raw',
                          'gpio_bes_port_toggle_bits', 'gpio_bes_pin_interrupt_configure']
            calls.update(gpio_bes_init=('bes_gpio_connect',), gpio_bes_call=('bes_gpio_call',))
            if not 0x20540000 <= bsyms.get('gpio_bes_data_0', 0) < 0x2055c000-96:
                raise ValueError('GPIO driver request storage is outside BTH data RAM')
            segments = parse_load_segments(run_readelf(bth))
            bdata = bth.read_bytes()
            config = bth.with_name('.config').read_text()
            api_targets = ['gpio_bes_pin_configure']
            if 'CONFIG_GPIO_GET_CONFIG=y\n' in config:
                api_targets.append(None)
            api_targets += ['gpio_bes_port_get_raw', 'gpio_bes_port_set_masked_raw',
                            'gpio_bes_port_set_bits_raw', 'gpio_bes_port_clear_bits_raw',
                            'gpio_bes_port_toggle_bits', 'gpio_bes_pin_interrupt_configure', None, None]
            if 'CONFIG_GPIO_GET_DIRECTION=y\n' in config:
                api_targets.append(None)
            off = file_span(segments, bsyms['bes_gpio_api'], len(api_targets)*4)
            actual = struct.unpack_from('<'+'I'*len(api_targets), bdata, off)
            expected = tuple((bsyms[name] | 1) if name else 0 for name in api_targets)
            if actual != expected:
                raise ValueError('GPIO API table does not reference the reviewed callbacks')
            off = file_span(segments, bsyms['gpio_bes_config_0'], 4)
            if struct.unpack_from('<I', bdata, off)[0] != (0x31000 if words[3] == 56 else 0x30000):
                raise ValueError('GPIO driver pin mask differs from the service grant')
        else:
            consumers += ['bes_gpio_validation_init', 'bes_gpio_validation_poll']
            calls.update(bes_gpio_validation_init=('bes_gpio_connect', 'gpio_access'),
                         gpio_access=('bes_gpio_call',))
        for name in consumers:
            if name not in bsyms:
                raise ValueError('missing BTH GPIO consumer: ' + name)
        for caller, targets in calls.items():
            code = subprocess.check_output([cross+'objdump', '-d', '--disassemble='+caller, str(bth)], text=True)
            for target in targets:
                branch = r'\bb(?:l)?(?:\.w)?' if gpio_api else r'\bbl(?:\.w)?'
                if not re.search(branch+r'\s+[0-9a-f]+ <'+target+r'>', code):
                    raise ValueError('GPIO client bypasses validation: ' + target)
        return dict(abi=words[1], capabilities=words[3], descriptor=address, dispatch=words[4],
                    request_bytes=words[5], snapshot_bytes=words[6], descriptor_bytes=32,
                    buffer=[0x20540000, 0x2055c000], stack_bound_bytes=stack,
                    reachable=sorted(seen), descriptor_read_only=True, integer_only=True,
                    bounded_call_graph=True, context='privileged BTH thread',
                    iomux_lock='AON MEMSC0 single attempt; sample requires no semaphore',
                    hardware_irqs_enabled=True, fault_latch=fault, zephyr_api=gpio_api)
    for name in ('resources_init', prefix + '_connect', prefix + '_read',
                 prefix + '_descriptor_valid', 'bes_resource_probe'):
        if name not in bsyms:
            raise ValueError('missing BTH resource consumer: ' + name)
    entry = bsyms.get('__init_resources_init', 0)
    if not entry or entry != bsyms.get('__init_PRE_KERNEL_1_start'):
        raise ValueError('resource discovery is not the first PRE_KERNEL_1 initializer')
    bsegments = parse_load_segments(run_readelf(bth))
    off = file_span(bsegments, entry, 8)
    if struct.unpack_from('<2I', bth.read_bytes(), off) != (bsyms['resources_init'] | 1, 0):
        raise ValueError('resource initializer registration mismatch')
    for caller, targets in {'resources_init': (prefix + '_connect', prefix + '_read'),
                            prefix + '_connect': ('dual_service_validate',
                                'bes_resource_descriptor_address_valid', prefix + '_descriptor_valid')}.items():
        code = subprocess.check_output([cross+'objdump', '-d', '--disassemble='+caller, str(bth)], text=True)
        for target in targets:
            if not re.search(r'\bbl(?:\.w)?\s+[0-9a-f]+ <'+target+r'>', code):
                raise ValueError('resource client does not call validator: '+target)
    return dict(abi=words[1], capabilities=words[3], descriptor=address, dispatch=words[4],
                request_bytes=words[5], snapshot_bytes=words[6], descriptor_bytes=32,
                buffer=[0x20540000, 0x2055c000], stack_bound_bytes=stack,
                reachable=sorted(seen), descriptor_read_only=True,
                integer_only=True, bounded_call_graph=True, early_init='PRE_KERNEL_1:0')
