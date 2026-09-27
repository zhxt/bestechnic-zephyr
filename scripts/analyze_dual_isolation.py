#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Accept injected M55 faults only with containment and 600s BTH liveness."""
import argparse
import json
from pathlib import Path
import analyze_boot_profile as profile
from analyze_dual_boot import prefix_contract
from analyze_dual_restart import PREFIX, RESET_FIELDS, RESET_DIAGNOSTIC, LIFECYCLE
from validation_profiles import validate_manifest

FIELDS = {
    'isolation_begin': 'version layout build m55_build pair fault_case ready_ms heartbeat_ms duration rc',
    'event': 'round session step rc elapsed',
    'ready': 'round session peer_ms beat stack elapsed rc',
    'detected': 'session reason age beat trace_stage injection elapsed rc',
    'isolated': 'session local_idle reset_held channel_clean failed_step service_rc rc',
    'hardware': 'round session phase reset_clr ram_sel0 ram_sel1 core_vtor rc',
    'held': 'session reset_held local_irq peer_irq rc',
    'isolation_result': 'pass session reason samples releases recoveries rc',
    'sample': 'id ms ticks timer stack guards rc',
}


class Isolation:
    @staticmethod
    def analyze(text, m, *, terminal=True):
        errors, missing, boot, rows, samples = [], [], [], [], []
        case = m.get('fault_case')
        expected_boot = [
            ('begin', dict(version=1, test=8, build=int(m['build'], 0))),
            ('stage', dict(stage='adapter_ready')),
            ('adapter', dict(cpuid=0x630f1321, ipsr=0, control=0)),
            ('image', dict(layout=0x50001, verified=1)),
            ('uart', dict(ibrd=1, fbrd=19)),
            ('state', dict(cache=0, mpu=0, systick=0)),
            *[('stage', dict(stage=x)) for x in ('handoff', 'reset', 'early', 'main')],
        ]
        fixed = dict(isolation_version=1, ready_timeout_ms=5000,
                     heartbeat_timeout_ms=1000, fault_poll_ms=20,
                     injection_stage=6, injection_beats=10, restart_rounds=1 if terminal else 2,
                     dual_layout='0x000a0004', duration_seconds=600)
        if (type(case) is not int or case not in (1, 2)
                or any(type(m.get(k)) is not type(v) or m[k] != v for k, v in fixed.items())
                or m.get('reset_diagnostic') != RESET_DIAGNOSTIC
                or m.get('lifecycle') != LIFECYCLE):
            errors.append('manifest isolation contract')
        sampler = m.get('reset_sampler', 0)
        if type(sampler) is not int or not sampler & 1 or not 0x00500000 <= sampler < 0x00510000:
            errors.append('sampler manifest')
        ended = False
        last_time = None
        lines = text.splitlines()
        for index, line in enumerate(lines):
            if ended and 'zephyr_' not in line:
                continue
            match = PREFIX.fullmatch(line)
            if not match:
                if index == len(lines) - 1 and not line.endswith(' !') and not ended:
                    missing.append('truncated last record')
                else:
                    errors.append('malformed prefix/record')
                continue
            ts, level, module, context, namespace, body = match.groups()
            kind, *words = body.split()
            if kind.startswith('stage='):
                words.insert(0, kind)
                kind = 'stage'
            try:
                pairs = [word.split('=', 1) for word in words]
                d = {k: (v if namespace == 'zephyr_bth' and k == 'stage' else int(v, 0))
                     for k, v in pairs}
                if len(d) != len(pairs) or any(
                        isinstance(v, int) and not 0 <= v <= 0xffffffffffffffff for v in d.values()):
                    raise ValueError()
            except ValueError:
                errors.append('invalid fields')
                continue
            if ended:
                errors.append('record after result')
            if ts != 'NA':
                now = int(ts)
                if now > 0xffffffffffffffff or (last_time is not None and now < last_time):
                    errors.append('timestamp order')
                last_time = now
            if level != 'I' or d.get('rc', 0) or d.get('error', 0):
                errors.append('runtime error')
            if namespace == 'zephyr_bth':
                if (rows or samples or len(boot) >= len(expected_boot)
                        or (kind, d) != expected_boot[len(boot)]):
                    errors.append('boot order/identity')
                if (module, context) != prefix_contract(namespace + ' ' + body + ' !'):
                    errors.append('boot prefix')
                if ts == 'NA' and kind not in ('begin', 'adapter') and d.get('stage') != 'adapter_ready':
                    errors.append('late NA')
                boot.append((kind, d))
                continue
            if namespace != 'zephyr_r1' or (module, context) != ('R1', 'MAIN') or ts == 'NA':
                errors.append('isolation prefix')
            wanted = RESET_FIELDS if kind == 'reset' else set(FIELDS.get(kind, '').split())
            if not wanted or set(d) != wanted:
                errors.append('isolation fields: ' + kind)
                continue
            record = dict(kind=kind, time=int(ts) if ts != 'NA' else 0, fields=d)
            if kind == 'sample':
                i = len(samples)
                if not rows or rows[0]['kind'] != 'isolation_begin':
                    errors.append('sample before begin')
                if (d['id'] != i or d['guards'] != 1 or d['stack'] < 128
                        or not i * 1000 <= d['ms'] <= i * 1000 + 100
                        or abs(d['timer'] - d['ms'] // 100) > 2
                        or abs(d['ticks'] - d['ms'] * 6000) > max(60000, d['ms'] * 60)):
                    errors.append('BTH sample health/time')
                if samples and (d['ticks'] <= samples[-1]['fields']['ticks']
                        or abs(record['time'] - samples[0]['time']
                               - d['ms'] + samples[0]['fields']['ms']) > max(10, d['ms'] // 100)):
                    errors.append('sample clock drift')
                samples.append(record)
            else:
                rows.append(record)
                if kind == 'isolation_result':
                    ended = True
        expected = [('isolation_begin', None), ('event', 1), ('event', 2),
                    ('event', 3), ('reset', 3), ('event', 4)]
        if case == 2:
            expected.append(('ready', None))
        expected += [('detected', None), ('reset', 4), ('isolated', None),
                     ('hardware', None)]
        if terminal:
            expected += [('held', None), ('isolation_result', None)]
        actual = [(r['kind'], r['fields'].get('step' if r['kind'] == 'event' else 'op'))
                  for r in rows]
        if actual != expected[:len(actual)]:
            errors.append('isolation order/missing/duplicate')
        if len(rows) != len(expected):
            missing.append('isolation incomplete')
        if boot != expected_boot:
            missing.append('boot incomplete')
        if len(samples) != 601:
            missing.append(f'samples {len(samples)}/601')
        origin = release = detected = None
        elapsed = 0
        for r in rows:
            k, d, now = r['kind'], r['fields'], r['time']
            if ('session' in d and d['session'] != 1) or ('round' in d and d['round'] != 0):
                errors.append('session identity')
            if k == 'isolation_begin':
                if d != dict(version=1, layout=0xa0004, build=int(m['build'], 0),
                             m55_build=int(m['m55_build'], 0), pair=m['message_pair'],
                             fault_case=case, ready_ms=5000, heartbeat_ms=1000, duration=600, rc=0):
                    errors.append('begin identity')
            elif k == 'event':
                if d['step'] == 1:
                    origin = now
                if d['step'] == 4:
                    release = now
                if (not elapsed <= d['elapsed'] <= 45000 or origin is None
                        or abs(now - origin - d['elapsed']) > 30):
                    errors.append('startup event deadline')
                elapsed = d['elapsed']
            elif k == 'ready':
                if (not d['beat'] or d['stack'] < 128 or d['peer_ms'] > 5000
                        or release is None or not 0 <= now - release < 5100):
                    errors.append('READY evidence')
            elif k == 'detected':
                detected = now
                limit = 5000 if case == 1 else 1000
                if (d['reason'] != case or d['injection'] != case or d['trace_stage'] != 6
                        or not limit <= d['age'] <= limit + 100
                        or (case == 1 and d['beat'] != 0)
                        or (case == 2 and d['beat'] != 10)
                        or origin is None or abs(now - origin - d['elapsed']) > 30
                        or release is None
                        or not (5000 if case == 1 else 1800) <= now - release <= (5200 if case == 1 else 2200)):
                    errors.append('fault detection/injection/deadline')
            elif k == 'reset':
                if (any(v > 0xffffffff for v in d.values()) or d['version'] != 1
                        or any(d[x] for x in ('reason', 'service_rc', 'diag_error', 'primask', 'rc'))
                        or d['sampler'] != sampler or not d['reset_before'] & 16 or d['reset_after'] & 16
                        or d['timer_ctrl'] & 0x82 != 0x82 or not 1 <= d['polls'] <= 1024
                        or d['samples'] != d['polls'] + 1
                        or not d['samples'] <= d['attempts'] <= 32 * d['samples']
                        or not 1 <= d['max_attempts'] <= min(32, d['attempts'])
                        or not 0 <= d['last_a'] - d['last_b'] <= 20
                        or d['max_delta'] < d['last_a'] - d['last_b']
                        or d['elapsed'] != (d['raw_end'] - d['raw_start']) & 0xffffffff
                        or d['elapsed'] >= 60000):
                    errors.append('reset sampling/readback')
            elif k == 'isolated':
                if (d != dict(session=1, local_idle=1, reset_held=1, channel_clean=1,
                              failed_step=0, service_rc=0, rc=0)
                        or detected is None or not 0 <= now - detected <= 100):
                    errors.append('containment failed/deadline')
            elif k == 'hardware':
                if d['phase'] != 4 or d['reset_clr'] & 16 or d['core_vtor'] != 0x200c0000:
                    errors.append('reset hardware evidence')
            elif k == 'held':
                if (d['reset_held'] != 1 or (d['local_irq'] | d['peer_irq']) & 0xa
                        or len(samples) != 601 or now < samples[-1]['time']):
                    errors.append('final reset/channel evidence')
            elif k == 'isolation_result':
                if (d != {'pass': 1, 'session': 1, 'reason': case,
                        'samples': 601, 'releases': 1, 'recoveries': 0, 'rc': 0}):
                    errors.append('final result')
                if missing or len(samples) != 601 or now < samples[-1]['time']:
                    errors.append('early final result')
        status = 'fail' if errors else 'incomplete' if missing else 'pass'
        session = dict(status=status, errors=errors, missing=missing, records=rows, samples=samples)
        return dict(status=status, session_count=1, sessions=[session])


def analyze(text, manifest):
    try:
        scenario = validate_manifest(manifest, restart=True, isolation=True)
        if manifest.get('fault_case') != scenario.fault_case:
            raise ValueError('fault case/profile mismatch')
    except ValueError as error:
        return dict(status='fail', session_count=0, sessions=[], errors=[str(error)])
    previous = profile.dual
    try:
        profile.dual = Isolation
        return profile.analyze(text, manifest)
    finally:
        profile.dual = previous


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('log', type=Path)
    ap.add_argument('--manifest', type=Path, required=True)
    ap.add_argument('--output', type=Path)
    args = ap.parse_args()
    result = analyze(args.log.read_bytes().decode('latin1'), json.loads(args.manifest.read_text()))
    text = json.dumps(result, indent=2) + '\n'
    if args.output:
        args.output.write_text(text)
    print(text, end='')
    return {'pass': 0, 'fail': 1, 'incomplete': 2}[result['status']]


if __name__ == '__main__':
    raise SystemExit(main())
