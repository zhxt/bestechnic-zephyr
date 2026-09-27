# SPDX-License-Identifier: Apache-2.0
"""Run the actual M55 injection and fatal publisher, with host register stubs."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]


class M55Fatal(unittest.TestCase):
    def test_actual_panic_publisher_and_lost_diagnostic(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'zephyr').mkdir()
            (root/'zephyr/kernel.h').write_text('''#pragma once
#include <stddef.h>
#include <stdint.h>
#include <stdbool.h>
struct arch_esf { struct {uint32_t pc,lr,xpsr;} basic; };
#define K_TIMEOUT_ABS_MS(x) (x)
void k_panic(void);
void k_sleep(int64_t);
int64_t k_uptime_get(void);
uint32_t k_uptime_get_32(void);
uint32_t k_cycle_get_32(void);
void *k_current_get(void);
int k_thread_stack_space_get(void *,size_t *);
''')
            (root/'cmsis_core.h').write_text('''#pragma once
#include <stdint.h>
struct regs {uint32_t CPUID,VTOR,CCR,CPACR,CFSR,HFSR,SHCSR,MMFAR,BFAR,ICSR,CTRL;};
extern struct regs regs;
#define SCB (&regs)
#define MPU (&regs)
#define __DMB() ((void)0)
#define __DSB() ((void)0)
void halt_loop(void);
#define __NOP() halt_loop()
#define __disable_irq() ((void)0)
#define __get_CONTROL() 2U
#define __get_PRIMASK() 0U
#define __get_BASEPRI() 0U
#define __get_MSPLIM() 0U
#define __get_PSPLIM() 0U
#define __get_MSP() 0U
#define __get_PSP() 0U
''')
            source=root/'test.c'
            source.write_text('''#include <assert.h>
#include <setjmp.h>
#include <bes2700_dual_boot.h>
static struct dual_trace trace;
static struct bes2700_lifecycle_control control;
#undef DUAL_TRACE
#define DUAL_TRACE (&trace)
#undef BES_LIFECYCLE_CTL
#define BES_LIFECYCLE_CTL (&control)
#define main m55_application_main
#include "'''+str(ROOT/'apps/bes2700yp/m55/src/main.c')+'''"
#undef main
struct regs regs;
static jmp_buf halted;
void halt_loop(void) { longjmp(halted,1); }
void k_panic(void) { k_sys_fatal_error_handler(4,NULL);assert(0); }
int main(void)
{
 control=(struct bes2700_lifecycle_control){.magic=BES_LIFECYCLE_MAGIC,
  .layout=BES_LIFECYCLE_LAYOUT,.guard=BES_LIFECYCLE_GUARD,.session=1};
 dual_shared.seq=20;dual_shared.beat=10;dual_shared.stage=2;trace.stage=5;
 if(!setjmp(halted)) { inject_fault();assert(0); }
 assert(control.unused[0]==CONFIG_BES2700_M55_FAULT_CASE);
#if CONFIG_BES2700_M55_FAULT_CASE == 5
 assert(dual_shared.seq==22 && dual_shared.stage==255 && dual_shared.error==104);
 assert(trace.stage==255 && trace.reason==4 && dual_shared.guard==DUAL_GUARD);
#else
 assert(dual_shared.seq==21 && dual_shared.stage==2 && !dual_shared.error);
 assert(trace.stage==5 && !trace.reason);
#endif
 control.session=2;control.unused[0]=0;
 inject_fault();assert(control.unused[0]==0); /* Replacement never reinjects. */
 return 0;
}
''')
            for case in (5,6):
                exe=root/f'fatal-{case}'
                subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',
                    '-ffunction-sections','-fdata-sections','-Wl,--gc-sections',
                    '-fsanitize=undefined','-fno-sanitize-recover=all',
                    '-DCONFIG_BES2700_M55_RESTART=1','-DCONFIG_BES2700_M55_RECOVERY=1',
                    f'-DCONFIG_BES2700_M55_FAULT_CASE={case}',
                    '-DCONFIG_SYS_CLOCK_HW_CYCLES_PER_SEC=24000000','-DCONFIG_DUAL_M55_BUILD=1',
                    '-I',str(root),'-I',str(ROOT/'include/bestechnic/bes2700yp'),str(source),
                    '-o',str(exe)],check=True)
                subprocess.run([str(exe)],check=True,timeout=10)
