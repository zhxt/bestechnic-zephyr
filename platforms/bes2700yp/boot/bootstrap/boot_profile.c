/* SPDX-License-Identifier: Apache-2.0 */
#ifndef BOOTPROF_HOST_TEST
#include "arch.h"
#include <bestechnic/bes2700yp/hw.h>
#include "bth_contract.h"
#include "boot_profile_id.h"
#include <stddef.h>
/* Register offsets and timer configuration are asserted in the HAL producer. */
#define CONFIG_SYSTICK_HZ BES2700YP_SLOW_HZ
#define CONFIG_SYSTICK_HZ_NOMINAL BES2700YP_SLOW_NOMINAL_HZ
#define BP_READ(a) (*(volatile uint32_t *)(uintptr_t)(a))
#define BP_RAM __attribute__((section(".boot_text_sram.boot_profile"),noinline))
#endif
#include "boot_profile.h"
#define BP ((volatile struct boot_profile *)(uintptr_t)BP_ADDR)
#define GUARD (*(volatile uint32_t *)(uintptr_t)(BP_END-4))
void bootprof_reset(void) { BP->magic=0; }
/* Called only before measurement. No timer, clock or DWT registers are written. */
void bootprof_init(uint32_t bytes,uint32_t crc)
{
 volatile uint32_t *p=(void *)(uintptr_t)BP_ADDR;
 for(unsigned i=0;i<(BP_END-BP_ADDR)/4;i++) { p[i]=0; }
 BP->bytes=bytes;BP->crc=crc;BP->slow_hz=CONFIG_SYSTICK_HZ;
 BP->slow_nominal=CONFIG_SYSTICK_HZ_NOMINAL;
#ifdef CALIB_SLOW_TIMER
 BP->slow_calibrated=1;
#endif
 GUARD=BP_GUARD;BP->magic=BP_MAGIC;__DMB();
}
/* Bounded synchronization read; only this function and mark form the hot path. */
static uint32_t BP_RAM bootprof_fast(uint32_t *error)
{
 for(unsigned i=0;i<10000;i++) {
  uint32_t a=BP_READ(0x40002004U),b=BP_READ(0x40002004U);
  if(a>=b && a-b<=20) { return 0U-b; }
 }
 *error|=1;return 0;
}
void BP_RAM bootprof_mark(uint32_t id,uint32_t crc)
{
 if(BP->magic!=BP_MAGIC || GUARD!=BP_GUARD) { BP->error|=2;return; }
 if(id!=BP->count || id>=BP_POINTS) { BP->error|=4;return; }
 volatile struct boot_profile_point *p=&BP->point[id];
 uint32_t error=0;
 p->id=id;p->fast0=bootprof_fast(&error);
 /* Native 32-bit always-on free-running counter, same source as SDK slow get. */
 p->slow=BP_READ(0x40080050U);p->fast1=bootprof_fast(&error);
 p->fast_ctrl=BP_READ(0x40002008U);p->fast_load=BP_READ(0x40002000U);
 p->periph=BP_READ(0x4000005cU);p->sysclk=BP_READ(0x40000060U);
 p->sysdiv=BP_READ(0x40000068U);p->cache=BP_READ(0x07ffa000U);
 p->mpu=BP_READ(0xe000ed94U);p->primask=__get_PRIMASK();p->basepri=__get_BASEPRI();
 p->log_last=BP_READ(0x2055c188U);p->log_lo=BP_READ(0x2055c190U);p->log_hi=BP_READ(0x2055c194U);
 p->crc=crc;p->demcr=BP_READ(0xe000edfcU);
 /* Optional passive observation only. Do not enable trace or write CYCCNT. */
 if(p->demcr&(1U<<24)) {
  p->dwt_ctrl=BP_READ(0xe0001000U);
  if(!(p->dwt_ctrl&(1U<<25)) && (p->dwt_ctrl&1)) {
   p->dwt_cycles=BP_READ(0xe0001004U);p->dwt_valid=1;
  }
 }
 p->fast_end=bootprof_fast(&error);p->error=error;BP->error|=error;
 __DMB();BP->count=id+1;__DMB();
}
#ifndef BOOTPROF_HOST_TEST
void bootprof_dump(void)
{
 if(BP->magic!=BP_MAGIC) { return; }
 uint32_t count=BP->count,guard=GUARD==BP_GUARD;
 uint32_t error=BP->error | (count!=BP_POINTS?8:0) | (!guard?16:0);
 bth_log_begin(error?'E':'I',"BOOT","EARLY");
 bth_puts("zephyr_bootprof begin version=1");
 bth_field(" variant=",BOOT_PROFILE_VARIANT);
 bth_field(" profile=",BOOT_PROFILE_ID);bth_field(" points=",BP_POINTS);
 bth_field(" bytes=",BP->bytes);bth_field(" expected_crc=",BP->crc);
 bth_field(" fast_hz=",BTH_TIMER_HZ);bth_field(" slow_hz=",BP->slow_hz);
 bth_field(" slow_nominal=",BP->slow_nominal);bth_field(" slow_calibrated=",BP->slow_calibrated);
 bth_field(" sampler=",(uint32_t)(uintptr_t)bootprof_mark);
 bth_field(" buffer=",BP_ADDR);bth_field(" size=",sizeof(*BP));bth_end();
 if(count>BP_POINTS) { count=BP_POINTS; }
 for(unsigned i=0;i<count;i++) {
  const volatile struct boot_profile_point *p=&BP->point[i];
  bth_log_begin(p->error?'E':'I',"BOOT","EARLY");bth_puts("zephyr_bootprof point");
#define PRINT(n) bth_field(" " #n "=",p->n);
  BP_FIELDS(PRINT)
#undef PRINT
  bth_end();
 }
 bth_log_begin(error?'E':'I',"BOOT","EARLY");bth_puts("zephyr_bootprof result");
 bth_field(" pass=",!error);bth_field(" points=",count);bth_field(" error=",error);
 bth_field(" guard=",guard);bth_end();
 BP->magic=0; /* Avoid a duplicate dump if a later boot operation fails. */
}
#endif
