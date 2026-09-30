#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Audit generated dual-core DTS/config resources without changing firmware."""
import argparse
import hashlib
import importlib.util
import json
import struct
import os
from pathlib import Path
import re
import sys

from audit_dual import check_resource_contract

ROOT = Path(__file__).resolve().parents[1]
POLICY = Path(__file__).with_name('resource_ownership.json')


def dt_library(zephyr):
    path = zephyr / 'scripts/dts/python-devicetree/src/devicetree/dtlib.py'
    spec = importlib.util.spec_from_file_location('bes_resource_dtlib', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, path


def config_values(path):
    values = {}
    for line in path.read_text().splitlines():
        match = re.fullmatch(r'(CONFIG_\w+)=(.*)', line)
        unset = re.fullmatch(r'# (CONFIG_\w+) is not set', line)
        if match or unset:
            key, value = (match[1], match[2]) if match else (unset[1], 'n')
            if key in values:
                raise ValueError('duplicate config key: ' + key)
            values[key] = value
    return values


def enabled(node):
    while node is not None:
        if 'status' in node.props and node.props['status'].to_string() not in ('okay', 'ok'):
            return False
        node = node.parent
    return True


def strings(node, key):
    return node.props[key].to_strings() if key in node.props else []


def number(node, key, default=None):
    return node.props[key].to_num() if key in node.props else default


def registers(node):
    """Generated trees may have multiple cells, but translated buses need review."""
    if 'reg' not in node.props:
        return []
    parent = node.parent
    address_cells = number(parent, '#address-cells', 2)
    size_cells = number(parent, '#size-cells', 1)
    if address_cells not in (1, 2) or size_cells not in (1, 2):
        raise ValueError('unsupported reg cell geometry: ' + node.path)
    ancestor = parent
    while ancestor.parent is not None:
        if 'ranges' not in ancestor.props or ancestor.props['ranges'].value:
            raise ValueError('unreviewed bus address translation: ' + node.path)
        ancestor = ancestor.parent
    cells = node.props['reg'].to_nums()
    width = address_cells + size_cells
    if not cells or len(cells) % width:
        raise ValueError('malformed reg: ' + node.path)
    result = []
    for i in range(0, len(cells), width):
        start = int.from_bytes(node.props['reg'].value[4*i:4*(i+address_cells)], 'big')
        size = int.from_bytes(node.props['reg'].value[4*(i+address_cells):4*(i+width)], 'big')
        if not size or start + size > 1 << 32:
            raise ValueError('invalid 32-bit register range: ' + node.path)
        result.append((start, size))
    return result


def overlaps(a, b):
    return a[0] < b[0] + b[1] and b[0] < a[0] + a[1]


def physical(region):
    start, size = region
    if 0x00500000 <= start < 0x00600000:
        if start + size > 0x00600000:
            raise ValueError('memory crosses BTH alias boundary')
        start += 0x20000000
    return start, size


def audit(root, release, zephyr):
    policy = json.loads(POLICY.read_text())
    if policy.get('schema') != 1 or policy.get('chip') != 'bes2700yp':
        raise ValueError('unsupported resource ownership policy')
    resources = check_resource_contract(root)
    dtlib, dtpath = dt_library(zephyr)
    contract_path = root / 'platforms/bes2700yp/boot/bootstrap/bth_contract.h'
    macros = {k: int(v, 0) for k, v in re.findall(
        r'^#define (BTH_\w+) (0x[0-9a-fA-F]+|[0-9]+)$', contract_path.read_text(), re.M)}
    boot = (root / 'include/bestechnic/bes2700yp/bes2700_dual_boot.h').read_text()
    dual = {k: int(v, 0) for k, v in re.findall(
        r'^#define (DUAL_\w+)\s+(0x[0-9a-fA-F]+|[0-9]+)U?$', boot, re.M)}
    regions = {r['name']: (r['start'], r['end']-r['start']) for r in resources['regions']}
    errors, claims, irq_users = [], [], {}
    report = dict(schema=1, scope='static-resource-ownership', hardware='not_tested',
                  errors=errors, unconfirmed=policy['unconfirmed'], cores={}, claims=claims,
                  limitations=['No ELF allocation or physical RAM-bank replacement audit',
                               'No runtime enforcement, voltage or IRQ timing validation',
                               'New controllers and pinmux encodings require an explicit policy review'])

    def fail(core, node, code, detail):
        errors.append(dict(core=core, node=node.path if node else None, code=code, detail=detail))

    def expect(core, node, condition, code, detail):
        if not condition:
            fail(core, node, code, detail)

    def node_regs(core, node):
        try:
            return registers(node)
        except (ValueError, dtlib.DTError) as error:
            fail(core, node, 'reg-format', str(error))
            return []

    paths = [POLICY, Path(__file__), contract_path,
             root / 'platforms/bes2700yp/resources.json', dtpath,
             Path(check_resource_contract.__code__.co_filename),
             root / 'include/bestechnic/bes2700yp/bes2700_dual_boot.h',
             root / 'include/bestechnic/bes2700yp/bes2700_lifecycle.h',
             root / 'include/bestechnic/bes2700yp/bes2700_observation.h']
    for core, core_policy in policy['cores'].items():
        dts_path, config_path = release / (core+'.dts'), release / (core+'.config')
        paths.extend([dts_path, config_path])
        tree, config = dtlib.DT(str(dts_path)), config_values(config_path)
        report['cores'][core] = dict(cpu=core_policy['cpu'], num_irqs=core_policy['num_irqs'])
        expected_config = {core_policy['soc_config']: 'y', 'CONFIG_MBOX': 'y',
                           'CONFIG_MBOX_BES2700': 'y', 'CONFIG_NUM_IRQS': str(core_policy['num_irqs']),
                           'CONFIG_SYS_CLOCK_HW_CYCLES_PER_SEC': str(macros['BTH_CPU_HZ']),
                           'CONFIG_SYS_CLOCK_TICKS_PER_SEC': '1000'}
        for key, value in expected_config.items():
            expect(core, None, config.get(key) == value, 'config-contract', key+' must be '+value)
        native_gpio = config.get('CONFIG_GPIO_BES2700YP', 'n') == 'y'
        expect(core, None, config.get('CONFIG_GPIO', 'n') == ('y' if native_gpio else 'n'),
               'unreviewed-runtime-owner', 'GPIO API requires the reviewed BTH service driver')
        if native_gpio:
            expect(core, None, core == 'bth', 'gpio-owner', 'GPIO API belongs to BTH')
            for key in ('CONFIG_GPIO_HOGS', 'CONFIG_LED_GPIO', 'CONFIG_INPUT_GPIO_KEYS'):
                expect(core, None, config.get(key, 'n') == 'n', 'gpio-init-owner', key)
        for key in ('CONFIG_SERIAL', 'CONFIG_PINCTRL', 'CONFIG_CLOCK_CONTROL',
                    'CONFIG_RESET', 'CONFIG_PM', 'CONFIG_PM_DEVICE', 'CONFIG_TICKLESS_KERNEL'):
            expect(core, None, config.get(key, 'n') == 'n', 'unreviewed-runtime-owner', key)
        native_irq = config.get('CONFIG_GPIO_BES2700YP_IRQ', 'n') == 'y'
        expect(core, None, not native_irq or native_gpio, 'gpio-irq-owner', 'IRQ requires BTH GPIO')
        gpio_mode = int(config.get('CONFIG_BES2700YP_GPIO_VALIDATION', '0'))
        expect(core, None, gpio_mode in ((0, 1, 2) if core == 'bth' else (0,)),
               'gpio-owner', 'restricted GPIO service is callable only from BTH')
        if gpio_mode and core == 'bth':
            manifest_path = release / 'manifest.json'
            layout_path = release / 'layout.json'
            paths.extend([manifest_path, layout_path])
            manifest = json.loads(manifest_path.read_text())
            layout = json.loads(layout_path.read_text())
            wanted = {'gpio-input': 1, 'gpio-led': 2, 'gpio-api-input': 1,
                      'gpio-api-led-restart': 2, 'gpio-irq-input': 1, 'gpio-irq-restart': 1,
                      'gpio-irq-recovery': 1}.get(manifest.get('validation_profile'))
            wanted_api = manifest.get('validation_profile', '').startswith(('gpio-api-', 'gpio-irq-'))
            wanted_irq = manifest.get('validation_profile', '').startswith('gpio-irq-')
            irq_service = layout.get('gpio_irq_service', {})
            expect(core, None, native_irq == wanted_irq and (not wanted_irq or
                   all(irq_service.get(k) == v for k, v in dict(abi=5, capabilities=64, irq=44,
                       priority=3, pins=0x30000, request_bytes=96, snapshot_bytes=64).items())),
                   'gpio-irq-contract', 'IRQ profile and audited service must match')
            service = layout.get('gpio_service', {})
            expect(core, None, layout.get('validation_profile') == manifest.get('validation_profile')
                   and gpio_mode == wanted and service.get('mode') == gpio_mode
                   and native_gpio == wanted_api
                   and service.get('zephyr_api', False) is wanted_api
                   and service.get('capabilities') == (40 if gpio_mode == 1 else 56),
                   'gpio-profile', 'GPIO profile/config/ELF capabilities must match')
            report['gpio_qualification'] = dict(owner='BTH bootstrap service',
                inputs=['P2_0', 'P2_1'], outputs=['P1_4'] if gpio_mode == 2 else [],
                unchanged=['P1_5', 'P2_2', 'P2_3'], irq='P2_0/P2_1 edge via BTH IRQ 44' if native_irq else 'polling only',
                pin_voltage='unchanged; requires board measurement')
        cpu = tree.get_node('/cpus/cpu@0')
        expect(core, cpu, core_policy['cpu'] in strings(cpu, 'compatible') and enabled(cpu)
               and number(cpu, 'clock-frequency') == macros['BTH_CPU_HZ'],
               'cpu-clock', 'CPU type/status/frequency differs from bootstrap contract')
        nvic = tree.label2node['nvic']
        expect(core, nvic, number(nvic, 'arm,num-irq-priority-bits') == policy['irq_priority_bits']
               and number(nvic, '#interrupt-cells') == 2, 'nvic-contract', 'NVIC cells/priority bits')

        # Derive allocations from existing runtime contracts; no second shared-memory map.
        expected_memory = dict(db_diag=regions['doorbell'], msg_shared=regions['message'],
                               lifecycle_control=regions['lifecycle'])
        if core == 'bth':
            expected_memory.update({k: tuple(v) for k, v in policy['bootstrap_memory'].items()})
            expected_memory.update(bth_code=(macros['BTH_CODE_BASE'], macros['BTH_CODE_SIZE']),
                                   bth_data=(macros['BTH_DATA_BASE'], macros['BTH_DATA_END']-macros['BTH_DATA_BASE']))
            chosen_labels = {'zephyr,flash': 'bth_code', 'zephyr,sram': 'bth_data'}
        else:
            expected_memory.update(m55_itcm=(dual['DUAL_ITCM'], 0x40000),
                                   m55_dtcm=(dual['DUAL_DTCM'], regions['message'][0]-dual['DUAL_DTCM']),
                                   m55_loader=regions['trampoline'], m55_shared=regions['heartbeat'],
                                   m55_mailbox=regions['mailbox'])
            chosen_labels = {'zephyr,flash': 'm55_itcm', 'zephyr,sram': 'm55_dtcm',
                             'zephyr,itcm': 'm55_itcm', 'zephyr,dtcm': 'm55_dtcm'}
        allowed_memory = {}
        for label, region in expected_memory.items():
            node = tree.label2node.get(label)
            expect(core, node, node is not None and enabled(node), 'memory-contract', label+' missing/disabled')
            if node:
                expect(core, node, node_regs(core, node) == [region], 'memory-contract', label+' range')
                allowed_memory[node.path] = label
        chosen = tree.get_node('/chosen')
        for key, label in chosen_labels.items():
            expect(core, chosen, key in chosen.props and chosen.props[key].to_path() is tree.label2node.get(label),
                   'chosen-memory', key+' must select '+label)
        for key, label in [('FLASH', chosen_labels['zephyr,flash']), ('SRAM', chosen_labels['zephyr,sram'])]:
            base, size = expected_memory[label]
            expect(core, None, int(config.get('CONFIG_'+key+'_BASE_ADDRESS', '-1'), 0) == base
                   and int(config.get('CONFIG_'+key+'_SIZE', '-1'), 0)*1024 == size,
                   'config-memory', key+' differs from generated DTS')

        expect(core, None, not native_gpio or gpio_mode in (1, 2),
               'gpio-profile', 'GPIO API requires a pinned service capability')
        gpio_nodes = []
        mailbox_nodes = []
        private_nodes = []
        for node in tree.node_iter():
            if not enabled(node):
                continue
            compat = strings(node, 'compatible')
            # A private peripheral under /cpus uses its CPU parent as an address container.
            private = any(c in ('arm,v8m-nvic', 'arm,v8.1m-nvic', 'arm,armv8m-systick',
                                'arm,armv8.1m-systick', 'arm,armv8.1m-mpu') for c in compat)
            if 'device_type' in node.props and node.props['device_type'].to_string() == 'cpu':
                continue
            memory = ('zephyr,memory-region' in compat or node.path.startswith('/reserved-memory/')
                      or strings(node, 'device_type') == ['memory'])
            if private and node.parent is cpu:
                cells = node.props['reg'].to_nums()
                regs = [(cells[0], cells[1])] if len(cells) == 2 else []
            else:
                regs = node_regs(core, node)
            kind = 'memory' if memory else 'private' if private else 'device'
            if private:
                private_nodes.append(node)
                permitted = ('arm,v8m-nvic', 'arm,armv8m-systick') if core == 'bth' else (
                    'arm,v8.1m-nvic', 'arm,armv8.1m-systick', 'arm,armv8.1m-mpu')
                expect(core, node, any(c in permitted for c in compat), 'private-type', 'core peripheral type')
                expected_private = (0xe000e100, 0xc00) if 'interrupt-controller' in node.props else (
                    (0xe000ed90, 0x40) if 'arm,armv8.1m-mpu' in compat else (0xe000e010, 0x10))
                expect(core, node, regs == [expected_private], 'private-range', 'core-local range')
            elif 'bestechnic,bes2700-mbox' in compat:
                kind = 'mailbox'
                mailbox_nodes.append(node)
                expect(core, node, regs == [tuple(r) for r in policy['mailbox']['reg']]
                       and strings(node, 'reg-names') == ['sys', 'bth']
                       and ('endpoint-bth' in node.props) == (core == 'bth')
                       and number(node, '#mbox-cells') == 1,
                       'mailbox-fields', 'only the reviewed channel-1 endpoint windows are shared')
            elif 'bestechnic,bes2700yp-gpio' in compat:
                gpio_nodes.append(node)
                wanted_ranges = [0, 16] if gpio_mode == 1 else [0, 12, 13, 3]
                ranges = node.props.get('gpio-reserved-ranges')
                expect(core, node, native_gpio and core == 'bth'
                       and regs == [(0x40081000, 0x1000)]
                       and number(node, 'ngpios') == 18 and number(node, '#gpio-cells') == 2
                       and 'gpio-controller' in node.props and ranges is not None
                       and ranges.to_nums() == wanted_ranges
                       and ((node.props['interrupts'].to_nums() if 'interrupts' in node.props else [])
                            == ([44, 3] if native_irq else []))
                       and not any(k in node.props for k in ('interrupts-extended',
                                                           'clocks', 'resets', 'pinctrl-0')),
                       'gpio-service-owner', 'GPIO range, pin grant and inherited resources')
                for alias, pin, flags in [('sw0', 16, 17), ('sw1', 17, 17), ('led0', 12, 1)]:
                    consumer = tree.alias2node.get(alias)
                    prop = consumer.props.get('gpios') if consumer else None
                    cells = struct.unpack('>3I', prop.value) if prop and len(prop.value) == 12 else ()
                    expect(core, consumer, len(cells) == 3 and tree.phandle2node.get(cells[0]) is node
                           and cells[1:] == (pin, flags), 'gpio-board-map', alias)
            elif memory:
                expect(core, node, node.path in allowed_memory, 'unassigned-memory', 'memory owner is not declared')
            elif regs:
                expect(core, node, False, 'unreviewed-device', 'MMIO ownership/dependencies are not granted')

            for region in regs:
                claims.append(dict(core=core, node=node.path, kind=kind, start=region[0], bytes=region[1]))
                if not private and not memory:
                    for macro in ('BTH_UART_BASE', 'BTH_TIMER_BASE'):
                        if overlaps(region, (macros[macro], 0x1000)):
                            fail(core, node, 'bootstrap-owner', macro+' remains owned by bootstrap/BTH')
                if memory:
                    for word in resources['repark_diagnostic']['physical_words']:
                        if overlaps(physical(region), (word, 4)):
                            fail(core, node, 'repark-reservation', 'REPARK physical word is not free RAM')

            # Decode local NVIC IRQs; reject other routing instead of guessing.
            irq_specs = []
            if 'interrupts-extended' in node.props:
                fail(core, node, 'irq-routing', 'extended interrupt routing requires review')
            if 'interrupts' in node.props:
                parent = node
                while parent is not None and 'interrupt-parent' not in parent.props:
                    parent = parent.parent
                controller = parent.props['interrupt-parent'].to_node() if parent else None
                cells = node.props['interrupts'].to_nums()
                if controller is not nvic or len(cells) % 2:
                    fail(core, node, 'irq-routing', 'expected complete local NVIC IRQ/priority pairs')
                else:
                    irq_specs = list(zip(cells[::2], cells[1::2]))
                    for irq, priority in irq_specs:
                        expect(core, node, irq < core_policy['num_irqs'] and priority < 1 << policy['irq_priority_bits'],
                               'irq-range', 'IRQ/priority outside local NVIC range')
                        key = (core, controller.path, irq)
                        if key in irq_users:
                            fail(core, node, 'irq-conflict', 'also claimed by '+irq_users[key])
                        irq_users[key] = node.path
            if kind == 'mailbox':
                expect(core, node, irq_specs == [(irq, policy['mailbox']['priority']) for irq in policy['mailbox']['irqs'][core]]
                       and strings(node, 'interrupt-names') == ['rx', 'tx-done'],
                       'mailbox-irqs', 'endpoint IRQ routing differs')

            # There is no reviewed general pinctrl/GPIO binding in this port yet.
            for key, prop in node.props.items():
                if key in ('clocks', 'resets', 'power-domains'):
                    fail(core, node, 'unreviewed-dependency', key+' provider and runtime ownership require review')
                if key.startswith('pinctrl-') and key != 'pinctrl-names':
                    fail(core, node, 'unreviewed-pinctrl', 'pad encoding and board wiring require review')
                    for state in prop.to_nodes():
                        for group in state.node_iter():
                            if 'pins' in group.props:
                                for pad in group.props['pins'].to_strings():
                                    if pad in policy['bootstrap_uart_pads']:
                                        fail(core, node, 'reserved-pad', pad+' remains reserved by bootstrap UART')
                if key == 'gpios' or key.endswith('-gpios'):
                    fail(core, node, 'unreviewed-gpio', 'controller-to-pad mapping and voltage are unconfirmed')
                if key == 'mboxes':
                    # phandle-array properties contain both references and cells.
                    cells = dtlib.to_nums(prop.value)
                    if len(cells) % 2:
                        fail(core, node, 'mailbox-channel', 'incomplete mailbox specifier')
                    for i in range(0, len(cells)-1, 2):
                        controller = tree.phandle2node.get(cells[i])
                        expect(core, node, controller is not None and enabled(controller)
                               and 'bestechnic,bes2700-mbox' in strings(controller, 'compatible')
                               and cells[i+1] == policy['mailbox']['logical_channel'],
                               'mailbox-channel', 'only logical channel 0 (hardware channel 1) is granted')
        expect(core, None, len(gpio_nodes) == int(native_gpio),
               'gpio-count', 'one enabled GPIO service controller is required with the driver')
        expect(core, None, len(mailbox_nodes) == 1, 'mailbox-count', 'one enabled endpoint per core required')
        expect(core, None, nvic in private_nodes and any('systick' in c for n in private_nodes for c in strings(n, 'compatible')),
               'private-peripheral', 'NVIC and SysTick must remain enabled')

    # Share only complete, reviewed endpoint windows and declared protocol reservations.
    shared = set(regions.values())
    for i, a in enumerate(claims):
        for b in claims[i+1:]:
            if a['kind'] == 'private' or b['kind'] == 'private':
                if a['core'] != b['core']:
                    continue
            ar, br = physical((a['start'], a['bytes'])), physical((b['start'], b['bytes']))
            if not overlaps(ar, br):
                continue
            allowed = a['core'] != b['core'] and ar == br and (
                a['kind'] == b['kind'] == 'mailbox' and ar in {tuple(r) for r in policy['mailbox']['reg']}
                or a['kind'] == b['kind'] == 'memory' and ar in shared)
            if not allowed:
                errors.append(dict(core=a['core'], node=a['node'], code='physical-overlap',
                                   detail=b['core']+':'+b['node']))
    report['bootstrap_reserved_pads'] = policy['bootstrap_uart_pads']
    report['inputs'] = {str(p.resolve()): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    report['status'] = 'fail' if errors else 'pass'
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--release', type=Path, required=True, help='directory with generated bth/m55 DTS and config')
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--zephyr-base', type=Path, default=Path(os.environ.get('ZEPHYR_BASE', ROOT.parent / 'zephyr')))
    parser.add_argument('--output', type=Path, required=True, help='report outside the frozen release directory')
    args = parser.parse_args()
    if args.output.resolve().is_relative_to(args.release.resolve()) or args.output.resolve().is_relative_to(args.root.resolve()):
        parser.error('Write the report outside the source and frozen release directories')
    try:
        report = audit(args.root, args.release, args.zephyr_base)
    except Exception as error:
        report = dict(schema=1, status='fail', scope='static-resource-ownership',
                      hardware='not_tested', errors=[dict(code='invalid-input', detail=str(error))])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps({k: v for k, v in report.items() if k not in ('claims', 'inputs')}, indent=2))
    return 0 if report['status'] == 'pass' else 1


if __name__ == '__main__':
    sys.exit(main())
