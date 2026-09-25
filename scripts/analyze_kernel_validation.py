#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Validate a fixed run or the captured window of a continuous run (exit 0/1/2)."""
import argparse
import json
import re
from pathlib import Path


def analyze(text, min_seconds=600, expected_build=None):
    text = text.rsplit('CHIP=best1600', 1)[-1]
    begins = list(re.finditer(r'zephyr_kv begin (?:(?:seconds=(\d+) samples=(\d+))|'
                              r'(?:continuous=1)) abi=3 interval_ms=1000', text))
    if not begins:
        return dict(status='incomplete', errors=['No v3 validation begin in latest boot'])
    begin = begins[-1]
    continuous = begin[1] is None
    seconds, count = (None, None) if continuous else map(int, begin.groups())
    header_tail = text[begin.end():].split('\n', 1)[0].strip()
    if header_tail not in (('format=3 !',) if continuous else ('', 'format=2 !')):
        return dict(status='incomplete', errors=[], missing=['Unsupported or truncated log-format header'])
    log_format = 3 if continuous else (2 if header_tail else 1)
    text = text[begin.end():]
    rows, errors, missing = {}, [], []
    for line in text.splitlines():
        match = re.search(r'zephyr_kv (?:(clock|state|time|threads|fast|slow|queue|errors) )?sample=', line)
        if not match:
            continue
        group = match.group(1) or 'meta'
        if log_format >= 2 and not line.rstrip().endswith(' !'):
            missing.append(f'Truncated {group} record (missing end marker)')
            continue
        values = {k: int(v, 16 if v.startswith('0x') else 10)
                  for k, v in re.findall(r'(\w+)=(0x[0-9a-fA-F]+|\d+)', line[match.start():])}
        sample = values.pop('sample', None)
        if sample is None:
            missing.append(f'Missing sample number in {group}')
            continue
        if log_format >= 2:
            aliases = {
                'clock': {'hz': 'tick_hz'},
                'time': {'up': 'uptime'},
                'fast': {'n': 'fast', 'last': 'fast_last', 'gap': 'fast_max'},
                'slow': {'n': 'slow', 'last': 'slow_last', 'gap': 'slow_max'},
                'errors': {'err': 'errors', 'to': 'timeouts'},
            }.get(group, {})
            values = {aliases.get(k, k): v for k, v in values.items()}
        row = rows.setdefault(sample, {})
        if group in row:
            errors.append(f'Duplicate {group} at sample {sample}')
        row[group] = values
    if re.search(r'zephyr_kv (invalid|clock_mismatch)', text):
        errors.append('Snapshot invalid or SYS clock changed')
    if re.search(r'ASSERT|HardFault|Start pmu shutdown', text):
        errors.append('Fault or shutdown in observed session')
    complete = re.search(r'zephyr_kv complete samples=(\d+)' +
                         (r' !\s*$' if log_format >= 2 else r'\s*$'), text, re.MULTILINE)
    if continuous:
        if complete:
            errors.append('Unexpected completion marker in continuous mode')
        count = max(rows, default=-1) + 1
    else:
        if not complete:
            missing.append('No completion marker')
        elif int(complete[1]) != count:
            errors.append('Completion count differs from begin')
        if count != seconds + 1 or seconds < min_seconds:
            errors.append('Declared duration/count below requested validation scope')
    if len(rows) != count or (rows and (min(rows) != 0 or max(rows) != count-1)):
        missing.append('Missing or unexpected sample numbers')
    required = {
        'meta': {'bth_ms', 'build', 'stage', 'seq', 'publish'},
        'time': {'uptime', 'hz', 'cycles'},
        'threads': {'fast', 'fast_last', 'fast_max', 'slow', 'slow_last', 'slow_max'},
        'queue': {'tx', 'rx', 'ack', 'full', 'errors', 'timeouts'},
    }
    if log_format >= 2:
        required = {
            'meta': {'bth_ms', 'build', 'stage'},
            'state': {'seq', 'publish'},
            'time': {'uptime', 'hz', 'cycles'},
            'fast': {'fast', 'fast_last', 'fast_max'},
            'slow': {'slow', 'slow_last', 'slow_max'},
            'queue': {'tx', 'rx', 'ack'},
            'errors': {'full', 'errors', 'timeouts'},
        }
    if continuous:
        required['clock'] = {'ticks', 'tick_hz'}
    flat = []
    for index in sorted(rows):
        row = rows[index]
        if any(group not in row or not fields <= row[group].keys()
               for group, fields in required.items()):
            missing.append(f'Incomplete fields at sample {index}')
            continue
        values = {key: row[group][key] for group, fields in required.items() for key in fields}
        values['_sample'] = index
        flat.append(values)
        if values['stage'] != 2 or values['seq'] % 2 or values['hz'] != 24000000:
            errors.append(f'Invalid stage/sequence/frequency at sample {index}')
        if any(values[k] for k in ('full', 'errors', 'timeouts')):
            errors.append(f'Queue or acknowledgement error at sample {index}')
        if values['fast_max'] > 250 or values['slow_max'] > 1500:
            errors.append(f'Worker wake gap exceeded at sample {index}')
        if ((values['uptime'] - values['fast_last']) & 0xffffffff) > 500 or \
                ((values['uptime'] - values['slow_last']) & 0xffffffff) > 1500:
            errors.append(f'Worker state stale at sample {index}')
        def distance(a, b):
            return min((a-b) & 0xffffffff, (b-a) & 0xffffffff)
        if distance(values['tx'], values['rx']) > 32 or distance(values['rx'], values['ack']) > 32:
            errors.append(f'Queue backlog exceeded at sample {index}')
    metrics = {}
    if len(flat) >= 2:
        first, last = flat[0], flat[-1]
        builds = {r['build'] for r in flat}
        if len(builds) != 1 or (expected_build is not None and builds != {expected_build}):
            errors.append('Build ID changed or differs from requested build')
        monotonic = ('bth_ms', 'uptime', 'seq', 'publish', 'fast', 'slow', 'tx', 'rx', 'ack')
        totals = {k: 0 for k in monotonic if k != 'bth_ms'}
        wall_total = 0
        if continuous and any(r['tick_hz'] <= 0 for r in flat):
            errors.append('BTH tick frequency invalid')
        for a, b in zip(flat, flat[1:]):
            if continuous:
                # Samples are about 1s apart. Unwrap unsigned counters, reject
                # implausibly large steps instead of accepting reset as wrap.
                steps = {k: (b[k]-a[k]) & 0xffffffff for k in totals}
                for k, step in steps.items():
                    totals[k] += step
                ticks = (b['ticks']-a['ticks']) & 0xffffffff
                # SDK slow-timer calibration may update its reported Hz.
                # Convert each interval using the current calibration.
                wall_step = ticks * 1000 / b['tick_hz'] if b['tick_hz'] > 0 else 0
                wall_total += wall_step
                if any(step >= 0x80000000 for step in steps.values()):
                    errors.append('Counter/time regression or unexpected restart')
                if b['_sample'] == a['_sample'] + 1:
                    if steps['uptime'] > 2500 or any(steps[k] > 100 for k in totals if k != 'uptime'):
                        errors.append('Implausible counter step or M55 restart')
                    if abs(steps['uptime']-wall_step) > max(200, wall_step*.01):
                        errors.append('M55/BTH interval time-scale mismatch')
            else:
                if any(b[k] < a[k] for k in monotonic):
                    errors.append('Counter/time regression or unexpected restart')
                wall_step = b['bth_ms'] - a['bth_ms']
            if b['publish'] == a['publish'] or (b['_sample'] == a['_sample'] + 1 and
                                               wall_step > 2500):
                errors.append('Publisher stalled or excessive sample gap')
        wall = wall_total if continuous else last['bth_ms']-first['bth_ms']
        uptime = totals['uptime'] if continuous else last['uptime']-first['uptime']
        deltas = totals if continuous else {k: last[k]-first[k] for k in totals}
        metrics = dict(bth_delta_ms=wall, m55_delta_ms=uptime,
                       build_id=hex(first['build']), fast_delta=deltas['fast'],
                       slow_delta=deltas['slow'], ack_delta=deltas['ack'],
                       fast_max_gap_ms=max(r['fast_max'] for r in flat),
                       slow_max_gap_ms=max(r['slow_max'] for r in flat))
        if continuous:
            metrics['bth_tick_hz_changes'] = sum(a['tick_hz'] != b['tick_hz'] for a, b in zip(flat, flat[1:]))
        if wall <= 0 or abs(uptime-wall) > max(200, wall * .01):
            errors.append('M55/BTH time-scale mismatch (>1%, 200ms sampling allowance)')
        if not continuous and complete and not missing and wall < seconds * 1000 * .99:
            errors.append('Observed duration shorter than declared window')
        if continuous and wall < min_seconds * 1000:
            missing.append('Captured continuous window shorter than requested minimum')
        for key, period in [('fast', 100), ('slow', 700)]:
            expected = uptime / period
            if abs(deltas[key]-expected) > max(2, expected*.02):
                errors.append(f'{key} worker rate mismatch (>2%, 2 iterations allowance)')
        if deltas['ack'] <= 0:
            errors.append('No queue round-trip progress')
    else:
        missing.append('Insufficient complete snapshots')
    status = 'fail' if errors else ('incomplete' if missing else 'pass')
    return dict(status=status, log_format=log_format, seconds=seconds, continuous=continuous,
                scope='captured_window_only' if continuous else 'fixed_duration_run',
                complete_snapshots=len(flat),
                errors=list(dict.fromkeys(errors)), missing=missing, metrics=metrics)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--min-seconds', type=int, default=600)
    parser.add_argument('--expected-build', type=lambda s: int(s, 0))
    parser.add_argument('-o', '--output', type=Path)
    args = parser.parse_args()
    result = analyze(args.log.read_text(errors='replace'), args.min_seconds, args.expected_build)
    output = json.dumps(result, indent=2) + '\n'
    if args.output:
        args.output.write_text(output)
    print(output, end='')
    return {'pass': 0, 'fail': 1, 'incomplete': 2}[result['status']]


if __name__ == '__main__':
    raise SystemExit(main())
