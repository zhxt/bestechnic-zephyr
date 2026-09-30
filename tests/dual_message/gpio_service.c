/* SPDX-License-Identifier: Apache-2.0 */
#define _GNU_SOURCE
#include <assert.h>
#include <stdint.h>
#include <string.h>
#include <sys/mman.h>
#define BES2700YP_BOOTSTRAP_ARCH_H
#define BES_RESOURCE_HOST_TEST
static uint32_t ipsr, control, mask, phase=3;
static unsigned calls;
static int hw_error, preempt;
static void simulate_preemption(void);
static uint32_t __get_IPSR(void) { return ipsr; }
static uint32_t __get_CONTROL(void) { return control; }
static uint32_t __get_PRIMASK(void) { return mask; }
static void __disable_irq(void) { mask=1; }
static void __set_PRIMASK(uint32_t v) { mask=v; }
#include <bestechnic/bes2700yp/hw.h>
uint32_t dual_service_phase(void) { return phase; }
int bes2700yp_gpio_access(uint32_t op,uint32_t pin,uint32_t value,struct bes2700yp_gpio_state *s)
{
 assert(mask==0);simulate_preemption();assert(op==1 || pin==16 || pin==17 || pin==12);assert(value<=1);calls++;
 *s=(struct bes2700yp_gpio_state){.pins=0x33000,.inputs=0x33000};return hw_error;
}
int bes2700yp_gpio_sample(uint32_t *inputs)
{
 assert(!mask);simulate_preemption();calls++;*inputs=0x33000;return hw_error;
}
#include "../../platforms/bes2700yp/boot/bootstrap/arbitration.c"
#include "../../platforms/bes2700yp/boot/bootstrap/gpio_service.c"
#include <bes2700yp_gpio_validation.h>
static void simulate_preemption(void)
{
 assert(bes_arbitration_busy());
 if(preempt){
  uint32_t owner=bes_arbitration_busy();
  assert(bes_gpio_dispatch(BES_GPIO_READ,BES_RESOURCE_RAM_START,96)==-4);
  assert(bes_arbitration_enter(DUAL_STOP,phase)==BES_ARBITRATION_BUSY);
  assert(bes_arbitration_state.pending && bes_arbitration_busy()==owner && !mask);
  ipsr=15;
  assert(bes_gpio_dispatch(BES_GPIO_READ,BES_RESOURCE_RAM_START,96)==-3);
  ipsr=0;
 }
}
static struct bes_gpio_io *io=(void *)BES_RESOURCE_RAM_START;
static void reset(void)
{
 memset(io,0xa5,sizeof(*io));io->abi=4;io->bytes=96;io->resource=4;
 io->pin=io->value=0;memset(io->reserved,0,sizeof(io->reserved));calls=0;
}
static int call(uint32_t op){return bes_gpio_dispatch(op,BES_RESOURCE_RAM_START,96);}
static void rejected(uint32_t op,int rc)
{
 struct bes_gpio_io before=*io;
 assert(call(op)==rc);assert(!memcmp(io,&before,sizeof(*io)) && !calls);
}
int main(void)
{
 assert(mmap(io,BES_RESOURCE_RAM_END-BES_RESOURCE_RAM_START,PROT_READ|PROT_WRITE,
   MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0)==io);
 reset();assert(!call(1));assert(calls==1 && !mask && io->snapshot.pins==0x33000);
 reset();preempt=1;assert(!call(1) && calls==1 && !mask && !bes_arbitration_busy());
 reset();assert(!call(5) && calls==1 && io->snapshot.inputs==0x33000);
 assert(!io->snapshot.clocks && !io->snapshot.outputs && !io->snapshot.mux_keys);
 assert(bes_arbitration_state.entered==bes_arbitration_state.exited);
 preempt=0;
 reset();io->pin=16;rejected(5,-1);
 reset();ipsr=1;rejected(1,-3);ipsr=0;control=1;rejected(1,-3);control=0;
 mask=1;rejected(1,-3);mask=0;rejected(0,-2);
 assert(bes_gpio_dispatch(1,BES_RESOURCE_RAM_END-92,96)==-1 && !calls);
 assert(bes_gpio_dispatch(1,BES_RESOURCE_RAM_START+1,96)==-1 && !calls);
 io->bytes=95;rejected(1,-1);reset();io->abi=3;rejected(1,-2);reset();
 io->reserved[2]=1;rejected(1,-1);reset();io->pin=18;rejected(2,-1);
 io->pin=13;rejected(3,-1);io->pin=12;
#if BES_GPIO_MODE == 1
 rejected(3,-2);rejected(4,-2);
#else
 assert(!call(3));assert(calls==1 && !mask && !bes_arbitration_busy());
#endif
 reset();bes_arbitration_state.owner=3;rejected(1,-4);io->pin=16;rejected(2,-4);
 bes_arbitration_state.owner=0;
 for(unsigned p=0;p<=5;p++) {
  reset();phase=p;io->pin=16;
  if(p!=3 && p!=4){rejected(2,-5);}else{assert(!call(2) && calls==1);}
  assert(!bes_arbitration_busy() && !mask);
 }
 phase=3;
 for(int h=-1;h>=-4;h--) {
  reset();hw_error=h;io->pin=17;struct bes_gpio_io before=*io;
  assert(call(2)==(h==-1?-1:h==-2?-4:h==-3?-5:-6));
  assert(calls==1 && !memcmp(io,&before,sizeof(*io)) && !mask && !bes_arbitration_busy());
 }
 reset();hw_error=0;io->pin=16;rejected(2,-6);assert(gpio_fault==1);
 io->pin=0;assert(!call(1) && io->snapshot.fault==1);
 struct bes_gpio_button b={0};
 assert(!bes_gpio_button_update(&b,0,0));assert(bes_gpio_button_update(&b,0,50));
 assert(!b.presses && !b.releases); /* Held at boot is never a cycle. */
 assert(!bes_gpio_button_update(&b,1,100));assert(bes_gpio_button_update(&b,1,150));
 assert(!bes_gpio_button_update(&b,0,200));assert(!bes_gpio_button_update(&b,1,210));
 assert(!bes_gpio_button_update(&b,0,220));assert(!bes_gpio_button_update(&b,0,269));
 assert(bes_gpio_button_update(&b,0,270));assert(b.presses==1 && !b.releases);
 assert(!bes_gpio_button_update(&b,1,300));assert(bes_gpio_button_update(&b,1,350));
 assert(b.presses==1 && b.releases==1);
 return 0;
}
