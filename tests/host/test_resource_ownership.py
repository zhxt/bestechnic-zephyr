# SPDX-License-Identifier: Apache-2.0
"""Exercise conflicting DTS/config inputs and the allowed cross-core sharing."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
from check_resources import audit
import ci

ZEPHYR = Path(os.environ.get('ZEPHYR_BASE', ROOT.parent / 'zephyr'))


def fixture(core):
    """Small generated-DTS-shaped inputs, independent of any local build archive."""
    bth = core == 'bth'
    nvic = 'arm,v8m-nvic' if bth else 'arm,v8.1m-nvic'
    systick = 'arm,armv8m-systick' if bth else 'arm,armv8.1m-systick'
    memory = (('bth_code', 0x510000, 0x30000), ('bth_data', 0x20540000, 0x1c000)) if bth else (
        ('m55_itcm', 0xa0000, 0x40000), ('m55_dtcm', 0x200c0000, 0x9c000),
        ('m55_loader', 0x2015e000, 0x100), ('m55_shared', 0x2015e100, 0x80))
    reserved = [('msg_shared', 0x2015c000, 0x2000), ('db_diag', 0x2015e200, 0x80),
                ('lifecycle_control', 0x2015e280, 0x80)]
    reserved += [('adapter', 0x20500000, 0x10000), ('handoff', 0x2055c000, 0x3fe0),
                 ('mailbox', 0x2055ffe0, 0x20)] if bth else [('m55_mailbox', 0x2015ffe0, 0x20)]
    chosen = f'zephyr,flash = &{memory[0][0]}; zephyr,sram = &{memory[1][0]};'
    if not bth:
        chosen += ' zephyr,itcm = &m55_itcm; zephyr,dtcm = &m55_dtcm;'
    cpu = 'arm,cortex-m33' if bth else 'arm,cortex-m55'
    text = f'''/dts-v1/;
/ {{
    #address-cells = <1>; #size-cells = <1>;
    chosen {{ {chosen} }};
    cpus {{ #address-cells = <1>; #size-cells = <0>;
        cpu@0 {{ device_type = "cpu"; compatible = "{cpu}";
            reg = <0>; clock-frequency = <24000000>; }};
    }};
    soc {{ #address-cells = <1>; #size-cells = <1>; ranges;
        compatible = "simple-bus"; interrupt-parent = <&nvic>;
        nvic: interrupt-controller@e000e100 {{ compatible = "{nvic}";
            reg = <0xe000e100 0xc00>; interrupt-controller;
            #interrupt-cells = <2>; arm,num-irq-priority-bits = <3>; }};
        systick: timer@e000e010 {{ compatible = "{systick}"; reg = <0xe000e010 0x10>; }};
    }};
    uart: serial@4000b000 {{ compatible = "bestechnic,bes2700-bth-uart";
        reg = <0x4000b000 0x1000>; status = "disabled"; }};
    mbox_peer: mailbox@500000a0 {{ compatible = "bestechnic,bes2700-mbox";
        reg = <0x500000a0 8>, <0x40000134 8>; reg-names = "sys", "bth";
        interrupt-parent = <&nvic>; interrupts = <{39 if bth else 41} 3>, <{37 if bth else 39} 3>;
        interrupt-names = "rx", "tx-done"; #mbox-cells = <1>;
        {'endpoint-bth;' if bth else ''}
    }};
'''
    for label, start, size in memory:
        text += f'{label}: memory@{start:x} {{ compatible = "zephyr,memory-region"; reg = <0x{start:x} 0x{size:x}>; }};\n'
    text += 'reserved-memory { #address-cells = <1>; #size-cells = <1>; ranges;\n'
    for label, start, size in reserved:
        text += f'{label}: memory@{start:x} {{ reg = <0x{start:x} 0x{size:x}>; }};\n'
    text += '};\n};\n'
    config = f'''CONFIG_SOC_BES2700YP_{'BTH' if bth else 'CM55'}=y
CONFIG_NUM_IRQS={64 if bth else 72}
CONFIG_SYS_CLOCK_HW_CYCLES_PER_SEC=24000000
CONFIG_SYS_CLOCK_TICKS_PER_SEC=1000
CONFIG_MBOX=y
CONFIG_MBOX_BES2700=y
CONFIG_FLASH_BASE_ADDRESS=0x{memory[0][1]:x}
CONFIG_FLASH_SIZE={memory[0][2]//1024}
CONFIG_SRAM_BASE_ADDRESS=0x{memory[1][1]:x}
CONFIG_SRAM_SIZE={memory[1][2]//1024}
'''
    return text, config


class ResourceOwnership(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name)
        self.release = self.base / 'release'
        self.release.mkdir()
        for core in ('bth', 'm55'):
            dts, config = fixture(core)
            (self.release / (core+'.dts')).write_text(dts)
            (self.release / (core+'.config')).write_text(config)

    def change(self, core, old, new, suffix='dts'):
        path = self.release / (core+'.'+suffix)
        text = path.read_text()
        self.assertIn(old, text)
        path.write_text(text.replace(old, new))

    def extra(self, core, body):
        path = self.release / (core+'.dts')
        with path.open('a') as stream:
            stream.write('/ { '+body+' };\n')

    def check(self, expected=None):
        result = audit(ROOT, self.release, ZEPHYR)
        if expected:
            self.assertEqual(result['status'], 'fail', result)
            self.assertIn(expected, {e['code'] for e in result['errors']}, result)
        else:
            self.assertEqual(result['status'], 'pass', result)
        return result

    def test_private_addresses_cross_core_irqs_and_mailbox_sharing_are_legal(self):
        report = self.check()
        self.assertTrue(report['unconfirmed'])
        self.assertEqual(report['hardware'], 'not_tested')
        self.assertEqual(report['bootstrap_reserved_pads'], ['P2_2', 'P2_3'])

    def test_same_core_irq_conflict_is_rejected(self):
        self.extra('bth', 'other { interrupts = <39 3>; interrupt-parent = <&nvic>; };')
        self.check('irq-conflict')

    def test_irq_range_and_controller_namespace(self):
        self.change('m55', '<41 3>', '<72 3>')
        self.check('irq-range')
        self.change('m55', '<72 3>', '<41 8>')
        self.check('irq-range')

    def test_mailbox_cannot_claim_parent_cmu_or_swap_endpoint(self):
        self.change('bth', '<0x500000a0 8>', '<0x50000000 0x1000>')
        self.check('mailbox-fields')
        self.change('bth', '<0x50000000 0x1000>', '<0x500000a0 8>')
        self.change('bth', 'endpoint-bth;', '')
        self.check('mailbox-fields')

    def test_only_logical_mailbox_channel_zero_is_granted(self):
        self.extra('bth', 'client { mboxes = <&mbox_peer 1>; };')
        self.check('mailbox-channel')
        self.change('bth', '<&mbox_peer 1>', '<&mbox_peer 0>')
        self.check()

    def test_second_controller_cannot_share_mailbox_fields(self):
        self.extra('m55', 'cmu@500000a0 { compatible = "test,cmu"; reg = <0x500000a0 8>; };')
        self.check('physical-overlap')

    def test_m55_cannot_enable_bootstrap_uart(self):
        self.change('m55', 'status = "disabled"', 'status = "okay"')
        self.check('bootstrap-owner')

    def test_timer_cannot_be_reconfigured_by_another_driver(self):
        self.extra('bth', 'timer@40002000 { compatible = "test,timer"; reg = <0x40002000 0x1000>; };')
        self.check('bootstrap-owner')

    def test_uart_disabled_does_not_free_pads_for_pinctrl(self):
        self.extra('bth', 'pins: uart-pins { pins = "P2_2", "P2_3"; }; client { pinctrl-0 = <&pins>; };')
        self.check('reserved-pad')

    def test_unknown_pinmux_and_gpio_routes_are_not_accepted(self):
        self.extra('m55', 'pins: new-pins { pinmux = <1234>; }; client { pinctrl-0 = <&pins>; };')
        self.check('unreviewed-pinctrl')
        self.extra('bth', 'led { gpios = <0 2 0>; };')
        self.check('unreviewed-gpio')

    def test_clock_dependency_needs_review(self):
        self.extra('bth', 'clock: clock { #clock-cells = <0>; }; client { clocks = <&clock>; };')
        self.check('unreviewed-dependency')

    def test_m55_sram_growth_overlaps_message_region(self):
        self.change('m55', '<0x200c0000 0x9c000>', '<0x200c0000 0x9e000>')
        self.check('physical-overlap')

    def test_bth_code_alias_is_not_additional_free_memory(self):
        self.extra('bth', 'extra@20510000 { compatible = "zephyr,memory-region"; reg = <0x20510000 0x30000>; };')
        self.check('physical-overlap')

    def test_repark_words_and_unallocated_tail_are_reserved(self):
        self.extra('m55', 'extra@20320000 { compatible = "zephyr,memory-region"; reg = <0x20320000 4>; };')
        self.check('repark-reservation')
        self.extra('m55', 'heap@2015e300 { compatible = "zephyr,memory-region"; reg = <0x2015e300 0x100>; };')
        self.check('unassigned-memory')

    def test_effectively_disabled_mailbox_is_not_available(self):
        self.change('bth', 'mbox_peer: mailbox@500000a0 {', 'mbox_peer: mailbox@500000a0 { status = "disabled";')
        self.check('mailbox-count')

    def test_parent_status_and_address_translation_are_checked(self):
        self.change('m55', 'soc { #address-cells', 'soc { status = "disabled"; #address-cells')
        self.check('private-peripheral')
        self.change('m55', 'soc { status = "disabled"; #address-cells', 'soc { #address-cells')
        self.extra('bth', 'bus { #address-cells = <1>; #size-cells = <1>; '
                   'ranges = <0 0x40000000 0x10000>; device@0 { reg = <0 0x1000>; }; };')
        self.check('reg-format')

    def test_clock_and_config_changes_need_new_ownership_review(self):
        self.change('bth', 'clock-frequency = <24000000>', 'clock-frequency = <48000000>')
        self.check('cpu-clock')
        self.change('m55', 'CONFIG_MBOX=y', 'CONFIG_MBOX=y\nCONFIG_PM=y', 'config')
        self.check('unreviewed-runtime-owner')

    def test_config_memory_must_match_generated_dts(self):
        self.change('m55', 'CONFIG_SRAM_SIZE=624', 'CONFIG_SRAM_SIZE=632', 'config')
        self.check('config-memory')

    def test_malformed_dts_fails_cli_without_writing_release(self):
        (self.release/'bth.dts').write_text('/dts-v1/; / { broken')
        output = self.base/'report.json'
        command = [sys.executable, str(ROOT/'scripts/check_resources.py'), '--release', str(self.release),
                   '--zephyr-base', str(ZEPHYR), '--output', str(output)]
        result = subprocess.run(command, capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(output.read_text())['errors'][0]['code'], 'invalid-input')
        result = subprocess.run(command[:-1]+[str(self.release/'report.json')], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertFalse((self.release/'report.json').exists())

    def run_ci(self, conflict=False):
        """Mock construction, then execute the real resource gate on its output."""
        if conflict:
            self.change('m55', '<0x200c0000 0x9c000>', '<0x200c0000 0x9e000>')
        workspace = self.base/'workspace'
        workspace.mkdir()
        (workspace/'bestechnic-zephyr').symlink_to(ROOT, target_is_directory=True)
        (workspace/'zephyr').symlink_to(ZEPHYR, target_is_directory=True)
        output = self.base/'ci'
        real_run = subprocess.run

        def run(command, **kwargs):
            if '-m' in command and 'west' in command:
                release = Path(command[command.index('-d')+1])/'release'
                shutil.copytree(self.release, release)
                (release/'zephyr.bin').write_bytes(b'host-test-image')
                checksums = ''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.name+'\n'
                                    for p in sorted(release.iterdir()))
                (release/'SHA256SUMS').write_text(checksums)
            elif command[1].endswith('/check_resources.py'):
                return real_run(command, **kwargs)
            return subprocess.CompletedProcess(command, 0)

        argv = ['ci.py', '--workspace', str(workspace), '--output', str(output),
                '--profiles', 'm55-restart', '--cross-compile', 'unused-test-toolchain-']
        with mock.patch.object(sys, 'argv', argv), mock.patch.object(ci.subprocess, 'run', run), \
                contextlib.redirect_stdout(io.StringIO()):
            if conflict:
                with self.assertRaises(subprocess.CalledProcessError):
                    ci.main()
            else:
                ci.main()
        report = json.loads((output/'summary.json').read_text())
        self.assertEqual(report['status'], 'fail' if conflict else 'pass')
        self.assertEqual(report['checks']['m55-restart-resources']['exit_code'], int(conflict))
        self.assertEqual('m55-restart' in report['artifacts'], not conflict)
        self.assertTrue((output/'m55-restart-resources.json').is_file())
        self.assertFalse((output/'m55-restart/release/m55-restart-resources.json').exists())

    def test_ci_records_resource_gate_success(self):
        self.run_ci()

    def test_ci_stops_on_resource_conflicts(self):
        self.run_ci(conflict=True)


if __name__ == '__main__':
    unittest.main()
