# SPDX-License-Identifier: Apache-2.0
"""Versioned post-functional observations; never synthesize firmware evidence."""
import re
import analyze_resources
import analyze_uart_resources
import analyze_arbitration
from validation_profiles import get_profile, layered

ROW = re.compile(r'(\d+)/([IE])/BTH/OBSERVE/MAIN \| zephyr_observe (\w+) (.+) !')
SAMPLE = re.compile(r'(\d+)/I/BTH/(?:LIFECYCLE|KERN)/MAIN \| zephyr_(?:lifecycle|dual) sample (.+) !')
NAMES = ('functional', 'short', 'long')


def fields(body):
    pairs = [word.split('=', 1) for word in body.split()]
    data = {key: int(value, 0) for key, value in pairs}
    if len(data) != len(pairs) or any(not 0 <= value <= 0xffffffff for value in data.values()):
        raise ValueError('invalid observation fields')
    return data


def analyze(text, manifest, core, scope='long'):
    if scope not in NAMES or (scope != 'long' and not layered(manifest)):
        return dict(status='fail', session_count=1, sessions=[dict(status='fail', errors=[
            'Requested observation scope is unavailable in this release'], missing=[])])
    if not layered(manifest):
        return core(text, manifest)
    scenario = get_profile(manifest['validation_profile'])
    contract = manifest['observation']
    filtered, records, samples, errors, missing = [], [], [], [], []
    functional = None
    origin = None
    checkpoint = None
    seen = {}
    terminal = None
    last_time = None
    completed = False
    if scenario.gpio_mode and not scenario.m55_restart:
        terminal_token = 'zephyr_gpio result '
    elif not scenario.m55_restart:
        terminal_token = 'zephyr_msg result '
    elif not scenario.fault_case or (scenario.recovery and not scenario.recovery_fail_step):
        terminal_token = 'zephyr_lifecycle session '
    elif scenario.recovery_fail_step:
        terminal_token = 'zephyr_lifecycle retry_blocked '
    else:
        terminal_token = 'zephyr_lifecycle hardware '
    lines = text.splitlines()
    for index, line in enumerate(lines):
        timed = re.match(r'(\d+)/', line)
        now = int(timed[1]) if timed else None
        if now is not None:
            if last_time is not None and now < last_time:
                errors.append('observation timestamp order')
            last_time = now
        if completed and 'zephyr_' in line:
            errors.append('record after long observation')
        if terminal_token in line:
            terminal = now
        sample = SAMPLE.fullmatch(line)
        if sample:
            # Full health, sequence and width validation remains in the core parser.
            try:
                d = {k: int(v, 0) for k, v in (x.split('=', 1) for x in sample[2].split())}
                samples.append((now, d['ms'], d['id']))
                if origin is None:
                    origin = now - d['ms']
            except (ValueError, KeyError):
                errors.append('observation sample fields')
        if 'zephyr_observe' not in line:
            if not completed or 'zephyr_' in line:
                filtered.append(line)
            continue
        match = ROW.fullmatch(line)
        if not match:
            if index == len(lines)-1 and not line.endswith(' !'):
                missing.append('truncated observation record')
            else:
                errors.append('malformed observation record')
            continue
        ts, level, kind, body = match.groups()
        try:
            d = fields(body)
        except (ValueError, TypeError):
            errors.append('invalid observation fields')
            continue
        record = dict(kind=kind, time=int(ts), fields=d)
        records.append(record)
        if level != 'I' or d.get('rc', 0):
            errors.append('observation runtime failure')
        if kind == 'functional':
            wanted = set('version ms session rc'.split())
            if scenario.m55_restart:
                wanted |= {'releases', 'attempts', 'recoveries'}
            if (functional is not None or seen or checkpoint or set(d) != wanted
                    or d.get('version') != 1 or not d.get('session')
                    or origin is None or terminal is None or not 0 <= now-terminal <= 100
                    or not 0 <= d.get('ms', -1) < contract['functional_limit_ms']
                    or abs(now-origin-d.get('ms', 0)) > 100):
                errors.append('functional identity/order/deadline')
            if scenario.m55_restart:
                expected = dict(session=2 if scenario.recovery else 1 if scenario.fault_case else 11,
                                releases=(1 if scenario.recovery_fail_step in (1, 3) else 2)
                                if scenario.recovery else 1 if scenario.fault_case else 11,
                                attempts=int(scenario.recovery),
                                recoveries=int(scenario.recovery and not scenario.recovery_fail_step))
                if any(d.get(k) != v for k, v in expected.items()):
                    errors.append('functional lifecycle counters')
            else:
                messages = [x for x in filtered if 'zephyr_msg result ' in x]
                if not messages or f"session={d.get('session')} !" not in messages[-1]:
                    errors.append('functional message session')
            functional = record
        elif kind in ('held', 'traffic'):
            wanted = (set('scope session local_idle reset_held local_irq peer_irq rc'.split())
                      if scenario.m55_restart else set('scope session finished live rc'.split()))
            expected_kind = 'held' if scenario.m55_restart else 'traffic'
            if (kind != expected_kind or set(d) != wanted or checkpoint is not None
                    or functional is None or d.get('scope') != len(seen)+1
                    or d.get('scope') not in (1, 2)
                    or d.get('session') != (functional or {}).get('fields', {}).get('session')):
                errors.append('observation terminal state identity/order')
            if scenario.m55_restart:
                if (d.get('local_idle') != 1 or d.get('reset_held') != 1
                        or (d.get('local_irq', 0) | d.get('peer_irq', 0)) & 0xa):
                    errors.append('observation terminal reset/channel state')
            elif d.get('finished') != 1 or d.get('live') != 1:
                errors.append('observation terminal traffic state')
            checkpoint = record
        elif kind == 'result':
            wanted = set('version scope pass session functional_ms ms samples rc'.split())
            ident = d.get('scope')
            f = (functional or {}).get('fields', {})
            expected_end = f.get('ms', 0) + contract['short_ms']
            if ident == 2:
                expected_end = max(expected_end, contract['long_ms'])
            if (set(d) != wanted or d.get('version') != 1 or ident not in (1, 2)
                    or ident != len(seen)+1 or d.get('pass') != 1
                    or functional is None or checkpoint is None
                    or (checkpoint or {}).get('fields', {}).get('scope') != ident
                    or d.get('session') != f.get('session') or d.get('functional_ms') != f.get('ms')
                    or origin is None or not samples or d.get('samples') != len(samples)
                    or not expected_end <= d.get('ms', -1) <= expected_end+1100
                    or abs(now-origin-d.get('ms', 0)) > 100
                    or (samples and (d.get('ms') != samples[-1][1]
                                     or not samples[-1][0] <= (checkpoint or {}).get('time', -1) <= now))):
                errors.append('observation result/window/order')
            if ident in (1, 2):
                seen[ident] = record
            checkpoint = None
            if ident == 2:
                completed = True
        else:
            errors.append('unknown observation event')
    base = core('\n'.join(filtered)+'\n', manifest)
    report = base['sessions'][0] if base.get('sessions') else dict(errors=[], missing=['boot'])
    if functional and report['missing']:
        errors.append('functional claim without complete scenario evidence')
    if samples and samples[-1][1] > contract['limit_ms']+100:
        errors.append('observation exceeded bounded budget')
    report['errors'] += errors
    scopes = {}
    for name in NAMES:
        present = functional is not None if name == 'functional' else NAMES.index(name) in seen
        scopes[name] = dict(status='fail' if report['errors'] else
                           'pass' if present and not report['missing'] else 'incomplete')
    required = functional is not None if scope == 'functional' else NAMES.index(scope) in seen
    report['missing'] += missing
    if not required:
        report['missing'].append('observation '+scope+' incomplete')
    report['status'] = 'fail' if report['errors'] else 'incomplete' if report['missing'] else 'pass'
    report.update(requested_scope=scope, scopes=scopes, observation_records=records,
                  complete=completed and report['status']=='pass',
                  overall_status='fail' if report['errors'] else 'pass' if completed and not report['missing'] else 'incomplete')
    return dict(status=report['status'], session_count=1, sessions=[report])


def finalize(result):
    """Profile/boot errors must also invalidate the scope summaries."""
    for session in result.get('sessions', []):
        if session.get('errors'):
            session['overall_status'] = 'fail'
            session['complete'] = False
            for item in session.get('scopes', {}).values():
                item['status'] = 'fail'
        elif session.get('missing'):
            session['complete'] = False
    if result.get('sessions') and 'requested_scope' in result['sessions'][-1]:
        session = result['sessions'][-1]
        result.update(requested_scope=session['requested_scope'],
                      overall_status=session['overall_status'], complete=session['complete'])
    return result


def run(profile_module, text, manifest, core, scope):
    class Scoped:
        @staticmethod
        def analyze(data, meta):
            return analyze_arbitration.run(data, meta, lambda arbitration_clean:
                analyze_uart_resources.run(arbitration_clean, meta, lambda uart_clean:
                    analyze_resources.run(uart_clean, meta, lambda clean: analyze(clean, meta, core, scope))))
    previous = profile_module.dual
    try:
        profile_module.dual = Scoped
        return finalize(profile_module.analyze(text, manifest))
    finally:
        profile_module.dual = previous
