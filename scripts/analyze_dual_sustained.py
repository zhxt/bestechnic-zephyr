#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Strict sustained IPC, T2 profile and heartbeat acceptance: exit 0/1/2."""
import argparse
import json
import re
from pathlib import Path
import analyze_dual_boot as heartbeat
import analyze_boot_profile as profile

FIELDS = set('magic version pair session build phase req ack acked handled overlap error rx requests kicks done queued spurious stack max_wait pauses burst seed elapsed stop_ms guard'.split())
ROW = re.compile(r'(\d+)/([IE])/BTH/IPC/MAIN \| zephyr_cs (begin|progress|endpoint|result) (.+) !')


class Sustained:
    @staticmethod
    def analyze(text, m):
        lines = text.splitlines()
        base, rows, errors, missing = [], [], [], []
        for i, line in enumerate(lines):
            if 'zephyr_cs ' not in line:
                base.append(line)
                continue
            match = ROW.fullmatch(line)
            if not match:
                errors.append('malformed sustained record')
                continue
            ts, level, kind, body = match.groups()
            try:
                pairs = [x.split('=', 1) for x in body.split()]
                d = {k: int(v, 0) for k, v in pairs}
                if len(d) != len(pairs) or any(v < 0 or v > 0xffffffff for v in d.values()):
                    raise ValueError()
            except ValueError:
                errors.append('bad sustained fields')
                continue
            rows.append(dict(index=i, time=int(ts), level=level, kind=kind, fields=d))
        result = heartbeat.analyze('\n'.join(base) + '\n', m)
        if not result['sessions']:
            return result
        s = result['sessions'][0]
        seconds, pair, limit = m['concurrent_seconds'], m['concurrent_pair'], m['concurrent_limit']
        if (m.get('concurrent_version') != 4 or m.get('duration_seconds') != seconds + 10 or
                m.get('progress_period') != 10 or limit != 0x0fffffff or seconds not in (600, 3600)):
            errors.append('sustained manifest contract')
        expected = [('begin', None, None)]
        expected += [('progress', i, side) for i in range(10, seconds, 10) for side in (0, 1)]
        expected += [('endpoint', None, 0), ('endpoint', None, 1), ('result', None, None)]
        actual = [(r['kind'], r['fields'].get('sample'), r['fields'].get('side')) for r in rows]
        if actual != expected[:len(actual)]:
            errors.append('sustained order/missing/duplicate')
        if len(rows) != len(expected):
            missing.append('sustained progress/endpoints/result')
        if any(r['level'] != 'I' for r in rows):
            errors.append('sustained error severity')
        stages = [i for i, line in enumerate(lines) if 'zephyr_dual stage id=7 rc=0' in line]
        sample_rows = {}
        for i, line in enumerate(lines):
            match = re.match(r'(\d+)/I/BTH/KERN/MAIN \| zephyr_dual sample id=(\d+) ', line)
            if match:
                sample_rows[int(match[2])] = (i, int(match[1]))
        if rows:
            b = rows[0]
            if b['fields'] != dict(version=4, channel=1, duration=seconds, progress_period=10,
                                    limit=limit, pair=pair, seed=0x27003301):
                errors.append('sustained begin identity')
            if not stages or (0 in sample_rows and not stages[-1] < b['index'] < sample_rows[0][0]):
                errors.append('sustained begin position')
        previous, endpoints, sessions = {}, [], set()
        for row in rows:
            kind, d = row['kind'], row['fields']
            if kind not in ('progress', 'endpoint'):
                continue
            progress = kind == 'progress'
            if set(d) != FIELDS | {'side'} | ({'sample'} if progress else set()) or d['side'] not in (0, 1):
                errors.append('sustained endpoint fields')
                continue
            side = d['side']
            sessions.add(d['session'])
            fixed = dict(magic=0x34434342, version=4, pair=pair,
                         build=int(m['build' if side == 0 else 'm55_build'], 0),
                         phase=2 if progress else 6, error=0, spurious=0, burst=32,
                         seed=0x27003301, guard=0xcc445aa5)
            if any(d[k] != v for k, v in fixed.items()):
                errors.append('sustained identity/state')
            if (not d['session'] or not 0 < d['overlap'] <= d['handled'] or
                    not 0 <= d['acked'] <= d['req'] <= limit or d['req'] - d['acked'] > 1 or
                    d['ack'] != d['handled'] or d['handled'] > limit or
                    d['stack'] < 128 or d['max_wait'] > 2000 or d['pauses'] > 1 or
                    not 31 <= d['queued'] <= d['requests'] or
                    not 0 <= d['done'] <= d['kicks'] <= d['requests'] <= 3*(d['req']+d['handled'])+100):
                errors.append('sustained sequence/stats/deadline')
            if side in previous:
                old = previous[side]
                if any(d[k] <= old[k] for k in ('req', 'acked', 'handled', 'elapsed')):
                    errors.append('sustained traffic stalled/regressed')
                if any(d[k] < old[k] for k in ('rx', 'requests', 'kicks', 'done', 'queued', 'pauses', 'max_wait')):
                    errors.append('sustained counter regression')
            previous[side] = d
            if progress:
                sample = d['sample']
                if d['stop_ms'] or not sample*1000-2500 <= d['elapsed'] <= sample*1000+1000:
                    errors.append('sustained stale/early-stop progress')
                if sample not in sample_rows or not (row['index'] > sample_rows[sample][0] and
                        0 <= row['time']-sample_rows[sample][1] <= 100):
                    errors.append('sustained progress position/time')
            else:
                endpoints.append(d)
                if (d['req'] != d['acked'] or d['req'] < 10000 or d['pauses'] != 1 or
                        d['kicks'] != d['done'] or
                        not seconds*1000 <= d['stop_ms'] <= seconds*1000+2000 or
                        not d['stop_ms'] <= d['elapsed'] <= seconds*1000+5000):
                    errors.append('sustained final state/duration')
        if len(sessions) > 1:
            errors.append('sustained session mismatch')
        if len(endpoints) == 2:
            a, b = endpoints
            if (a['handled'] != b['req'] or b['handled'] != a['req'] or
                    a['rx'] != b['kicks'] or b['rx'] != a['kicks']):
                errors.append('sustained cross-core accounting')
        finals = [r for r in rows if r['kind'] == 'result']
        if finals:
            final = finals[-1]
            if len(endpoints) != 2 or final['fields'] != dict(finished=1, rc=0, session=endpoints[0]['session']):
                errors.append('sustained final result')
            if not seconds*1000 <= final['time']-rows[0]['time'] <= seconds*1000+5500:
                errors.append('sustained duration/deadline')
            if any('zephyr_dual result ' in line for line in lines[:final['index']]):
                errors.append('late sustained result')
        if any('zephyr_dual result pass=1' in line for line in lines) and missing:
            errors.append('heartbeat success without sustained evidence')
        s['errors'] += errors
        s['missing'] += missing
        s['sustained_records'] = rows
        s['status'] = 'fail' if s['errors'] else 'incomplete' if s['missing'] else 'pass'
        result['status'] = s['status']
        return result


def analyze(text, manifest):
    old = profile.dual
    try:
        profile.dual = Sustained
        return profile.analyze(text, manifest)
    finally:
        profile.dual = old


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('log', type=Path)
    ap.add_argument('--manifest', type=Path, required=True)
    ap.add_argument('--output', type=Path)
    args = ap.parse_args()
    result = analyze(args.log.read_bytes().decode('latin1'), json.loads(args.manifest.read_text()))
    text = json.dumps(result, indent=2) + '\n'
    if args.output:
        args.output.write_text(text)
    print(text, end='')
    return {'pass': 0, 'fail': 1, 'incomplete': 2}[result['status']]


if __name__ == '__main__':
    raise SystemExit(main())
