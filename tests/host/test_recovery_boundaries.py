# SPDX-License-Identifier: Apache-2.0
"""Extended fault evidence and fail-closed recovery acceptance regressions."""
import copy
import unittest
from analyze_dual_recovery import analyze
from test_recovery_parser import fixture as base_fixture, manifest as base_manifest
from test_restart_parser import fixture as restart_fixture
from validation_profiles import get_profile

NAMES={3:'m55-ipc-stall-recovery',4:'m55-quiesce-recovery',5:'m55-fatal-recovery',
       6:'m55-fatal-unreadable-recovery'}
FAILURES={1:'m55-repark-failure',3:'m55-load-failure',5:'m55-recovery-ready-failure'}
REASONS={3:4,4:5,5:6,6:2}


def decode(line):
    time=int(line.split('/')[0]);body=line.split('zephyr_lifecycle ',1)[1].split()
    return time,body[0],dict((k,int(v,0)) for k,v in (x.split('=') for x in body[1:-1]))


def encode(time,kind,**fields):
    return f'{time}/I/BTH/LIFECYCLE/MAIN | zephyr_lifecycle {kind} '+ ' '.join(f'{k}={v}' for k,v in fields.items())+' !'


def manifest(case=3,fail=0):
    return dict(base_manifest(2),validation_profile=FAILURES[fail] if fail else NAMES[case],
                fault_case=2 if fail else case,recovery_fail_step=fail)


def fixture(case=3,fail=0):
    original=base_fixture(2).splitlines()
    boot=[x for x in original if 'zephyr_lifecycle ' not in x]
    rows=[decode(x) for x in original if 'zephyr_lifecycle ' in x]
    if not fail:
        detected={3:5002,4:10103,5:4102,6:5002}[case]
        shift=detected-5002
        changed=[]
        for time,kind,d in rows:
            if kind=='isolation_begin':d['fault_case']=case
            if kind=='detected':
                time=detected;d.update(reason=REASONS[case],age=5000 if case==4 else 100 if case==5 else 1000,
                    beat=70 if case==4 else 20 if case==3 else 10,trace_stage=255 if case==5 else 5 if case==6 else 6,
                    injection=4 if case==5 else 0 if case==6 else case,elapsed=detected-2100)
            elif kind not in ('sample','held','recovery_result') and time>=5003:
                time+=shift
            if kind=='recovery_result':d['reason']=REASONS[case]
            changed.append((time,kind,d))
        context=dict(session=1,readable=0 if case==6 else 1,peer_stage=255 if case==5 else 2,
            peer_error=104 if case==5 else 0,peer_seq=21 if case==6 else 20,
            peer_beat=70 if case==4 else 20 if case==3 else 10,heartbeat_age=1000 if case==6 else 20,
            sent=1000 if case==4 else 48,acked=1000 if case==4 else 32,
            handled=1000 if case==4 else 0,peer_sent=1000 if case==4 else 0,
            quiesce=1 if case==4 else 0,idle=0,fatal_invoked=case if case in (5,6) else 0,rc=0)
        changed.append((detected-1,'fault_context',context))
        if case==4:
            for line in restart_fixture().splitlines():
                if 'zephyr_lifecycle ' not in line:continue
                t,k,d=decode(line)
                if d.get('round')==0 and (k in ('endpoint','peer') or k=='event' and d['step']==5):
                    changed.append((t,k,d))
        rows=changed
    else:
        changed=[]
        for t,k,d in rows:
            if k=='worker_rebuilt' and fail==1:continue
            if d.get('round')==1:
                if fail==1:continue
                if fail==3 and t>5102:continue
                if fail==5 and t>6101:continue
            if k=='recovery_result':
                k='recovery_failure_result';d.update(recoveries=0,releases=2 if fail==5 else 1)
            changed.append((t,k,d))
        failed_time=5106 if fail in (1,3) else 11103
        if fail in (1,3):
            changed.append((5104,'recovery_injected',dict(session=2,step=fail,operation_rc=12 if fail==1 else 13,rc=0)))
        if fail==5:
            changed.append((failed_time-2,'replacement_timeout',dict(session=2,reason=1,readable=1,beat=0,trace_stage=6,injection=1,rc=0)))
        if fail==1:
            changed.append((5105,'hold_confirmed',dict(session=2,reset_held=1,rc=0)))
        else:
            reset=next(d.copy() for t,k,d in rows if k=='reset' and d.get('session')==2 and d['op']==4)
            if fail==3:reset['reset_before']=reset['reset_after']
            changed.append((failed_time-1,'reset',reset))
        changed.append((failed_time,'recovery_failed',dict(session=2,step=fail,
            operation_rc={1:12,3:13,5:16}[fail],local_idle=1,reset_held=1,channel_clean=1,containment_rc=0,rc=0)))
        changed.append((failed_time+1,'retry_blocked',dict(session=2,attempts=1,releases=2 if fail==5 else 1,blocked=1,rc=0)))
        rows=changed
    rows.sort(key=lambda r:r[0])
    return '\n'.join(boot+[encode(t,k,**d) for t,k,d in rows])+'\n'


class RecoveryBoundaries(unittest.TestCase):
    def test_all_extended_profiles_complete_and_incomplete(self):
        for case,fail in [(c,0) for c in NAMES]+[(2,f) for f in FAILURES]:
            with self.subTest(case=case,fail=fail):
                m=manifest(case,fail);text=fixture(case,fail)
                self.assertEqual(get_profile(m['validation_profile']).recovery_fail_step,fail)
                result=analyze(text,m)
                self.assertEqual(result['status'],'pass',result)
                self.assertEqual(analyze(text[:text.index('20000/I/BTH')],m)['status'],'incomplete')
                self.assertEqual(analyze(text+text,m)['session_count'],2)

    def test_live_ipc_requires_pending_requests_and_recent_heartbeat(self):
        text,m=fixture(),manifest()
        for old,new in [('sent=48 acked=32','sent=32 acked=32'),('heartbeat_age=20','heartbeat_age=1000'),
                        ('age=1000 beat=20','age=999 beat=20'),('readable=1','readable=0'),
                        ('peer_stage=2','peer_stage=255'),('injection=3','injection=0')]:
            self.assertEqual(analyze(text.replace(old,new,1),m)['status'],'fail',(old,new))

    def test_quiesce_requires_real_traffic_and_timeout(self):
        text,m=fixture(4),manifest(4)
        for old,new in [('quiesce=1 idle=0','quiesce=1 idle=1'),('age=5000','age=4999'),
                        ('acked=1000','acked=999'),('peer_beat=70','peer_beat=2')]:
            self.assertEqual(analyze(text.replace(old,new,1),m)['status'],'fail',(old,new))

    def test_fatal_and_unreadable_evidence_not_interchangeable(self):
        for case in (5,6):
            text,m=fixture(case),manifest(case)
            for old,new in [(f'fatal_invoked={case}','fatal_invoked=0'),
                            ('peer_seq=20','peer_seq=21') if case==5 else ('peer_seq=21','peer_seq=20'),
                            ('peer_error=104','peer_error=0') if case==5 else ('heartbeat_age=1000','heartbeat_age=0')]:
                self.assertEqual(analyze(text.replace(old,new,1),m)['status'],'fail')

    def test_failed_recovery_cannot_pass_without_containment_or_retry_limit(self):
        for step in FAILURES:
            text,m=fixture(2,step),manifest(2,step)
            for old,new in [('local_idle=1','local_idle=0'),('containment_rc=0','containment_rc=1'),
                            ('blocked=1','blocked=0'),('recoveries=0','recoveries=1'),('attempts=1','attempts=2')]:
                self.assertEqual(analyze(text.replace(old,new),m)['status'],'fail',(step,old))
            for kind in ('recovery_failed','retry_blocked','held'):
                line=next(x for x in text.splitlines() if f'zephyr_lifecycle {kind} ' in x)
                self.assertEqual(analyze(text.replace(line+'\n',''),m)['status'],'fail',(step,kind))
                self.assertEqual(analyze(text.replace(line,line+'\n'+line),m)['status'],'fail')
            for key,value in [('recovery_fail_step',0),('lifecycle_log',{}),('fault_case',1)]:
                bad=copy.deepcopy(m);bad[key]=value
                self.assertEqual(analyze(text,bad)['status'],'fail')

    def test_no_cross_format_or_late_errors(self):
        text,m=fixture(),manifest()
        self.assertEqual(analyze(text.replace('zephyr_lifecycle','zephyr_r1'),m)['status'],'fail')
        self.assertEqual(analyze(text+'602003/E/BTH/LIFECYCLE/MAIN | zephyr_lifecycle recovery_failed rc=44 !\n',m)['status'],'fail')
