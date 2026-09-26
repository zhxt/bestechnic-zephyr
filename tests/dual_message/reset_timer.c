/* SPDX-License-Identifier: Apache-2.0 */
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#define BES_RESET_HOST_TEST
static uint32_t irq, initial_irq, calls, mode;
static uint32_t __get_PRIMASK(void) { return irq; }
static void __disable_irq(void) { irq=1; }
static void __set_PRIMASK(uint32_t key) { irq=key; }
static uint32_t timer_register_value(void)
{
 assert(irq==1);uint32_t n=calls++;
 if(mode==0) { return n%2?980:1000; } /* delta=20 is valid */
 if(mode==1) { return n%2?979:1000; } /* delta=21 must exhaust */
 if(mode==2) { return n<2?(n?0xffffffffU:0):(n%2?0xfffffffdU:0xfffffffeU); }
 if(mode==3) { return 500; } /* equal values are a valid instantaneous sample */
 if(mode==4) { return n%2?1001:1000; } /* backwards sample */
 return n<62?(n%2?979:1000):(n%2?990:1000); /* final allowed attempt */
}
#define RESET_VALUE() timer_register_value()
#include "../../platforms/bes2700yp/boot/bootstrap/reset_timer.c"
int main(void)
{
 for(initial_irq=0;initial_irq<2;initial_irq++) {
  for(mode=0;mode<6;mode++) {
   struct bes_reset_diag d={0};uint32_t result=0x12345678U;
   calls=0;irq=initial_irq;
   int rc=bes_reset_timer_read(&d,&result);
   assert(irq==initial_irq && calls==2*d.attempts);
   if(mode==1 || mode==4) {
    assert(rc==-7 && result==0x12345678U && d.attempts==32 && d.samples==0);
   } else {
    assert(rc==0 && d.samples==1 && result==0U-d.last_b);
    assert(d.attempts==(mode==2?2U:mode==5?32U:1U));
   }
   assert(d.max_attempts==d.attempts);
  }
 }
 puts("Actual SRAM reader: threshold, wrap, exhaustion, output and IRQ state pass");
}
