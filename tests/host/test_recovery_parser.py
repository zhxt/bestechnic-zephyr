# SPDX-License-Identifier: Apache-2.0
import copy
import unittest
from analyze_dual_recovery import analyze
from analyze_dual_isolation import analyze as isolation_analyze
from analyze_dual_restart import analyze as restart_analyze
from test_isolation_parser import manifest as isolation_manifest, fixture as isolation_fixture
from test_restart_parser import fixture as restart_fixture


def manifest(case=1):
    return dict(isolation_manifest(case), recovery_version=1, recovery_limit=1,
                injection_session=1, restart_rounds=2,
                validation_profile='m55-ready-recovery' if case == 1 else 'm55-heartbeat-recovery')


def fixture(case=1):
    original = isolation_fixture(case).splitlines()
    boot = [line for line in original if 'zephyr_bth ' in line or 'zephyr_bootprof ' in line]
    rows = [(int(line.split('/')[0]), line) for line in original
            if 'zephyr_r1 ' in line and ' held ' not in line and ' isolation_result ' not in line]
    def row(time, kind, **fields):
        rows.append((time, f'{time}/I/BTH/R1/MAIN | zephyr_r1 {kind} ' +
                     ' '.join(f'{k}={v}' for k, v in fields.items()) + ' !'))
    base = 8200 if case == 1 else 5100
    row(base-1, 'recovery_begin', old_session=1, new_session=2, limit=1, rc=0)
    for line in restart_fixture().splitlines():
        if 'zephyr_r1 ' in line and ('round=1 ' in line):
            time = int(line.split('/')[0])-7100+base
            rows.append((time, str(time) + '/' + line.split('/', 1)[1]))
    row(base+3, 'worker_rebuilt', session=2, rc=0)
    row(602001, 'held', session=2, reset_held=1, local_irq=0, peer_irq=81920, rc=0)
    row(602002, 'recovery_result', **dict({'pass': 1}, session=2, reason=case, samples=601,
                                        releases=2, attempts=1, recoveries=1, rc=0))
    return '\n'.join(boot + [line for _, line in sorted(rows, key=lambda r: r[0])]) + '\n'


class RecoveryParser(unittest.TestCase):
    def test_complete_partial_and_separate_boots(self):
        for case in (1, 2):
            text, m = fixture(case), manifest(case)
            result = analyze(text, m)
            self.assertEqual(result['status'], 'pass', result)
            partial = text[:text.index('20000/I/BTH/R1')]
            self.assertEqual(analyze(partial, m)['status'], 'incomplete')
            self.assertEqual(analyze(text + partial, m)['status'], 'incomplete')
            self.assertEqual(analyze(text[:-20], m)['status'], 'incomplete')
            self.assertEqual(analyze(text + text, m)['session_count'], 2)

    def test_recovery_must_have_new_session_and_real_traffic(self):
        for case in (1, 2):
            text, m = fixture(case), manifest(case)
            for old, new in [('local_idle=1', 'local_idle=0'),
                             ('restore_ok=1', 'restore_ok=0'), ('read1=537657353', 'read1=0'),
                             ('new_session=2', 'new_session=1'), ('session=2', 'session=1'),
                             ('attempts=1 recoveries=1', 'attempts=2 recoveries=1'),
                             ('releases=2', 'releases=3'), ('sent=1000', 'sent=999'),
                             ('acked=1000', 'acked=999'), ('handled=1000', 'handled=999'),
                             ('channel_clean=1', 'channel_clean=0'),
                             ('peer_irq=81920', 'peer_irq=81928'), ('guards=1', 'guards=0')]:
                with self.subTest(case=case, field=old):
                    self.assertIn(old, text)
                    self.assertEqual(analyze(text.replace(old, new, 1), m)['status'], 'fail')

    def test_missing_duplicate_reordered_and_failed_records(self):
        text, m = fixture(), manifest()
        for kind in ('recovery_begin', 'worker_rebuilt', 'repark', 'ready', 'endpoint', 'held'):
            line = next(line for line in text.splitlines() if 'zephyr_r1 '+kind+' ' in line)
            self.assertEqual(analyze(text.replace(line+'\n', ''), m)['status'], 'fail', kind)
            self.assertEqual(analyze(text.replace(line, line+'\n'+line), m)['status'], 'fail', kind)
        line = next(line for line in text.splitlines() if 'zephyr_r1 worker_rebuilt ' in line)
        self.assertEqual(analyze(text.replace(line, line.replace('rc=0', 'rc=44')), m)['status'], 'fail')
        # Old isolation success must never substitute for restored traffic.
        self.assertEqual(analyze(isolation_fixture(), m)['status'], 'fail')

    def test_each_missing_field_is_rejected(self):
        text, m = fixture(), manifest()
        for kind in ('recovery_begin', 'worker_rebuilt', 'repark', 'held', 'recovery_result'):
            line = next(line for line in text.splitlines() if 'zephyr_r1 '+kind+' ' in line)
            prefix, body = line.split(' | ', 1)
            parts = body.split()
            for i in range(2, len(parts)-1):
                broken = prefix+' | '+' '.join(parts[:i]+parts[i+1:])
                self.assertEqual(analyze(text.replace(line, broken, 1), m)['status'], 'fail')

    def test_manifest_and_analyzer_separation(self):
        m, text = manifest(), fixture()
        for key, value in [('recovery_limit', 2), ('injection_session', 2), ('restart_rounds', 1),
                           ('fault_case', 2), ('recovery_version', True)]:
            bad = copy.deepcopy(m)
            bad[key] = value
            self.assertEqual(analyze(text, bad)['status'], 'fail')
        self.assertEqual(isolation_analyze(text, m)['status'], 'fail')
        self.assertEqual(restart_analyze(text, m)['status'], 'fail')
        self.assertEqual(analyze(text, isolation_manifest())['status'], 'fail')
