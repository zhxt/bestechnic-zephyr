# SPDX-License-Identifier: Apache-2.0
"""UART resource readback evidence, checked before the lifecycle/IPC parser."""
import re

ROW = re.compile(r'(NA|\d+)/([IE])/BTH/RESOURCE/MAIN \| zephyr_uart_resource snapshot (.+) !')
FIELDS = set('version build expected rc abi bytes phase valid source source_hz divider configured_hz '
             'clocks reset_released rx_pin tx_pin rx_mux tx_mux pull_up pull_down'.split())
EXPECTED = dict(abi=2, bytes=64, valid=7, source=1, source_hz=24000000, divider=1,
                configured_hz=24000000, clocks=3, reset_released=3, rx_pin=18,
                tx_pin=19, rx_mux=4, tx_mux=4, pull_up=1, pull_down=0)


def run(text, manifest, analyze):
    contract = manifest.get('uart_resource_service')
    if contract is None:
        return analyze(text)
    phases = [0, 3, 4] if manifest.get('restart_version') else [0, 3]
    filtered, records, errors, missing = [], [], [], []
    started = False
    phase_zero_before_start = False
    released = False
    held = False
    functional = False
    previous_time = None
    for line in text.splitlines():
        if 'zephyr_observe functional ' in line:
            functional = True
        if 'zephyr_dual stage id=3 ' in line or ('zephyr_lifecycle event ' in line and ' step=1 ' in line):
            started = True
        if 'zephyr_dual stage id=6 ' in line or ('zephyr_lifecycle reset ' in line and ' op=3 ' in line):
            released = True
        if 'zephyr_lifecycle reset ' in line and ' op=4 ' in line:
            held = True
        if 'zephyr_uart_resource' not in line:
            filtered.append(line)
            continue
        match = ROW.fullmatch(line)
        if not match:
            errors.append('UART malformed resource record')
            continue
        try:
            pairs = [word.split('=', 1) for word in match[3].split()]
            d = {key: int(value, 0) for key, value in pairs}
            if len(pairs) != len(d) or set(d) != FIELDS or any(not 0 <= v <= 0xffffffff for v in d.values()):
                raise ValueError()
        except (ValueError, TypeError):
            errors.append('UART invalid resource fields')
            continue
        index = len(records)
        phase = phases[index] if index < len(phases) else -1
        if (match[2] != 'I' or d['rc'] or d['version'] != 2 or
                d['build'] != int(manifest['build'], 0) or d['expected'] != phase or d['phase'] != phase or
                any(d[k] != v for k, v in EXPECTED.items())):
            errors.append('UART resource identity/phase/readback')
        if functional:
            errors.append('UART snapshot after functional completion')
        if phase == 0:
            phase_zero_before_start = not started
            if started:
                errors.append('UART early query after lifecycle start')
        elif not phase_zero_before_start or not released or (phase == 4 and not held):
            errors.append('UART resource lifecycle order')
        if records and any(d[k] != records[0][k] for k in EXPECTED):
            errors.append('UART resource changed during lifecycle')
        if match[1] != 'NA':
            now = int(match[1])
            if previous_time is not None and now < previous_time:
                errors.append('UART resource timestamp order')
            previous_time = now
        records.append(d)
    if not isinstance(contract, dict) or contract.get('abi') != 2 or contract.get('capabilities') != 2:
        errors.append('UART resource manifest contract')
    if len(records) < len(phases):
        missing.append('UART resource snapshots incomplete')
    result = analyze('\n'.join(filtered) + '\n')
    if not result.get('sessions'):
        result['sessions'] = [dict(status='incomplete', errors=[], missing=['boot'])]
        result['session_count'] = 1
    session = result['sessions'][0]
    session['errors'] += errors
    session['missing'] += missing
    session['uart_resource_snapshots'] = records
    session['status'] = 'fail' if session['errors'] else 'incomplete' if session['missing'] else 'pass'
    result['status'] = session['status']
    # Scope results may not claim success with absent resource evidence.
    if errors or missing:
        session['complete'] = False
        session['overall_status'] = session['status']
        for item in session.get('scopes', {}).values():
            item['status'] = session['status']
    return result
