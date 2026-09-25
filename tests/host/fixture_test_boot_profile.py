# SPDX-License-Identifier: Apache-2.0
import json,re,subprocess,sys,tempfile,unittest
from pathlib import Path
from analyze_boot_profile import analyze,POINT_FIELDS
from fixture_test_dual_doorbell import fixture as dual_fixture,manifest as dual_manifest
PORT=Path(__file__).resolve().parents[2]

def manifest():
    return dict(dual_manifest(),code_bytes=34436,crc32=0x12345678,profile_version=1,
        profile_variant=0,profile_id='0x12344321',profile_points=12,
        profile_sampler=0x00503001,profile_buffer=0x2055c200,profile_size=1136)

def fixture(wrap=False):
    m=manifest()
    begin=dict(version=1,variant=0,profile=0x12344321,points=12,bytes=m['code_bytes'],
        expected_crc=m['crc32'],fast_hz=6000000,slow_hz=16000,slow_nominal=16000,
        slow_calibrated=0,sampler=m['profile_sampler'],buffer=m['profile_buffer'],size=1136)
    points=[];start=0xffff0000 if wrap else 100000
    log_last=(start+100000-10)&0xffffffff
    for i in range(12):
        fast=(start+i*100000)&0xffffffff
        d={k:0 for k in POINT_FIELDS}
        d.update(id=i,fast0=fast,fast1=(fast+10)&0xffffffff,fast_end=(fast+80)&0xffffffff,
            slow=((0xffffff00 if wrap else 0)+i*100000//375)&0xffffffff,fast_ctrl=0x82,
            fast_load=0xffffffff,periph=512,sysclk=7,sysdiv=0,cache=1 if i<4 else 0,
            mpu=1 if i<5 else 0,primask=0 if i<3 else 1,log_last=log_last,
            crc=m['crc32'] if i in (2,7,8) else 1 if i==9 else 0)
        points.append(d)
    def row(kind,d):return '0/I/BTH/BOOT/EARLY | zephyr_bootprof '+kind+' '+' '.join(f'{k}={v}' for k,v in d.items())+' !'
    lines=dual_fixture().splitlines();idx=next(i for i,s in enumerate(lines) if 'zephyr_bth image ' in s)+1
    lines[idx:idx]=[row('begin',begin)]+[row('point',d) for d in points]+[row('result',{'pass':1,'points':12,'error':0,'guard':1})]
    return '\n'.join(lines)+'\n'

class ProfileParserTest(unittest.TestCase):
    def test_complete_and_native_counter_wrap(self):
        for wrap in (False,True):
            r=analyze(fixture(wrap),manifest());self.assertEqual(r['status'],'pass',r['sessions'][0]['errors'])
            self.assertAlmostEqual(r['sessions'][0]['profile']['total']['fast_ms'],800000/6000)
    def test_missing_duplicate_and_wrong_order(self):
        lines=fixture().splitlines()
        for i in [n for n,s in enumerate(lines) if 'zephyr_bootprof ' in s]:
            for changed in (lines[:i]+lines[i+1:],lines[:i]+[lines[i]]+lines[i:]):
                self.assertEqual(analyze('\n'.join(changed)+'\n',manifest())['status'],'fail')
    def test_corrupt_prefix_and_counters(self):
        for old,new in [('profile=305414945','profile=1'),('fast_ctrl=130','fast_ctrl=0'),
                        ('buffer=542491136','buffer=0'),('points=12','points=11'),
                        ('guard=1','guard=0'),('slow_hz=16000','slow_hz=0'),
                        ('0/I/BTH/BOOT/EARLY | zephyr_bootprof','0/I/M55/BOOT/EARLY | zephyr_bootprof'),
                        ('0/I/BTH/BOOT/EARLY | zephyr_bootprof','NA/I/BTH/BOOT/EARLY | zephyr_bootprof'),
                        ('version=1 variant=0','version=1 version=1 variant=0'),
                        ('crc=305419896','crc=0')]:
            with self.subTest(new=new):
                self.assertIn(old,fixture());self.assertEqual(analyze(fixture().replace(old,new),manifest())['status'],'fail')
    def test_t1_variant_and_t0_cannot_be_mixed(self):
        t1=fixture().replace('version=1 variant=0','version=1 variant=1')
        m=dict(manifest(),profile_variant=1)
        self.assertEqual(analyze(t1,m)['status'],'pass')
        self.assertEqual(analyze(t1,manifest())['status'],'fail')
        self.assertEqual(analyze(fixture(),m)['status'],'fail')
        self.assertEqual(analyze(t1,dict(m,profile_variant=3))['status'],'fail')

    def test_t2_variant_rejects_t0_t1_and_unknown(self):
        t2=fixture().replace('version=1 variant=0','version=1 variant=2')
        self.assertEqual(analyze(t2,dict(manifest(),profile_variant=2))['status'],'pass')
        for variant in (0,1,3):
            self.assertEqual(analyze(t2,dict(manifest(),profile_variant=variant))['status'],'fail')

    def test_no_timing_evidence_and_wrong_manifest(self):
        self.assertEqual(analyze(dual_fixture(),manifest())['status'],'fail')
        self.assertEqual(analyze(fixture(),dict(manifest(),profile_version=2))['status'],'fail')
    def test_partial_and_restart(self):
        text=fixture().split('2100/I/BTH/KERN/MAIN')[0]
        self.assertEqual(analyze(text,manifest())['status'],'incomplete')
        self.assertEqual(analyze(fixture()+text,manifest())['status'],'incomplete')
        text=fixture().split('zephyr_bootprof point')[0]+'zephyr_bootprof point id='
        self.assertEqual(analyze(text,manifest())['status'],'incomplete')
    def test_late_fault_and_actual_offsets(self):
        text=fixture().replace('\n','\r\n')
        for r in analyze(text,manifest())['sessions'][0]['raw_records']:
            self.assertEqual(text[r['byte_start']:r['byte_end']].rstrip('\r\n'),r['raw'])
        self.assertEqual(analyze(fixture()+'600103/E/BTH/FAULT/FAULT | zephyr_bth stage=fatal !\n',manifest())['status'],'fail')
    def test_cli(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'layout.json').write_text(json.dumps(manifest()))
            for text,expected in [(fixture(),0),(fixture().replace('guard=1','guard=0'),1),(fixture().split('2100/I/BTH/KERN/MAIN')[0],2)]:
                (p/'log.cap').write_text(text)
                r=subprocess.run([sys.executable,str(PORT/'scripts/analyze_boot_profile.py'),str(p/'log.cap'),'--manifest',str(p/'layout.json')],capture_output=True,text=True)
                self.assertEqual(r.returncode,expected,r.stderr)

class IntegratedPressureTest(unittest.TestCase):
    def test_baseline_identity_and_rounds_are_bound(self):
        from build_boot_profile import validate_base
        for n,b,m in [(1000,'0xa58f4b32','0x777bac3c'),(10000,'0xd327cdf0','0xd28679d8')]:
            layout=dict(build=b,m55_build=m,doorbell_rounds=n,duration_seconds=600)
            validate_base(layout,n,'T2')
            for key,value in [('build','0x0'),('m55_build','0x0'),('doorbell_rounds',3),('duration_seconds',60)]:
                with self.assertRaises(ValueError):validate_base(dict(layout,**{key:value}),n,'T2')
            with self.assertRaises(ValueError):validate_base(layout,10000 if n==1000 else 1000,'T2')
            if n==10000:
                with self.assertRaises(ValueError):validate_base(layout,n,'T1')

    def test_profile_with_10000_rounds_requires_matching_ipc(self):
        text=fixture().replace('version=1 variant=0','version=1 variant=2')
        old=[x for x in dual_fixture().splitlines() if 'zephyr_db ' in x]
        new=[x for x in dual_fixture(10000).splitlines() if 'zephyr_db ' in x]
        for a,b in zip(old,new):text=text.replace(a,b)
        m=dict(manifest(),profile_variant=2,doorbell_rounds=10000)
        self.assertEqual(analyze(text,m)['status'],'pass')
        self.assertEqual(analyze(text,dict(m,doorbell_rounds=1000))['status'],'fail')
        self.assertEqual(analyze(text.replace('bth_rx=20003','bth_rx=20002'),m)['status'],'fail')

class SamplerTest(unittest.TestCase):
    def test_ram_crc_matches_reference_across_lengths(self):
        import ctypes,zlib
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);(d/'crc.c').write_text('#include "bth_contract.h"\nuint32_t calc(const uint8_t *p,uint32_t n) { return bth_crc32(p,n); }\n')
            subprocess.run(['cc','-shared','-fPIC','-O2','-Wall','-Werror','-DBES_BTH_BOOT_CRC_RAM',
                '-I',str(PORT/'platforms/bes2700yp/boot/bootstrap'),str(d/'crc.c'),'-o',str(d/'crc.so')],check=True)
            lib=ctypes.CDLL(str(d/'crc.so'));lib.calc.argtypes=[ctypes.c_char_p,ctypes.c_uint32];lib.calc.restype=ctypes.c_uint32
            for n in list(range(257))+[1024,34420,65536]:
                data=bytes((i*37+19)&255 for i in range(n))
                self.assertEqual(lib.calc(data,n),zlib.crc32(data))


    def test_metadata_exceptions_reject_other_mutations(self):
        from build_boot_profile import compare_except_metadata
        original=bytes(range(100))
        for i in range(100):
            changed=bytearray(original);changed[i]^=1
            if 20<=i<40 or 70<=i<90:
                compare_except_metadata(original,changed,[(20,40),(70,90)])
            else:
                with self.assertRaises(ValueError):compare_except_metadata(original,changed,[(20,40),(70,90)])
        with self.assertRaises(ValueError):compare_except_metadata(original,original+b'\0',[])

    def test_real_sampler_guards_order_bounded_reads_and_passive_dwt(self):
        with tempfile.TemporaryDirectory() as tmp:
            exe=Path(tmp)/'sampler'
            subprocess.run(['cc','-std=gnu11','-O2','-Wall','-Wextra','-Werror','-fsanitize=undefined',
                '-fno-sanitize-recover=all',str(PORT/'tests/boot_profile/sampler.c'),'-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True,timeout=5)

if __name__=='__main__':unittest.main()
