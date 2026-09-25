# SPDX-License-Identifier: Apache-2.0
"""Require complete interrupt and heartbeat evidence; never inherit an old pass."""
import unittest
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from analyze_dual_doorbell import analyze
from fixture_test_log_prefix import fixture as heartbeat, manifest as base_manifest


def manifest(rounds=1000):
    return dict(base_manifest(), doorbell_version=2, doorbell_rounds=rounds)


def fixture(rounds=1000):
    lines=heartbeat().splitlines()
    start=next(i for i,s in enumerate(lines) if 'stage id=7 ' in s)+1
    lines.insert(start,f'0/I/BTH/IPC/MAIN | zephyr_db begin version=2 channel=1 rounds={rounds} !')
    end=next(i for i,s in enumerate(lines) if 'sample id=1 ' in s)+1
    n=rounds
    fields=dict(finished=1,rc=0,phases=31,bth_rx=2*n+3,bth_req=2*n+35,bth_kicks=2*n+5,
        bth_done=2*n+5,bth_queued=31,bth_spurious=0,m55_stage=5,m55_error=0,
        m55_rx=2*n+5,m55_req=2*n+33,m55_kicks=2*n+3,m55_done=2*n+3,
        m55_queued=31,m55_spurious=0,bth_stack=2200,m55_stack=1500)
    lines.insert(end,'1100/I/BTH/IPC/MAIN | zephyr_db result '+
                 ' '.join(f'{k}={v}' for k,v in fields.items())+' !')
    return '\n'.join(lines)+'\n'


class DoorbellLogTest(unittest.TestCase):
    def test_cli_exit_status_matches_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'layout.json').write_text(json.dumps(manifest()))
            script=Path(__file__).with_name('analyze_dual_doorbell.py')
            for text,code,status in [(fixture(),0,'pass'),
                    (fixture().replace('bth_queued=31','bth_queued=32'),1,'fail'),
                    (fixture().split('2100/I/BTH/KERN/MAIN')[0],2,'incomplete')]:
                (p/'capture.cap').write_text(text)
                result=subprocess.run([sys.executable,str(script),str(p/'capture.cap'),
                    '--manifest',str(p/'layout.json')],text=True,capture_output=True)
                self.assertEqual(result.returncode,code,result.stderr)
                self.assertEqual(json.loads(result.stdout)['status'],status)

    def test_complete_both_packages(self):
        for n in (1000,10000):
            r=analyze(fixture(n),manifest(n))
            self.assertEqual(r['status'],'pass',r['sessions'][0]['errors'])
            self.assertEqual(r['sessions'][0]['samples'],601)

    def test_old_heartbeat_pass_is_insufficient(self):
        self.assertEqual(analyze(heartbeat(),manifest())['status'],'fail')

    def test_missing_duplicate_and_wrong_order(self):
        lines=fixture().splitlines()
        for i in [j for j,s in enumerate(lines) if 'zephyr_db ' in s]:
            for changed in (lines[:i]+lines[i+1:],lines[:i]+[lines[i]]+lines[i:]):
                self.assertEqual(analyze('\n'.join(changed)+'\n',manifest())['status'],'fail')
        ipc=[s for s in lines if 'zephyr_db ' in s]
        rest=[s for s in lines if 'zephyr_db ' not in s]
        self.assertEqual(analyze('\n'.join(rest+ipc)+'\n',manifest())['status'],'fail')

    def test_corrupt_prefix_and_fields_fail(self):
        for old,new in [('1100/I/BTH/IPC','1100/I/M55/IPC'),
                        ('1100/I/BTH/IPC','NA/I/BTH/IPC'),
                        ('1100/I/BTH/IPC','noise1100/I/BTH/IPC'),
                        ('1100/I/BTH/IPC','1/I/BTH/IPC'),
                        ('1100/I/BTH/IPC','1100/E/BTH/IPC'),
                        ('phases=31','phases=15'),('bth_rx=2003','bth_rx=2002'),
                        ('m55_done=2003','m55_done=2002'),('bth_queued=31','bth_queued=32'),
                        ('bth_spurious=0','bth_spurious=1'),('m55_error=0','m55_error=1'),
                        ('bth_stack=2200','bth_stack=127'),('m55_stack=1500','m55_stack=127'),
                        ('finished=1','finished=1 finished=1'),('phases=31','extra=0 phases=31'),
                        ('finished=1 rc=0','finished=1 rc=14')]:
            with self.subTest(new=new):
                self.assertIn(old,fixture())
                self.assertEqual(analyze(fixture().replace(old,new),manifest())['status'],'fail')

    def test_partial_and_restart(self):
        lines=fixture().splitlines(True)
        partial=''.join(lines[:next(i for i,s in enumerate(lines) if 'sample id=1 ' in s)])
        self.assertEqual(analyze(partial,manifest())['status'],'incomplete')
        r=analyze(fixture()+partial,manifest())
        self.assertEqual(r['session_count'],2)
        self.assertEqual(r['status'],'incomplete')
        after_ipc=''.join(lines[:next(i for i,s in enumerate(lines) if 'sample id=3 ' in s)])
        self.assertEqual(analyze(after_ipc,manifest())['status'],'incomplete')

    def test_partial_run_with_ipc_failure_fails(self):
        text=fixture().split('2100/I/BTH/KERN/MAIN')[0]
        text=text.replace('1100/I/BTH/IPC','1100/E/BTH/IPC').replace('finished=1 rc=0','finished=1 rc=14')
        self.assertEqual(analyze(text,manifest())['status'],'fail')

    def test_identity_and_manifest(self):
        for m in (manifest(10000),dict(manifest(),doorbell_version=1),dict(manifest(),build='0x1')):
            self.assertEqual(analyze(fixture(),m)['status'],'fail')

    def test_original_bytes_retained(self):
        text='ignored boot noise\n'+fixture().replace('\n','\r\n')
        for r in analyze(text,manifest())['sessions'][0]['raw_records']:
            self.assertEqual(text[r['byte_start']:r['byte_end']].rstrip('\r\n'),r['raw'])

    def test_final_heartbeat_failure_overrides_ipc_pass(self):
        self.assertEqual(analyze(fixture().replace('pass=1 samples=601 rc=0','pass=0 samples=601 rc=90'),manifest())['status'],'fail')

if __name__=='__main__':unittest.main()
