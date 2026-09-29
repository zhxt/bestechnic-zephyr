# SPDX-License-Identifier: Apache-2.0
import ctypes
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import analyze_dual_message as parser
from test_message_parser import manifest as msg_manifest, fixture as msg_fixture
from test_observation_parser import fixture as obs_fixture


def fixture(mode):
    m = msg_manifest('ipc-sequential')
    m['validation_profile'] = 'gpio-input' if mode == 1 else 'gpio-led'
    m['gpio_service'] = dict(abi=4, mode=mode, capabilities=8 if mode == 1 else 24,
                            request_bytes=96, snapshot_bytes=64)
    m, _, text = obs_fixture(m, msg_fixture(m))
    events = []
    def row(time, kind, **d):
        events.append(f'{time}/I/BTH/GPIO/MAIN | zephyr_gpio {kind} ' +
                      ' '.join(f'{k}={v}' for k, v in d.items()) + ' !')
    row(1, 'begin', version=1, build=int(m['build'], 0), mode=mode, target=10,
        poll_ms=10, debounce_ms=50, timeout_ms=300000)
    baseline = dict(phase=3, fault=0, pins=0x33000, inputs=0x33000, directions=0, outputs=0,
                    mux_led=0x44444444, mux_keys=0x44440000, pull_up=0x80000000, pull_down=0,
                    clocks=0x4002, resets=0x4002, irq_enabled=0, control=0)
    row(2, 'snapshot', stage=0, **baseline)
    configured = dict(baseline, pull_up=baseline['pull_up']|0x30000)
    if mode == 2:
        configured.update(mux_led=baseline['mux_led']&~0xf0000, directions=0x1000, outputs=0x1000)
    row(3, 'snapshot', stage=1, **configured)
    row(4, 'waiting', pins=0x30000, cycles_each=10)
    for pin in (16, 17):
        row(54, 'key', pin=pin, ms=50, level=1, presses=0, releases=0)
        for count in range(1, 11):
            ms = count*1000
            row(ms+4, 'key', pin=pin, ms=ms, level=0, presses=count, releases=count-1)
            row(ms+504, 'key', pin=pin, ms=ms+500, level=1, presses=count, releases=count)
    if mode == 2:
        for step in range(1, 21):
            row(step*1000+4, 'led', ms=step*1000, step=step, pin=12, level=0 if step%2 else 1)
    row(40123, 'snapshot', stage=2, **configured)
    row(40124, 'result', version=1, mode=mode, **{'pass':1}, ms=40120, samples=4000,
        p0=10, r0=10, p1=10, r1=10, led_steps=20 if mode==2 else 0,
        pad_checks=3999 if mode==2 else 0, busy=0, rc=0)
    boot, lines = [], []
    for line in text.splitlines():
        (boot if 'zephyr_bth ' in line or 'zephyr_bootprof ' in line else lines).append(line)
    # GPIO completes after IPC and immediately before the observation marker.
    lines = [line.replace('40124/I/BTH/OBSERVE', '40125/I/BTH/OBSERVE') for line in lines]
    return m, '\n'.join(boot+sorted(lines+events, key=lambda line:int(line.split('/')[0])))+'\n'


class GPIO(unittest.TestCase):
    def test_actual_service_and_button_debounce(self):
        for mode in (1, 2):
            with tempfile.TemporaryDirectory() as tmp:
                exe = str(Path(tmp) / 'service')
                subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-std=gnu11',
                    '-fsanitize=undefined', '-fno-sanitize-recover=all', '-DBES_GPIO_MODE='+str(mode),
                    '-I', str(ROOT/'include/bestechnic/bes2700yp'),
                    '-I', str(ROOT.parent/'modules/hal/bestechnic/include'),
                    str(ROOT/'tests/dual_message/gpio_service.c'),
                    str(ROOT/'platforms/bes2700yp/resources/contract.c'), '-o', exe], check=True)
                subprocess.run([exe], check=True, timeout=10)

    def test_actual_client(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe = str(Path(tmp)/'client')
            subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-std=gnu11',
                '-fsanitize=undefined', '-fno-sanitize-recover=all',
                '-I', str(ROOT/'include/bestechnic/bes2700yp'),
                *[str(ROOT/p) for p in ('tests/dual_message/gpio_client.c',
                    'platforms/bes2700yp/resources/contract.c',
                    'platforms/bes2700yp/resources/gpio_contract.c',
                    'platforms/bes2700yp/resources/gpio_client.c',
                    'platforms/bes2700yp/boot/service_contract.c')], '-o', exe], check=True)
            subprocess.run([exe], check=True, timeout=10)

    def test_descriptor_capability_and_abi(self):
        with tempfile.TemporaryDirectory() as tmp:
            so = str(Path(tmp)/'gpio.so')
            subprocess.run(['cc', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                '-I', str(ROOT/'include/bestechnic/bes2700yp'),
                str(ROOT/'platforms/bes2700yp/resources/gpio_contract.c'), '-o', so], check=True)
            lib = ctypes.CDLL(so)
            for cap in (8, 24):
                words = [0x31534552, 4, 32, cap, 0x14000001, 96, 64, 0]
                check = lambda w: lib.bes_gpio_descriptor_valid((ctypes.c_uint32*8)(*w))
                self.assertEqual(check(words), 1)
                for i in range(8):
                    bad = words.copy(); bad[i] ^= 1
                    self.assertEqual(check(bad), 0)

    def test_both_profiles_and_mutations(self):
        for mode in (1, 2):
            m, text = fixture(mode)
            r = parser.analyze(text, m, 'short')
            self.assertEqual(r['status'], 'pass', r)
            self.assertFalse(r['complete'])
            missing_contract = dict(m); missing_contract.pop('gpio_service')
            self.assertEqual(parser.analyze(text, missing_contract, 'short')['status'], 'fail')
            self.assertEqual(parser.analyze(text, m)['status'], 'incomplete')
            replacements = [('target=10', 'target=9'), ('pin=16 ms=1000', 'pin=18 ms=1000'),
                ('level=0 presses=1 releases=0', 'level=0 presses=2 releases=0'),
                ('stage=1 phase=3', 'stage=1 phase=2'), ('debounce_ms=50', 'debounce_ms=0'),
                ('p0=10 r0=10', 'p0=10 r0=9'), ('mode='+str(mode)+' pass=1', 'mode=0 pass=1'),
                ('samples=4000 p0', 'samples=0 p0'), ('/GPIO/MAIN', '/GPIO/IRQ'),
                ('fault=0 pins=208896', 'fault=1 pins=208896')]
            if mode == 2:
                replacements += [('step=2 pin=12 level=1','step=2 pin=12 level=0'),
                                 ('pad_checks=3999','pad_checks=0')]
            for old, new in replacements:
                self.assertIn(old, text)
                bad = parser.analyze(text.replace(old, new, 1), m, 'short')
                self.assertEqual(bad['status'], 'fail', (old, bad))
            for token in ('zephyr_gpio key ', 'zephyr_gpio snapshot ', 'zephyr_gpio result '):
                bad = '\n'.join(line for line in text.splitlines() if token not in line)+'\n'
                self.assertNotEqual(parser.analyze(bad, m, 'short')['status'], 'pass')
            # A non-target pull changes after configuration: never accept preservation.
            configured = next(x for x in text.splitlines() if 'snapshot stage=1 ' in x)
            changed = configured.replace('pull_up=2147680256', 'pull_up=2147942400')
            self.assertNotEqual(configured, changed)
            self.assertEqual(parser.analyze(text.replace(configured, changed),m,'short')['status'], 'fail')
