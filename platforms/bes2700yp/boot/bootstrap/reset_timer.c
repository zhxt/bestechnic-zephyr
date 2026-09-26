/* SPDX-License-Identifier: Apache-2.0 */
#include "reset_timer.h"
#ifndef BES_RESET_HOST_TEST
#include "arch.h"
#define RESET_VALUE() (*(volatile uint32_t *)0x40002004U)
#endif

/* The two MMIO reads must execute from SRAM even with Flash cache disabled.
 * Mask only this read pair; retry accounting and the caller run unmasked. */
int BES_RESET_RAM bes_reset_timer_read(struct bes_reset_diag *d, uint32_t *value)
{
 for(unsigned i=1;i<=BES_RESET_READ_ATTEMPTS;i++) {
  uint32_t key=__get_PRIMASK();
  __disable_irq();
  uint32_t a=RESET_VALUE(),b=RESET_VALUE();
  __set_PRIMASK(key);
  uint32_t delta=a-b;
  d->attempts++;d->last_a=a;d->last_b=b;
  if(i>d->max_attempts) { d->max_attempts=i; }
  if(delta>d->max_delta) { d->max_delta=delta; }
  if(a>=b && delta<=20) {
   *value=0U-b;d->samples++;return 0;
  }
 }
 /* Do not poison the unrelated logger's sticky error or publish fake ticks. */
 return -7;
}
