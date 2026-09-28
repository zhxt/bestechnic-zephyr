#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Require real isolation, one new session, restored traffic and 600s BTH health."""
import argparse
import json
from pathlib import Path
import analyze_boot_profile as profile
from analyze_dual_isolation import Isolation
from analyze_dual_restart import PREFIX, Restart, RESET_FIELDS
from validation_profiles import validate_manifest, layered
import analyze_observation as observation
from analyze_lifecycle_contract import LOG_MODULE, LOG_NAMESPACE, LOG_CONTRACT, FAULT_REASONS


class Recovery:
    @staticmethod
    def analyze(text, manifest):
        errors, missing, initial, continuation, records = [], [], [], [], []
        observing = layered(manifest)
        phase = 0
        previous_initial = previous_continuation = None
        begin_time = held_time = sample_time = last_time = None
        rebuilt = False
        failure_rows = []
        fail_step = manifest.get('recovery_fail_step')
        samples = 0
        mapping = None
        case = manifest.get('fault_case')
        reason = FAULT_REASONS.get(case)
        expected_meta = dict(recovery_version=1, recovery_limit=1, injection_session=1)
        if (any(type(manifest.get(k)) is not int or manifest[k] != v
               for k, v in expected_meta.items()) or type(fail_step) is not int or fail_step not in (0,1,3,5)):
            errors.append('manifest recovery contract')
        lines = text.splitlines()
        for index, line in enumerate(lines):
            if phase == 3 and 'zephyr_' not in line:
                continue
            match = PREFIX.fullmatch(line)
            if not match:
                if index == len(lines)-1 and not line.endswith(' !') and phase != 3:
                    missing.append('truncated last record')
                else:
                    errors.append('malformed prefix/record')
                continue
            ts, level, module, context, namespace, body = match.groups()
            if phase == 3:
                errors.append('record after result')
            if ts != 'NA':
                now = int(ts)
                if now > 0xffffffffffffffff or (last_time is not None and now < last_time):
                    errors.append('timestamp order')
                last_time = now
            else:
                now = None
            if namespace == 'zephyr_bth':
                if phase:
                    errors.append('boot after recovery')
                initial.append(line)
                continue
            if (namespace, module, context, level) != (LOG_NAMESPACE, LOG_MODULE, 'MAIN', 'I') or now is None:
                errors.append('recovery prefix/runtime error')
            kind, *words = body.split()
            try:
                pairs = [word.split('=', 1) for word in words]
                d = {k: int(v, 0) for k, v in pairs}
                if len(d) != len(pairs) or any(not 0 <= v <= 0xffffffffffffffff for v in d.values()):
                    raise ValueError()
            except ValueError:
                errors.append('invalid fields')
                continue
            if d.get('rc', 0) or d.get('error', 0):
                errors.append('runtime error')
            records.append(dict(kind=kind, time=now, fields=d))
            if kind == 'sample':
                if phase >= 2:
                    errors.append('sample after final hold')
                initial.append(line)
                samples += 1
                sample_time = now
            elif kind == 'recovery_begin':
                if (phase != 0 or previous_initial != 'hardware'
                        or d != dict(old_session=1, new_session=2, limit=1, rc=0)):
                    errors.append('recovery entry/order')
                phase = 1
                begin_time = now
            elif kind == 'worker_rebuilt':
                if (phase != 1 or rebuilt or previous_continuation != ('event', 2)
                        or d != dict(session=2, rc=0)):
                    errors.append('worker rebuild identity/order')
                rebuilt = True
            elif kind == 'held':
                expected_previous=('retry_blocked',None) if fail_step else ('session',None)
                if (phase != 1 or previous_continuation != expected_previous
                        or set(d) != set('session reset_held local_irq peer_irq rc'.split())
                        or d.get('session') != 2 or d.get('reset_held') != 1
                        or (d.get('local_irq', 0) | d.get('peer_irq', 0)) & 0xa
                        or samples != 601 or now is None or sample_time is None or now < sample_time):
                    errors.append('final reset/channel evidence')
                phase = 2
                held_time = now
            elif kind in ('recovery_result','recovery_failure_result'):
                if (phase != 2 or (not rebuilt and fail_step!=1)
                        or kind != ('recovery_failure_result' if fail_step else 'recovery_result') or d != {
                        'pass': 1, 'session': 2, 'reason': reason, 'samples': 601,
                        'releases': 1 if fail_step in (1,3) else 2, 'attempts': 1,
                        'recoveries': 0 if fail_step else 1, 'rc': 0}
                        or now is None or held_time is None or now < held_time):
                    errors.append('final recovery result/order')
                phase = 3
            elif phase == 0:
                initial.append(line)
                previous_initial = kind
                if kind == 'hardware':
                    mapping = (d.get('ram_sel0'), d.get('ram_sel1'))
            elif phase == 1:
                if kind == 'event' and d.get('step') == 3 and not rebuilt:
                    errors.append('load before worker rebuild')
                if (now is None or begin_time is None or not 0 <= now-begin_time <= 45000):
                    errors.append('recovery deadline')
                failure_record=(fail_step and (failure_rows or kind in ('recovery_injected','hold_confirmed','replacement_timeout')
                                or (kind=='reset' and d.get('op')==4)))
                if failure_record:
                    failure_rows.append(dict(kind=kind,time=now,fields=d))
                else:
                    continuation.append(line)
                previous_continuation = (kind, d.get('step'))
            else:
                errors.append('unexpected recovery record')
        expected_last = ('retry_blocked', None) if fail_step else ('session', None)
        complete = (phase == 1 and previous_continuation == expected_last) if observing else phase == 3
        if not complete:
            missing.append('recovery incomplete')
        if not rebuilt and fail_step!=1:
            missing.append('worker rebuild missing')
        # Both validators consume the original evidence, without synthesizing
        # successful boot, isolation or traffic records for either session.
        isolated = Isolation.analyze('\n'.join(initial), manifest, terminal=False)['sessions'][0]
        if fail_step==1:
            restarted=dict(errors=['unexpected operation before rejected REPARK'] if continuation else [],missing=[])
        else:
            restarted = Restart.analyze('\n'.join(continuation), manifest,
                continuation=True, ram_mapping=mapping,
                end_step={3:2,5:4}.get(fail_step))['sessions'][0]
        for label, result in [('isolation', isolated), ('new session', restarted)]:
            errors.extend(label + ': ' + item for item in result['errors'])
            missing.extend(label + ': ' + item for item in result['missing'])
        if fail_step:
            expected_order=(['recovery_injected'] if fail_step in (1,3) else ['replacement_timeout'])+[
                'hold_confirmed' if fail_step==1 else 'reset','recovery_failed','retry_blocked']
            order=[r['kind'] for r in failure_rows]
            if order!=expected_order[:len(order)]:
                errors.append('recovery failure containment order')
            if len(order)!=len(expected_order):
                missing.append('recovery failure containment incomplete')
            failed_time=None
            for row in failure_rows:
                kind,d,now=row['kind'],row['fields'],row['time']
                operation_rc={1:12,3:13,5:16}[fail_step]
                if kind=='recovery_injected':
                    if d!=dict(session=2,step=fail_step,operation_rc=operation_rc,rc=0):
                        errors.append('failure injection identity')
                elif kind=='replacement_timeout':
                    if d!=dict(session=2,reason=1,readable=1,beat=0,trace_stage=6,injection=1,rc=0):
                        errors.append('replacement READY timeout evidence')
                elif kind=='hold_confirmed':
                    if d!=dict(session=2,reset_held=1,rc=0):
                        errors.append('already held evidence')
                elif kind=='reset':
                    if set(d)!=RESET_FIELDS:
                        errors.append('failure reset fields')
                        continue
                    if (d['round']!=1 or d['session']!=2 or d['op']!=4 or d['version']!=1
                            or any(d[x] for x in ('reason','service_rc','diag_error','primask','rc'))
                            or d['sampler']!=manifest['reset_sampler'] or d['reset_after']&16
                            or (fail_step==5 and not d['reset_before']&16)
                            or d['timer_ctrl']&0x82!=0x82 or not 1<=d['polls']<=1024
                            or d['samples']!=d['polls']+1
                            or not d['samples']<=d['attempts']<=32*d['samples']
                            or not 1<=d['max_attempts']<=min(32,d['attempts'])
                            or not 0<=d['last_a']-d['last_b']<=20
                            or d['max_delta']<d['last_a']-d['last_b']
                            or d['elapsed']!=(d['raw_end']-d['raw_start'])&0xffffffff
                            or d['elapsed']>=60000):
                        errors.append('failure reset sampling/readback')
                elif kind=='recovery_failed':
                    if d!=dict(session=2,step=fail_step,operation_rc=operation_rc,
                               local_idle=1,reset_held=1,channel_clean=1,containment_rc=0,rc=0):
                        errors.append('recovery failure containment')
                    failed_time=now
                    if fail_step==5:
                        events=[r for r in records if r['kind']=='event' and r['fields'].get('session')==2
                                and r['fields'].get('step')==4]
                        if len(events)!=1 or not 5000<=now-events[0]['time']<=5150:
                            errors.append('replacement READY failure deadline')
                elif kind=='retry_blocked':
                    if (d!=dict(session=2,attempts=1,releases=1 if fail_step in (1,3) else 2,blocked=1,rc=0)
                            or failed_time is None or not 0<=now-failed_time<=100):
                        errors.append('recovery retry limit')
        status = 'fail' if errors else 'incomplete' if missing else 'pass'
        session = dict(status=status, errors=errors, missing=missing,
                       records=records, samples=isolated['samples'])
        return dict(status=status, session_count=1, sessions=[session])


def analyze(text, manifest, scope='long'):
    try:
        scenario = validate_manifest(manifest, restart=True, isolation=True, recovery=True)
        if (manifest.get('fault_case') != scenario.fault_case
                or manifest.get('recovery_fail_step') != scenario.recovery_fail_step):
            raise ValueError('fault case/profile mismatch')
    except ValueError as error:
        return dict(status='fail', session_count=0, sessions=[], errors=[str(error)])
    return observation.run(profile, text, manifest, Recovery.analyze, scope)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--scope', choices=observation.NAMES, default='long')
    args = parser.parse_args()
    result = analyze(args.log.read_bytes().decode('latin1'), json.loads(args.manifest.read_text()), args.scope)
    content = json.dumps(result, indent=2) + '\n'
    if args.output:
        args.output.write_text(content)
    print(content, end='')
    return {'pass': 0, 'fail': 1, 'incomplete': 2}[result['status']]


if __name__ == '__main__':
    raise SystemExit(main())
