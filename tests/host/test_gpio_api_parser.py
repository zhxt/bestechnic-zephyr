# SPDX-License-Identifier: Apache-2.0
import re
import unittest

import analyze_dual_message as message
import analyze_dual_restart as restart
from test_gpio import fixture as input_fixture
from test_restart_parser import manifest as restart_manifest, fixture as restart_fixture
from test_observation_parser import fixture as observation_fixture


def fixture():
    manifest = restart_manifest()
    manifest['validation_profile'] = 'gpio-api-led-restart'
    manifest['gpio_service'] = dict(abi=4, mode=2, capabilities=56, request_bytes=96,
                                    snapshot_bytes=64, zephyr_api=True)
    manifest, _, text = observation_fixture(manifest, restart_fixture(manifest))
    events = []
    baseline = dict(version=1, phase=3, fault=0, pins=0x33000, inputs=0x33000,
                    directions=0, outputs=0, mux_led=0xffffffff, mux_keys=0xffffffff,
                    pull_up=0x80000000, pull_down=0, clocks=0x4002, resets=0x4002,
                    irq_enabled=0, control=0, mask_errors=0, rc=0)

    def row(time, kind, **data):
        events.append(f'{time}/I/BTH/GPIO/MAIN | zephyr_gpio_api {kind} ' +
                      ' '.join(f'{k}={v}' for k, v in data.items())+' !')

    row(3102, 'baseline', **baseline, round=0, stage=0, sample=0, transitions=0, max_ticks=0)
    configured = dict(baseline, directions=0x1000, mux_led=0xfff0ffff)
    for n in range(11):
        for stage in (0, 1):
            data = dict(configured, phase=3+stage, outputs=stage*0x1000,
                        inputs=0x32000+stage*0x1000, round=n, stage=stage, sample=0,
                        transitions=n*2+stage+1, max_ticks=24000)
            row(2100+n*5000+(1003 if stage == 0 else 3102), 'checkpoint', **data)
    functional = next(int(line.split('/')[0]) for line in text.splitlines()
                      if 'zephyr_observe functional ' in line)
    for line in text.splitlines():
        match = re.search(r'zephyr_lifecycle sample id=(\d+) ', line)
        time = int(line.split('/')[0]) if line.split('/')[0].isdigit() else 0
        if match and time > functional:
            row(time, 'observe', **dict(configured, phase=4, outputs=0x1000, inputs=0x33000),
                round=10, stage=2, sample=int(match[1]), transitions=22, max_ticks=24000)
    boot, lines = [], []
    for line in text.splitlines():
        (boot if 'zephyr_bth ' in line or 'zephyr_bootprof ' in line else lines).append(line)
    return manifest, '\n'.join(boot+sorted(lines+events, key=lambda line: int(line.split('/')[0])))+'\n'


class GpioApiParser(unittest.TestCase):
    def test_native_input_requires_standard_api_identity(self):
        manifest, text = input_fixture(1)
        manifest['validation_profile'] = 'gpio-api-input'
        manifest['gpio_service']['zephyr_api'] = True
        text = text.replace('zephyr_gpio begin version=2 ', 'zephyr_gpio begin version=3 api=1 ')
        self.assertEqual(message.analyze(text, manifest, 'short')['status'], 'pass')
        for bad in (text.replace('api=1', 'api=0'), text.replace('api=1 ', ''),
                    text.replace('begin version=3', 'begin version=2')):
            self.assertEqual(message.analyze(bad, manifest, 'short')['status'], 'fail')
        manifest['gpio_service']['zephyr_api'] = False
        self.assertEqual(message.analyze(text, manifest, 'short')['status'], 'fail')

    def test_native_output_lifecycle_and_short(self):
        manifest, text = fixture()
        result = restart.analyze(text, manifest, 'short')
        self.assertEqual(result['status'], 'pass', result)
        self.assertFalse(result['complete'])
        self.assertEqual(restart.analyze(text, manifest, 'long')['status'], 'incomplete')
        for old, new in [('stage=0 sample=0 transitions=1', 'stage=1 sample=0 transitions=1'),
                         ('transitions=22', 'transitions=21'), ('mask_errors=0', 'mask_errors=1'),
                         ('outputs=4096', 'outputs=0'), ('inputs=204800', 'inputs=208896'),
                         ('mux_led=4293984255', 'mux_led=4293918719'),
                         ('max_ticks=24000', 'max_ticks=0'), ('clocks=16386', 'clocks=0'),
                         ('/GPIO/MAIN', '/GPIO/IRQ')]:
            self.assertIn(old, text)
            self.assertEqual(restart.analyze(text.replace(old, new, 1), manifest, 'short')['status'],
                             'fail', old)
        for token in ('zephyr_gpio_api baseline ', 'zephyr_gpio_api checkpoint ',
                      'zephyr_gpio_api observe '):
            bad = '\n'.join(line for line in text.splitlines() if token not in line)+'\n'
            result = restart.analyze(bad, manifest, 'short')
            self.assertNotEqual(result['status'], 'pass', token)
            self.assertNotEqual(result['sessions'][0]['scopes']['short']['status'], 'pass', token)
        # Reordered or duplicated successful-looking checkpoints cannot fill coverage.
        checkpoint = next(line for line in text.splitlines() if 'zephyr_gpio_api checkpoint ' in line)
        self.assertEqual(restart.analyze(text.replace(checkpoint, checkpoint+'\n'+checkpoint),
                                        manifest, 'short')['status'], 'fail')

    def test_missing_metadata_and_failure_after_short(self):
        manifest, text = fixture()
        manifest['gpio_service']['zephyr_api'] = False
        self.assertEqual(restart.analyze(text, manifest, 'short')['status'], 'fail')
        manifest['gpio_service']['zephyr_api'] = True
        last = [line for line in text.splitlines() if 'zephyr_gpio_api observe ' in line][-1]
        self.assertEqual(restart.analyze(text+last.replace('/I/', '/E/').replace('rc=0', 'rc=5')+'\n',
                                        manifest, 'short')['status'], 'fail')
