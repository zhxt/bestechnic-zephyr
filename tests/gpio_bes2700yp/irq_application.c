/* SPDX-License-Identifier: Apache-2.0 */
#include <stdlib.h>
#include <stdio.h>
#include "shim.h"
#include "bth_contract.h"
#include <bes2700yp_gpio_irq.h>
#include "../../bsp/drivers/gpio/gpio_bes2700yp.c"
static struct bes_gpio_config config={.common={.port_pin_mask=0x30000}};
static struct bes_gpio_data driver_data;
struct device test_device={.config=&config,.data=&driver_data};
const struct gpio_driver_api *test_api=&bes_gpio_api;
static uint32_t now,pending,port=0x30000;
static bool suppress;
static struct bes_gpio_irq_state hw;
uint32_t k_uptime_get_32(void){return now;}
void bth_puts(const char *s){fputs(s,stdout);}
void bth_dec(uint32_t n){printf("%u",n);}
void bth_log_begin(char level,const char *module,const char *ctx){printf("%u/%c/BTH/%s/%s | ",now,level,module,ctx);}
void bth_end(void){puts(" !");}
int bes_gpio_connect(void){return 0;}
int bes_gpio_call(uint32_t op,uint32_t pin,uint32_t value,struct bes_gpio_io *io)
{(void)op;(void)pin;(void)value;io->snapshot.fault=0;io->snapshot.inputs=port;return 0;}
int bes_gpio_irq_connect(void){return 0;}
int bes_gpio_irq_call(uint32_t op,uint32_t pin,uint32_t mode)
{
 assert(!irq_mask);
 if(op==BES_GPIO_IRQ_CLAIM){hw.wake_mask|=1;return 0;}
 if(op==BES_GPIO_IRQ_ACK){uint32_t bits=pending;pending=0;return bits;}
 assert(op==BES_GPIO_IRQ_CONFIG && (pin==16||pin==17) && mode<3);
 uint32_t bit=BIT(pin);
 hw.enabled=(hw.enabled&~bit)|(mode?bit:0);hw.route=hw.enabled;
 hw.masked=(hw.masked&~bit)|(mode?0:bit);
 if(mode){hw.edge|=bit;hw.rising=(hw.rising&~bit)|(mode==2?bit:0);}
 return 0;
}
int bes_gpio_irq_read(struct bes_gpio_irq_io *io)
{assert(!nvic_enabled && !irq_mask);io->state=hw;return 0;}
#include "../../apps/bes2700yp/bth/src/gpio_irq_validation.c"
static int poll_for(uint32_t ms)
{
 for(uint32_t end=now+ms;now<end;now+=10){
  int rc=bes_gpio_validation_poll();if(rc){return rc;}
 }
 return 0;
}
static void levels(uint32_t next)
{
 uint32_t changes=port^next;
 pending=changes&hw.enabled&((next&hw.rising)|(~next&~hw.rising));
 port=next;
 if(pending && nvic_enabled && !suppress){in_isr=true;gpio_bes_isr(&test_device);in_isr=false;}
}
int main(int argc,char **argv)
{
 assert(argc==2);int scenario=atoi(argv[1]);
 assert(!gpio_bes_init(&test_device));assert(!bes_gpio_validation_init());
 assert(!poll_for(100));assert(!bes_gpio_validation_done());
 if(scenario==1){
  suppress=true;levels(0);assert(!poll_for(100));levels(0x30000);assert(poll_for(100)==110);
 }else if(scenario==2){
  for(unsigned i=0;i<33;i++){levels(0);levels(0x30000);}
  assert(poll_for(10)==106 && overflow);
 }else if(scenario==3){
  now+=180001;assert(poll_for(10)==107);
 }else if(scenario==4){
  hw.route|=1;assert(bes_gpio_irq_validation_check(0)==102);
 }else{
  while(!bes_gpio_validation_done()){
   uint32_t prior=stage;
   assert(!poll_for(100));
   for(uint32_t i=0;i<target && stage==prior;i++){
    levels(0);assert(!poll_for(150));levels(0x30000);assert(!poll_for(150));
   }
  }
  assert(stage==4 && complete && !failure);assert(!bes_gpio_validation_functional());
  printf("%u/I/BTH/KERN/MAIN | zephyr_dual sample id=0 !\n",now);
  assert(!bes_gpio_irq_validation_check(1000));
  bes_gpio_validation_end();assert(!hw.enabled && !driver_data.callbacks.head);
 }
 return 0;
}
