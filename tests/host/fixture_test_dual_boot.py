# SPDX-License-Identifier: Apache-2.0
import ctypes
import struct
import subprocess
import tempfile
import unittest
import zlib
from pathlib import Path
from analyze_dual_boot import analyze

MANIFEST = {'build': '0x12345678', 'm55_build': '0x87654321'}

def fixture():
    lines = ['zephyr_bth begin version=1 test=8 build=0x12345678 !',
             'zephyr_bth stage=adapter_ready !',
             'zephyr_bth adapter cpuid=0x630f1321 ipsr=0 control=0 !',
             'zephyr_bth image layout=0x50001 verified=1 !',
             'zephyr_bth uart ibrd=1 fbrd=19 !',
             'zephyr_bth state cache=0 mpu=0 systick=0 !']
    lines += [f'zephyr_bth stage={s} !' for s in ('handoff', 'reset', 'early', 'main')]
    lines += ['zephyr_dual begin version=1 test=8 build=0x12345678 m55_build=0x87654321 layout=0x80001 duration=600 bth_hz=24000000 m55_hz=24000000 !']
    lines += [f'zephyr_dual stage id={i} rc=0 !' for i in range(1, 7)]
    lines += ['zephyr_dual peer cpuid=0x411fd221 vtor=0xa0000 build=0x87654321 stage=2 error=0 mpu=0 ccr=0 control=2 !',
              'zephyr_dual stage id=7 rc=0 !']
    for i in range(601):
        c = i * 24000000
        lines.append(f'zephyr_dual sample id={i} ms={i*1000} ticks={i*6000000} timer={i*10} m55_ms={i*1000} beat={i*10} cycles_hi={c>>32} cycles_lo={c&0xffffffff} bth_stack=2500 m55_stack=2500 guards=1 rc=0 !')
    lines.append('zephyr_dual result pass=1 samples=601 rc=0 !')
    return '\n'.join(lines) + '\n'

class DualLogTest(unittest.TestCase):
    def test_complete_and_wraps(self):
        r=analyze(fixture(), MANIFEST)
        self.assertEqual(r['status'], 'pass')
        self.assertEqual(r['sessions'][0]['last_sample']['cycles_hi'], 3)

    def test_faults_rejected(self):
        for old, new in [('test=8', 'test=7'), ('stage=early', 'stage=reset'),
                         ('id=4 rc=0', 'id=4 rc=1'), ('cpuid=0x411fd221', 'cpuid=0x410fd210'),
                         ('vtor=0xa0000', 'vtor=0x40000'), ('ccr=0 control=2', 'ccr=65536 control=2'),
                         ('m55_build=0x87654321', 'm55_build=1'), ('id=50 ms=', 'id=51 ms='),
                         ('m55_ms=50000', 'm55_ms=49000'), ('beat=500 ', 'beat=490 '),
                         ('m55_stack=2500', 'm55_stack=64'), ('guards=1', 'guards=0'),
                         ('ticks=300000000 ', 'ticks=200000000 '),
                         ('cycles_lo=1200000000 ', 'cycles_lo=1000000000 '),
                         ('pass=1 samples=601', 'pass=0 samples=601'),
                         ('pass=1 samples=601', 'pass=1 samples=600')]:
            with self.subTest(old=old):
                self.assertIn(old, fixture())
                self.assertEqual(analyze(fixture().replace(old,new,1),MANIFEST)['status'],'fail')

    def test_partial_and_latest_boot(self):
        lines=fixture().splitlines(True)
        for count in (1,10,15,19,80,619,620):
            with self.subTest(count=count):
                self.assertEqual(analyze(''.join(lines[:count]),MANIFEST)['status'],'incomplete')
        self.assertEqual(analyze(fixture()+lines[0],MANIFEST)['status'],'incomplete')
        self.assertEqual(analyze(fixture()+fixture(),MANIFEST)['session_count'],2)
        self.assertEqual(analyze(''.join(lines[:40])+lines[40][:20],MANIFEST)['status'],'incomplete')

    def test_noise_and_late_fault(self):
        self.assertEqual(analyze(fixture()+'\xfc\x80\n',MANIFEST)['status'],'pass')
        self.assertEqual(analyze(fixture()+'zephyr_dual fatal rc=1 !\n',MANIFEST)['status'],'fail')
        self.assertEqual(analyze(fixture().replace('zephyr_dual sample id=40 ', '\xfc\nzephyr_dual sample id=40 '),MANIFEST)['status'],'fail')

class ImageValidationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();p=Path(cls.temp.name)
        (p/'check.c').write_text('#include "bes2700_dual_image.h"\nint check(const unsigned char *p, unsigned n, unsigned crc) { return dual_image_check(p,n,crc); }\n')
        subprocess.run(['cc','-shared','-fPIC','-fsanitize=undefined','-fno-sanitize-recover=all','-Wall','-Wextra','-Werror',
                        '-I',str(Path(__file__).resolve().parents[2]/'include'),str(p/'check.c'),'-o',str(p/'check.so')],check=True)
        cls.lib=ctypes.CDLL(str(p/'check.so'));cls.check=cls.lib.check
        cls.check.argtypes=[ctypes.c_char_p,ctypes.c_uint,ctypes.c_uint];cls.check.restype=ctypes.c_int
    @classmethod
    def tearDownClass(cls): cls.temp.cleanup()
    def valid(self):
        p=bytearray(100)
        struct.pack_into('<8I',p,0,0xbe57ec1c,0,0,0,0x10000,100,56,24)
        struct.pack_into('<6I',p,32,0x2015e000,56,28,0xa0000,84,16)
        struct.pack_into('<2I',p,84,0x200c0100,0xa0009)
        return p
    def test_valid(self):
        p=bytes(self.valid());self.assertEqual(self.check(p,len(p),zlib.crc32(p)),0)
    def test_malformed_with_recomputed_crc(self):
        for off,value in [(0,0),(4,1),(16,0),(20,96),(24,52),(28,12),(28,0xffffffff),
                          (32,0x2015e100),(36,52),(40,0xfffffffc),(44,0x2015c000),
                          (44,0x200c0000),(44,0x20510000),(48,56),(52,0),
                          (84,0x2015ffe0),(84,0x200c0101),(88,0xa0008),(88,0xb0001)]:
            with self.subTest(offset=off,value=value):
                p=self.valid();struct.pack_into('<I',p,off,value);p=bytes(p)
                self.assertNotEqual(self.check(p,len(p),zlib.crc32(p)),0)
    def test_all_single_byte_corruptions(self):
        p=self.valid();crc=zlib.crc32(p)
        for i in range(len(p)):
            q=bytearray(p);q[i]^=1
            with self.subTest(offset=i):self.assertNotEqual(self.check(bytes(q),len(q),crc),0)
    def test_all_truncations(self):
        p=bytes(self.valid())
        for i in range(len(p)):
            with self.subTest(size=i):self.assertNotEqual(self.check(p[:i],i,zlib.crc32(p[:i])),0)



def diagnostic_fixture():
    from analyze_dual_boot import HW, TRACE
    lines=fixture().replace('zephyr_dual begin version=1','zephyr_dual begin version=2').replace('layout=0x80001','layout=0x80002').splitlines()
    result=[]
    for line in lines:
        result.append(line)
        ident=None
        if line=='zephyr_dual stage id=4 rc=0 !': ident=0
        elif line=='zephyr_dual stage id=6 rc=0 !': ident=1
        elif line.startswith('zephyr_dual peer '): ident=2
        if ident is None:continue
        hw={k:0 for k in sorted(HW)}
        hw.update(id=ident,rc=0,phase=2 if ident==0 else 3)
        if ident:hw.update(release_sp=0x2015ffe0,release_pc=0x2015e001)
        diag={k:0 for k in sorted(TRACE)}
        diag.update(id=ident,elapsed=0,reads=1 if ident==2 else 0,retries=0,stable=1,seq=2,magic=0x384d3535)
        if ident==2:diag.update(stage=5,cpuid=0x411fd221,vtor=0xa0000)
        for kind,d in [('hw',hw),('diag',diag)]:
            result.append('zephyr_dual '+kind+' '+' '.join(f'{k}={v}' for k,v in d.items())+' !')
    return '\n'.join(result)+'\n'

class DiagnosticLogTest(unittest.TestCase):
    def setUp(self):self.manifest=dict(MANIFEST,log_version=2)
    def test_complete_v2(self):
        r=analyze(diagnostic_fixture(),self.manifest)
        self.assertEqual(r['status'],'pass',r)
        self.assertEqual(len(r['sessions'][0]['diagnostics']),3)
    def test_missing_duplicate_reordered_snapshots(self):
        lines=diagnostic_fixture().splitlines()
        indices=[i for i,s in enumerate(lines) if s.startswith(('zephyr_dual hw ','zephyr_dual diag '))]
        for i in indices:
            with self.subTest(index=i):
                self.assertEqual(analyze('\n'.join(lines[:i]+lines[i+1:]),self.manifest)['status'],'fail')
                self.assertEqual(analyze('\n'.join(lines[:i]+[lines[i]]+lines[i:]),self.manifest)['status'],'fail')
        i=indices[0];lines[i],lines[i+1]=lines[i+1],lines[i]
        self.assertEqual(analyze('\n'.join(lines),self.manifest)['status'],'fail')
    def test_bad_release_readback(self):
        text=diagnostic_fixture().replace('release_pc=538304513','release_pc=0')
        self.assertNotEqual(text,diagnostic_fixture())
        self.assertEqual(analyze(text,self.manifest)['status'],'fail')
    def test_old_failure_stays_failed(self):
        text=diagnostic_fixture().split('zephyr_dual sample ')[0]
        text=text.replace('zephyr_dual stage id=7 rc=0','zephyr_dual stage id=7 rc=1')
        text+='zephyr_dual result pass=0 samples=0 rc=87 !\n'
        r=analyze(text,self.manifest)
        self.assertEqual(r['status'],'fail')
        self.assertEqual(len(r['sessions'][0]['hardware']),3)
    def test_mid_boot_is_incomplete(self):
        text=diagnostic_fixture().split('zephyr_dual stage id=5')[0]
        self.assertEqual(analyze(text,self.manifest)['status'],'incomplete')

if __name__ == '__main__':unittest.main()
