/* SPDX-License-Identifier: Apache-2.0 */
#include <assert.h>
#include <stdlib.h>
#include <string.h>
#include <errno.h>
#include <bes2700yp_gpio.h>
#include "bth_contract.h"
static uint32_t now, ticks, irq_mask;
static unsigned operations[6], results, led_records;
static int fail_op;
static struct bes_gpio_snapshot hardware={.abi=4,.bytes=64,.phase=3,
 .pins=BES_GPIO_PINS,.inputs=BES_GPIO_PINS,.mux_led=0x44444444,
 .clocks=0x4002,.resets=0x4002};
static struct mock_systick systick={.LOAD=23999,.VAL=12000};
static struct mock_scb scb;
static struct mock_diag diag;
struct mock_systick *SysTick=&systick;
struct mock_scb *SCB=&scb;
struct mock_diag *BTH_DIAG=&diag;
uint32_t k_uptime_get_32(void){return now;}
uint32_t bth_ticks(void){return ticks++;}
uint32_t __get_PRIMASK(void){return irq_mask;}
void bth_puts(const char *s){results+=!strcmp(s,"result");led_records+=!strcmp(s,"led");}
void bth_dec(uint32_t n){(void)n;}
void bth_field(const char *s,uint32_t n){(void)s;(void)n;}
void bth_log_begin(char c,const char *s,const char *t){(void)c;(void)s;(void)t;}
void bth_end(void){}
int bes_gpio_connect(void){return 0;}
int bes_gpio_call(uint32_t op,uint32_t pin,uint32_t value,struct bes_gpio_io *io)
{
 assert(op>=1 && op<=5);operations[op]++;
 /* Simulated slow MMIO can consume time, but does not mask SysTick. */
 ticks+=op==BES_GPIO_SAMPLE?100:24000;
 if(op==(uint32_t)fail_op){return -EIO;}
 if(op==BES_GPIO_INPUT){hardware.pull_up|=1U<<pin;}
 if(op==BES_GPIO_OUTPUT){
  hardware.directions|=1U<<pin;hardware.mux_led&=~(15U<<16);
 }
 if(op==BES_GPIO_OUTPUT || op==BES_GPIO_WRITE){
  hardware.outputs=(hardware.outputs&~(1U<<pin))|(value<<pin);
  hardware.inputs=(hardware.inputs&~(1U<<pin))|(value<<pin);
 }
 if(op==BES_GPIO_SAMPLE){
  io->snapshot=(struct bes_gpio_snapshot){.abi=4,.bytes=64,.phase=hardware.phase,
   .fault=hardware.fault,.pins=BES_GPIO_PINS,.inputs=hardware.inputs};
 }else{io->snapshot=hardware;}
 return 0;
}
#include "../../apps/bes2700yp/bth/src/gpio_validation.c"
static int run(uint32_t duration)
{
 for(uint32_t end=now+duration;now<end;now+=10){
  int rc=bes_gpio_validation_poll();if(rc){return rc;}
 }
 return 0;
}
int main(int argc,char **argv)
{
 assert(argc==2);int scenario=atoi(argv[1]);
 if(scenario==1){
  fail_op=BES_GPIO_INPUT;assert(bes_gpio_validation_init());
  bes_gpio_validation_end();assert(!operations[BES_GPIO_OUTPUT] && !operations[BES_GPIO_WRITE]);
  return 0;
 }
 assert(!bes_gpio_validation_init());
 if(scenario==2){
  assert(run(300020)==110);assert(results==1 && !bes_gpio_validation_done());return 0;
 }
 if(scenario==3){
  hardware.pull_up^=1U<<18;assert(run(1020)==98);assert(results==1);return 0;
 }
 if(scenario==4){
  fail_op=BES_GPIO_SAMPLE;assert(run(20)==99);assert(results==1);return 0;
 }
 if(scenario==5){
  irq_mask=1;assert(run(20)==99 && mask_errors==1);return 0;
 }
 if(scenario==6 && CONFIG_BES2700YP_GPIO_VALIDATION==2){
  fail_op=BES_GPIO_WRITE;assert(run(1020)==101);assert(!led_records);return 0;
 }
 /* No key press: remain interactive well beyond the first health sample. */
 assert(!run(30000));assert(!bes_gpio_validation_done() && !results);
 assert(operations[BES_GPIO_SAMPLE]==3000 && operations[BES_GPIO_READ]<=31);
 assert(led_records==(CONFIG_BES2700YP_GPIO_VALIDATION==2?20U:0U));
 for(unsigned i=0;i<10;i++){
  hardware.inputs&=~BES_GPIO_KEYS;assert(!run(500));
  hardware.inputs|=BES_GPIO_KEYS;assert(!run(500));
 }
 assert(bes_gpio_validation_done());
 if(scenario==7){
  hardware.pull_up^=1U<<18;
  assert(bes_gpio_validation_functional()==98 && results==1);return 0;
 }
 assert(!bes_gpio_validation_functional() && results==1);
 assert(!run(60000));assert(bes_gpio_validation_done() && results==1);
 assert(operations[BES_GPIO_SAMPLE]==10000 && operations[BES_GPIO_READ]<=102);
 bes_gpio_validation_end();
 assert(CONFIG_BES2700YP_GPIO_VALIDATION!=2 || (hardware.outputs&BES_GPIO_LED));
 return 0;
}
