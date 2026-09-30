# SPDX-License-Identifier: Apache-2.0
"""Standard GPIO output retention at M55 lifecycle boundaries."""
import re

from validation_profiles import get_profile

ROW = re.compile(r'(\d+)/([IE])/BTH/GPIO/MAIN \| zephyr_gpio_api (baseline|checkpoint|observe) (.+) !')
FIELDS = set('version round stage sample phase fault pins inputs directions outputs mux_led mux_keys '
             'pull_up pull_down clocks resets irq_enabled control transitions max_ticks mask_errors rc'.split())
MASKS = dict(mux_led=0xf0000, mux_keys=0, pull_up=0x1000, pull_down=0x1000,
             directions=0x1000, outputs=0x1000, clocks=0, resets=0, irq_enabled=0, control=0)


def run(text, manifest, core):
    scenario = get_profile(manifest['validation_profile'])
    if scenario.gpio_irq or not (scenario.gpio_api and scenario.m55_restart):
        return core(text, manifest)
    clean, rows, errors, missing = [], [], [], []
    last_time = None
    for index, line in enumerate(text.splitlines()):
        timed = re.match(r'(\d+)/', line)
        if timed:
            now = int(timed[1])
            if last_time is not None and now < last_time:
                errors.append('GPIO API timestamp order')
            last_time = now
        if 'zephyr_gpio_api' not in line:
            clean.append(line)
            continue
        match = ROW.fullmatch(line)
        if not match:
            errors.append('malformed GPIO API record')
            continue
        ts, level, kind, body = match.groups()
        try:
            pairs = [word.split('=', 1) for word in body.split()]
            data = {k: int(v, 0) for k, v in pairs}
            if (set(data) != FIELDS or len(data) != len(pairs) or
                    any(not 0 <= v <= 0xffffffff for v in data.values())):
                raise ValueError()
        except (ValueError, TypeError):
            errors.append('invalid GPIO API fields')
            continue
        rows.append(dict(index=index, time=int(ts), level=level, kind=kind, fields=data))
    result = core('\n'.join(clean)+'\n', manifest)
    if not result.get('sessions'):
        return result
    service = manifest.get('gpio_service', {})
    expected = dict(abi=4, mode=2, capabilities=56, request_bytes=96, snapshot_bytes=64,
                    zephyr_api=True)
    if any(type(service.get(k)) is not type(v) or service[k] != v for k, v in expected.items()):
        errors.append('GPIO API layout contract')
    baseline, count, observed, maximum = None, 0, {}, 0
    original = text.splitlines()
    markers = {}
    sample_lines = {}
    functional = None
    for index, line in enumerate(original):
        found = re.search(r'zephyr_lifecycle (ready|hardware|session) round=(\d+) ', line)
        if found:
            markers[(found[1], int(found[2]))] = index
        found = re.search(r'zephyr_lifecycle sample id=(\d+) ', line)
        if found:
            sample_lines[int(found[1])] = index
        if 'zephyr_observe functional ' in line:
            functional = index
    for row in rows:
        d, kind = row['fields'], row['kind']
        if (row['level'] != 'I' or d['version'] != 1 or d['rc'] or d['fault'] or
                d['mask_errors'] or d['pins'] != 0x33000 or
                any(d[k] & ~0x33000 for k in ('inputs', 'outputs', 'directions')) or
                d['clocks'] & 0x4002 != 0x4002 or d['resets'] & 0x4002 != 0x4002):
            errors.append('GPIO API identity/state/error')
        if kind == 'baseline':
            if (baseline is not None or count or d['round'] or d['stage'] or d['sample'] or
                    d['phase'] != 3 or d['transitions'] or d['max_ticks'] or
                    row['index'] <= markers.get(('ready', 0), row['index'])):
                errors.append('GPIO API baseline order')
            baseline = d
            continue
        if baseline is None:
            errors.append('GPIO API missing baseline before operation')
            continue
        if kind == 'checkpoint':
            wanted_round, wanted_stage = divmod(count, 2)
            count += 1
            level = wanted_stage
            if (d['round'] != wanted_round or d['stage'] != wanted_stage or d['sample'] or
                    wanted_round >= 11 or d['transitions'] != count or
                    d['phase'] != 3+wanted_stage or observed or
                    row['index'] <= markers.get(('ready' if wanted_stage == 0 else 'hardware',
                                                  wanted_round), row['index']) or
                    row['index'] >= markers.get(('session', wanted_round), len(original))):
                errors.append('GPIO API lifecycle checkpoint order/count')
        else:
            level = 1
            ident = d['sample']
            if (count != 22 or d['round'] != 10 or d['stage'] != 2 or d['phase'] != 4 or
                    d['transitions'] != 22 or functional is None or row['index'] <= functional or
                    ident not in sample_lines or row['index'] <= sample_lines.get(ident, row['index']) or
                    ident in observed or (observed and ident != max(observed)+1)):
                errors.append('GPIO API terminal observation order')
            observed[ident] = row
        if (any((d[k] ^ baseline[k]) & ~mask for k, mask in MASKS.items()) or
                d['mux_led'] & 0xf0000 or not d['directions'] & 0x1000 or
                (d['pull_up'] | d['pull_down'] | d['irq_enabled'] | d['control']) & 0x1000 or
                bool(d['outputs'] & 0x1000) != bool(level) or
                bool(d['inputs'] & 0x1000) != bool(level)):
            errors.append('GPIO API pad/latch/configuration preservation')
        if d['max_ticks'] < maximum or not d['max_ticks']:
            errors.append('GPIO API timing diagnostics')
        maximum = d['max_ticks']
    if baseline is None or count != 22:
        missing.append('GPIO API complete lifecycle checkpoints')
    if functional is not None:
        expected_samples = {ident for ident, index in sample_lines.items() if index > functional}
        if not expected_samples.issubset(observed):
            missing.append('GPIO API terminal sample checks')
    session = result['sessions'][0]
    session['errors'] += errors
    session['missing'] += missing
    session['gpio_api_records'] = rows
    session['status'] = 'fail' if session['errors'] else 'incomplete' if session['missing'] else 'pass'
    if session['missing']:
        session['overall_status'] = 'incomplete' if not session['errors'] else 'fail'
        for item in session.get('scopes', {}).values():
            if item['status'] == 'pass':
                item['status'] = 'incomplete'
    result['status'] = session['status']
    return result
