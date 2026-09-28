# SPDX-License-Identifier: Apache-2.0
"""Synthetic protocol fixtures, including failures after a short success."""
import copy
import json
import math
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

import analyze_dual_isolation as isolation
import analyze_dual_message as message
import analyze_dual_recovery as recovery
import analyze_dual_restart as restart
from validation_profiles import get_profile, observation_contract
from test_message_parser import fixture as msg_fixture, manifest as msg_manifest
from test_restart_parser import fixture as restart_fixture, manifest as restart_manifest
from test_isolation_parser import fixture as iso_fixture, manifest as iso_manifest
from test_recovery_parser import fixture as rec_fixture, manifest as rec_manifest
from test_recovery_boundaries import fixture as boundary_fixture, manifest as boundary_manifest

ROOT = Path(__file__).resolve().parents[2]


def cases():
    yield restart, restart_manifest(), restart_fixture()
    for case in (1, 2):
        yield isolation, iso_manifest(case), iso_fixture(case)
        yield recovery, rec_manifest(case), rec_fixture(case)
    for case in (3, 4, 5, 6):
        yield recovery, boundary_manifest(case), boundary_fixture(case)
    for fail in (1, 3, 5):
        yield recovery, boundary_manifest(fail=fail), boundary_fixture(fail=fail)
    for name in ('ipc-sequential', 'ipc-fault-injection'):
        m = msg_manifest(name)
        yield message, m, msg_fixture(m)


def fixture(m, legacy):
    """Construct version-2 test input; these are not archived hardware logs."""
    m = copy.deepcopy(m)
    m.update(validation_schema=2, observation=observation_contract(m['validation_profile']))
    p = get_profile(m['validation_profile'])
    lines = [line for line in legacy.splitlines() if not any(token in line for token in
             ('zephyr_dual result ', 'zephyr_lifecycle held ', 'zephyr_lifecycle result ',
              'zephyr_lifecycle isolation_result ', 'zephyr_lifecycle recovery_result ',
              'zephyr_lifecycle recovery_failure_result '))]
    samples = [line for line in lines if ' sample id=' in line]
    origin = int(samples[0].split('/')[0])
    marker = ('zephyr_msg result ' if not p.m55_restart else
              'zephyr_lifecycle retry_blocked ' if p.recovery_fail_step else
              'zephyr_lifecycle session ' if not p.fault_case or p.recovery else
              'zephyr_lifecycle hardware ')
    terminal = [line for line in lines if marker in line][-1]
    terminal_time = int(terminal.split('/')[0])
    done = terminal_time + 1 - origin
    session = int(re.search(r'\bsession=(\d+)', terminal)[1])
    events = []

    def add(time, kind, **data):
        events.append(f'{time}/I/BTH/OBSERVE/MAIN | zephyr_observe {kind} ' +
                      ' '.join(f'{k}={v}' for k, v in data.items()) + ' !')
    data = dict(version=1, ms=done, session=session)
    if p.m55_restart:
        data.update(releases=(1 if p.recovery_fail_step in (1, 3) else 2) if p.recovery
                    else 1 if p.fault_case else 11, attempts=int(p.recovery),
                    recoveries=int(p.recovery and not p.recovery_fail_step))
    add(origin+done, 'functional', **data, rc=0)
    short_ms = math.ceil((done+60000)/1000)*1000
    long_ms = max(short_ms, 600000)
    for i in range(601, long_ms//1000+1):
        # Late lifecycle completion: retain actual sample count through both windows.
        lines.append(f'{origin+i*1000}/I/BTH/LIFECYCLE/MAIN | zephyr_lifecycle sample '
                     f'id={i} ms={i*1000} ticks={i*6000000} timer={i*10} stack=1600 guards=1 rc=0 !')
    for scope, ms in ((1, short_ms), (2, long_ms)):
        offset = 2 if scope == 2 and long_ms == short_ms else 0
        if p.m55_restart:
            add(origin+ms+offset+1, 'held', scope=scope, session=session, local_idle=1,
                reset_held=1, local_irq=0, peer_irq=81920, rc=0)
        else:
            add(origin+ms+offset+1, 'traffic', scope=scope, session=session, finished=1, live=1, rc=0)
        add(origin+ms+offset+2, 'result', **dict(version=1, scope=scope, **{'pass': 1}, session=session,
            functional_ms=done, ms=ms, samples=ms//1000+1, rc=0))
    boot = [line for line in lines if 'zephyr_bth ' in line or 'zephyr_bootprof ' in line]
    rest = [line for line in lines if line not in boot] + events
    text = '\n'.join(boot + sorted(rest, key=lambda line: int(line.split('/')[0])))+'\n'
    short_line = next(line for line in text.splitlines() if 'zephyr_observe result version=1 scope=1 ' in line)
    short = text[:text.index(short_line)+len(short_line)+1]
    return m, text, short


class ObservationParser(unittest.TestCase):
    def test_all_fourteen_scenarios_keep_short_and_long_separate(self):
        for parser, m, old in cases():
            with self.subTest(profile=m['validation_profile']):
                m, text, short = fixture(m, old)
                full = parser.analyze(text, m)
                self.assertEqual(full['status'], 'pass', full)
                r = parser.analyze(short, m, 'short')
                self.assertEqual(r['status'], 'pass', r)
                self.assertEqual(r['overall_status'], 'incomplete')
                self.assertFalse(r['complete'])
                self.assertEqual(parser.analyze(short, m)['status'], 'incomplete')
                function = short[:short.index('zephyr_observe functional')].rsplit('\n', 1)[0]+'\n'
                self.assertEqual(parser.analyze(function, m, 'short')['status'], 'incomplete')
                self.assertEqual(parser.analyze(short + function, m, 'short')['status'], 'incomplete')

    def test_no_early_success_or_missing_terminal_checks(self):
        for parser, old_m, old in cases():
            m, text, short = fixture(old_m, old)
            state = next(line for line in short.splitlines() if 'zephyr_observe held ' in line or 'zephyr_observe traffic ' in line)
            final = short.splitlines()[-1]
            for broken in (short.replace(state+'\n', ''), short.replace(state, state+'\n'+state),
                           short.replace('functional_ms=', 'unknown='),
                           short.replace('version=1 scope=1', 'version=1 scope=2'),
                           short.replace(final, final.replace('pass=1', 'pass=0')),
                           short.replace('reset_held=1', 'reset_held=0') if 'held ' in state
                           else short.replace('live=1', 'live=0')):
                with self.subTest(profile=m['validation_profile']):
                    self.assertEqual(parser.analyze(broken, m, 'short')['status'], 'fail')
            # Keep authentic-looking short records but remove one observed second.
            sample = next(line for line in short.splitlines() if ' sample id=60 ' in line)
            self.assertEqual(parser.analyze(short.replace(sample+'\n', ''), m, 'short')['status'], 'fail')

    def test_later_errors_invalidate_short_success(self):
        for parser, old_m, old in cases():
            m, text, short = fixture(old_m, old)
            sample = next(line for line in text.splitlines() if ' sample id=200 ' in line)
            bad = text.replace(sample, sample.replace('guards=1', 'guards=0'))
            r = parser.analyze(bad, m, 'short')
            self.assertEqual(r['status'], 'fail')
            self.assertEqual(r['sessions'][0]['scopes']['short']['status'], 'fail')
            self.assertEqual(parser.analyze(short+'900000/E/BTH/FAULT/FAULT | zephyr_bth stage=fatal !\n', m, 'short')['status'], 'fail')

    def test_fields_identity_budget_and_protocol_are_strict(self):
        m, text, short = fixture(rec_manifest(), rec_fixture())
        for kind in ('functional', 'held', 'result'):
            line = next(line for line in short.splitlines() if 'zephyr_observe '+kind+' ' in line)
            prefix, body = line.split(' | ')
            words = body.split()
            for i in range(2, len(words)-1):
                bad = prefix+' | '+' '.join(words[:i]+words[i+1:])
                self.assertEqual(recovery.analyze(short.replace(line, bad), m, 'short')['status'], 'fail', (kind, words[i]))
        for field, value in [('short_ms', 59000), ('version', True), ('long_ms', 60)]:
            bad = copy.deepcopy(m); bad['observation'][field] = value
            self.assertEqual(recovery.analyze(short, bad, 'short')['status'], 'fail')
        self.assertEqual(recovery.analyze(short.replace('releases=2', 'releases=3'), m, 'short')['status'], 'fail')
        self.assertEqual(recovery.analyze(short, dict(m, build='0x123'), 'short')['status'], 'fail')
        self.assertEqual(recovery.analyze(short[:-12], m, 'short')['status'], 'incomplete')

    def test_legacy_and_sustained_cannot_claim_short_scope(self):
        for name in ('ipc-sequential', 'ipc-backpressure', 'ipc-backpressure-1h'):
            m = msg_manifest(name); text = msg_fixture(m)
            self.assertEqual(message.analyze(text, m, 'short')['status'], 'fail')
            if 'backpressure' in name:
                m.update(validation_schema=2, observation=observation_contract(name))
                self.assertEqual(message.analyze(text, m)['status'], 'pass')
                self.assertEqual(message.analyze(text, m, 'short')['status'], 'fail')

    def test_late_function_requires_a_full_post_functional_window(self):
        lines = restart_fixture().splitlines()
        for i, line in enumerate(lines):
            if 'round=10 ' in line:
                time, rest = line.split('/', 1)
                lines[i] = str(int(time)+530000)+'/'+rest
        m, text, short = fixture(restart_manifest(), '\n'.join(lines)+'\n')
        self.assertEqual(restart.analyze(text, m)['status'], 'pass')
        self.assertEqual(restart.analyze(short, m, 'short')['status'], 'pass')
        early = '\n'.join(line for line in text.splitlines()
                          if not re.match(r'\d+/', line) or int(line.split('/')[0]) < 603000)+'\n'
        self.assertEqual(restart.analyze(early, m, 'short')['status'], 'incomplete')
        # Move both checkpoint prefixes and their elapsed field a full second early.
        # Samples are still complete, so the failure specifically includes window coverage.
        final = short.splitlines()[-1]
        ms = int(re.search(r' ms=(\d+)', final)[1])
        broken = short.replace(final, final.replace(f' ms={ms}', f' ms={ms-1000}'))
        self.assertEqual(restart.analyze(broken, m, 'short')['status'], 'fail')

    def test_cli_scope_exit_codes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            m, text, short = fixture(rec_manifest(), rec_fixture())
            (root/'layout.json').write_text(json.dumps(m)); (root/'serial.log').write_text(short)
            base = [sys.executable, '-B', str(ROOT/'scripts/analyze_dual_recovery.py'),
                    str(root/'serial.log'), '--manifest', str(root/'layout.json')]
            for args, code in [([], 2), (['--scope', 'short'], 0), (['--scope', 'invalid'], 2)]:
                result = subprocess.run(base+args, capture_output=True, text=True)
                self.assertEqual(result.returncode, code, result.stderr)
