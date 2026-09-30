# SPDX-License-Identifier: Apache-2.0
"""Require real GPIO ISR events, stable key cycles and retained IRQ routing."""
import re
from validation_profiles import get_profile

KEYS = 0x30000
ROW = re.compile(r'(\d+)/([IE])/BTH/GPIO/MAIN \| zephyr_gpio_irq (\w+) (.+) !')
FIELDS = {
    'begin': 'stage version mode target pins irq events0 events1 rc',
    'cycle': 'stage pin count mode evidence ms rc',
    'snapshot': 'stage checkpoint mode enabled mask edge rising route wake irq events0 events1 spurious max_cycles overflow fault rc',
    'stage_result': 'stage pass mode count0 count1 target irq events0 events1 ms rc',
    'result': 'stage version pass rc',
    'waiting': 'stage count0 count1 target ms',
    'failure': 'stage rc api_error',
}


def evidence(text, manifest):
    scenario = get_profile(manifest['validation_profile'])
    expected = [10, 11] if scenario.m55_restart else [1, 2, 3, 4]
    clean, records, errors, missing = [], [], [], []
    active = None
    completed = []
    baseline = None
    snapshots = set()
    final = False
    pause = 0
    previous_time = None
    markers = {}
    checkpoints = {}
    samples = {}
    final_index = None
    for index, line in enumerate(text.splitlines()):
        sample = re.search(r'zephyr_(?:lifecycle|dual) sample id=(\d+) ', line)
        if sample:
            samples[int(sample[1])] = index
        if 'zephyr_lifecycle ready round=0 ' in line:
            markers['ready'] = index
        if 'zephyr_lifecycle detected ' in line or 'zephyr_lifecycle endpoint round=0 ' in line:
            markers.setdefault('traffic', index)
        if 'zephyr_lifecycle session ' in line:
            markers['held'] = index
        if 'zephyr_gpio_irq' not in line:
            clean.append(line)
            continue
        match = ROW.fullmatch(line)
        if not match:
            if not line.endswith(' !'):
                missing.append('truncated GPIO IRQ record')
            else:
                errors.append('malformed GPIO IRQ record')
            continue
        time, level, kind, body = match.groups()
        time = int(time)
        if previous_time is not None and time < previous_time:
            errors.append('GPIO IRQ timestamp order')
        previous_time = time
        if kind == 'diagnostic':
            errors.append('GPIO IRQ hardware failure diagnostic')
            continue
        if kind == 'prompt':
            prompt = re.fullmatch(r'stage=(\d+) release_both_then_press_and_release_each_key count=(\d+)', body)
            if not prompt or active is None or (int(prompt[1]), int(prompt[2])) != (active['stage'], active['target']):
                errors.append('GPIO IRQ prompt identity')
            continue
        try:
            pairs = [word.split('=', 1) for word in body.split()]
            d = {k: int(v, 0) for k, v in pairs}
            if (kind not in FIELDS or set(d) != set(FIELDS[kind].split()) or len(d) != len(pairs)
                    or any(not 0 <= v <= 0xffffffff for v in d.values())):
                raise ValueError()
        except (ValueError, TypeError):
            errors.append('GPIO IRQ fields')
            continue
        row = dict(index=index, time=time, kind=kind, fields=d)
        records.append(row)
        if level != 'I' or d.get('rc') or kind == 'failure':
            errors.append('GPIO IRQ runtime failure')
        if kind == 'begin':
            wanted = expected[len(completed)] if len(completed) < len(expected) else None
            if active is not None or final or d['stage'] != wanted:
                errors.append('GPIO IRQ stage order')
            mode = 2 if wanted == 2 else 0 if wanted == 3 else 1
            target = 1 if wanted in (3, 4) else 10
            if (d['version'] != 1 or d['mode'] != mode or d['pins'] != KEYS or d['target'] != target):
                errors.append('GPIO IRQ stage contract')
            active = dict(d, start=time, index=index, counts=[0, 0], last_ms=[None, None])
            snapshots = set()
            if wanted == 10 and not markers.get('ready', index) < index:
                errors.append('GPIO IRQ pre-stage before READY')
            if wanted == 11 and not markers.get('held', index) < index:
                errors.append('GPIO IRQ post-stage before held peer')
            continue
        if kind == 'snapshot':
            if d['checkpoint'] >= 100:
                if d['checkpoint'] in checkpoints:
                    errors.append('duplicate GPIO IRQ checkpoint')
                checkpoints[d['checkpoint']] = index
            mode = 2 if d['stage'] == 2 else 0 if d['stage'] == 3 else 1
            enabled = KEYS if mode else 0
            if (d['mode'] != mode or d['enabled'] & KEYS != enabled or d['route'] != enabled
                    or d['mask'] & KEYS != (0 if mode else KEYS) or d['edge'] & KEYS != KEYS
                    or d['rising'] & KEYS != (KEYS if mode in (0, 2) else 0)
                    or not d['wake'] & 1 or d['overflow'] or d['fault']):
                errors.append('GPIO IRQ register/error state')
            if baseline is not None:
                if any((d[k] ^ baseline[k]) & ~KEYS for k in ('enabled', 'mask', 'edge', 'rising', 'route')) or d['wake'] != baseline['wake']:
                    errors.append('GPIO IRQ changed foreign state')
                if any(d[k] < baseline[k] for k in ('irq', 'events0', 'events1', 'spurious', 'max_cycles')):
                    errors.append('GPIO IRQ counters regressed')
            baseline = d
            if d['checkpoint'] in (0, 1):
                if not active or d['stage'] != active['stage'] or d['checkpoint'] in snapshots:
                    errors.append('GPIO IRQ snapshot order')
                snapshots.add(d['checkpoint'])
            elif d['checkpoint'] >= 1000:
                if not final or d['stage'] != expected[-1]:
                    errors.append('GPIO IRQ observation before result')
            elif not scenario.m55_restart or not 100 <= d['checkpoint'] <= 121:
                errors.append('GPIO IRQ checkpoint identity')
            continue
        if kind == 'result':
            if final or active is not None or completed != expected or d != dict(stage=expected[-1], version=1, **{'pass': 1}, rc=0):
                errors.append('GPIO IRQ final coverage/order')
            final = True
            final_index = index
            continue
        if active is None or d['stage'] != active['stage']:
            errors.append('GPIO IRQ event outside stage')
            continue
        if not 0 <= d.get('ms', 0) <= 180100 or abs(time-active['start']-d.get('ms', 0)) > 100:
            errors.append('GPIO IRQ stage time/deadline')
        if kind == 'cycle':
            pin = d['pin'] - 16
            if pin not in (0, 1):
                errors.append('GPIO IRQ pin grant')
                continue
            if (d['count'] != active['counts'][pin]+1 or d['mode'] != active['mode']
                    or bool(d['evidence']) != bool(active['mode']) or d['ms'] < 150
                    or (active['last_ms'][pin] is not None and d['ms']-active['last_ms'][pin] < 100)):
                errors.append('GPIO IRQ cycle requires fresh ISR and stable levels')
            active['counts'][pin] = d['count']
            active['last_ms'][pin] = d['ms']
        elif kind == 'stage_result':
            if (d['pass'] != 1 or d['mode'] != active['mode'] or d['target'] != active['target']
                    or [d['count0'], d['count1']] != active['counts']
                    or min(active['counts']) < active['target'] or snapshots != {0, 1}):
                errors.append('GPIO IRQ stage coverage')
            for key in ('events0', 'events1', 'irq'):
                if (d[key] < active['target'] if active['mode'] else d[key] != 0):
                    errors.append('GPIO IRQ missing ISR or masked interrupt')
                if baseline is None or d[key] != baseline[key]-active[key]:
                    errors.append('GPIO IRQ raw event accounting')
            if active['stage'] == 10:
                pause = time-active['start']
                markers['pre_end'] = index
            completed.append(active['stage'])
            active = None
        elif kind == 'waiting':
            if d['target'] != active['target'] or [d['count0'], d['count1']] != active['counts']:
                errors.append('GPIO IRQ waiting counters')
    if scenario.m55_restart and 'pre_end' in markers and not markers['pre_end'] < markers.get('traffic', -1):
        errors.append('GPIO IRQ traffic started before pre-stage completed')
    if final:
        wanted = {1000+i for i, index in samples.items() if index > final_index}
        if scenario.m55_restart:
            wanted |= {102, 103} if scenario.recovery else set(range(100, 122))
        if set(checkpoints) != wanted:
            missing.append('GPIO IRQ lifecycle/observation checkpoints')
        for point, index in checkpoints.items():
            if point >= 1000 and not samples.get(point-1000, index) < index:
                errors.append('GPIO IRQ checkpoint before health sample')
    if not final or completed != expected:
        missing.append('GPIO IRQ interactive stages/result')
    service = manifest.get('gpio_irq_service', {})
    if any(type(service.get(k)) is not type(v) or service[k] != v for k, v in
           dict(abi=5, capabilities=64, irq=44, priority=3, pins=KEYS, request_bytes=96, snapshot_bytes=64).items()):
        errors.append('GPIO IRQ manifest contract')
    return '\n'.join(clean)+'\n', records, errors, missing, pause


def run(text, manifest, core):
    if not get_profile(manifest['validation_profile']).gpio_irq:
        return core(text, manifest)
    clean, rows, errors, missing, pause = evidence(text, manifest)
    # This value is derived from reviewed interactive records, never trusted
    # from manifest input. Only the first session's total duration is extended;
    # traffic/READY/reset/QUIESCE/progress budgets stay unchanged.
    result = core(clean, dict(manifest, _gpio_irq_pause_ms=pause))
    if not result.get('sessions'):
        result.setdefault('errors', []).extend(errors)
        result['status'] = 'fail' if result['errors'] else 'incomplete'
        return result
    s = result['sessions'][0]
    s['errors'] += errors
    s['missing'] += missing
    s['gpio_irq_records'] = rows
    s['status'] = 'fail' if s['errors'] else 'incomplete' if s['missing'] else 'pass'
    result['status'] = s['status']
    return result
