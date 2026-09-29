# SPDX-License-Identifier: Apache-2.0
import copy
import ctypes
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import analyze_arbitration as parser


class Arbitration(unittest.TestCase):
    def test_descriptor_and_legacy_separation(self):
        with tempfile.TemporaryDirectory() as tmp:
            so = Path(tmp) / 'contract.so'
            subprocess.run(['cc', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror',
                '-I', str(ROOT / 'include/bestechnic/bes2700yp'),
                str(ROOT / 'platforms/bes2700yp/resources/contract.c'),
                str(ROOT / 'platforms/bes2700yp/resources/arbitration_contract.c'), '-o', str(so)], check=True)
            lib = ctypes.CDLL(str(so))
            words = [0x31534552, 3, 32, 4, 0x14000001, 96, 64, 0]
            value = lambda w: (ctypes.c_uint32 * 8)(*w)
            self.assertEqual(lib.bes_arbitration_descriptor_valid(value(words)), 1)
            self.assertEqual(lib.bes_resource_descriptor_valid(value(words)), 0)
            legacy = words.copy(); legacy[1] = legacy[3] = 1
            self.assertEqual(lib.bes_resource_descriptor_valid(value(legacy)), 1)
            self.assertEqual(lib.bes_arbitration_descriptor_valid(value(legacy)), 0)
            for i in range(8):
                bad = words.copy(); bad[i] ^= 1
                self.assertEqual(lib.bes_arbitration_descriptor_valid(value(bad)), 0)

    def compile_actual(self, kind):
        with tempfile.TemporaryDirectory() as tmp:
            exe = Path(tmp) / kind
            files = [ROOT / ('tests/dual_message/arbitration_' + kind + '.c'),
                     ROOT / 'platforms/bes2700yp/resources/contract.c',
                     ROOT / 'platforms/bes2700yp/resources/arbitration_contract.c']
            if kind == 'client':
                files += [ROOT / 'platforms/bes2700yp/resources/arbitration_client.c',
                          ROOT / 'platforms/bes2700yp/boot/service_contract.c']
            subprocess.run(['cc', '-Wall', '-Wextra', '-Werror', '-std=gnu11',
                '-fsanitize=undefined', '-fno-sanitize-recover=all',
                '-I', str(ROOT / 'include/bestechnic/bes2700yp'),
                '-I', str(ROOT.parent / 'modules/hal/bestechnic/include'),
                *map(str, files), '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True, timeout=10)

    def test_actual_service(self):
        self.compile_actual('service')

    def test_actual_client(self):
        self.compile_actual('client')

    def test_parsers_and_probe_contract(self):
        from test_observation_parser import cases, fixture
        for analyzer, old_manifest, legacy in cases():
            for probe in (False,True):
                if probe and old_manifest['validation_profile'] != 'm55-restart':
                    continue
                manifest, full, short = fixture(old_manifest,legacy)
                if probe:
                    manifest['validation_profile']='resource-arbitration'
                manifest['arbitration_service']=dict(abi=3,capabilities=4,probe=probe)
                lines, emitted=[],set()
                for line in short.splitlines():
                    lines.append(line)
                    phase=None
                    if 'zephyr_bth stage=main !' in line: phase=0
                    elif 'zephyr_dual stage id=6 ' in line or ('zephyr_lifecycle reset ' in line and ' op=3 ' in line): phase=3
                    elif manifest.get('restart_version') and 'zephyr_observe functional ' in line: phase=4
                    if phase is None or phase in emitted: continue
                    emitted.add(phase)
                    d={k:0 for k in parser.FIELDS}
                    d.update(parser.EXPECTED,version=3,build=int(manifest['build'],0),expected=phase,phase=phase,
                             entered=phase,exited=phase,last_op=phase)
                    if probe and phase==4: d.update(busy=2,stop_requests=1,stop_completed=1,probe_mask=31,probe_runs=1)
                    if phase==4: lines.pop()
                    lines.append(line.split('/')[0]+'/I/BTH/RESOURCE/MAIN | zephyr_arbitration snapshot '+
                                 ' '.join(f'{k}={v}' for k,v in d.items())+' !')
                    if phase==4: lines.append(line)
                text='\n'.join(lines)+'\n'
                result=analyzer.analyze(text,manifest,'short')
                self.assertEqual(result['status'],'pass',(manifest['validation_profile'],result))
                for old,new in [('owner=0','owner=3'),('pending=0','pending=1'),('rc=0','rc=1'),
                                ('probe_errors=0','probe_errors=1'),('bytes=64','bytes=32'),
                                ('snapshot ','snapshot rc=0 '),('/RESOURCE/','/OTHER/')]:
                    self.assertEqual(analyzer.analyze(text.replace(old,new),manifest,'short')['status'],'fail')
                absent='\n'.join(line for line in lines if 'zephyr_arbitration' not in line)+'\n'
                self.assertEqual(analyzer.analyze(absent,manifest,'short')['status'],'incomplete')
                records=[line for line in lines if 'zephyr_arbitration' in line]
                late='\n'.join(line for line in lines if line!=records[-1])+'\n'+records[-1]+'\n'
                self.assertEqual(analyzer.analyze(late,manifest,'short')['status'],'fail')
                if probe:
                    absent_contract=dict(manifest);del absent_contract['arbitration_service']
                    self.assertEqual(analyzer.analyze(text,absent_contract,'short')['status'],'fail')
                    self.assertEqual(analyzer.analyze(text.replace('probe_mask=31','probe_mask=15'),manifest,'short')['status'],'fail')
