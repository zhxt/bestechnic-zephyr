/* SPDX-License-Identifier: Apache-2.0 */
/* Resident bare HAL bridge. Only BTH Zephyr's loader calls this service.
 * No RTX, DMA, vendor trace, IRQ registration or automatic M55 application. */
#include "arch.h"
#include <bes2700yp_resources.h>
#include <bes2700yp_uart_resources.h>

extern const struct bes_resource_descriptor bes_resource_service;
extern const struct bes_resource_descriptor bes_uart_resource_service;
#include <bestechnic/bes2700yp/hw.h>
#include "bes2700_dual_boot.h"
static uint32_t phase, release_sp, release_pc;
uint32_t dual_service_phase(void) { return phase; }
#ifdef BES_BTH_M55_RESTART
#include "bth_contract.h"
#include "reset_timer.h"
#ifndef BES_RESET_HOST_TEST
/* Frozen HAL AONCMU GBL_RESET_CLR and BTH timer control registers. */
#define RESET_READBACK() BTH_REG(0x400800ccU)
#define RESET_TIMER_CTRL() BTH_REG(BTH_TIMER_BASE+8U)
#endif
/* Frozen producer reg_aoncmu_best1600.h: SOFT_RSTN_MCUCPU_CLR is bit 4.
 * Interpret the existing public snapshot here, never in the Zephyr apps. */
#define M55_CPU_RESET_RELEASE (1U << 4)
static int reset_status(void)
{
 struct bes2700yp_hw_snapshot h;
 __DSB();bes2700yp_snapshot(&h);
 return h.reset_clr & M55_CPU_RESET_RELEASE ? -6 : 0;
}
static int BES_RESET_RAM hold_cpu_reset(uint32_t op)
{
 struct bes_reset_diag d={0};
 d.version=BES_RESET_DIAG_VERSION;d.op=op;
 d.sampler=(uint32_t)(uintptr_t)bes_reset_timer_read;
 d.primask=__get_PRIMASK();d.timer_ctrl=RESET_TIMER_CTRL();
 d.reset_before=RESET_READBACK();
 phase=5; /* Fault until hardware confirms reset; never permit REPARK here. */
 int rc=0;
 if(BTH_DIAG->error==91) { d.reason=BES_RESET_CLOCK_LATCHED;rc=-10; }
 else if((d.timer_ctrl&0x82U)!=0x82U) { d.reason=BES_RESET_TIMER_CONFIG;rc=-11; }
 else if(bes_reset_timer_read(&d,&d.raw_start)) { d.reason=BES_RESET_SAMPLE_FAILED;rc=-7; }
 /* Always contain the peer, including when the initial timer sample fails. */
 bes2700yp_m55_stop();__DSB();
 d.reset_after=RESET_READBACK();
 for(unsigned poll=0;!rc && poll<BES_RESET_POLL_LIMIT;poll++) {
  d.polls++;d.reset_after=RESET_READBACK();
  if(bes_reset_timer_read(&d,&d.raw_end)) { d.reason=BES_RESET_SAMPLE_FAILED;rc=-7;break; }
  d.elapsed=d.raw_end-d.raw_start;
  if(BTH_DIAG->error==91) { d.reason=BES_RESET_CLOCK_LATCHED;rc=-10;break; }
  if(d.elapsed>=BES_LIFECYCLE_RESET_MS*(BTH_TIMER_HZ/1000U)) {
   d.reason=BES_RESET_TIMEOUT;rc=-8;break;
  }
  if(!(d.reset_after&M55_CPU_RESET_RELEASE)) { phase=4;break; }
 }
 if(!rc && phase!=4) { d.reason=BES_RESET_POLL_EXHAUSTED;rc=-9; }
 d.service_rc=(uint32_t)rc;d.diag_error=BTH_DIAG->error;
 volatile uint32_t *out=(void *)BES_RESET_DIAG;
 const uint32_t *in=(const void *)&d;
 for(unsigned i=0;i<sizeof(d)/4;i++) { out[i]=in[i]; }
 __DSB();return rc;
}
static __attribute__((noinline)) int repark_cpu(void)
{
 _Static_assert(BES2700YP_REPARK_API==1,"repark HAL contract");
 struct bes2700yp_repark_result hw;
 BES_REPARK_DIAG->version=BES_REPARK_DIAG_VERSION;
 BES_REPARK_DIAG->op=BES_LIFECYCLE_REPARK;
 BES_REPARK_DIAG->phase_before=phase;
 phase=5; /* A failed mapping or readback never permits CPU release. */
 int rc=bes2700yp_m55_repark_prepare(&hw);
#define COPY_PARK(n) BES_REPARK_DIAG->n=hw.n;
 BES_REPARK_HW_FIELDS(COPY_PARK)
#undef COPY_PARK
 if(!rc) { bes2700yp_m55_start(DUAL_DTCM);phase=2; }
 else { bes2700yp_m55_stop();__DSB(); }
 BES_REPARK_DIAG->service_rc=(uint32_t)rc;BES_REPARK_DIAG->phase_after=phase;
 __DSB();return rc;
}
#endif
static int dual_dispatch(uint32_t op, uint32_t arg)
{
 if (op == BES_RESOURCE_DISCOVER) {
  if (arg == BES_UART_RESOURCE_ABI) { return (int32_t)(uintptr_t)&bes_uart_resource_service; }
  return arg == BES_RESOURCE_ABI ? (int32_t)(uintptr_t)&bes_resource_service : BES_RESOURCE_UNSUPPORTED;
 }
#ifdef BES_BTH_M55_RESTART
 if(op==BES_LIFECYCLE_RESET_STATUS && phase==4) {
  int rc=reset_status();if(rc) { phase=5; }return rc;
 }
 if(op==BES_LIFECYCLE_REPARK && phase==4) {
  return repark_cpu();
 }
#endif
 if (op == DUAL_SNAPSHOT && arg == DUAL_HW_ADDR && phase >= 2 && phase <=
#ifdef BES_BTH_M55_RESTART
     5
#else
     3
#endif
     ) {
  struct bes2700yp_hw_snapshot snapshot;
  bes2700yp_snapshot(&snapshot);
  volatile struct dual_hw *h=DUAL_HW;
  h->phase=phase;
  h->core_vtor=snapshot.core_vtor;
  h->reset_set=snapshot.reset_set; h->reset_clr=snapshot.reset_clr;
  h->ram_sel0=snapshot.ram_sel0; h->ram_sel1=snapshot.ram_sel1;
  h->oclk=snapshot.oclk; h->oreset=snapshot.oreset; h->sysclk=snapshot.sysclk;
  /* The TCM window need not be accessible while the CPU is held reset. */
  h->vector_sp=phase<4?*(volatile uint32_t *)DUAL_DTCM:0;
  h->vector_pc=phase<4?*(volatile uint32_t *)(DUAL_DTCM+4):0;
  h->release_sp=release_sp; h->release_pc=release_pc; __DSB(); return 0;
 }
 if (op == DUAL_CHECK_CLOCK) {
  return bes2700yp_clocks_are_24m();
 }
 if (op == DUAL_PREPARE && phase == 0) {
  int rc = bes2700yp_m55_prepare();
  if (rc) { return rc; }
  phase = 1; return 0;
 }
 if (op == DUAL_PARK && phase == 1) {
  /* Caller waits 2 ms after PREPARE, as required by the vendor loader. */
  bes2700yp_m55_park_word(DUAL_DTCM, DUAL_MAILBOX);
  bes2700yp_m55_park_word(DUAL_DTCM + 4, (DUAL_DTCM + 8) | 1);
  bes2700yp_m55_park_word(DUAL_DTCM + 8, 0xe7fdbf30U);
  __DSB();
  bes2700yp_m55_dtcm_enable();
  bes2700yp_m55_start(DUAL_DTCM);
  phase = 2; return 0;
 }
 if (op == DUAL_RELEASE && phase == 2 && arg == (DUAL_TRAMPOLINE | 1)) {
  /* Match SDK: write and verify while M55 is parked, BEFORE CPU reset. */
  *(volatile uint32_t *)DUAL_DTCM = DUAL_MAILBOX;
  *(volatile uint32_t *)(DUAL_DTCM + 4) = arg;
  __DSB();
  release_sp=*(volatile uint32_t *)DUAL_DTCM;
  release_pc=*(volatile uint32_t *)(DUAL_DTCM+4);
  if (release_sp!=DUAL_MAILBOX || release_pc!=arg) { return -5; }
#ifdef BES_BTH_M55_RESTART
  int rc=hold_cpu_reset(DUAL_RELEASE);if(rc) { return rc; }
#else
  bes2700yp_m55_stop();
#endif
  bes2700yp_m55_start(DUAL_DTCM);
  phase = 3; return 0;
 }
 if (op == DUAL_STOP && phase >= 2) {
  /* CPU reset only: RAM, clocks and the power domain remain enabled. */
#ifdef BES_BTH_M55_RESTART
  if(phase==5) { return -6; }
  if(phase==4) {
   int rc=reset_status();if(rc) { phase=5; }return rc;
  }
  return hold_cpu_reset(DUAL_STOP);
#else
  bes2700yp_m55_stop(); phase = 4; return 0;
#endif
 }
 return -4;
}
void dual_service_init(void)
{
 volatile struct dual_service *s = (void *)DUAL_SERVICE_ADDR;
 s->magic = 0;
 s->layout = DUAL_LAYOUT; s->dispatch = (uint32_t)dual_dispatch;
 s->itcm = DUAL_ITCM; s->itcm_size = 0x40000U;
 s->dtcm = DUAL_DTCM; s->dtcm_size = 0xa0000U; s->mailbox = DUAL_MAILBOX;
 __DSB(); s->magic = DUAL_SERVICE_MAGIC; __DSB();
}
