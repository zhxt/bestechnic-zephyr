# SPDX-License-Identifier: Apache-2.0
"""Versioned parser and real C timestamp/formatter with only MMIO output mocked."""
import json
import re
import subprocess
import tempfile
import unittest
from pathlib import Path
from analyze_dual_boot import analyze, prefix_contract
from fixture_test_dual_boot import MANIFEST, diagnostic_fixture


def fixture(duration=600):
    lines=diagnostic_fixture().splitlines()
    head=[s for s in lines if not s.startswith(('zephyr_dual sample ', 'zephyr_dual result '))]
    head=[s.replace('begin version=2','begin version=3').replace('duration=600',f'duration={duration}') for s in head]
    for i in range(duration+1):
        c=i*24000000
        head.append(f'zephyr_dual sample id={i} ms={i*1000} ticks={i*6000000} timer={i*10} m55_ms={i*1000} beat={i*10} cycles_hi={c>>32} cycles_lo={c&0xffffffff} bth_stack=2500 m55_stack=2500 guards=1 rc=0 !')
    head.append(f'zephyr_dual result pass=1 samples={duration+1} rc=0 !')
    result=[];time=0
    for i,body in enumerate(head):
        if body.startswith('zephyr_dual sample '):time=int(re.search(r' ms=(\d+)',body)[1])+100
        if body.startswith('zephyr_dual result '):time+=2
        mod,ctx=prefix_contract(body)
        result.append(f'{"NA" if i<3 else time}/I/BTH/{mod}/{ctx} | {body}')
    return '\n'.join(result)+'\n'


def manifest(duration=600):
    return dict(MANIFEST,log_version=3,prefix_version=1,duration_seconds=duration)


class PrefixParserTest(unittest.TestCase):
    def test_ten_minute_and_one_hour(self):
        for duration in (600,3600):
            with self.subTest(duration=duration):
                r=analyze(fixture(duration),manifest(duration))
                self.assertEqual(r['status'],'pass',r['sessions'][0]['errors'])
                self.assertEqual(r['sessions'][0]['samples'],duration+1)
                self.assertEqual(r['sessions'][0]['last_sample']['ticks'],duration*6000000)

    def test_old_format_unchanged(self):
        self.assertEqual(analyze(diagnostic_fixture(),dict(MANIFEST,log_version=2))['status'],'pass')

    def test_corrupt_prefix_cannot_hide_runtime_bytes(self):
        for old,new in [('40100/I/BTH/KERN/MAIN |','noise 40100/I/BTH/KERN/MAIN |'),
                        ('40100/I/BTH/KERN/MAIN |','40100/I/M55/KERN/MAIN |'),
                        ('40100/I/BTH/KERN/MAIN |','40100/I/BTH/BOOT/MAIN |'),
                        ('40100/I/BTH/KERN/MAIN |','40100/E/BTH/KERN/MAIN |'),
                        ('40100/I/BTH/KERN/MAIN |','NA/I/BTH/KERN/MAIN |'),
                        ('40100/I/BTH/KERN/MAIN |','1/I/BTH/KERN/MAIN |'),
                        ('40100/I/BTH/KERN/MAIN |','18446744073709551616/I/BTH/KERN/MAIN |'),
                        ('40100/I/BTH/KERN/MAIN | ','')]:
            with self.subTest(new=new):
                self.assertIn(old,fixture())
                self.assertEqual(analyze(fixture().replace(old,new),manifest())['status'],'fail')

    def test_missing_or_corrupt_begin_prefix_fails(self):
        for text in (fixture().replace('NA/I/BTH/BOOT/EARLY | ', '',1), 'garbage'+fixture()):
            self.assertEqual(analyze(text,manifest())['status'],'fail')

    def test_timestamp_stuck_or_wrong_rate_fails(self):
        text=re.sub(r'\d+/I/BTH/KERN/MAIN', '0/I/BTH/KERN/MAIN',fixture())
        self.assertEqual(analyze(text,manifest())['status'],'fail')
        text=fixture().replace('40100/I/BTH/KERN/MAIN','41100/I/BTH/KERN/MAIN')
        self.assertEqual(analyze(text,manifest())['status'],'fail')

    def test_one_hour_raw_32bit_counter_is_rejected(self):
        text=fixture(3600)
        text=re.sub(r'ticks=(\d+)',lambda m:f'ticks={int(m[1])&0xffffffff}',text)
        self.assertEqual(analyze(text,manifest(3600))['status'],'fail')

    def test_duration_cannot_be_guessed(self):
        self.assertEqual(analyze(fixture(600),manifest(3600))['status'],'fail')
        self.assertEqual(analyze(fixture(3600),manifest(600))['status'],'fail')

    def test_partial_final_body_and_new_boot(self):
        text=fixture().rsplit('600100/I/BTH/KERN/MAIN',1)[0]
        self.assertEqual(analyze(text,manifest())['status'],'incomplete')
        r=analyze(fixture()+fixture().splitlines(True)[0],manifest())
        self.assertEqual(r['status'],'incomplete');self.assertEqual(r['session_count'],2)

    def test_truncated_final_prefix_is_incomplete(self):
        text=fixture().split("40100/I/BTH/KERN/MAIN")[0]+"40100/I/BTH/KE"
        self.assertEqual(analyze(text,manifest())["status"],"incomplete")

    def test_boundary_noise_and_late_prefixed_fault(self):
        self.assertEqual(analyze(fixture()+'\xfe\xff\n'+fixture(),manifest())['status'],'pass')
        fault='600103/E/BTH/FAULT/FAULT | zephyr_bth stage=fatal !\n'
        self.assertEqual(analyze(fixture()+fault,manifest())['status'],'fail')

    def test_raw_records_and_byte_offsets_retained(self):
        text=fixture().replace('\n','\r\n')
        r=analyze(text,manifest())
        for row in r['sessions'][0]['records']:
            self.assertEqual(text[row['byte_start']:row['byte_end']].rstrip('\r\n'),row['raw'])


class ClockAndFormatterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory();p=Path(cls.tmp.name)
        port=Path(__file__).resolve().parents[2]
        # Replace only the UART putc peripheral seam. Timer register reads and
        # persistent state still use the actual header and mapped address ranges.
        text=(port/'platforms/bes2700yp/boot/bootstrap/bth_contract.h').read_text()
        a=text.index('static inline void bth_putc(');b=text.index('static inline void bth_puts(',a)
        (p/'bth_contract.h').write_text(text[:a]+'static void bth_putc(char ch);\n'+text[b:])
        (p/'bth_log_clock.h').write_bytes((port/'platforms/bes2700yp/boot/bootstrap/bth_log_clock.h').read_bytes())
        (p/'test.c').write_text(r'''
#define _GNU_SOURCE
#include <sys/mman.h>
#include <stdint.h>
#include <stdio.h>
#include <assert.h>
static unsigned mask;
static uint32_t __get_PRIMASK(void) { return mask; }
static void __disable_irq(void) { mask=1; }
static void __set_PRIMASK(uint32_t m) { mask=m; }
#define __DMB() __asm__ volatile("" ::: "memory")
#define CONFIG_BTH_LOG_PREFIX 1
#include "bth_contract.h"
static void bth_putc(char ch) { putchar(ch); }
static void raw(uint32_t n) { BTH_REG(BTH_TIMER_BASE+4)=0U-n; }
int main(void) {
 assert(mmap((void *)0x2055c000,4096,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0)==(void *)0x2055c000);
 assert(mmap((void *)BTH_TIMER_BASE,4096,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0)==(void *)BTH_TIMER_BASE);
 bth_log_reset(); bth_log_begin('I',"BOOT","EARLY"); bth_puts("early"); bth_end();
 raw(0xfffffff0U); bth_log_start();
 uint64_t total=0; uint32_t r=0xfffffff0U;
 for(unsigned i=0;i<36000;i++) {
  r+=600000; raw(r); bth_log_poll(); total+=600000;
  assert(BTH_LOG->ticks==total); assert(mask==0);
 }
 /* 1 hour without printing, with 100 ms sampler: five hardware wraps. */
 mask=1; uint64_t tick; assert(bth_log_time(&tick)); assert(mask==1); mask=0;
 assert(tick==21600000000ULL);
 bth_log_begin('I',"KERN","MAIN"); bth_puts("one_hour"); bth_end();
 BTH_LOG->busy=1;
 bth_log_begin('E',"FAULT","FAULT"); bth_puts("busy_fault"); bth_end();
 assert(BTH_LOG->ticks==total); BTH_LOG->busy=0;
 /* Fatal can interrupt an unfinished record, without a blocking lock. */
 bth_log_begin('I',"KERN","MAIN"); bth_puts("unfinished");
 bth_log_begin('E',"FAULT","FAULT"); bth_puts("fault"); bth_end();
 bth_dec64(UINT64_MAX);bth_putc('\n');
 return 0;
}
''')
        cls.binary=p/'test'
        subprocess.run(['cc','-O1','-Wall','-Wextra','-Werror','-fsanitize=undefined','-fno-sanitize-recover=all','-I',str(p),str(p/'test.c'),'-o',str(cls.binary)],check=True)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def test_real_formatter_wraps_irq_state_and_fatal_degradation(self):
        out=subprocess.check_output([str(self.binary)],text=True)
        self.assertEqual(out.splitlines(),[
            'NA/I/BTH/BOOT/EARLY | early !',
            '3600000/I/BTH/KERN/MAIN | one_hour !',
            'NA/E/BTH/FAULT/FAULT | busy_fault !',
            '3600000/I/BTH/KERN/MAIN | unfinished',
            '3600000/E/BTH/FAULT/FAULT | fault !',
            '18446744073709551615'])

if __name__=='__main__':unittest.main()
