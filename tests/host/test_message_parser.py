# SPDX-License-Identifier: Apache-2.0
import json
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from fixture_test_concurrent_parser import fixture as old_fixture, manifest as old_manifest
from analyze_dual_message import analyze, CASES


def manifest(package='ipc-backpressure'):
    mode,seconds,heartbeat={'ipc-sequential':(1,600,600),'ipc-backpressure':(2,600,610),'ipc-fault-injection':(3,600,600),'ipc-backpressure-1h':(2,3600,3610)}[package]
    return dict(old_manifest(),validation_schema=1,validation_profile=package,message_mode=mode,message_seconds=seconds,
                duration_seconds=heartbeat,message_version=2,message_layout=0x90001,
                message_pair=12345,progress_period=10)


def fixture(m=None):
    m=manifest() if m is None else m;old=old_manifest();mode=m['message_mode'];seconds=m['message_seconds']
    text='\n'.join(x for x in old_fixture().splitlines() if not any(k in x for k in ('zephyr_cc ','zephyr_dual sample ','zephyr_dual result ')))
    for key in ('build','m55_build'):text=text.replace(old[key],m[key])
    for field,key in [('profile','profile_id'),('bytes','code_bytes'),('expected_crc','crc32'),('sampler','profile_sampler')]:
        value=m[key];value=int(value,0) if isinstance(value,str) else value
        text=re.sub(r'\b'+field+r'=\d+',field+'='+str(value),text)
    text=text.replace('crc='+str(old['crc32']),'crc='+str(m['crc32']))
    text=text.replace('duration=600','duration='+str(m['duration_seconds']))
    lines=text.splitlines()
    lines.append(f"0/I/BTH/IPC/MAIN | zephyr_msg begin version=2 channel=1 duration={seconds} progress_period=10 mode={mode} layout=589825 pair={m['message_pair']} depth=16 payload=96 !")
    finish=seconds+1 if mode==2 else 40
    def endpoint(side,sample,final=False):
        sent=10000 if mode!=2 else (seconds if final else sample)*1000
        d=dict(side=side,magic=0x35534d42,version=2,layout=0x90001,pair=m['message_pair'],
            build=int(m['build' if side==0 else 'm55_build'],0),session=100,phase=6 if final else 2,
            stage=1 if mode==2 else 2 if mode==1 else 15,sent=sent,acked=sent if final else sent-16,
            handled=sent,rejected=11 if mode==3 else 0,full=sample,depth=16,max_wait=201,
            rx=sent,kicks=sent,done=sent,requests=sent+2,queued=2,spurious=0,stack=2000,
            elapsed=seconds*1000+2 if final and mode==2 else sample*1000-1000,
            stop_ms=(seconds*1000 if mode==2 else 38000) if final else 0,
            len0=0xffffffff,len1=0xffffffff,len2=0xffffffff,len3=1,pauses=1 if mode==2 else 0,error=0,guard=0x91c75a35)
        if not final:d['sample']=sample
        return f"{sample*1000+120+side}/I/BTH/IPC/MAIN | zephyr_msg {'endpoint' if final else 'progress'} "+' '.join(f'{k}={v}' for k,v in d.items())+' !'
    for i in range(m['duration_seconds']+1):
        cycles=i*24000000
        lines.append(f'{i*1000+100}/I/BTH/KERN/MAIN | zephyr_dual sample id={i} ms={i*1000} ticks={i*6000000} timer={i*10} m55_ms={i*1000} beat={i*10} cycles_hi={cycles>>32} cycles_lo={cycles&0xffffffff} bth_stack=2500 m55_stack=2500 guards=1 rc=0 !')
        if mode==2 and i and i%10==0 and i<seconds:lines += [endpoint(0,i),endpoint(1,i)]
        if i==finish:
            if mode==3:
                lines += [f'{i*1000+101+c}/I/BTH/IPC/MAIN | zephyr_msg case id={c+1} expected={e} bth={e} m55={e} !' for c,e in enumerate(CASES)]
            lines += [endpoint(0,i,True),endpoint(1,i,True),f'{i*1000+123}/I/BTH/IPC/MAIN | zephyr_msg result finished=1 rc=0 session=100 !']
    lines.append(f"{m['duration_seconds']*1000+130}/I/BTH/KERN/MAIN | zephyr_dual result pass=1 samples={m['duration_seconds']+1} rc=0 !")
    return '\n'.join(lines)+'\n'


class MessageParser(unittest.TestCase):
    def test_profiles_partial_and_boot_isolation(self):
        for package in ('ipc-sequential','ipc-backpressure','ipc-fault-injection','ipc-backpressure-1h'):
            with self.subTest(package=package):
                m=manifest(package);data=fixture(m);r=analyze(data,m)
                self.assertEqual(r['status'],'pass',r['sessions'][0]['errors'])
                partial=data.split('2100/I/BTH/KERN/MAIN')[0]
                self.assertEqual(analyze(partial,m)['status'],'incomplete')
                self.assertEqual(analyze(data+partial,m)['status'],'incomplete')
                self.assertEqual(analyze(old_fixture(),m)['status'],'fail')

    def test_missing_progress_and_corruption(self):
        m=manifest();data=fixture(m);lines=data.splitlines()
        indices=[i for i,x in enumerate(lines) if 'zephyr_msg progress ' in x]
        for i in (indices[0],indices[len(indices)//2],indices[-1]):
            self.assertEqual(analyze('\n'.join(lines[:i]+lines[i+1:])+'\n',m)['status'],'fail')
        for old,new in [('phase=6','phase=5'),('stop_ms=600000','stop_ms=3000'),
                        ('acked=19984','acked=9984'),('len3=1','len3=0'),('guard=2445761077','guard=0'),
                        ('stack=2000','stack=64'),('max_wait=201','max_wait=2001'),('spurious=0','spurious=1'),
                        ('rc=0 session=100','rc=3 session=100'),('NA/I/BTH/BOOT/EARLY | ','')]:
            with self.subTest(old=old):
                self.assertTrue(old in data,old)
                self.assertEqual(analyze(data.replace(old,new,-1 if old=='len3=1' else 1),m)['status'],'fail')

    def test_negative_case_evidence(self):
        m=manifest('ipc-fault-injection');data=fixture(m);lines=data.splitlines()
        for i,line in enumerate(lines):
            if 'zephyr_msg case ' in line:
                self.assertEqual(analyze('\n'.join(lines[:i]+lines[i+1:])+'\n',m)['status'],'fail')
                wrong=re.sub(r'm55=\d+','m55=0',line)
                self.assertEqual(analyze(data.replace(line,wrong),m)['status'],'fail')
        for old,new in [('rejected=11','rejected=10'),('stage=15','stage=14')]:
            self.assertEqual(analyze(data.replace(old,new,1),m)['status'],'fail')

    def test_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'layout.json').write_text(json.dumps(manifest()))
            for data,code in [(fixture(),0),(fixture().replace('phase=6','phase=5'),1),
                              (fixture().split('2100/I/BTH/KERN/MAIN')[0],2)]:
                (root/'capture.cap').write_text(data)
                r=subprocess.run([sys.executable,str(Path(__file__).resolve().parents[2] / 'scripts/analyze_dual_message.py'),
                    str(root/'capture.cap'),'--manifest',str(root/'layout.json')],capture_output=True)
                self.assertEqual(r.returncode,code,r.stderr)
