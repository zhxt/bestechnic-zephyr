# SPDX-License-Identifier: Apache-2.0
"""Read-only resource evidence, checked before the lifecycle/IPC parser."""
import re

ROW = re.compile(r'(NA|\d+)/([IE])/BTH/RESOURCE/MAIN \| zephyr_resource snapshot (.+) !')
FIELDS = set('version build expected rc abi bytes valid phase clocks_24m core_vtor '
             'reset_set reset_clr ram_sel0 ram_sel1 oclk oreset sysclk'.split())
HW = set('core_vtor reset_set reset_clr ram_sel0 ram_sel1 oclk oreset sysclk'.split())


def run(text, manifest, analyze):
    contract = manifest.get('resource_service')
    if contract is None:
        return analyze(text)
    phases = [0, 3, 4] if manifest.get('restart_version') else [0, 3]
    filtered, records, errors, missing = [], [], [], []
    started = False
    phase_zero_before_start = False
    released = False
    held = False
    previous_time = None
    for line in text.splitlines():
        if 'zephyr_dual stage id=3 ' in line or ('zephyr_lifecycle event ' in line and ' step=1 ' in line):
            started = True
        if 'zephyr_dual stage id=6 ' in line or ('zephyr_lifecycle reset ' in line and ' op=3 ' in line):
            released = True
        if 'zephyr_lifecycle reset ' in line and ' op=4 ' in line:
            held = True
        if 'zephyr_resource' not in line:
            filtered.append(line)
            continue
        match = ROW.fullmatch(line)
        if not match:
            errors.append('malformed resource record')
            continue
        try:
            pairs = [word.split('=', 1) for word in match[3].split()]
            d = {key: int(value, 0) for key, value in pairs}
            if len(pairs) != len(d) or set(d) != FIELDS or any(not 0 <= v <= 0xffffffff for v in d.values()):
                raise ValueError()
        except (ValueError, TypeError):
            errors.append('invalid resource fields')
            continue
        index = len(records)
        phase = phases[index] if index < len(phases) else -1
        if (match[2] != 'I' or d['rc'] or d['version'] != 1 or d['abi'] != 1 or d['bytes'] != 64 or
                d['build'] != int(manifest['build'], 0) or d['expected'] != phase or d['phase'] != phase or
                d['valid'] != (7 if phase else 1) or d['clocks_24m'] != int(bool(phase))):
            errors.append('resource identity/phase/result')
        if phase == 0:
            phase_zero_before_start = not started
            if started or any(d[k] for k in HW):
                errors.append('early resource read touched unavailable hardware')
        elif not phase_zero_before_start or not released or (phase == 4 and not held):
            errors.append('resource lifecycle order')
        if phase == 4 and (d['reset_clr'] & 16 or d['core_vtor'] != 0x200c0000):
            errors.append('resource reset readback')
        if len(records) >= 2 and any(d[k] != records[1][k] for k in ('ram_sel0', 'ram_sel1')):
            errors.append('resource RAM mapping changed')
        if match[1] != 'NA':
            now = int(match[1])
            if previous_time is not None and now < previous_time:
                errors.append('resource timestamp order')
            previous_time = now
        records.append(d)
    if not isinstance(contract, dict) or contract.get('abi') != 1 or contract.get('capabilities') != 1:
        errors.append('resource manifest contract')
    if len(records) < len(phases):
        missing.append('resource snapshots incomplete')
    result = analyze('\n'.join(filtered) + '\n')
    if not result.get('sessions'):
        result['sessions'] = [dict(status='incomplete', errors=[], missing=['boot'])]
        result['session_count'] = 1
    session = result['sessions'][0]
    session['errors'] += errors
    session['missing'] += missing
    session['resource_snapshots'] = records
    session['status'] = 'fail' if session['errors'] else 'incomplete' if session['missing'] else 'pass'
    result['status'] = session['status']
    # Scope results may not claim success with absent resource evidence.
    if errors or missing:
        session['complete'] = False
        session['overall_status'] = session['status']
        for item in session.get('scopes', {}).values():
            item['status'] = session['status']
    return result
