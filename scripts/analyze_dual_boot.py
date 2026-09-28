#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Strict V08a dual boot log validator: 0 pass, 1 fail, 2 incomplete."""
import argparse
import json
import re
from validation_profiles import layered
from pathlib import Path

TRACE = set('stage cpuid vtor msp psp control primask basepri ccr mpu cpacr cfsr hfsr shcsr mmfar bfar icsr reason msplim psplim pc lr xpsr esf_valid'.split())
HW = set('phase core_vtor reset_set reset_clr ram_sel0 ram_sel1 oclk oreset sysclk vector_sp vector_pc release_sp release_pc'.split())
SAMPLE = set('id ms ticks timer m55_ms beat cycles_hi cycles_lo bth_stack m55_stack guards rc'.split())


def session(lines, manifest):
    errors, missing, samples, stages = [], [], [], []
    boot = []
    diagnostics, hardware = [], []
    observing=layered(manifest)
    version=int(manifest.get("log_version",1))
    duration=int(manifest.get("duration_seconds",600))
    begin = peer = result = None
    running = False
    expected_boot = [
        ('begin', dict(version=1, test=8, build=int(manifest['build'], 0))),
        ('stage', dict(stage='adapter_ready')),
        ('adapter', dict(cpuid=0x630f1321, ipsr=0, control=0)),
        ('image', dict(layout=0x50001, verified=1)), ('uart', dict(ibrd=1, fbrd=19)),
        ('state', dict(cache=0, mpu=0, systick=0)),
        *[('stage',dict(stage=s)) for s in ('handoff','reset','early','main')]]
    for index, raw in enumerate(lines):
        line=raw.strip()
        if not line:
            continue
        if not line.endswith(' !'):
            if index == len(lines)-1:
                missing.append('truncated last record')
            else:
                errors.append('truncated interior record')
            continue
        try:
            namespace, kind, *words = line[:-2].split()
            if kind.startswith('stage='):
                words.insert(0,kind); kind='stage'
            d={}
            for word in words:
                key,value=word.split('=',1)
                if key in d: raise ValueError('duplicate')
                d[key]=value if key=='stage' and namespace=='zephyr_bth' else int(value,0)
        except (ValueError,IndexError):
            errors.append('malformed record'); continue
        if namespace=='zephyr_bth':
            if begin is not None or len(boot)>=len(expected_boot) or (kind,d)!=expected_boot[len(boot)]:
                errors.append('boot context/stage mismatch')
            boot.append((kind,d)); continue
        if namespace!='zephyr_dual' or result is not None:
            errors.append('unknown/late record'); continue
        if kind=='begin':
            expected=dict(version=version,test=8,build=int(manifest['build'],0),m55_build=int(manifest['m55_build'],0),
                          layout=0x80002 if version>=2 else 0x80001,duration=duration,bth_hz=24000000,m55_hz=24000000)
            if begin is not None or boot!=expected_boot or d!=expected: errors.append('dual begin mismatch')
            begin=d; running=True
        elif kind=='stage':
            if not running or samples or d!=dict(id=len(stages)+1,rc=0) or len(stages)>=7:
                errors.append('loader stage failure/order')
            if d.get('id')==7 and peer is None: errors.append('READY before peer context')
            if d.get('id')==7 and version>=2 and (len(diagnostics)!=3 or len(hardware)!=3):
                errors.append('READY without diagnostic checkpoints')
            stages.append(d)
        elif kind in ('hw','diag'):
            target=hardware if kind=='hw' else diagnostics
            ident=d.get('id'); expected_fields=({'id','rc'}|HW) if kind=='hw' else ({'id','elapsed','reads','retries','stable','seq','magic'}|TRACE)
            if version<2 or not running or samples or ident!=len(target) or ident not in (0,1,2) or set(d)!=expected_fields:
                errors.append('diagnostic identity/fields/order')
            elif len(stages)!=(4 if ident==0 else 6) or (ident==2)!=(peer is not None):
                errors.append('diagnostic stage order')
            elif kind=='hw':
                if len(diagnostics)!=ident or d['rc'] or d['phase']!=(2 if ident==0 else 3):
                    errors.append('hardware snapshot failure/order')
                if ident and (d['release_sp']!=0x2015ffe0 or d['release_pc']!=0x2015e001):
                    errors.append('release vector readback mismatch')
            elif len(hardware)!=ident+1 or d['stable'] not in (0,1) or any(v<0 or v>0xffffffff for v in d.values()):
                errors.append('diagnostic snapshot malformed/order')
            target.append(d)
        elif kind=='peer':
            if peer is not None or len(stages)!=6 or set(d)!=set('cpuid vtor build stage error mpu ccr control'.split()):
                errors.append('peer context order/fields')
            elif (d['cpuid']&0xff00fff0)!=0x4100d220 or d['vtor']!=0xa0000 or d['build']!=int(manifest['m55_build'],0) or \
                 d['stage']!=2 or d['error'] or d['mpu'] or d['ccr']&0x30000 or d['control']!=2:
                errors.append('peer CPU/image/memory context')
            peer=d
        elif kind=='sample':
            if not running or len(stages)!=7 or peer is None or set(d)!=SAMPLE or any(v<0 for v in d.values()):
                errors.append('sample order/fields'); continue
            i=d['id']; cycles=(d['cycles_hi']<<32)|d['cycles_lo']
            if i!=len(samples) or i>(660 if observing else duration): errors.append('sample missing/duplicate/order')
            if d['rc'] or d['guards']!=1 or min(d['bth_stack'],d['m55_stack'])<128: errors.append('error/guard/stack')
            if not i*1000<=d['ms']<=i*1000+100 or abs(d['m55_ms']-d['ms'])>250 or abs(d['timer']-d['ms']//100)>2:
                errors.append('sleep/timer/peer time drift')
            if abs(d['beat']-d['m55_ms']//100)>3: errors.append('peer heartbeat count')
            if i and (abs(d['ticks']-d['ms']*6000)>d['ms']*60 or
                      abs(cycles-d['m55_ms']*24000)>max(24000,d['m55_ms']*240)):
                errors.append('cycle timebase drift')
            if samples:
                prev=samples[-1]
                if any(d[k]<=prev[k] for k in ('ms','ticks','timer','m55_ms','beat')):
                    errors.append('stalled core/counter regression')
                if cycles <= (prev['cycles_hi']<<32)|prev['cycles_lo']: errors.append('M55 cycles stalled')
            samples.append(d)
        elif kind=='result':
            if not running or len(stages)!=7 or d!={'pass':1,'samples':duration+1,'rc':0}:
                errors.append('failed result/order')
            result=d
        else:
            errors.append('unknown dual record')
    if boot!=expected_boot: missing.append('boot stages')
    if begin is None or peer is None or len(stages)!=7: missing.append('loader/READY')
    if version>=2 and (len(diagnostics)!=3 or len(hardware)!=3): missing.append('diagnostic checkpoints')
    if not observing and len(samples)!=duration+1: missing.append(f'samples {len(samples)}/{duration+1}')
    if not observing and result is None: missing.append('result')
    if observing and not samples: missing.append('samples')
    return dict(status='fail' if errors else 'incomplete' if missing else 'pass', errors=errors,missing=missing,
                samples=len(samples),last_sample=samples[-1] if samples else None,loader_stages=len(stages),peer=peer,diagnostics=diagnostics,hardware=hardware)


PREFIX = re.compile(r'(?P<time>NA|[0-9]+)/(?P<level>[IEWD])/BTH/(?P<module>BOOT|LOADER|KERN|FAULT)/(?P<context>EARLY|MAIN|FAULT|IRQ[0-9]+) \| (?P<body>zephyr_[^\r\n]+)')


def prefix_contract(body):
    """Identity of the emitter, not the CPU being observed in a diagnostic."""
    if body.startswith('zephyr_bth '):
        fatal=body.startswith(('zephyr_bth fault ', 'zephyr_bth result ', 'zephyr_bth stage=fatal'))
        return ('FAULT','FAULT') if fatal else ('BOOT','MAIN' if body=='zephyr_bth stage=main !' else 'EARLY')
    return ('KERN' if body.startswith(('zephyr_dual sample ', 'zephyr_dual result ')) else 'LOADER','MAIN')


def analyze(text,manifest):
    groups=[]; current=[]; offset=0
    # latin1 preserves source byte offsets for CLI capture input, including noise.
    for raw_line in text.splitlines(keepends=True):
        raw=raw_line.rstrip('\r\n')
        size=len(raw_line.encode('latin1',errors='replace'))
        match=PREFIX.fullmatch(raw)
        body=match['body'] if match else raw
        record=dict(raw=raw,body=body,byte_start=offset,byte_end=offset+size,
                    prefix=(dict(domain='BTH', **{k:match[k] for k in ('time','level','module','context')}) if match else None))
        offset+=size
        # A corrupt prefix around a begin record remains a failed session;
        # never strip arbitrary bytes and then call that record valid.
        is_begin=body.startswith('zephyr_bth begin ') or 'zephyr_bth begin ' in raw
        if is_begin:
            if current:groups.append(current)
            current=[record]
        elif current:
            if any(x['body'].startswith('zephyr_dual result ') and x['body'].endswith(' !') for x in current) and 'zephyr_' not in raw:
                continue
            current.append(record)
    if current:groups.append(current)
    sessions=[]
    required=manifest.get('prefix_version',0)
    for records in groups:
        report=session([x['body'] for x in records],manifest)
        last_time=None; sample_origin=None
        for record_index, record in enumerate(records):
            body=record['body']; prefix=record['prefix']
            if not body:continue
            if required not in (0,1):report['errors'].append('unsupported prefix version')
            if prefix is None:
                if required:
                    if record_index==len(records)-1 and not body.endswith(' !') and ' | zephyr_' not in body:
                        report['missing'].append('truncated prefix/record')
                    else:report['errors'].append('missing/malformed required prefix')
                continue
            if not required:report['errors'].append('unexpected prefix for legacy manifest')
            module,context=prefix_contract(body)
            if (prefix['module'],prefix['context'])!=(module,context):report['errors'].append('prefix emitter/context mismatch')
            failed=bool(re.search(r' (?:rc|error)=(?:0x[0-9a-fA-F]+|[0-9]+)',body) and
                        any(int(v,0)!=0 for v in re.findall(r' (?:rc|error)=(0x[0-9a-fA-F]+|[0-9]+)',body)))
            expected_level='E' if module=='FAULT' or failed or ' pass=0 ' in body else 'I'
            if prefix['level']!=expected_level:report['errors'].append('prefix severity mismatch')
            unavailable=body.startswith(('zephyr_bth begin ','zephyr_bth stage=adapter_ready','zephyr_bth adapter ')) or module=='FAULT'
            if prefix['time']=='NA':
                if not unavailable:report['errors'].append('unavailable runtime timestamp')
                continue
            now=int(prefix['time'])
            if now>0xffffffffffffffff or (last_time is not None and now<last_time):report['errors'].append('timestamp overflow/regression')
            last_time=now
            if body.startswith('zephyr_dual sample '):
                match=re.search(r' ms=([0-9]+) ',body)
                if match:
                    ms=int(match[1])
                    if sample_origin is None:sample_origin=(now,ms)
                    dt=now-sample_origin[0]; dm=ms-sample_origin[1]
                    if abs(dt-dm)>max(10,dm//100):report['errors'].append('timestamp/sample time drift')
        report['records']=records
        if report['errors']:report['status']='fail'
        sessions.append(report)
    return dict(status=sessions[-1]['status'] if sessions else 'incomplete',sessions=sessions,session_count=len(sessions))


def main():
    ap=argparse.ArgumentParser(description=__doc__); ap.add_argument('log',type=Path)
    ap.add_argument('--manifest',type=Path,required=True);ap.add_argument('--output',type=Path)
    a=ap.parse_args();report=analyze(a.log.read_bytes().decode('latin1'),json.loads(a.manifest.read_text()))
    text=json.dumps(report,indent=2)+'\n'
    if a.output:a.output.write_text(text)
    print(text,end='');return {'pass':0,'fail':1,'incomplete':2}[report['status']]
if __name__=='__main__':raise SystemExit(main())
