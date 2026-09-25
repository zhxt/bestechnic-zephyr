/* SPDX-License-Identifier: Apache-2.0 */
/* Resident bare HAL bridge. Only BTH Zephyr's loader calls this service.
 * No RTX, DMA, vendor trace, IRQ registration or automatic M55 application. */
#include "arch.h"
#include <bestechnic/bes2700yp/hw.h>
#include "bes2700_dual_boot.h"
static uint32_t phase, release_sp, release_pc;
static int dual_dispatch(uint32_t op, uint32_t arg)
{
 if (op == DUAL_SNAPSHOT && arg == DUAL_HW_ADDR && phase >= 2 && phase <= 3) {
  struct bes2700yp_hw_snapshot snapshot;
  bes2700yp_snapshot(&snapshot);
  volatile struct dual_hw *h=DUAL_HW;
  h->phase=phase;
  h->core_vtor=snapshot.core_vtor;
  h->reset_set=snapshot.reset_set; h->reset_clr=snapshot.reset_clr;
  h->ram_sel0=snapshot.ram_sel0; h->ram_sel1=snapshot.ram_sel1;
  h->oclk=snapshot.oclk; h->oreset=snapshot.oreset; h->sysclk=snapshot.sysclk;
  h->vector_sp=*(volatile uint32_t *)DUAL_DTCM;
  h->vector_pc=*(volatile uint32_t *)(DUAL_DTCM+4);
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
  bes2700yp_m55_stop();
  bes2700yp_m55_start(DUAL_DTCM);
  phase = 3; return 0;
 }
 if (op == DUAL_STOP && phase >= 2) {
  /* Keep RAM powered. Full power-off/restart belongs to V08d. */
  bes2700yp_m55_stop(); phase = 4; return 0;
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
