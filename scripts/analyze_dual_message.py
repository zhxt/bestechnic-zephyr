#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Strict message validation scenarios and boot/heartbeat acceptance; exits 0/1/2."""
import argparse
import json
import re
from pathlib import Path
import analyze_dual_boot as heartbeat
import analyze_boot_profile as profile
from validation_profiles import validate_manifest
import analyze_observation as observation

FIELDS=set('magic version layout pair build session phase stage sent acked handled rejected full depth max_wait rx requests kicks done queued spurious stack elapsed stop_ms len0 len1 len2 len3 pauses error guard'.split())
ROW=re.compile(r'(\d+)/([IE])/BTH/IPC/MAIN \| zephyr_msg (begin|progress|case|endpoint|result) (.+) !')
CASES=[5,4,6,7,7,4,4,4,4,3,5]


class Message:
    @staticmethod
    def analyze(text,m):
        lines=text.splitlines();base=[];rows=[];errors=[];missing=[]
        for i,line in enumerate(lines):
            if 'zephyr_msg ' not in line:
                base.append(line);continue
            match=ROW.fullmatch(line)
            if not match:
                errors.append('malformed message record');continue
            ts,level,kind,body=match.groups()
            try:
                pairs=[x.split('=',1) for x in body.split()];d={k:int(v,0) for k,v in pairs}
                if len(d)!=len(pairs) or any(v<0 or v>0xffffffff for v in d.values()):raise ValueError()
            except ValueError:
                errors.append('invalid message fields');continue
            rows.append(dict(index=i,time=int(ts),level=level,kind=kind,fields=d))
        result=heartbeat.analyze('\n'.join(base)+'\n',m)
        if not result['sessions']:return result
        s=result['sessions'][0]
        mode=m['message_mode'];seconds=m['message_seconds'];pair=m['message_pair']
        if (m.get('message_version')!=2 or m.get('message_layout')!=0x90001 or m.get('progress_period')!=10):
            errors.append('message manifest contract')
        expected=[('begin',None,None,None)]
        if mode==2:expected += [('progress',i,side,None) for i in range(10,seconds,10) for side in (0,1)]
        if mode==3:expected += [('case',None,None,i) for i in range(1,12)]
        expected += [('endpoint',None,0,None),('endpoint',None,1,None),('result',None,None,None)]
        actual=[(r['kind'],r['fields'].get('sample'),r['fields'].get('side'),r['fields'].get('id')) for r in rows]
        if actual!=expected[:len(actual)]:errors.append('message record order/missing/duplicate')
        if len(rows)!=len(expected):missing.append('message progress/cases/endpoints/result')
        if any(r['level']!='I' for r in rows):errors.append('message error severity')
        samples={}
        for i,line in enumerate(lines):
            match=re.match(r'(\d+)/I/BTH/KERN/MAIN \| zephyr_dual sample id=(\d+) ',line)
            if match:samples[int(match[2])]=(i,int(match[1]))
        stages=[i for i,line in enumerate(lines) if 'zephyr_dual stage id=7 rc=0' in line]
        if rows:
            b=rows[0]
            if b['fields']!=dict(version=2,channel=1,duration=seconds,progress_period=10,mode=mode,
                                 layout=0x90001,pair=pair,depth=16,payload=96):errors.append('message begin identity')
            if not stages or (0 in samples and not stages[-1]<b['index']<samples[0][0]):errors.append('message begin position')
        previous={};ends=[];sessions=set()
        for row in rows:
            kind=row['kind'];d=row['fields']
            if kind=='case':
                case=d.get('id',0)
                if not 1<=case<=11 or d!=dict(id=case,expected=CASES[case-1],bth=CASES[case-1],m55=CASES[case-1]):
                    errors.append('negative case mismatch')
                continue
            if kind not in ('progress','endpoint'):continue
            progress=kind=='progress'
            if set(d)!=FIELDS|{'side'}|({'sample'} if progress else set()) or d['side'] not in (0,1):
                errors.append('message endpoint fields');continue
            side=d['side'];sessions.add(d['session'])
            fixed=dict(magic=0x35534d42,version=2,layout=0x90001,pair=pair,
                build=int(m['build' if side==0 else 'm55_build'],0),phase=2 if progress else 6,
                stage=1 if mode==2 else 2 if mode==1 else 15,rejected=11 if mode==3 else 0,
                error=0,spurious=0,guard=0x91c75a35)
            if any(d[k]!=v for k,v in fixed.items()):errors.append('message identity/state')
            if (not d['session'] or not 0<=d['acked']<=d['sent']<=0x7fffffff or d['sent']-d['acked']>16 or
                d['handled']>0x7fffffff or d['depth']!=16 or d['max_wait']>2000 or d['stack']<128 or
                d['pauses']>1 or not 0<=d['done']<=d['kicks']<=d['requests'] or d['queued']>d['requests']):
                errors.append('message counters/window/deadline')
            if side in previous:
                old=previous[side]
                if any(d[k]<=old[k] for k in ('sent','acked','handled','elapsed')):errors.append('message traffic stalled/regressed')
                if any(d[k]<old[k] for k in ('rx','requests','kicks','done','queued','full','pauses','max_wait')):
                    errors.append('message statistics regression')
            previous[side]=d
            if progress:
                sample=d['sample']
                if d['stop_ms'] or not sample*1000-2500<=d['elapsed']<=sample*1000+1000:errors.append('message stale/early progress')
                if sample not in samples or not (row['index']>samples[sample][0] and 0<=row['time']-samples[sample][1]<=100):
                    errors.append('message progress position/time')
            else:
                ends.append(d)
                if d['sent']!=d['acked'] or d['done']!=d['kicks'] or any(d[f'len{i}']!=(1 if i==3 else 0xffffffff) for i in range(4)):
                    errors.append('message final accounting/length coverage')
                if mode==2:
                    if (d['sent']<100000 or not d['full'] or d['pauses']!=1 or
                        not seconds*1000<=d['stop_ms']<=seconds*1000+2000 or
                        not d['stop_ms']<=d['elapsed']<=seconds*1000+5000):errors.append('message final load/duration')
                elif d['sent']!=10000 or d['handled']!=10000 or d['pauses'] or not 0<d['stop_ms']<=d['elapsed']<590000:
                    errors.append('message sequential final state')
        if len(sessions)>1:errors.append('message session mismatch')
        if len(ends)==2:
            a,b=ends
            if a['sent']!=b['handled'] or b['sent']!=a['handled'] or a['rx']!=b['kicks'] or b['rx']!=a['kicks']:
                errors.append('message cross-core accounting')
        finals=[r for r in rows if r['kind']=='result']
        if finals:
            f=finals[-1]
            if len(ends)!=2 or f['fields']!=dict(finished=1,rc=0,session=ends[0]['session']):errors.append('message final result')
            elapsed=f['time']-rows[0]['time']
            if not (seconds*1000<=elapsed<=seconds*1000+5500 if mode==2 else 0<elapsed<590000):errors.append('message final time')
            if any('zephyr_dual result ' in line for line in lines[:f['index']]):errors.append('late message result')
        if any('zephyr_dual result pass=1' in line for line in lines) and missing:errors.append('heartbeat pass without message evidence')
        s['errors']+=errors;s['missing']+=missing;s['message_records']=rows
        s['status']='fail' if s['errors'] else 'incomplete' if s['missing'] else 'pass'
        result['status']=s['status'];return result


def analyze(text,manifest,scope='long'):
    try:
        validate_manifest(manifest)
    except ValueError as error:
        return dict(status='fail', session_count=0, sessions=[], errors=[str(error)])
    return observation.run(profile, text, manifest, Message.analyze, scope)


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('log',type=Path)
    ap.add_argument('--manifest',type=Path,required=True);ap.add_argument('--output',type=Path)
    ap.add_argument('--scope',choices=observation.NAMES,default='long')
    args=ap.parse_args();r=analyze(args.log.read_bytes().decode('latin1'),json.loads(args.manifest.read_text()), args.scope)
    text=json.dumps(r,indent=2)+'\n'
    if args.output:args.output.write_text(text)
    print(text,end='');return {'pass':0,'fail':1,'incomplete':2}[r['status']]


if __name__=='__main__':raise SystemExit(main())
