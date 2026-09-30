# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
import analyze_gpio_irq as parser
from audit_resources import check_gpio_irq_scope

class GpioIrq(unittest.TestCase):
    def test_actual_service_context_and_error_contract(self):
        with tempfile.TemporaryDirectory() as directory:
            exe=str(Path(directory)/'service')
            subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror',
                '-fsanitize=undefined','-fno-sanitize-recover=all',
                '-I',str(ROOT/'include/bestechnic/bes2700yp'),
                '-I',str(ROOT.parent/'modules/hal/bestechnic/include'),
                str(ROOT/'tests/dual_message/gpio_irq_service.c'),
                str(ROOT/'platforms/bes2700yp/resources/contract.c'),'-o',exe],check=True)
            subprocess.run([exe],check=True,timeout=10)

    def test_actual_client_discovery_and_errno_mapping(self):
        with tempfile.TemporaryDirectory() as directory:
            exe=str(Path(directory)/'client')
            subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror',
                '-fsanitize=undefined','-fno-sanitize-recover=all',
                '-I',str(ROOT/'include/bestechnic/bes2700yp'),
                *[str(ROOT/path) for path in ('tests/dual_message/gpio_irq_client.c',
                    'platforms/bes2700yp/resources/contract.c',
                    'platforms/bes2700yp/resources/gpio_irq_contract.c',
                    'platforms/bes2700yp/resources/gpio_irq_client.c',
                    'platforms/bes2700yp/boot/service_contract.c')],'-o',exe],check=True)
            subprocess.run([exe],check=True,timeout=10)

    def test_irq_service_global_mask_audit(self):
        name='bes_gpio_irq_dispatch'
        with self.assertRaisesRegex(ValueError,'under PRIMASK'):
            check_gpio_irq_scope([(0,'cpsid','i'),(4,'bl','100 <bes2700yp_gpio_irq_ack>'),(8,'bx','lr')],name)
        check_gpio_irq_scope([(0,'cpsid','i'),(2,'msr','PRIMASK, r4'),
                              (4,'bl','100 <bes2700yp_gpio_irq_ack>'),(8,'bx','lr')],name)

    def test_irq_evidence_requires_events_masking_and_complete_stages(self):
        m, text=fixture()
        self.assertEqual(parser.evidence(text,m)[2:4],([],[]))
        for old,new in [('evidence=1','evidence=0'),('mode=0 target=1','mode=1 target=1'),
                        ('count0=10 count1=10','count0=9 count1=10'),('route=196608','route=196609'),
                        ('irq=0 events0=0 events1=0 ms=','irq=1 events0=0 events1=0 ms=')]:
            with self.subTest(old=old):
                self.assertTrue(parser.evidence(text.replace(old,new,1),m)[2])
        self.assertTrue(parser.evidence('\n'.join(x for x in text.splitlines() if ' result ' not in x),m)[3])


    def test_irq_profiles_reject_legacy_observation_contract(self):
        from validation_profiles import validate_manifest
        from test_message_parser import manifest
        m=manifest('ipc-sequential')
        m['validation_profile']='gpio-irq-input'
        with self.assertRaisesRegex(ValueError,'layered observation'):
            validate_manifest(m)

    def test_complete_profiles_and_interaction_deadlines(self):
        from analyze_dual_message import analyze as messages
        from analyze_dual_restart import analyze as restart
        from analyze_dual_recovery import analyze as recovery
        for name, analyze in [('gpio-irq-input', messages), ('gpio-irq-restart', restart),
                              ('gpio-irq-recovery', recovery)]:
            m, text = full_fixture(name)
            with self.subTest(profile=name):
                result = analyze(text, m, 'short')
                self.assertEqual(result['status'], 'pass', result)
                bad = text.replace('evidence=1', 'evidence=0', 1)
                self.assertEqual(analyze(bad, m, 'short')['status'], 'fail')
                if name != 'gpio-irq-input':
                    # A user-supplied extension cannot replace actual pre-stage evidence.
                    bad = '\n'.join(x for x in text.splitlines() if 'zephyr_gpio_irq' not in x)
                    self.assertNotEqual(analyze(bad, dict(m, _gpio_irq_pause_ms=60000), 'short')['status'], 'pass')


def fixture():
    m=dict(validation_profile='gpio-irq-input',gpio_irq_service=dict(abi=5,capabilities=64,irq=44,
        priority=3,pins=0x30000,request_bytes=96,snapshot_bytes=64))
    lines=[];time=0;raw=0
    def row(kind,**d):
        lines.append(f'{time}/I/BTH/GPIO/MAIN | zephyr_gpio_irq {kind} '+' '.join(f'{k}={v}' for k,v in d.items())+' !')
    for stage in (1,2,3,4):
        mode=2 if stage==2 else 0 if stage==3 else 1;target=1 if stage in (3,4) else 10
        row('begin',stage=stage,version=1,mode=mode,target=target,pins=0x30000,irq=raw,events0=raw,events1=raw,rc=0)
        def snapshot(checkpoint):
            row('snapshot',stage=stage,checkpoint=checkpoint,mode=mode,enabled=0x30000 if mode else 0,
                mask=0 if mode else 0x30000,edge=0x30000,rising=0x30000 if mode in (0,2) else 0,
                route=0x30000 if mode else 0,wake=0x1011,irq=raw,events0=raw,events1=raw,
                spurious=0,max_cycles=100,overflow=0,fault=0,rc=0)
        snapshot(0)
        for count in range(1,target+1):
            time+=200
            for pin in (16,17):row('cycle',stage=stage,pin=pin,count=count,mode=mode,evidence=int(bool(mode)),ms=count*200,rc=0)
        raw+=target if mode else 0;snapshot(1)
        row('stage_result',stage=stage,**{'pass':1},mode=mode,count0=target,count1=target,target=target,
            irq=target if mode else 0,events0=target if mode else 0,events1=target if mode else 0,ms=target*200,rc=0)
        time+=1
    row('result',stage=4,version=1,**{'pass':1},rc=0)
    return m,'\n'.join(lines)+'\n'


def full_fixture(name):
    import math
    import re
    from validation_profiles import observation_contract
    from test_message_parser import manifest as message_manifest, fixture as message_fixture
    from test_restart_parser import manifest as restart_manifest, fixture as restart_fixture
    from test_recovery_boundaries import manifest as recovery_manifest, fixture as recovery_fixture
    if name == 'gpio-irq-input':
        m = message_manifest('ipc-sequential');text=message_fixture(m)
    elif name == 'gpio-irq-restart':
        m=restart_manifest();text=restart_fixture()
    else:
        m=recovery_manifest(3);text=recovery_fixture(3)
    m.update(validation_profile=name, validation_schema=2, observation=observation_contract(name),
             gpio_service=dict(abi=4, mode=1, capabilities=40, request_bytes=96, snapshot_bytes=64, zephyr_api=True),
             gpio_irq_service=fixture()[0]['gpio_irq_service'])
    lines=[x for x in text.splitlines() if not any(t in x for t in ('zephyr_dual result ',
        'zephyr_lifecycle held ', 'zephyr_lifecycle result ', 'zephyr_lifecycle isolation_result ',
        'zephyr_lifecycle recovery_result '))]
    origin=int(next(x for x in lines if ' sample id=0 ' in x).split('/')[0])
    extra=[];raw=0
    def emit(time,kind,**d):
        extra.append(f'{time}/I/BTH/GPIO/MAIN | zephyr_gpio_irq {kind} '+
                     ' '.join(f'{k}={v}' for k,v in d.items())+' !')
    def stage(start,ident,mode,target,period):
        nonlocal raw
        emit(start,'begin',stage=ident,version=1,mode=mode,target=target,pins=0x30000,
             irq=raw,events0=raw,events1=raw,rc=0)
        def snap(when,point):
            emit(when,'snapshot',stage=ident,checkpoint=point,mode=mode,enabled=0x30000 if mode else 0,
                mask=0 if mode else 0x30000,edge=0x30000,rising=0x30000 if mode in (0,2) else 0,
                route=0x30000 if mode else 0,wake=0x1011,irq=raw,events0=raw,events1=raw,
                spurious=0,max_cycles=100,overflow=0,fault=0,rc=0)
        snap(start,0)
        for count in range(1,target+1):
            for pin in (16,17):
                emit(start+count*period,'cycle',stage=ident,pin=pin,count=count,mode=mode,
                     evidence=int(bool(mode)),ms=count*period,rc=0)
        raw+=target if mode else 0
        end=start+target*period;snap(end,1)
        emit(end,'stage_result',stage=ident,**{'pass':1},mode=mode,count0=target,count1=target,
             target=target,irq=target if mode else 0,events0=target if mode else 0,
             events1=target if mode else 0,ms=target*period,rc=0)
        return end
    if name=='gpio-irq-input':
        start=int(next(x for x in lines if 'zephyr_msg result ' in x).split('/')[0])+1
        for ident in (1,2,3,4):
            start=stage(start,ident,2 if ident==2 else 0 if ident==3 else 1,1 if ident>=3 else 10,200)+1
        final=start
    else:
        ready=int(next(x for x in lines if 'zephyr_lifecycle ready round=0 ' in x).split('/')[0])
        pause=60000
        changed=[]
        for line in lines:
            if 'zephyr_lifecycle ' in line and ' sample id=' not in line:
                when=int(line.split('/')[0])
                if when>ready:
                    line=str(when+pause)+'/'+line.split('/',1)[1]
                    if ((' event ' in line or ' session ' in line) and 'round=0 ' in line) or ' detected ' in line:
                        line=re.sub(r'elapsed=(\d+)',lambda match:'elapsed='+str(int(match[1])+pause),line)
            changed.append(line)
        lines=changed
        stage(ready+1,10,1,10,6000)
        held=int([x for x in lines if 'zephyr_lifecycle session ' in x][-1].split('/')[0])
        final=stage(held+1,11,1,10,200)+1
    ident=4 if name=='gpio-irq-input' else 11
    emit(final,'result',stage=ident,version=1,**{'pass':1},rc=0)
    def checkpoint(time,point,ident):
        emit(time,'snapshot',stage=ident,checkpoint=point,mode=1,enabled=0x30000,mask=0,
             edge=0x30000,rising=0,route=0x30000,wake=0x1011,irq=raw if ident!=10 else 10,
             events0=raw if ident!=10 else 10,events1=raw if ident!=10 else 10,
             spurious=0,max_cycles=100,overflow=0,fault=0,rc=0)
    for line in lines:
        when=int(line.split('/')[0]) if line[0].isdigit() else 0
        sample=re.search(r' sample id=(\d+) ',line)
        if sample and when>final:checkpoint(when+1,1000+int(sample[1]),ident)
        if name!='gpio-irq-input':
            boundary=re.search(r'zephyr_lifecycle (ready|hardware) round=(\d+) ',line)
            if boundary and (name=='gpio-irq-restart' or boundary[2]=='1'):
                point=100+2*int(boundary[2])+(boundary[1]=='hardware')
                checkpoint(when+1+(60000 if point==100 else 0),point,10)

    def observe(when,kind,**d):
        extra.append(f'{when}/I/BTH/OBSERVE/MAIN | zephyr_observe {kind} '+
                     ' '.join(f'{k}={v}' for k,v in d.items())+' !')
    done=final+1-origin
    session=2 if name=='gpio-irq-recovery' else 11 if name=='gpio-irq-restart' else 1
    if name=='gpio-irq-input':
        session=int(re.search(r'session=(\d+)',next(x for x in lines if 'zephyr_msg result ' in x))[1])
    fields=dict(version=1,ms=done,session=session,rc=0)
    if name!='gpio-irq-input':fields.update(releases=session,attempts=int(session==2),recoveries=int(session==2))
    observe(origin+done,'functional',**fields)
    short=math.ceil((done+60000)/1000)*1000
    for scope,ms in ((1,short),(2,600000)):
        if name=='gpio-irq-input':observe(origin+ms+1,'traffic',scope=scope,session=session,finished=1,live=1,rc=0)
        else:observe(origin+ms+1,'held',scope=scope,session=session,local_idle=1,reset_held=1,local_irq=0,peer_irq=81920,rc=0)
        observe(origin+ms+2,'result',version=1,scope=scope,**{'pass':1},session=session,
                functional_ms=done,ms=ms,samples=ms//1000+1,rc=0)
    boot=[x for x in lines if 'zephyr_bth ' in x or 'zephyr_bootprof ' in x]
    rest=[x for x in lines if x not in boot]+extra
    return m,'\n'.join(boot+sorted(rest,key=lambda x:int(x.split('/')[0])))+'\n'
