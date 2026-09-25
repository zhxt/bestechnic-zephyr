#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Strict T0/T1/T2 profile plus unchanged V08b IPC/heartbeat acceptance. 0/1/2 exit."""
import argparse,json,re
from pathlib import Path
import analyze_dual_doorbell as dual

ROW=re.compile(r'(?P<time>[0-9]+)/(?P<level>[IE])/BTH/BOOT/EARLY \| zephyr_bootprof (?P<kind>begin|point|result) (?P<body>.+) !')
ANY_TIME=re.compile(r'(\d+)/[IEWD]/BTH/[^ ]+ \| ')
POINT_FIELDS=set('id fast0 slow fast1 fast_end error fast_ctrl fast_load periph sysclk sysdiv cache mpu primask basepri log_last log_lo log_hi crc demcr dwt_ctrl dwt_cycles dwt_valid'.split())
NAMES=['timer_open','log_start','source_crc','dcache_off','icache_off','mpu_off','copy','data_crc','exec_crc','guards','empty_a','empty_b']

def diff(a,b):return (a-b)&0xffffffff

def inspect(rows,manifest,errors,missing):
    points=[];begin=None;result=None;warnings=[];intervals=[]
    for row in rows:
        try:
            pairs=[word.split('=',1) for word in row['body'].split()]
            d={k:int(v,0) for k,v in pairs}
            if len(d)!=len(pairs) or any(v<0 or v>0xffffffff for v in d.values()):raise ValueError()
        except ValueError:errors.append('profile malformed fields');continue
        row['fields']=d;kind=row['kind']
        if row['level']!=('E' if d.get('error',0) else 'I'):errors.append('profile error severity')
        if kind=='begin':
            expected=dict(version=1,variant=manifest['profile_variant'],profile=int(manifest['profile_id'],0),points=12,
                bytes=manifest['code_bytes'],expected_crc=manifest['crc32'],fast_hz=6000000,
                sampler=manifest['profile_sampler'],buffer=manifest['profile_buffer'],size=manifest['profile_size'])
            if begin or points or result or set(d)!=set(expected)|{'slow_hz','slow_nominal','slow_calibrated'} or any(d.get(k)!=v for k,v in expected.items()):errors.append('profile identity/order')
            if not 1000<=d.get('slow_hz',0)<=100000 or not 1000<=d.get('slow_nominal',0)<=100000 or d.get('slow_calibrated') not in (0,1):errors.append('profile slow frequency metadata')
            begin=d
        elif kind=='point':
            if begin is None or result or set(d)!=POINT_FIELDS or d.get('id')!=len(points) or len(points)>=12:
                errors.append('profile point fields/order');continue
            i=d['id']
            if d['error'] or d['fast_ctrl']!=0x82 or not d['periph']&(1<<9):errors.append('profile timer/sample error')
            if not diff(d['fast1'],d['fast0'])<=diff(d['fast_end'],d['fast0'])<=60000:errors.append('profile sample bracket')
            if i>=3 and d['primask']!=1:errors.append('profile interrupt state')
            if i>=4 and d['cache']&1:errors.append('profile cache still enabled')
            if i>=5 and d['mpu']!=0:errors.append('profile MPU still enabled')
            expected_crc=manifest['crc32'] if i in (2,7,8) else 1 if i==9 else 0
            if d['crc']!=expected_crc:errors.append('profile CRC/guards')
            if i>=1 and (d['log_lo'] or d['log_hi']):errors.append('profile clock not initially zero')
            if i==1 and diff(d['fast0'],d['log_last'])>60000:errors.append('profile clock baseline outside bracket')
            if i>1 and d['log_last']!=points[1]['log_last']:errors.append('profile clock baseline overwritten')
            if d['dwt_valid'] not in (0,1) or (d['dwt_valid'] and (not d['demcr']&(1<<24) or d['dwt_ctrl']&(1<<25) or not d['dwt_ctrl']&1)):
                errors.append('profile DWT validity')
            if points:
                prev=points[-1];dt=diff(d['fast0'],prev['fast0'])
                if not 0<dt<3600000000:errors.append('profile fast stopped/reset/interval too long')
                if any(d[k]!=prev[k] for k in ('fast_ctrl','fast_load','periph','sysclk','sysdiv')):errors.append('profile clock configuration changed')
                interval=dict(start=i-1,end=i,name=NAMES[i],fast_ticks=dt,fast_ms=dt/6000,
                    slow_ticks=diff(d['slow'],prev['slow']))
                if begin and begin.get('slow_hz'):interval['slow_ms']=interval['slow_ticks']*1000/begin['slow_hz']
                if d['dwt_valid'] and prev['dwt_valid']:interval['cpu_cycles_mod32']=diff(d['dwt_cycles'],prev['dwt_cycles'])
                intervals.append(interval)
            points.append(d)
        else:
            if result or begin is None or len(points)!=12 or d!={'pass':1,'points':12,'error':0,'guard':1}:errors.append('profile final result')
            result=d
    if begin is None:missing.append('profile begin')
    if len(points)!=12:missing.append(f'profile points {len(points)}/12')
    if result is None:missing.append('profile result')
    total=None
    if len(points)==12 and begin and begin.get('slow_hz'):
        fast=diff(points[9]['fast0'],points[1]['fast0']);slow=diff(points[9]['slow'],points[1]['slow'])
        total=dict(fast_ms=fast/6000,slow_ms=slow*1000/begin['slow_hz'],scope='P1..P9; excludes deferred UART output and pre-timer initialization')
        if not slow or not fast:errors.append('profile clock stopped')
        else:
            total['fast_over_slow']=total['fast_ms']/total['slow_ms']
            if not 0.9<=total['fast_over_slow']<=1.1:warnings.append('fast/nominal-slow mismatch >10%; verify slow calibration and external elapsed time')
        total['empty_probe_ms']=diff(points[11]['fast0'],points[10]['fast0'])/6000
        warnings.append('AON frequency metadata is not an independent wall-clock calibration; compare external timing')
    return dict(begin=begin,points=points,result=result,intervals=intervals,total=total,warnings=warnings)


def analyze(text,manifest):
    groups=[];current=[];offset=0
    for line in text.splitlines(keepends=True):
        if 'zephyr_bth begin ' in line:
            if current:groups.append(current)
            current=[]
        if current or 'zephyr_bth begin ' in line:current.append(dict(raw=line.rstrip('\r\n'),byte_start=offset,byte_end=offset+len(line.encode('latin1')),terminated=line.endswith(('\n','\r'))))
        offset+=len(line.encode('latin1'))
    if current:groups.append(current)
    sessions=[]
    for records in groups:
        filtered=[];profile=[];errors=[];missing=[];image=False;uart=False;last=None
        for record in records:
            raw=record['raw'];tm=ANY_TIME.match(raw)
            if tm:
                t=int(tm[1])
                if t>0xffffffffffffffff or (last is not None and t<last):errors.append('global timestamp regression')
                last=t
            if 'zephyr_bth image ' in raw:image=True
            if 'zephyr_bth uart ' in raw:uart=True
            if 'zephyr_bootprof ' not in raw:filtered.append(raw);continue
            m=ROW.fullmatch(raw)
            if not m:
                if not record['terminated'] and re.match(r'\d+/[IE]/BTH/BOOT/EARLY \| zephyr_bootprof ',raw):missing.append('truncated profile tail')
                else:errors.append('malformed profile prefix/record')
                continue
            if not image or uart:errors.append('profile outside image/uart boundary')
            profile.append(dict(**record,**m.groupdict()))
        base=dual.analyze('\n'.join(filtered)+'\n',manifest)
        report=base['sessions'][0] if base['sessions'] else dict(status='incomplete',errors=[],missing=['boot'])
        info=inspect(profile,manifest,errors,missing)
        if uart and missing:errors.append('boot continued without complete timing evidence')
        if manifest.get('profile_version')!=1 or manifest.get('profile_variant') not in (0,1,2):errors.append('profile manifest version')
        report['errors']+=errors;report['missing']+=missing
        report['status']='fail' if report['errors'] else 'incomplete' if report['missing'] else 'pass'
        report.update(profile=info,profile_records=profile,raw_records=records)
        sessions.append(report)
    return dict(status=sessions[-1]['status'] if sessions else 'incomplete',session_count=len(sessions),sessions=sessions)


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('log',type=Path);ap.add_argument('--manifest',type=Path,required=True);ap.add_argument('--output',type=Path)
    a=ap.parse_args();r=analyze(a.log.read_bytes().decode('latin1'),json.loads(a.manifest.read_text()));text=json.dumps(r,indent=2)+'\n'
    if a.output:a.output.write_text(text)
    print(text,end='');return {'pass':0,'fail':1,'incomplete':2}[r['status']]
if __name__=='__main__':raise SystemExit(main())
