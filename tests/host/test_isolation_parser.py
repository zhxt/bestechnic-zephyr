# SPDX-License-Identifier: Apache-2.0
import copy
import unittest
from analyze_dual_isolation import analyze
from analyze_dual_restart import analyze as restart_analyze
from analyze_dual_message import analyze as message_analyze
from test_restart_parser import manifest as restart_manifest, fixture as restart_fixture
from validation_profiles import validate_manifest


def manifest(case=1):
    return dict(restart_manifest(),
                validation_profile='m55-ready-timeout' if case == 1 else 'm55-heartbeat-stop',
                isolation_version=1, fault_case=case, ready_timeout_ms=5000,
                heartbeat_timeout_ms=1000, ipc_timeout_ms=1000, fault_poll_ms=20,
                injection_stage=6, injection_beats=10, restart_rounds=1)


def fixture(case=1):
    m = manifest(case)
    original = restart_fixture()
    boot = [line for line in original.splitlines()
            if 'zephyr_bth ' in line or 'zephyr_bootprof ' in line]
    rows = []
    def row(time, kind, **fields):
        rows.append((time, f'{time}/I/BTH/LIFECYCLE/MAIN | zephyr_lifecycle {kind} ' +
                     ' '.join(f'{key}={value}' for key, value in fields.items()) + ' !'))
    row(1999, 'isolation_begin', version=1, layout=0xa0004, build=int(m['build'], 0),
        m55_build=int(m['m55_build'], 0), pair=m['message_pair'], fault_case=case,
        ready_ms=5000, heartbeat_ms=1000, duration=600, rc=0)
    for line in original.splitlines():
        if 'zephyr_lifecycle sample ' in line or ('round=0 session=1' in line and
                (' event ' in line and any(f'step={i} ' in line for i in (1, 2, 3, 4))
                 or ' reset ' in line and 'op=3 ' in line
                 or case == 2 and ' ready ' in line)):
            rows.append((int(line.split('/')[0]), line))
    detected = 8102 if case == 1 else 5002
    row(detected, 'detected', session=1, reason=case, age=5000 if case == 1 else 1000,
        beat=0 if case == 1 else 10, trace_stage=6, injection=case, elapsed=detected-2100, rc=0)
    reset = next(line for line in original.splitlines()
                 if 'zephyr_lifecycle reset round=0 ' in line and 'op=4 ' in line)
    rows.append((detected+1, str(detected+1) + '/' + reset.split('/', 1)[1]))
    row(detected+2, 'isolated', session=1, local_idle=1, reset_held=1, channel_clean=1,
        failed_step=0, service_rc=0, rc=0)
    row(detected+3, 'hardware', round=0, session=1, phase=4, reset_clr=0x581,
        ram_sel0=460165705, ram_sel1=112347, core_vtor=0x200c0000, rc=0)
    row(602001, 'held', session=1, reset_held=1, local_irq=0, peer_irq=0, rc=0)
    row(602002, 'isolation_result', **{'pass': 1, 'session': 1, 'reason': case,
                                     'samples': 601, 'releases': 1, 'recoveries': 0, 'rc': 0})
    return '\n'.join(boot + [text for _, text in sorted(rows, key=lambda item: item[0])]) + '\n'


class IsolationParser(unittest.TestCase):
    def test_complete_profiles_and_partial_observation(self):
        for case in (1, 2):
            m, text = manifest(case), fixture(case)
            result = analyze(text, m)
            self.assertEqual(result['status'], 'pass', result)
            partial = text[:text.index('20000/I/BTH/LIFECYCLE')]
            self.assertEqual(analyze(partial, m)['status'], 'incomplete')
            self.assertEqual(analyze(text + partial, m)['status'], 'incomplete')
            self.assertEqual(analyze(text[:-15], m)['status'], 'incomplete')

    def test_faults_must_not_be_misreported_as_expected_injection(self):
        for case in (1, 2):
            text, m = fixture(case), manifest(case)
            for old, new in [('trace_stage=6', 'trace_stage=255'),
                             (f'injection={case}', 'injection=0'),
                             (f'reason={case} age=', 'reason=3 age='),
                             ('local_idle=1', 'local_idle=0'),
                             ('reset_held=1', 'reset_held=0'),
                             ('channel_clean=1', 'channel_clean=0'),
                             ('failed_step=0', 'failed_step=4'),
                             ('service_rc=0', 'service_rc=4294967295'),
                             ('reset_after=1409', 'reset_after=1425'),
                             ('phase=4 reset_clr=1409', 'phase=3 reset_clr=1425'),
                             ('local_irq=0', 'local_irq=8'),
                             ('releases=1', 'releases=2'),
                             ('recoveries=0', 'recoveries=1'),
                             ('guards=1', 'guards=0'),
                             ('/I/BTH/LIFECYCLE', '/E/BTH/LIFECYCLE'),
                             ('session=1', 'session=2')]:
                with self.subTest(case=case, mutation=new):
                    self.assertIn(old, text)
                    self.assertEqual(analyze(text.replace(old, new, 1), m)['status'], 'fail')
            age = 5000 if case == 1 else 1000
            for value in (0, age-1, age+101):
                self.assertEqual(analyze(text.replace(f'age={age}', f'age={value}'), m)['status'], 'fail')

    def test_order_duplicates_and_early_success(self):
        m, text = manifest(), fixture()
        lines = text.splitlines()
        at = next(i for i, line in enumerate(lines) if 'zephyr_lifecycle isolated ' in line)
        duplicate = lines[:at] + [lines[at]] + lines[at:]
        self.assertEqual(analyze('\n'.join(duplicate), m)['status'], 'fail')
        missing = [line for line in lines if 'zephyr_lifecycle reset ' not in line]
        self.assertEqual(analyze('\n'.join(missing), m)['status'], 'fail')
        missing_sample = [line for line in lines if 'sample id=600 ' not in line]
        self.assertEqual(analyze('\n'.join(missing_sample), m)['status'], 'fail')

    def test_manifest_and_analyzer_separation(self):
        for case in (1, 2):
            m = manifest(case)
            validate_manifest(m, restart=True, isolation=True)
            self.assertEqual(restart_analyze('', m)['status'], 'fail')
            self.assertEqual(message_analyze('', m)['status'], 'fail')
            for field, value in [('fault_case', 3-case), ('heartbeat_timeout_ms', 999),
                                 ('injection_stage', 5), ('reset_sampler', 0)]:
                bad = copy.deepcopy(m)
                bad[field] = value
                self.assertEqual(analyze(fixture(case), bad)['status'], 'fail')
        self.assertEqual(analyze('', restart_manifest())['status'], 'fail')
