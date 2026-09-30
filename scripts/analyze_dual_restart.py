#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Strict lifecycle/profile/BTH liveness acceptance. Exit 0/1/2."""
import argparse
import json
import re
from pathlib import Path
import analyze_boot_profile as profile
from analyze_dual_boot import prefix_contract
from analyze_dual_message import FIELDS
from validation_profiles import validate_manifest, layered, get_profile
import analyze_observation as observation
import analyze_gpio_restart
from analyze_lifecycle_contract import LOG_MODULE, LOG_NAMESPACE, LOG_CONTRACT, FAULT_REASONS

LIFECYCLE = dict(layout=0x000a0004, address=0x2015e280, bytes=128, rounds=11,
                 target=1000, observe_seconds=600, ready_ms=5000,
                 message_ms=30000, quiesce_ms=5000, reset_ms=10)
RESET_DIAGNOSTIC = dict(version=1, address=0x2055c1a0, bytes=80,
                       read_attempts=32, poll_limit=1024)
RESET_FIELDS = set(('round session version op reason service_rc polls samples attempts '
                    'max_attempts last_a last_b max_delta elapsed reset_before reset_after '
                    'timer_ctrl diag_error sampler raw_start raw_end primask rc').split())
REPARK_DIAGNOSTIC = dict(version=1,address=0x2055c800,bytes=100,bank=9,selector_mask=7<<27,
    physical_words=[0x20320000,0x20320004,0x20330000],
    expected_words=[0x2015ffe0,0x200c0009,0xe7fdbf30])
REPARK_FIELDS = set(('round session version op service_rc phase_before phase_after reason '
    'reset_before reset_after sel0_before sel1_before sel0_axi sel1_axi sel0_after sel1_after '
    'phys0 phys1 phys2 expected0 expected1 expected2 read0 read1 read2 restore_ok write_mask rc').split())

PREFIX=re.compile(r'(NA|\d+)/([IE])/BTH/([A-Z0-9]+)/([A-Z]+) \| (zephyr_\w+) (.+) !')

class Restart:
    @staticmethod
    def analyze(text,m, *, continuation=False, ram_mapping=None, round_start=1, end_step=None):
        observing=layered(m)
        errors=[];missing=[];boot=[];rows=[];samples=[];last_time=None;ended=False
        expected_boot=[('begin',dict(version=1,test=8,build=int(m['build'],0))),
            ('stage',dict(stage='adapter_ready')),('adapter',dict(cpuid=0x630f1321,ipsr=0,control=0)),
            ('image',dict(layout=0x50001,verified=1)),('uart',dict(ibrd=1,fbrd=19)),
            ('state',dict(cache=0,mpu=0,systick=0)),
            *[('stage',dict(stage=x)) for x in ('handoff','reset','early','main')]]
        lines=text.splitlines()
        for line_index,line in enumerate(lines):
            if ended and 'zephyr_' not in line:continue
            match=PREFIX.fullmatch(line)
            if not match:
                if line_index==len(lines)-1 and not line.endswith(' !') and not ended:
                    missing.append('truncated last record');continue
                errors.append('malformed prefix/record');continue
            ts,level,module,context,namespace,body=match.groups()
            if ts!='NA':
                now=int(ts)
                if now>0xffffffffffffffff or (last_time is not None and now<last_time):errors.append('timestamp order')
                last_time=now
            kind,*words=body.split()
            if kind.startswith('stage='):words.insert(0,kind);kind='stage'
            try:
                pairs=[x.split('=',1) for x in words]
                d={k:(v if k=='stage' and namespace=='zephyr_bth' else int(v,0)) for k,v in pairs}
                if len(d)!=len(pairs):raise ValueError()
                if any(isinstance(v,int) and not 0<=v<=0xffffffffffffffff for v in d.values()):raise ValueError()
            except ValueError:errors.append('invalid fields');continue
            if ended:errors.append('record after result')
            if level!='I' or d.get('rc',0) or d.get('error',0):errors.append('runtime error')
            if namespace=='zephyr_bth':
                if rows or samples or len(boot)>=len(expected_boot) or (kind,d)!=expected_boot[len(boot)]:errors.append('boot order/identity')
                if (module,context)!=prefix_contract(namespace+' '+body+' !'):errors.append('boot prefix')
                if ts=='NA' and kind not in ('begin','adapter') and d.get('stage')!='adapter_ready':errors.append('late NA')
                boot.append((kind,d));continue
            if namespace!=LOG_NAMESPACE or (module,context)!=(LOG_MODULE,'MAIN') or ts=='NA':errors.append('LIFECYCLE prefix/namespace')
            record=dict(kind=kind,time=int(ts) if ts!='NA' else 0,fields=d)
            if kind=='sample':
                if not rows or rows[0]['kind']!='begin':errors.append('sample before begin')
                i=len(samples)
                if set(d)!=set('id ms ticks timer stack guards rc'.split()) or d.get('id')!=i:
                    errors.append('sample fields/order')
                    if set(d)!=set('id ms ticks timer stack guards rc'.split()):continue
                else:
                    if d['rc'] or d['guards']!=1 or d['stack']<128 or not i*1000<=d['ms']<=i*1000+100:errors.append('sample health/time')
                    if abs(d['timer']-d['ms']//100)>2 or abs(d['ticks']-d['ms']*6000)>max(60000,d['ms']*60):errors.append('sample clocks')
                    if samples and (d['ticks']<=samples[-1]['fields']['ticks'] or abs((record['time']-samples[0]['time'])-(d['ms']-samples[0]['fields']['ms']))>max(10,d['ms']//100)):
                        errors.append('sample counter/prefix drift')
                samples.append(record)
            else:
                rows.append(record)
                if kind=='result':ended=True
        expected=[] if continuation else [('begin',None,None)]
        for n in (range(round_start,round_start+1) if continuation else range(11)):
            expected += [('event',n,1)]+([('repark',n,7)] if n else [])+[('event',n,x) for x in (2,3)]+[('reset',n,3),('event',n,4),('ready',n,None)]+[('endpoint',n,x) for x in (0,1)]+[('peer',n,None)]+[('event',n,x) for x in (5,6)]+[('reset',n,4),('event',n,7),('hardware',n,None),('event',n,8),('session',n,None)]
        if continuation and end_step is not None:
            expected=expected[:expected.index(('event',round_start,end_step))+1]
        if not continuation and not observing:expected += [('result',None,None)]
        actual=[(r['kind'],r['fields'].get('round'),r['fields'].get('step' if r['kind']=='event' else 'op' if r['kind'] in ('reset','repark') else 'side')) for r in rows]
        if actual!=expected[:len(actual)]:errors.append('lifecycle order/missing/duplicate')
        if len(rows)!=len(expected):missing.append('lifecycle incomplete')
        if not continuation and boot!=expected_boot:missing.append('boot incomplete')
        if not continuation and not observing and len(samples)!=601:missing.append(f'samples {len(samples)}/601')
        if not continuation and observing and not samples:missing.append('samples')
        if continuation and (boot or samples):errors.append('unexpected continuation boot/sample')
        if m.get('lifecycle_log')!=LOG_CONTRACT:errors.append('lifecycle log contract')
        if m.get('restart_version')!=4 or m.get('restart_rounds')!=(2 if continuation else 11) or m.get('restart_target')!=1000 or m.get('dual_layout')!='0x000a0004' or m.get('duration_seconds')!=600 or m.get('lifecycle')!=LIFECYCLE or m.get('reset_diagnostic')!=RESET_DIAGNOSTIC or m.get('repark_diagnostic')!=REPARK_DIAGNOSTIC:errors.append('manifest contract')
        sampler=m.get('reset_sampler',0)
        if not isinstance(sampler,int) or not sampler&1 or not 0x00500000<=sampler<0x00510000:errors.append('sampler manifest')
        endpoints={};elapsed={};origins={};release_time={}
        pause=m.get('_gpio_irq_pause_ms', 0) if get_profile(m['validation_profile']).gpio_irq else 0
        for r in rows:
            k=r['kind'];d=r['fields'];n=d.get('round');session=n+1 if n is not None else None
            fieldsets={'event':'round session step rc elapsed','ready':'round session peer_ms beat stack elapsed rc',
                       'peer':'round session ms beat cycles elapsed stack guards rc',
                       'hardware':'round session phase reset_clr ram_sel0 ram_sel1 core_vtor rc',
                       'session':'round session elapsed reset_held peer_idle channel_clean rc'}
            if k in fieldsets and set(d)!=set(fieldsets[k].split()):
                errors.append('lifecycle fields');continue
            if k=='begin':
                if d!=dict(version=4,layout=0xa0004,build=int(m['build'],0),m55_build=int(m['m55_build'],0),pair=m['message_pair'],rounds=11,restarts=10,target=1000,duration=600,rc=0):errors.append('begin identity')
            elif k=='repark':
                if set(d)!=REPARK_FIELDS:
                    errors.append('repark fields');continue
                if (any(v>0xffffffff for v in d.values()) or d['session']!=session or
                    d['version']!=1 or d['op']!=7 or d['phase_before']!=4 or d['phase_after']!=2 or
                    any(d[x] for x in ('reason','service_rc','rc')) or
                    (d['reset_before']|d['reset_after'])&16 or
                    d['sel0_before']&(7<<27)!=3<<27 or
                    d['sel0_axi']!=d['sel0_before']&~(7<<27) or
                    d['sel0_after']!=d['sel0_before'] or
                    d['sel1_before']!=d['sel1_axi'] or d['sel1_before']!=d['sel1_after'] or
                    ram_mapping!=(d['sel0_before'],d['sel1_before']) or
                    d['restore_ok']!=1 or d['write_mask']!=7 or
                    [d['phys'+str(i)] for i in range(3)]!=REPARK_DIAGNOSTIC['physical_words'] or
                    [d['expected'+str(i)] for i in range(3)]!=REPARK_DIAGNOSTIC['expected_words'] or
                    [d['read'+str(i)] for i in range(3)]!=REPARK_DIAGNOSTIC['expected_words']):
                    errors.append('repark mapping/readback')
            elif k=='reset':
                if set(d)!=RESET_FIELDS:
                    errors.append('reset fields');continue
                if (d['session']!=session or d['version']!=1 or d['op'] not in (3,4) or
                    any(d[x] for x in ('reason','service_rc','diag_error','primask','rc')) or
                    d['sampler']!=sampler or not d['reset_before']&16 or d['reset_after']&16 or
                    d['timer_ctrl']&0x82!=0x82 or not 1<=d['polls']<=1024 or
                    d['samples']!=d['polls']+1 or not d['samples']<=d['attempts']<=32*d['samples'] or
                    not 1<=d['max_attempts']<=min(32,d['attempts']) or
                    not 0<=d['last_a']-d['last_b']<=20 or d['max_delta']<d['last_a']-d['last_b'] or
                    d['elapsed']!=(d['raw_end']-d['raw_start'])&0xffffffff or d['elapsed']>=60000):
                    errors.append('reset sampling/readback')
            elif k=='event':
                if set(d)!=set('round session step rc elapsed'.split()) or d['session']!=session or not 0<=d['elapsed']<=45000+(pause+100 if n==0 else 0):errors.append('event identity/deadline')
                if d['step']==1:origins[n]=r['time']
                if d['step']==4:release_time[n]=r['time']
                if d['elapsed']<elapsed.get(n,0):errors.append('elapsed regression')
                elapsed[n]=d['elapsed']
                if abs(r['time']-origins.get(n,r['time'])-d['elapsed'])>30:errors.append('event elapsed drift')
            elif k=='ready':
                if set(d)!=set('round session peer_ms beat stack elapsed rc'.split()) or d['session']!=session or d['peer_ms']>5000 or not d['beat'] or d['stack']<128 or not 0<=r['time']-release_time.get(n,r['time'])<=5100:errors.append('ready contract')
            elif k=='endpoint':
                if set(d)!=FIELDS|{'round','side'}:errors.append('endpoint fields');continue
                side=d['side'];fixed=dict(magic=0x35534d42,version=2,layout=0x90001,pair=m['message_pair'],build=int(m['build' if side==0 else 'm55_build'],0),session=session,phase=6,stage=2,sent=1000,acked=1000,handled=1000,rejected=0,spurious=0,pauses=0,error=0,guard=0x91c75a35,len0=0xffffffff,len1=0xffffffff,len2=0xffffffff,len3=1,depth=16)
                if any(d.get(key)!=value for key,value in fixed.items()):errors.append('endpoint state/accounting')
                if d['done']!=d['kicks'] or not 0<d['kicks']<=d['requests'] or d['queued']>d['requests'] or d['stack']<128 or d['max_wait']>2000 or not 0<d['stop_ms']<=d['elapsed']<=30000:errors.append('endpoint limits')
                endpoints[n,side]=d
            elif k=='hardware':
                mapping=(d['ram_sel0'],d['ram_sel1'])
                if ram_mapping is None:ram_mapping=mapping
                if d['session']!=session or d['phase']!=4 or d['reset_clr']&16 or d['core_vtor']!=0x200c0000 or mapping!=ram_mapping:
                    errors.append('reset readback/RAM retention')
            elif k=='session':
                if set(d)!=set('round session elapsed reset_held peer_idle channel_clean rc'.split()) or d['session']!=session or any(d[x]!=1 for x in ('reset_held','peer_idle','channel_clean')) or not elapsed.get(n,0)<=d['elapsed']<=45000+(pause+100 if n==0 else 0):errors.append('session shutdown')
                a=endpoints.get((n,0));b=endpoints.get((n,1))
                if not a or not b or a['rx']!=b['kicks'] or b['rx']!=a['kicks']:errors.append('IRQ accounting')
            elif k=='peer':
                if set(d)!=set('round session ms beat cycles elapsed stack guards rc'.split()) or d['session']!=session or d['guards']!=1 or d['stack']<128 or not 0<d['ms']<=30000 or abs(d['ms']-d['elapsed'])>250 or not d['beat'] or abs(d['beat']-d['ms']//100)>3 or abs(d['cycles']-d['ms']*24000)>max(24000,d['ms']*240):errors.append('peer heartbeat/cycles')
            elif k=='result':
                if d!={'pass':1,'sessions':11,'restarts':10,'samples':601,'rc':0}:errors.append('final result')
                if missing or len(samples)!=601 or r['time']<samples[-1]['time']:errors.append('early final result')
        if continuation and end_step==5:
            a=endpoints.get((round_start,0));b=endpoints.get((round_start,1))
            if not a or not b or a['rx']!=b['kicks'] or b['rx']!=a['kicks']:errors.append('IRQ accounting')
        status='fail' if errors else 'incomplete' if missing else 'pass'
        s=dict(status=status,errors=errors,missing=missing,records=rows,samples=samples)
        return dict(status=status,session_count=1,sessions=[s])

def analyze(text,manifest,scope='long'):
    try:
        validate_manifest(manifest, restart=True)
    except ValueError as error:
        return dict(status='fail', session_count=0, sessions=[], errors=[str(error)])
    return observation.finalize(analyze_gpio_restart.run(text, manifest,
        lambda data, meta: observation.run(profile, data, meta, Restart.analyze, scope)))


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('log',type=Path)
    ap.add_argument('--manifest',type=Path,required=True);ap.add_argument('--output',type=Path)
    ap.add_argument('--scope',choices=observation.NAMES,default='long')
    a=ap.parse_args();r=analyze(a.log.read_bytes().decode('latin1'),json.loads(a.manifest.read_text()),a.scope)
    text=json.dumps(r,indent=2)+'\n'
    if a.output:a.output.write_text(text)
    print(text,end='');return {'pass':0,'fail':1,'incomplete':2}[r['status']]
if __name__=='__main__':raise SystemExit(main())
