# SPDX-License-Identifier: Apache-2.0
import unittest
from analyze_dual_restart import analyze
from test_message_parser import fixture as q_fixture,manifest as q_manifest

def manifest():
    return dict(q_manifest('ipc-sequential'),validation_profile='m55-restart',restart_version=4,restart_rounds=11,
                restart_target=1000,dual_layout='0x000a0004',reset_sampler=0x00502001,
                reset_diagnostic=dict(version=1,address=0x2055c1a0,bytes=80,read_attempts=32,poll_limit=1024),
                repark_diagnostic=dict(version=1,address=0x2055c800,bytes=100,bank=9,selector_mask=7<<27,
                    physical_words=[0x20320000,0x20320004,0x20330000],
                    expected_words=[0x2015ffe0,0x200c0009,0xe7fdbf30]),
                lifecycle=dict(layout=0x000a0004,address=0x2015e280,bytes=128,rounds=11,
                               target=1000,observe_seconds=600,ready_ms=5000,
                               message_ms=30000,quiesce_ms=5000,reset_ms=10))

def fixture(m=None):
    m=manifest() if m is None else m
    boot=[l for l in q_fixture(m).splitlines() if 'zephyr_bth ' in l or 'zephyr_bootprof ' in l]
    rows=[]
    def row(time,kind,**fields):
        rows.append((time,f'{time}/I/BTH/R1/MAIN | zephyr_r1 {kind} '+' '.join(f'{k}={v}' for k,v in fields.items())+' !'))
    row(1999,'begin',version=4,layout=0xa0004,build=int(m['build'],0),m55_build=int(m['m55_build'],0),pair=m['message_pair'],rounds=11,restarts=10,target=1000,duration=600,rc=0)
    for n in range(11):
        base=2100+n*5000
        for step,elapsed in ((1,0),(2,2),(3,1000),(4,1001),(5,3003),(6,3100),(7,3101),(8,3102)):
            row(base+elapsed,'event',round=n,session=n+1,step=step,rc=0,elapsed=elapsed)
        if n:
            row(base+1,'repark',round=n,session=n+1,version=1,op=7,service_rc=0,
                phase_before=4,phase_after=2,reason=0,reset_before=0x581,reset_after=0x581,
                sel0_before=460165705,sel1_before=112347,sel0_axi=460165705&~(7<<27),
                sel1_axi=112347,sel0_after=460165705,sel1_after=112347,
                phys0=0x20320000,phys1=0x20320004,phys2=0x20330000,
                expected0=0x2015ffe0,expected1=0x200c0009,expected2=0xe7fdbf30,
                read0=0x2015ffe0,read1=0x200c0009,read2=0xe7fdbf30,restore_ok=1,write_mask=7,rc=0)
        for op,elapsed in ((3,1000),(4,3100)):
            row(base+elapsed,'reset',round=n,session=n+1,version=1,op=op,reason=0,service_rc=0,
                polls=1,samples=2,attempts=2,max_attempts=1,last_a=1000,last_b=999,max_delta=1,
                elapsed=60,reset_before=0x591,reset_after=0x581,timer_ctrl=0x82,diag_error=0,
                sampler=m['reset_sampler'],raw_start=100,raw_end=160,primask=0,rc=0)
        row(base+1002,'ready',round=n,session=n+1,peer_ms=100,beat=1,stack=2000,elapsed=1002,rc=0)
        for side in (0,1):
            row(base+3000+side,'endpoint',round=n,side=side,magic=0x35534d42,version=2,layout=0x90001,pair=m['message_pair'],
                build=int(m['build' if side==0 else 'm55_build'],0),session=n+1,phase=6,stage=2,
                sent=1000,acked=1000,handled=1000,rejected=0,full=60,depth=16,max_wait=20,
                rx=130,kicks=130,done=130,requests=130,queued=1,spurious=0,stack=2000,elapsed=2000,
                stop_ms=1990,len0=0xffffffff,len1=0xffffffff,len2=0xffffffff,len3=1,pauses=0,error=0,guard=0x91c75a35)
        row(base+3002,'peer',round=n,session=n+1,ms=2000,beat=20,cycles=48000000,elapsed=2000,stack=2000,guards=1,rc=0)
        row(base+3101,'hardware',round=n,session=n+1,phase=4,reset_clr=0x581,ram_sel0=460165705,ram_sel1=112347,core_vtor=0x200c0000,rc=0)
        row(base+3103,'session',round=n,session=n+1,elapsed=3103,reset_held=1,peer_idle=1,channel_clean=1,rc=0)
    for i in range(601):
        row(2000+i*1000,'sample',id=i,ms=i*1000,ticks=i*6000000,timer=i*10,stack=1600,guards=1,rc=0)
    row(602001,'result',**{'pass':1,'sessions':11,'restarts':10,'samples':601,'rc':0})
    return '\n'.join(boot+[s for _,s in sorted(rows,key=lambda x:x[0])])+'\n'

class RestartParser(unittest.TestCase):
    def test_entry_diagnostic_cannot_be_accepted_as_success(self):
        text=fixture();m=manifest()
        line='1999/E/BTH/R1/MAIN | zephyr_r1 precheck dispatch=872437209 service_layout=655364 service_errors=8 state_errors=0 rc=1 !\n'
        position=text.index('2000/I/BTH/R1')
        r=analyze(text[:position]+line+text[position:],m)
        self.assertEqual(r['status'],'fail')
        self.assertTrue(any(record['kind']=='precheck' for record in r['sessions'][0]['records']))

    def test_complete_and_incomplete(self):
        m=manifest();text=fixture(m);r=analyze(text,m)
        self.assertEqual(r['status'],'pass',r)
        self.assertEqual(analyze(text[:text.index('10000/I/BTH/R1')],m)['status'],'incomplete')
        self.assertEqual(analyze(text+text[:text.index('10000/I/BTH/R1')],m)['status'],'incomplete')
        self.assertEqual(analyze(text[:-20],m)['status'],'incomplete')

    def test_faults_and_missing_evidence(self):
        m=manifest();text=fixture(m)
        replacements=[('reset_held=1','reset_held=0'),('peer_idle=1','peer_idle=0'),
            ('channel_clean=1','channel_clean=0'),('reset_clr=1409','reset_clr=1425'),
            ('ram_sel0=460165705','ram_sel0=0'),('core_vtor=537657344','core_vtor=0'),('restarts=10','restarts=9'),
            ('session=2','session=1'),('acked=1000','acked=999'),('handled=1000','handled=999'),
            ('len3=1','len3=0'),('phase=6','phase=5'),('error=0 guard=2445761077','error=10 guard=2445761077'),
            ('kicks=130','kicks=129'),('guards=1','guards=0'),('step=7','step=8'),
            ('/I/BTH/R1/MAIN','/I/BTH/IPC/MAIN'),('NA/I/BTH/BOOT/EARLY | ','')]
        for old,new in replacements:
            with self.subTest(old=old):
                self.assertIn(old,text);self.assertEqual(analyze(text.replace(old,new,1),m)['status'],'fail')
        lines=text.splitlines()
        for token in ('zephyr_r1 ready round=3','zephyr_r1 session round=9','zephyr_r1 sample id=500'):
            self.assertEqual(analyze('\n'.join(l for l in lines if token not in l)+'\n',m)['status'],'fail')
        self.assertEqual(analyze(q_fixture(),m)['status'],'fail')

    def test_wrong_manifest_budgets_and_old_abi_fail(self):
        text=fixture()
        for key in manifest()['lifecycle']:
            m=manifest();m['lifecycle'][key]+=1
            with self.subTest(key=key):
                self.assertEqual(analyze(text,m)['status'],'fail')
        m=manifest();m['restart_version']=1;m['dual_layout']='0x000a0001'
        self.assertEqual(analyze(text,m)['status'],'fail')
        m=manifest();m['restart_version']=2;m['dual_layout']='0x000a0002'
        self.assertEqual(analyze(text,m)['status'],'fail')
        m=manifest();m['restart_version']=3;m['dual_layout']='0x000a0003'
        self.assertEqual(analyze(text,m)['status'],'fail')

    def test_repark_mapping_and_readback(self):
        text=fixture();m=manifest()
        line=next(l for l in text.splitlines() if 'zephyr_r1 repark round=1 ' in l)
        for key in ('version','op','service_rc','phase_before','phase_after','reason',
                    'reset_before','reset_after','sel0_before','sel1_before','sel0_axi',
                    'sel1_axi','sel0_after','sel1_after','phys0','phys1','phys2',
                    'expected0','expected1','expected2','read0','read1','read2','restore_ok','write_mask'):
            import re
            value=int(re.search(r'\b'+key+r'=(\d+)',line)[1])
            replacement=value^16 if key.startswith('reset_') else value+1
            with self.subTest(key=key):
                broken=re.sub(r'\b'+key+r'=\d+',key+'='+str(replacement),line)
                self.assertEqual(analyze(text.replace(line,broken),m)['status'],'fail')
        self.assertEqual(analyze(text.replace(line+'\n',''),m)['status'],'fail')

    def test_reset_sample_diagnostics(self):
        text=fixture();m=manifest()
        for old,new in [('reason=0','reason=1'),('service_rc=0','service_rc=4294967289'),
                        ('max_attempts=1','max_attempts=33'),('elapsed=60','elapsed=60000'),
                        ('reset_after=1409','reset_after=1425'),('last_b=999','last_b=979'),
                        ('sampler=5242881','sampler=335544321'),('diag_error=0','diag_error=91'),
                        ('polls=1','polls=0'),('raw_end=160','raw_end=159')]:
            with self.subTest(old=old):
                if old.startswith('sampler='):
                    old='sampler='+str(m['reset_sampler'])
                self.assertIn(old,text)
                self.assertEqual(analyze(text.replace(old,new,1),m)['status'],'fail')
        lines=text.splitlines()
        self.assertEqual(analyze('\n'.join(l for l in lines if 'zephyr_r1 reset round=2' not in l)+'\n',m)['status'],'fail')

    def test_each_missing_field_fails_without_crash(self):
        text=fixture();m=manifest();lines=text.splitlines()
        for kind in ('event','reset','repark','ready','endpoint','peer','hardware','session','sample','result'):
            line=next(x for x in lines if 'zephyr_r1 '+kind+' ' in x)
            prefix,body=line.split(' | ',1)
            parts=body.split()
            for i in range(2,len(parts)-1):
                with self.subTest(kind=kind,field=parts[i]):
                    broken=prefix+' | '+' '.join(parts[:i]+parts[i+1:])
                    self.assertEqual(analyze(text.replace(line,broken,1),m)['status'],'fail')
