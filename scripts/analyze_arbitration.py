# SPDX-License-Identifier: Apache-2.0
"""Resource arbitration evidence, checked before the lifecycle/IPC parser."""
import re

ROW = re.compile(r'(NA|\d+)/([IE])/BTH/RESOURCE/MAIN \| zephyr_arbitration snapshot (.+) !')
FIELDS = set('version build expected rc abi bytes phase owner pending entered exited busy '
             'stop_requests stop_completed last_op last_rc probe_mask probe_errors probe_runs reserved'.split())
EXPECTED = dict(abi=3, bytes=64, owner=0, pending=0, probe_errors=0, reserved=0)


def run(text, manifest, analyze):
    contract = manifest.get('arbitration_service')
    if contract is None:
        if manifest.get('validation_profile') != 'resource-arbitration':
            return analyze(text)
        contract = {}
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
        if 'zephyr_arbitration' not in line:
            filtered.append(line)
            continue
        match = ROW.fullmatch(line)
        if not match:
            errors.append('arbitration malformed resource record')
            continue
        try:
            pairs = [word.split('=', 1) for word in match[3].split()]
            d = {key: int(value, 0) for key, value in pairs}
            if len(pairs) != len(d) or set(d) != FIELDS or any(not 0 <= v <= 0xffffffff for v in d.values()):
                raise ValueError()
        except (ValueError, TypeError):
            errors.append('arbitration invalid resource fields')
            continue
        index = len(records)
        phase = phases[index] if index < len(phases) else -1
        if (match[2] != 'I' or d['rc'] or d['version'] != 3 or
                d['build'] != int(manifest['build'], 0) or d['expected'] != phase or d['phase'] != phase or
                any(d[k] != v for k, v in EXPECTED.items())):
            errors.append('arbitration resource identity/phase/readback')
        if functional:
            errors.append('arbitration snapshot after functional completion')
        if phase == 0:
            phase_zero_before_start = not started
            if started:
                errors.append('arbitration early query after lifecycle start')
        elif not phase_zero_before_start or not released or (phase == 4 and not held):
            errors.append('arbitration resource lifecycle order')
        if d['entered'] != d['exited'] or (phase == 0 and any(d[k] for k in
                ('entered','exited','busy','stop_requests','stop_completed','last_op','last_rc','probe_mask','probe_runs'))):
            errors.append('arbitration ownership accounting')
        if phase in (3,4) and (not d['entered'] or d['last_rc']):
            errors.append('arbitration final operation result')
        enabled = isinstance(contract,dict) and contract.get('probe') is True
        injected = enabled and phase == 4
        want = dict(busy=2, stop_requests=1, stop_completed=1, probe_mask=31, probe_runs=1) if injected else dict(busy=0, stop_requests=0, stop_completed=0, probe_mask=0, probe_runs=0)
        if any(d[k] != v for k,v in want.items()):
            errors.append('arbitration injection evidence')
        if records and any(d[k] < records[-1][k] for k in ('entered','exited','busy','stop_requests','stop_completed')):
            errors.append('arbitration counter regression')
        if match[1] != 'NA':
            now = int(match[1])
            if previous_time is not None and now < previous_time:
                errors.append('arbitration resource timestamp order')
            previous_time = now
        records.append(d)
    if not isinstance(contract, dict) or contract.get('abi') != 3 or contract.get('capabilities') != 4 or type(contract.get('probe')) is not bool or contract['probe'] != (manifest.get('validation_profile') == 'resource-arbitration'):
        errors.append('arbitration resource manifest contract')
    if len(records) < len(phases):
        missing.append('arbitration resource snapshots incomplete')
    result = analyze('\n'.join(filtered) + '\n')
    if not result.get('sessions'):
        result['sessions'] = [dict(status='incomplete', errors=[], missing=['boot'])]
        result['session_count'] = 1
    session = result['sessions'][0]
    session['errors'] += errors
    session['missing'] += missing
    session['arbitration_snapshots'] = records
    session['status'] = 'fail' if session['errors'] else 'incomplete' if session['missing'] else 'pass'
    result['status'] = session['status']
    # Scope results may not claim success with absent resource evidence.
    if errors or missing:
        session['complete'] = False
        session['overall_status'] = session['status']
        for item in session.get('scopes', {}).values():
            item['status'] = session['status']
    return result
