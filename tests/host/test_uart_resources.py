# SPDX-License-Identifier: Apache-2.0
import copy
import ctypes
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import analyze_uart_resources as parser


class UARTResources(unittest.TestCase):
    def test_descriptor_and_legacy_separation(self):
        with tempfile.TemporaryDirectory() as tmp:
            so = Path(tmp) / 'contract.so'
            subprocess.run(['cc', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                '-I', str(ROOT / 'include/bestechnic/bes2700yp'),
                str(ROOT / 'platforms/bes2700yp/resources/contract.c'),
                str(ROOT / 'platforms/bes2700yp/resources/uart_contract.c'), '-o', str(so)], check=True)
            lib = ctypes.CDLL(str(so))
            words = [0x31534552, 2, 32, 2, 0x14000001, 96, 64, 0]
            value = lambda w: (ctypes.c_uint32 * 8)(*w)
            self.assertEqual(lib.bes_uart_resource_descriptor_valid(value(words)), 1)
            self.assertEqual(lib.bes_resource_descriptor_valid(value(words)), 0)
            legacy = words.copy(); legacy[1] = legacy[3] = 1
            self.assertEqual(lib.bes_resource_descriptor_valid(value(legacy)), 1)
            self.assertEqual(lib.bes_uart_resource_descriptor_valid(value(legacy)), 0)
            for i in range(8):
                bad = words.copy(); bad[i] ^= 1
                self.assertEqual(lib.bes_uart_resource_descriptor_valid(value(bad)), 0)

    def compile_actual(self, kind):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / kind
            files = [ROOT / ('tests/dual_message/uart_resource_' + kind + '.c'),
                     ROOT / 'platforms/bes2700yp/resources/contract.c',
                     ROOT / 'platforms/bes2700yp/resources/uart_contract.c']
            if kind == 'client':
                files += [ROOT / 'platforms/bes2700yp/resources/uart_client.c',
                          ROOT / 'platforms/bes2700yp/boot/service_contract.c']
            subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-std=gnu11',
                '-fsanitize=undefined', '-fno-sanitize-recover=all',
                '-I', str(ROOT / 'include/bestechnic/bes2700yp'),
                '-I', str(ROOT.parent / 'modules/hal/bestechnic/include'),
                *map(str, files), '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True, timeout=10)

    def test_actual_service(self):
        self.compile_actual('service')

    def test_actual_client(self):
        self.compile_actual('client')

    def test_full_scenario_parsers(self):
        from test_observation_parser import cases, fixture
        for analyzer, old_manifest, legacy in cases():
            manifest, full, short = fixture(old_manifest, legacy)
            manifest['uart_resource_service'] = dict(abi=2, capabilities=2)
            lines, emitted = [], set()
            for line in short.splitlines():
                lines.append(line)
                phase = None
                if 'zephyr_bth stage=main !' in line:
                    phase = 0
                elif 'zephyr_dual stage id=6 ' in line or ('zephyr_lifecycle reset ' in line and ' op=3 ' in line):
                    phase = 3
                elif manifest.get('restart_version') and 'zephyr_observe functional ' in line:
                    phase = 4
                if phase is None or phase in emitted:
                    continue
                emitted.add(phase)
                d = dict(parser.EXPECTED, version=2, build=int(manifest['build'], 0), expected=phase, rc=0, phase=phase)
                if phase == 4:
                    lines.pop()
                lines.append(line.split('/')[0] + '/I/BTH/RESOURCE/MAIN | zephyr_uart_resource snapshot ' +
                             ' '.join(f'{k}={v}' for k, v in d.items()) + ' !')
                if phase == 4:
                    lines.append(line)
            text = '\n'.join(lines)+'\n'
            result = analyzer.analyze(text, manifest, 'short')
            self.assertEqual(result['status'], 'pass', (manifest['validation_profile'], result))
            for old, new in [('configured_hz=24000000', 'configured_hz=0'), ('rx_mux=4','rx_mux=3'),
                             ('reset_released=3','reset_released=1'), ('valid=7','valid=3'),
                             ('pull_up=1','pull_up=0'), ('snapshot ', 'snapshot rc=0 '),
                             ('/RESOURCE/', '/LOADER/')]:
                self.assertEqual(analyzer.analyze(text.replace(old,new), manifest, 'short')['status'], 'fail')
            uart_lines = [line for line in lines if 'zephyr_uart_resource' in line]
            late = [line for line in lines if line != uart_lines[-1]] + [uart_lines[-1]]
            self.assertEqual(analyzer.analyze('\n'.join(late)+'\n', manifest, 'short')['status'], 'fail')
            missing = '\n'.join(line for line in lines if 'zephyr_uart_resource' not in line)+'\n'
            self.assertEqual(analyzer.analyze(missing, manifest, 'short')['status'], 'incomplete')
