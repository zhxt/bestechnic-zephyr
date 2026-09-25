#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""V08b: require both dual heartbeat validation and interrupt doorbell evidence."""
import argparse
import json
import re
from pathlib import Path
import analyze_dual_boot as dual

IPC=re.compile(r'([0-9]+)/([IE])/BTH/IPC/MAIN \| (zephyr_db (?:begin|result) [^\r\n]+ !)')
FIELDS=set('finished rc phases bth_rx bth_req bth_kicks bth_done bth_queued bth_spurious m55_stage m55_error m55_rx m55_req m55_kicks m55_done m55_queued m55_spurious bth_stack m55_stack'.split())


def analyze(text,manifest):
    groups=[];current=[];offset=0
    for line in text.splitlines(keepends=True):
        raw=line.rstrip('\r\n');m=dual.PREFIX.fullmatch(raw)
        if (m and m['body'].startswith('zephyr_bth begin ')) or 'zephyr_bth begin ' in raw:
            if current:groups.append(current)
            current=[]
        if current or 'zephyr_bth begin ' in raw:
            current.append(dict(raw=raw,byte_start=offset,byte_end=offset+len(line.encode('latin1',errors='replace'))))
        offset+=len(line.encode('latin1',errors='replace'))
    if current:groups.append(current)
    sessions=[]
    for records in groups:
        filtered=[];ipc=[];errors=[];missing=[];ready=False;sample_seen=False;ended=False;begin=False;last_time=None
        rounds=int(manifest['doorbell_rounds'])
        for record in records:
            raw=record['raw'];m=IPC.fullmatch(raw);dm=dual.PREFIX.fullmatch(raw)
            body=m[3] if m else dm['body'] if dm else raw
            stamp=int(m[1]) if m else int(dm['time']) if dm and dm['time']!='NA' else None
            if stamp is not None:
                if stamp>0xffffffffffffffff or (last_time is not None and stamp<last_time):errors.append('IPC/dual timestamp regression')
                last_time=stamp
            if body=='zephyr_dual stage id=7 rc=0 !':ready=True
            if body.startswith('zephyr_dual sample '):sample_seen=True
            if body.startswith('zephyr_dual result '):ended=True
            if not m:
                filtered.append(raw);continue
            try:
                parts=body[:-2].split();pairs=[word.split('=',1) for word in parts[2:]]
                d={k:int(v,0) for k,v in pairs}
                if len(d)!=len(pairs):raise ValueError('duplicate')
            except ValueError:
                errors.append('IPC malformed fields');continue
            ipc.append(dict(**record,timestamp_ms=stamp,level=m[2],body=body,fields=d))
            if m[2]!=('E' if d.get('rc',0) else 'I'):errors.append('IPC severity mismatch')
            if parts[1]=='begin':
                if begin or not ready or sample_seen or ended or d!={'version':2,'channel':1,'rounds':rounds}:errors.append('IPC begin/order mismatch')
                begin=True
            else:
                expected=dict(finished=1,rc=0,phases=31,bth_rx=2*rounds+3,bth_req=2*rounds+35,
                    bth_kicks=2*rounds+5,bth_done=2*rounds+5,bth_queued=31,bth_spurious=0,
                    m55_stage=5,m55_error=0,m55_rx=2*rounds+5,m55_req=2*rounds+33,
                    m55_kicks=2*rounds+3,m55_done=2*rounds+3,m55_queued=31,m55_spurious=0)
                if not begin or not sample_seen or ended or len(ipc)!=2 or set(d)!=FIELDS or any(d.get(k)!=v for k,v in expected.items()) or min(d.get('bth_stack',0),d.get('m55_stack',0))<128:
                    errors.append('IPC result/counts/order/stack')
        base=dual.analyze('\n'.join(filtered)+'\n',manifest)
        report=base['sessions'][0] if base['sessions'] else dict(status='incomplete',errors=[],missing=['boot'],samples=0)
        if manifest.get('doorbell_version')!=2:errors.append('IPC manifest version mismatch')
        if not begin:missing.append('IPC begin')
        if len(ipc)<2:missing.append('IPC result')
        if ended and missing:errors.append('completed dual run without IPC evidence')
        report['errors']+=errors;report['missing']+=missing
        report['status']='fail' if report['errors'] else 'incomplete' if report['missing'] else 'pass'
        report['ipc_records']=ipc
        # Exact original bytes/offsets are retained here; base records are filtered.
        report['raw_records']=records
        sessions.append(report)
    return dict(status=sessions[-1]['status'] if sessions else 'incomplete',session_count=len(sessions),sessions=sessions)


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('log',type=Path)
    ap.add_argument('--manifest',type=Path,required=True);ap.add_argument('--output',type=Path)
    a=ap.parse_args();report=analyze(a.log.read_bytes().decode('latin1'),json.loads(a.manifest.read_text()))
    text=json.dumps(report,indent=2)+'\n'
    if a.output:a.output.write_text(text)
    print(text,end='');return {'pass':0,'fail':1,'incomplete':2}[report['status']]
if __name__=='__main__':raise SystemExit(main())
