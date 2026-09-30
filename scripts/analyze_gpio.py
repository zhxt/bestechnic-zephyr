# SPDX-License-Identifier: Apache-2.0
"""GPIO qualification evidence, nested inside boot, IPC and observation checks."""
import re
from validation_profiles import get_profile

ROW = re.compile(r'(\d+)/([IE])/BTH/GPIO/MAIN \| zephyr_gpio (\w+) (.+) !')
SNAPSHOT = set('stage phase fault pins inputs directions outputs mux_led mux_keys pull_up pull_down clocks resets irq_enabled control'.split())
FIELDS = {
    'begin': set('version build mode target poll_ms snapshot_ms debounce_ms timeout_ms'.split()),
    'snapshot': SNAPSHOT,
    'waiting': {'pins', 'cycles_each'},
    'key': set('pin ms level presses releases'.split()),
    'led': set('ms step pin level'.split()),
    'result': set('version mode pass ms samples p0 r0 p1 r1 led_steps pad_checks busy rc'.split()),
    'error': {'stage', 'rc'},
    'timing': set('version sample ms calls sample_calls read_calls write_calls max_ticks sample_max_ticks read_max_ticks write_max_ticks mask_errors systick_load systick_val systick_pending rc'.split()),
}


def run(text, manifest, core):
    scenario = get_profile(manifest['validation_profile'])
    mode = scenario.gpio_mode
    if not mode:
        return core(text, manifest)
    base, rows, errors, missing = [], [], [], []
    service = manifest.get('gpio_service', {})
    expected = dict(abi=4, mode=mode, capabilities=40 if mode == 1 else 56,
                    request_bytes=96, snapshot_bytes=64)
    if scenario.gpio_api:
        expected['zephyr_api'] = True
    if any(type(service.get(k)) is not type(v) or service[k] != v for k, v in expected.items()):
        errors.append('GPIO layout service contract')
    for index, line in enumerate(text.splitlines()):
        if 'zephyr_gpio ' not in line:
            base.append(line)
            continue
        match = ROW.fullmatch(line)
        if not match:
            errors.append('malformed GPIO record')
            continue
        time, level, kind, body = match.groups()
        try:
            pairs = [item.split('=', 1) for item in body.split()]
            d = {key: int(value, 0) for key, value in pairs}
            wanted_fields = FIELDS.get(kind, set())
            if kind == 'begin' and scenario.gpio_api:
                wanted_fields = wanted_fields | {'api'}
            if (kind not in FIELDS or set(d) != wanted_fields or len(d) != len(pairs)
                    or any(not 0 <= v <= 0xffffffff for v in d.values())):
                raise ValueError()
        except ValueError:
            errors.append('invalid GPIO fields')
            continue
        rows.append(dict(index=index, time=int(time), level=level, kind=kind, fields=d))
    result = core('\n'.join(base)+'\n', manifest)
    if not result.get('sessions'):
        return result
    s = result['sessions'][0]
    state, snapshots, keys, led, final, origin = 0, {}, {}, 0, False, None
    timing = {}
    samples = {}
    for i, line in enumerate(text.splitlines()):
        match = re.match(r'(\d+)/I/BTH/KERN/MAIN \| zephyr_dual sample id=(\d+) ', line)
        if match:
            samples[int(match[2])] = (i, int(match[1]))
    for row in rows:
        d, kind, time = row['fields'], row['kind'], row['time']
        if row['level'] != 'I' or kind == 'error':
            errors.append('GPIO firmware error')
        if kind == 'begin':
            wanted = dict(version=3 if scenario.gpio_api else 2, build=int(manifest['build'], 0),
                          mode=mode, target=10, poll_ms=10, snapshot_ms=1000,
                          debounce_ms=50, timeout_ms=300000)
            if scenario.gpio_api:
                wanted['api'] = 1
            if state or d != wanted:
                errors.append('GPIO begin identity/order')
            state = 1
        elif kind == 'snapshot':
            stage = d['stage']
            if stage not in (0, 1, 2) or stage in snapshots or state != (1, 2, 4)[min(stage, 2)]:
                errors.append('GPIO snapshot order')
            if stage == 2 and final:
                errors.append('GPIO snapshot after result')
            snapshots[stage] = d
            state = 2 if stage == 0 else 3 if stage == 1 else 5
            if d['phase'] != 3 or d['fault'] or d['pins'] != 0x33000 or any(
                    d[k] & ~0x33000 for k in ('inputs', 'directions', 'outputs')):
                errors.append('GPIO snapshot identity/state')
            if d['clocks'] & 0x4002 != 0x4002 or d['resets'] & 0x4002 != 0x4002:
                errors.append('GPIO bank unavailable')
            if stage and 0 in snapshots:
                before = snapshots[0]
                changed = 0x30000 | (0x1000 if mode == 2 else 0)
                masks = dict(mux_led=0xf0000 if mode == 2 else 0, mux_keys=0xff,
                             pull_up=changed, pull_down=changed, directions=changed,
                             outputs=0x1000 if mode == 2 else 0,
                             clocks=0, resets=0, irq_enabled=0, control=0)
                if any((d[k] ^ before[k]) & ~mask for k, mask in masks.items()):
                    errors.append('GPIO changed protected state')
                if (d['directions'] & 0x30000 or d['mux_keys'] & 0xff
                        or d['pull_up'] & 0x30000 != 0x30000 or d['pull_down'] & 0x30000
                        or (d['irq_enabled'] | d['control']) & changed):
                    errors.append('GPIO key configuration')
                if mode == 2 and (d['directions'] & 0x1000 != 0x1000 or d['mux_led'] & 0xf0000
                        or d['outputs'] & 0x1000 != 0x1000 or (d['pull_up'] | d['pull_down']) & 0x1000
                        or (stage == 2 and d['inputs'] & 0x1000 != 0x1000)):
                    errors.append('GPIO LED configuration/final high')
        elif kind == 'waiting':
            if state != 3 or d != dict(pins=0x30000, cycles_each=10):
                errors.append('GPIO waiting identity/order')
            state, origin = 4, time
        elif kind in ('key', 'led'):
            if state != 4 or origin is None or abs(time-origin-d['ms']) > 100:
                errors.append('GPIO event order/time')
            if kind == 'led':
                led += 1
                if (mode != 2 or d['pin'] != 12 or d['step'] != led or led > 20
                        or d['level'] != (0 if led % 2 else 1)
                        or not led*1000 <= d['ms'] <= led*1000+250):
                    errors.append('GPIO LED sequence/deadline')
            else:
                pin = d['pin']
                old = keys.get(pin)
                if pin not in (16, 17) or d['level'] not in (0, 1):
                    errors.append('GPIO key pin/level')
                    continue
                presses, releases = (old['presses'], old['releases']) if old else (0, 0)
                if old:
                    if old['level'] == d['level'] or d['ms']-old['ms'] < 50:
                        errors.append('GPIO key debounce/transition')
                    if d['level'] == 0:
                        presses += 1
                    elif presses > releases:
                        releases += 1
                elif d['ms'] < 50:
                    errors.append('GPIO key initial debounce')
                if d['presses'] != presses or d['releases'] != releases:
                    errors.append('GPIO key cycle accounting')
                keys[pin] = d
        elif kind == 'timing':
            ident = d['sample']
            previous = timing[max(timing)] if timing else None
            maxima = ('sample_max_ticks', 'read_max_ticks', 'write_max_ticks')
            counts = ('sample_calls', 'read_calls', 'write_calls')
            if (state not in (4, 5) or d['version'] != 2 or ident in timing
                    or ident not in samples or (ident != 1 and ident % 10)
                    or (timing and ident <= max(timing)) or d['rc'] or d['mask_errors']
                    or d['systick_load'] != 23999 or d['systick_val'] > d['systick_load']
                    or d['systick_pending'] > 1 or not all(d[k] for k in maxima+counts)
                    or d['max_ticks'] != max(d[k] for k in maxima)
                    or d['calls'] != sum(d[k] for k in counts)
                    or d['read_calls'] > d['ms']//1000+4
                    or d['read_calls'] < max(1, d['ms']//1100-2)
                    or d['write_calls'] < 2 or origin is None
                    or abs(time-origin-d['ms']) > 100
                    or (ident in samples and not (samples[ident][0] < row['index']
                            and 0 <= time-samples[ident][1] <= 100))
                    or (previous and any(d[k] < previous[k] for k in counts+maxima))):
                errors.append('GPIO timing/cadence/interrupt diagnostics')
            timing[ident] = d
        elif kind == 'result':
            if state != 5 or final or origin is None or abs(time-origin-d['ms']) > 100:
                errors.append('GPIO result order/time')
            if not any('zephyr_msg result finished=1 rc=0 ' in line for line in text.splitlines()[:row['index']]):
                errors.append('GPIO result before IPC completion')
            final = True
            for i, pin in enumerate((16, 17)):
                key = keys.get(pin, {})
                if (key.get('level') != 1 or key.get('releases', 0) < 10
                        or key.get('presses') != d['p'+str(i)] or key.get('releases') != d['r'+str(i)]):
                    errors.append('GPIO insufficient key cycles')
            if (d['version'] != 2 or d['mode'] != mode or d['pass'] != 1 or d['rc']
                    or d['samples'] < 50 or d['samples'] > d['ms']//10+1
                    or not 50 <= d['ms'] < 590000 or d['led_steps'] != led
                    or (mode == 1 and d['pad_checks'])
                    or (mode == 2 and (led != 20 or d['pad_checks'] < 20 or d['ms'] < 20010))):
                errors.append('GPIO result/counter coverage')
        elif kind != 'error':
            errors.append('unknown GPIO event')
    expected_timing = {i for i in samples if i == 1 or (i and i % 10 == 0)}
    if set(timing) != expected_timing:
        missing.append('GPIO timing diagnostics')
    if not final or set(snapshots) != {0, 1, 2}:
        missing.append('GPIO begin/configuration/events/result')
    s['errors'] += errors
    s['missing'] += missing
    s['gpio_records'] = rows
    s['status'] = 'fail' if s['errors'] else 'incomplete' if s['missing'] else 'pass'
    result['status'] = s['status']
    return result
