#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Strict V06/V07a session validation; exit 0 pass, 1 fail, 2 incomplete.

The last boot determines the top-level status. Real cold power removal cannot
be inferred from a UART log. Each session remains separate in the report.
"""
import argparse
import json
import re
from pathlib import Path

STAGES = ['adapter_ready', 'handoff', 'reset', 'early', 'main']
SAMPLE_KEYS = set('id ms raw ticks ppm timer produced consumed errors timer_gap producer_gap '
    'consumer_gap rounds tx_bytes rx_bytes irq tx_irq rx_irq rt_irq uart_errors error_irq '
    'stack_main stack_producer stack_consumer guards rc'.split())
UART_KEYS = set('round tx rx wait_rc errors rc elapsed_ticks irq tx_irq rx_irq rt_irq error_irq '
                'source rsr dr mis entry_mis fr cr imsc'.split())
UART_V3_KEYS = set('pattern muted restored pre_fr pre_rsr pre_lcr pre_cr armed_fr armed_rsr '
    'armed_lcr armed_ifls armed_cr armed_imsc armed_ris armed_ovsampst discarded '
    'error_index error_lcr error_ifls error_ris rx_reads d0 d1 d2 d3 d4 d5 d6 d7'.split())

RECOVERY_KEYS = set('round mode wait_rc tx rx_reads wait_ticks elapsed_ticks muted restored '
    'errors source irq rc armed_fr armed_cr armed_imsc pending_fr pending_cr pending_imsc '
    'pending_rsr pending_ris clean_fr clean_cr clean_imsc clean_rsr clean_ris clean_lcr discarded'.split())


def check_session(records, manifest):
    errors, missing, stages, seen, samples = [], [], [], {}, []
    uart_rounds, recoveries = [], []
    log_version = int(manifest.get('log_version', 1))
    uart_keys = UART_KEYS | (UART_V3_KEYS if log_version >= 3 else set())
    if log_version not in (1, 2, 3, 4):
        errors.append('unsupported log version')
    result_seen = False
    for lineno, namespace, line in records:
        if not line.endswith(' !'):
            missing.append(f'line {lineno}: truncated record')
            continue
        try:
            words = line[:-2].split()
            kind = 'stage' if words[0].startswith('stage=') else words.pop(0)
            fields = {}
            for word in words:
                key, value = word.split('=', 1)
                if key in fields:
                    raise ValueError('duplicate field')
                fields[key] = value if key == 'stage' else int(value, 0)
        except (IndexError, ValueError):
            errors.append(f'line {lineno}: malformed record')
            continue
        if namespace == 'boot' and kind == 'stage':
            if stages != STAGES[:len(stages)] or len(stages) >= 5 or fields != {'stage': STAGES[len(stages)]}:
                errors.append(f'line {lineno}: out-of-order boot stage')
            stages.append(fields.get('stage'))
        elif namespace == 'kernel' and kind == 'sample':
            if result_seen or ('kernel', 'context') not in seen or stages != STAGES:
                errors.append(f'line {lineno}: sample outside running interval')
            if set(fields) != SAMPLE_KEYS or any(v < 0 for v in fields.values()):
                errors.append(f'line {lineno}: invalid sample fields')
            else:
                samples.append(fields)
        elif namespace == 'kernel' and kind == 'recovery':
            if log_version != 4 or result_seen or ('kernel', 'context') not in seen or stages != STAGES:
                errors.append(f'line {lineno}: recovery outside running interval/version')
            if set(fields) != RECOVERY_KEYS or any(v < 0 for k, v in fields.items() if k != 'wait_rc'):
                errors.append(f'line {lineno}: invalid recovery fields')
            else:
                if (not samples or samples[-1]['id'] != fields['round'] * 5 - 1 or
                        len(uart_rounds) != fields['round'] - 1):
                    errors.append(f'line {lineno}: recovery at wrong sample/order')
                recoveries.append(fields)
        elif namespace == 'kernel' and kind == 'uart':
            if log_version not in (2, 3, 4) or result_seen or ('kernel', 'context') not in seen or stages != STAGES:
                errors.append(f'line {lineno}: UART record outside running interval/version')
            if set(fields) != uart_keys or any(v < 0 for k, v in fields.items() if k != 'wait_rc'):
                errors.append(f'line {lineno}: invalid UART fields')
            else:
                if not samples or samples[-1]['id'] != fields['round'] * 5 - 1:
                    errors.append(f'line {lineno}: UART record at wrong sample')
                if log_version == 4 and (not recoveries or len(recoveries) != fields['round'] or
                        recoveries[-1]['round'] != fields['round']):
                    errors.append(f'line {lineno}: UART recovery evidence missing before transfer')
                uart_rounds.append(fields)
        else:
            key = namespace, kind
            allowed = {'boot': {'begin': 0, 'adapter': 1, 'image': 1, 'uart': 1, 'state': 1},
                       'kernel': {'begin': 5, 'context': 5, 'result': 5}}
            if kind not in allowed[namespace]:
                errors.append(f'line {lineno}: unexpected {namespace} {kind} (possible fault)')
            elif len(stages) != allowed[namespace][kind]:
                errors.append(f'line {lineno}: {kind} at wrong stage')
            if key in seen or result_seen:
                errors.append(f'line {lineno}: duplicate or late {kind}')
            seen[key] = fields
            if key == ('kernel', 'result'):
                result_seen = True
    duration = int(manifest['duration_seconds'])
    build = int(str(manifest['build']), 0)
    expected = {
        ('boot', 'begin'): {'version': 1, 'test': 6, 'build': build},
        ('boot', 'image'): {'layout': int(str(manifest['layout']), 0), 'verified': 1},
        ('boot', 'uart'): {'ibrd': 1, 'fbrd': 19},
        ('boot', 'state'): {'cache': 0, 'mpu': 0, 'systick': 0},
        ('kernel', 'begin'): {'version': log_version, 'test': 6, 'build': build, 'duration': duration,
            'cpu_hz': 24000000, 'timer_hz': 6000000, 'uart_hz': 24000000,
            'period_ms': 100, 'block_bytes': 256, 'heap_bytes': 0},
        ('kernel', 'result'): {'pass': 1, 'samples': duration + 1, 'rounds': duration // 5, 'rc': 0},
    }
    if log_version >= 3:
        expected[('kernel', 'begin')].update(
            pattern_offset=int(manifest['pattern_offset']), tx_isolated=1)
    if log_version == 4:
        expected[('kernel', 'begin')]['fault_mode'] = 1
        if manifest.get('fault_mode') != 1 or duration != 600 or manifest.get('pattern_offset') != 0:
            errors.append('invalid V07a manifest scenario')
    for key, fields in expected.items():
        if key not in seen:
            missing.append('/'.join(key))
        elif seen[key] != fields:
            errors.append(f'{key} mismatch: {seen[key]}')
    adapter, context = seen.get(('boot', 'adapter')), seen.get(('kernel', 'context'))
    if adapter is None or context is None:
        missing.append('CPU context')
    else:
        if adapter != {'cpuid': 0x630f1321, 'ipsr': 0, 'control': 0}:
            errors.append('invalid adapter context')
        fixed = dict(cpuid=0x630f1321, vtor=0x00510000, control=2, ipsr=0, primask=0,
                     basepri=0, faultmask=0, data=1, bss=1, uart_ready=1)
        if set(context) != set(fixed) | {'msp', 'psp'} or any(context.get(k) != v for k, v in fixed.items()):
            errors.append('invalid Zephyr context')
        if any(not 0x20540000 < context.get(k, 0) <= 0x2055c000 or context[k] % 8 for k in ('msp', 'psp')):
            errors.append('invalid stack pointer')
    if stages != STAGES:
        missing.append('complete boot stages')
    ids = [s['id'] for s in samples]
    if ids != list(range(len(ids))) or any(i > duration for i in ids):
        errors.append('missing/duplicate/out-of-order/out-of-range sample')
    if len(ids) != duration + 1:
        missing.append(f'samples: {len(ids)}/{duration + 1}')
    if log_version >= 2:
        if [r['round'] for r in uart_rounds] != list(range(1, len(uart_rounds) + 1)):
            errors.append('missing/duplicate/out-of-order UART round')
        if len(uart_rounds) != duration // 5:
            missing.append(f'UART diagnostics: {len(uart_rounds)}/{duration // 5}')
        for r in uart_rounds:
            if r['round'] > duration // 5 or r['tx'] != 256 or r['rx'] != 256 or \
                    any(r[k] for k in ('wait_rc', 'errors', 'rc', 'error_irq', 'source',
                                      'rsr', 'dr', 'mis', 'entry_mis', 'fr', 'cr', 'imsc')) or \
                    not 0 < r['elapsed_ticks'] < 3000000 or not r['tx_irq'] or \
                    not r['rx_irq'] + r['rt_irq'] or r['irq'] < max(r['tx_irq'], r['rx_irq'], r['rt_irq']):
                errors.append(f"UART round {r['round']}: transfer/error/IRQ check failed")
            if log_version >= 3:
                pattern = r['round'] - 1 + int(manifest['pattern_offset'])
                good = (r['pattern'] == pattern and r['muted'] == r['restored'] == 1
                    and r['pre_lcr'] == 0x70 and r['pre_cr'] == 0x301 and not r['pre_fr'] & 8
                    and r['armed_fr'] & 0xf8 == 0x90 and r['armed_lcr'] == 0x70
                    and r['armed_cr'] == 0x381 and r['armed_ovsampst'] == 8
                    and not r['armed_ris'] & 0x780 and 0 <= r['discarded'] <= 32
                    and r['rx_reads'] == 256
                    and not any(r[k] for k in ('armed_rsr', 'armed_ifls', 'armed_imsc',
                        'error_index', 'error_lcr', 'error_ifls', 'error_ris'))
                    and all(r[f'd{i}'] == ((i * 73 + pattern * 31) ^ (i >> 2)) & 255
                            for i in range(8)))
                if not good:
                    errors.append(f"UART round {r['round']}: isolation/setup/RX trace check failed")
    if log_version == 4:
        if [r['round'] for r in recoveries] != list(range(1, len(recoveries) + 1)):
            errors.append('missing/duplicate/out-of-order recovery')
        if len(recoveries) != duration // 5:
            missing.append(f'recovery diagnostics: {len(recoveries)}/{duration // 5}')
        for r in recoveries:
            if not (1 <= r['round'] <= duration // 5 and r['mode'] == 1 and r['wait_rc'] == -11
                    and r['tx'] == 8 and r['muted'] == r['restored'] == 1
                    and 1194000 <= r['wait_ticks'] <= 1500000
                    and r['wait_ticks'] <= r['elapsed_ticks'] < 3000000
                    and r['armed_fr'] & 0xf8 == 0x90 and r['armed_cr'] == 0x381
                    and r['pending_fr'] & 0xf8 == 0x80 and r['pending_cr'] == 0x381
                    and r['pending_ris'] & 0x50 and not r['pending_ris'] & 0x780
                    and r['clean_fr'] & 0xf8 == 0x90 and r['clean_cr'] == 0x301
                    and r['clean_lcr'] == 0x70 and not r['clean_ris'] & 0x7d0
                    and 0 <= r['discarded'] <= 32
                    and not any(r[k] for k in ('rx_reads', 'errors', 'source', 'irq', 'rc',
                        'armed_imsc', 'pending_imsc', 'pending_rsr', 'clean_imsc', 'clean_rsr'))):
                errors.append(f"recovery {r['round']}: injection/timeout/cleanup check failed")
    wraps = 0
    for index, s in enumerate(samples):
        problems = []
        if not s['id'] * 1000 <= s['ms'] <= s['id'] * 1000 + 100:
            problems.append('sleep deadline')
        if not 0 <= s['raw'] <= 0xffffffff:
            problems.append('counter width')
        expected_ticks = s['ms'] * 6000
        ppm = abs(s['ticks'] - expected_ticks) * 1000000 // expected_ticks if expected_ticks else 0
        if s['ppm'] != ppm or (s['id'] and ppm > 10000):
            problems.append('timebase >1% or bad ppm')
        if s['id'] == 0 and s['ticks'] > 600000:
            problems.append('initial tick offset')
        if any(s[k] for k in ('errors', 'uart_errors', 'error_irq', 'rc')) or s['guards'] != 1:
            problems.append('error/guard')
        if abs(s['timer'] - s['ms'] // 100) > 2 or not 0 <= s['timer'] - s['produced'] <= 2 or \
                not 0 <= s['produced'] - s['consumed'] <= 2:
            problems.append('thread/timer progress')
        if s['id'] == duration and not s['timer'] == s['produced'] == s['consumed']:
            problems.append('final messages not drained')
        if any(s[k] >= 3000000 for k in ('timer_gap', 'producer_gap', 'consumer_gap')):
            problems.append('scheduling gap >=500ms')
        if any(s[k] < 128 for k in ('stack_main', 'stack_producer', 'stack_consumer')):
            problems.append('stack reserve')
        if s['rounds'] != s['id'] // 5 or s['tx_bytes'] != s['rounds'] * 256 or s['rx_bytes'] != s['tx_bytes']:
            problems.append('UART rounds/bytes')
        if s['tx_irq'] < s['rounds'] or s['rx_irq'] + s['rt_irq'] < s['rounds'] or \
                s['irq'] < max(s['tx_irq'], s['rx_irq'], s['rt_irq']):
            problems.append('missing hardware IRQ evidence')
        if index:
            prev = samples[index - 1]
            if s['ticks'] - prev['ticks'] != (s['raw'] - prev['raw']) & 0xffffffff:
                problems.append('counter wrap accumulation')
            wraps += s['raw'] < prev['raw']
            if any(s[k] < prev[k] for k in ('ms', 'ticks', 'timer', 'produced', 'consumed', 'rounds',
                    'tx_bytes', 'rx_bytes', 'irq', 'tx_irq', 'rx_irq', 'rt_irq',
                    'timer_gap', 'producer_gap', 'consumer_gap')):
                problems.append('counter regression')
            if s['id'] and any(s[k] <= prev[k] for k in ('timer', 'produced', 'consumed')):
                problems.append('stalled worker')
            if s['rounds'] > prev['rounds'] and (s['tx_irq'] <= prev['tx_irq'] or
                    s['rx_irq'] + s['rt_irq'] <= prev['rx_irq'] + prev['rt_irq']):
                problems.append('round without real UART interrupts')
            if log_version >= 2 and s['id'] % 5 == 0:
                diag = next((r for r in uart_rounds if r['round'] == s['id'] // 5), None)
                if diag is None:
                    missing.append(f"UART diagnostic before sample {s['id']}")
                elif any(s[k] - prev[k] != diag[k] for k in ('irq', 'tx_irq', 'rx_irq', 'rt_irq', 'error_irq')):
                    problems.append('UART diagnostic/cumulative IRQ mismatch')
        if problems:
            errors.append(f"sample {s['id']}: {', '.join(problems)}")
    return {'status': 'fail' if errors else 'incomplete' if missing else 'pass',
            'build': seen.get(('kernel', 'begin'), {}).get('build'), 'duration_seconds': duration,
            'samples': len(samples), 'last_sample': samples[-1] if samples else None,
            'timer_wraps': wraps, 'max_ppm': max((s['ppm'] for s in samples[1:]), default=None),
            'errors': errors, 'missing': missing, 'cold_boot': 'requires_operator_confirmation',
            'recovery_rounds': len(recoveries), 'last_recovery': recoveries[-1] if recoveries else None,
            'uart_diagnostic_rounds': len(uart_rounds), 'last_uart': uart_rounds[-1] if uart_rounds else None,
            'line_start': records[0][0] if records else None}


def analyze(lines, manifest):
    if isinstance(lines, str):
        lines = lines.splitlines()
    sessions, current = [], []
    text_only = int(manifest.get('log_version', 1)) >= 3
    kernel_started = False
    for lineno, raw in enumerate(lines, 1):
        match = re.search(r'zephyr_bth(_kernel)? (.*)', raw.rstrip('\r\n'))
        if not match:
            if text_only and kernel_started and raw.strip():
                # A live capture can end halfway through the namespace.
                if any(prefix.startswith(raw) for prefix in ('zephyr_bth ', 'zephyr_bth_kernel ')):
                    current.append((lineno, 'kernel', 'truncated'))
                else:
                    current.append((lineno, 'kernel', 'unexpected_text !'))
            continue
        namespace, record = ('kernel' if match[1] else 'boot'), match[2]
        if namespace == 'boot' and record.startswith('begin '):
            if current:
                sessions.append(check_session(current, manifest))
            current = []
            kernel_started = False
        if text_only and kernel_started and raw[:match.start()].strip():
            current.append((lineno, 'kernel', 'unexpected_text !'))
        if namespace == 'kernel' and record.startswith('begin '):
            kernel_started = True
        current.append((lineno, namespace, record))
        if namespace == 'kernel' and record.startswith('result '):
            kernel_started = False
    if current:
        sessions.append(check_session(current, manifest))
    return {'status': sessions[-1]['status'] if sessions else 'incomplete',
            'sessions': sessions, 'session_count': len(sessions)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('log', type=Path)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    manifest = json.loads(args.manifest.read_text())
    with args.log.open(errors='replace') as stream:
        report = analyze(stream, manifest)
    text = json.dumps(report, indent=2) + '\n'
    if args.output:
        args.output.write_text(text)
    print(text, end='')
    return {'pass': 0, 'fail': 1, 'incomplete': 2}[report['status']]


if __name__ == '__main__':
    raise SystemExit(main())
