/* SPDX-License-Identifier: Apache-2.0 */
#include <zephyr/kernel.h>
#include <zephyr/drivers/gpio.h>
#include <cmsis_core.h>
#include <bes2700yp_gpio_irq.h>
#include <bes2700yp_gpio_irq_validation.h>
#include <bes2700yp_gpio_validation.h>
#include "bth_contract.h"

#define KEYS BES_GPIO_IRQ_KEYS
#define QUEUE_SIZE 32U
static const struct gpio_dt_spec keys[2] = {
 GPIO_DT_SPEC_GET(DT_ALIAS(sw0), gpios), GPIO_DT_SPEC_GET(DT_ALIAS(sw1), gpios),
};
struct irq_event { uint32_t pins; };
static struct irq_event events[QUEUE_SIZE];
static volatile uint32_t head, tail, overflow;
static struct gpio_callback callback;
static struct bes_gpio_button buttons[2];
static uint32_t credits[2], down_credit[2], cycles[2];
static uint32_t stage, mode, target, start_ms, reported, failure;
static int access_error;
static bool initialized, complete, functional_reported;
static struct bes_gpio_irq_state baseline;
static struct bes_gpio_irq_stats before;

static void field(const char *name, uint32_t value) { bth_puts(name); bth_dec(value); }
static void begin(const char *name)
{
 bth_log_begin(failure?'E':'I', "GPIO", "MAIN"); bth_puts("zephyr_gpio_irq "); bth_puts(name);
 field(" stage=", stage);
}
static void on_irq(const struct device *dev, struct gpio_callback *cb, uint32_t pins)
{
 ARG_UNUSED(dev); ARG_UNUSED(cb);
 uint32_t next=head+1U;
 if(next-tail>QUEUE_SIZE){overflow=1;return;}
 events[head%QUEUE_SIZE].pins=pins;__DMB();head=next;
}
static int fail(uint32_t rc)
{
 failure=rc;begin("failure");field(" rc=",rc);field(" api_error=",(uint32_t)-access_error);bth_end();
 if(initialized){
  struct bes_gpio_irq_state state;
  int read=bes_gpio_irq_get_state(keys[0].port,&state);
  begin("diagnostic");field(" read_error=",(uint32_t)-read);
  if(!read){
#define DIAG(n) field(" " #n "=",state.n);
   BES_GPIO_IRQ_FIELDS(DIAG)
#undef DIAG
  }
  bth_end();
 }
 return (int)rc;
}
static int snapshot(uint32_t checkpoint)
{
 struct bes_gpio_irq_state s;
 struct bes_gpio_irq_stats stats;
 int rc=bes_gpio_irq_get_state(keys[0].port,&s);
 if(!rc){rc=bes_gpio_irq_get_stats(keys[0].port,&stats);}
 uint32_t enabled=mode?KEYS:0U;
 if(rc || stats.fault || overflow){return fail(101);}
 /* Only the two granted IRQ bits and the GPIO wake gate may change. */
 if((s.enabled&KEYS)!=enabled || (s.route&KEYS)!=enabled ||
    (s.masked&KEYS)!=(mode?0U:KEYS) || (s.edge&KEYS)!=KEYS ||
    (s.rising&KEYS)!=((mode==2U || mode==0U)?KEYS:0U) || (s.debounce&KEYS) ||
    (s.directions&KEYS) || !(s.wake_mask&1U) || (s.wake_status&~1U) ||
    (s.bth_status&~KEYS) || stats.enabled!=enabled ||
    ((s.enabled^baseline.enabled)&~KEYS) || ((s.masked^baseline.masked)&~KEYS) ||
    ((s.edge^baseline.edge)&~KEYS) || ((s.rising^baseline.rising)&~KEYS) ||
    ((s.debounce^baseline.debounce)&~KEYS) || ((s.route^baseline.route)&~KEYS) ||
    ((s.wake_mask^baseline.wake_mask)&~1U) || s.sys_route!=baseline.sys_route ||
    s.btc_route!=baseline.btc_route || s.sens_route!=baseline.sens_route ||
    s.directions!=baseline.directions){return fail(102);}
 begin("snapshot");field(" checkpoint=",checkpoint);field(" mode=",mode);
 field(" enabled=",s.enabled);field(" mask=",s.masked);field(" edge=",s.edge);
 field(" rising=",s.rising);field(" route=",s.route);field(" wake=",s.wake_mask);
 field(" irq=",stats.interrupts);field(" events0=",stats.events0);field(" events1=",stats.events1);
 field(" spurious=",stats.spurious);field(" max_cycles=",stats.max_ticks);
 field(" overflow=",overflow);field(" fault=",stats.fault);field(" rc=",0);bth_end();
 return 0;
}
static int set_mode(uint32_t wanted)
{
 /* Disable both before changing polarity. No pin direction/mux changes. */
 for(unsigned i=0;i<2;i++){
  access_error=gpio_pin_interrupt_configure(keys[i].port,keys[i].pin,GPIO_INT_DISABLE);
  if(access_error){return fail(103);}
 }
 for(unsigned i=0;i<2 && wanted;i++){
  access_error=gpio_pin_interrupt_configure(keys[i].port,keys[i].pin,
      wanted==2U?GPIO_INT_EDGE_RISING:GPIO_INT_EDGE_FALLING);
  if(access_error){return fail(103);}
 }
 mode=wanted;return 0;
}
int bes_gpio_irq_validation_start(uint32_t next)
{
 stage=next;complete=false;target=next==3U||next==4U?1U:10U;
 if(!initialized){
  if(!gpio_is_ready_dt(&keys[0]) || keys[0].port!=keys[1].port){return fail(104);}
  for(unsigned i=0;i<2;i++){
   if(gpio_pin_configure_dt(&keys[i],GPIO_INPUT)){return fail(104);}
  }
  if(bes_gpio_irq_get_state(keys[0].port,&baseline)){return fail(104);}
  gpio_init_callback(&callback,on_irq,KEYS);
  if(gpio_add_callback(keys[0].port,&callback)){return fail(104);}
  initialized=true;
 }
 /* Post-restart stage deliberately retains hardware state and registration. */
 if(next!=11U && set_mode(next==2U?2U:next==3U?0U:1U)){return (int)failure;}
 unsigned key=irq_lock();tail=head;irq_unlock(key);
 for(unsigned i=0;i<2;i++){
  buttons[i]=(struct bes_gpio_button){0};credits[i]=down_credit[i]=cycles[i]=0;
 }
 if(bes_gpio_irq_get_stats(keys[0].port,&before)){return fail(105);}
 start_ms=k_uptime_get_32();reported=0;
 begin("begin");field(" version=",1);field(" mode=",mode);field(" target=",target);
 field(" pins=",KEYS);field(" irq=",before.interrupts);
 field(" events0=",before.events0);field(" events1=",before.events1);field(" rc=",0);bth_end();
 if(snapshot(0)){return (int)failure;}
 begin("prompt");bth_puts(" release_both_then_press_and_release_each_key");field(" count=",target);bth_end();
 return 0;
}
int bes_gpio_irq_validation_poll(void)
{
 if(failure){return (int)failure;}
 struct bes_gpio_irq_stats stats;
 if(bes_gpio_irq_get_stats(keys[0].port,&stats) || stats.fault || overflow){return fail(106);}
 if(complete){return 0;}
 uint32_t now=k_uptime_get_32();
 if(now-start_ms>180000U){return fail(107);}
 /* One producer (IRQ 44), one consumer. At most a queue's worth per poll. */
 uint32_t limit=head;__DMB();
 while(tail!=limit){
  uint32_t pins=events[tail%QUEUE_SIZE].pins;
  if(!pins || (pins&~KEYS)){return fail(108);}
  for(unsigned i=0;i<2;i++){if(pins&(1U<<(16+i))){credits[i]++;}}
  __DMB();tail++;
 }
 gpio_port_value_t inputs;
 if(gpio_port_get_raw(keys[0].port,&inputs)){return fail(109);}
 for(unsigned i=0;i<2;i++){
  struct bes_gpio_button *b=&buttons[i];
  uint32_t prior_press=b->presses,prior_release=b->releases;
  int changed=bes_gpio_button_update(b,!!(inputs&(1U<<(16+i))),now);
  if(changed && b->presses!=prior_press){
   down_credit[i]=credits[i];credits[i]=0;
  }
  if(changed && b->releases!=prior_release){
   uint32_t evidence=mode==2U?credits[i]:down_credit[i];
   if(mode && !evidence){return fail(110);}
   if(!mode && (stats.events0!=before.events0 || stats.events1!=before.events1)){
    return fail(111);
   }
   cycles[i]++;begin("cycle");field(" pin=",16U+i);field(" count=",cycles[i]);
   field(" mode=",mode);field(" evidence=",evidence);field(" ms=",now-start_ms);
   field(" rc=",0);bth_end();
  }
  if(changed && b->stable){credits[i]=0;down_credit[i]=0;}
 }
 if(cycles[0]>=target && cycles[1]>=target && buttons[0].stable && buttons[1].stable){
  if(snapshot(1)){return (int)failure;}
  if(bes_gpio_irq_get_stats(keys[0].port,&stats)){return fail(112);}
  complete=true;begin("stage_result");field(" pass=",1);field(" mode=",mode);
  field(" count0=",cycles[0]);field(" count1=",cycles[1]);field(" target=",target);
  field(" irq=",stats.interrupts-before.interrupts);
  field(" events0=",stats.events0-before.events0);field(" events1=",stats.events1-before.events1);
  field(" ms=",now-start_ms);field(" rc=",0);bth_end();
 }else if(now-start_ms>=reported+10000U){
  reported=now-start_ms;begin("waiting");field(" count0=",cycles[0]);field(" count1=",cycles[1]);
  field(" target=",target);field(" ms=",reported);bth_end();
 }
 return 0;
}
int bes_gpio_irq_validation_done(void){return complete && !failure;}
int bes_gpio_irq_validation_check(uint32_t checkpoint)
{
 if(!initialized){return fail(113);}
 return snapshot(checkpoint);
}
int bes_gpio_irq_validation_result(void)
{
 if(!complete || failure){return fail(114);}
 functional_reported=true;begin("result");field(" version=",1);field(" pass=",1);field(" rc=",0);bth_end();return 0;
}
void bes_gpio_irq_validation_end(void)
{
 if(!initialized){return;}
 for(unsigned i=0;i<2;i++){(void)gpio_pin_interrupt_configure(keys[i].port,keys[i].pin,GPIO_INT_DISABLE);}
 (void)gpio_remove_callback(keys[0].port,&callback);
}
#ifndef CONFIG_BES2700_M55_RESTART
int bes_gpio_validation_init(void){return bes_gpio_irq_validation_start(1);}
int bes_gpio_validation_poll(void)
{
 int rc=bes_gpio_irq_validation_poll();
 if(!rc && complete && stage<4U){rc=bes_gpio_irq_validation_start(stage+1U);}
 return rc;
}
int bes_gpio_validation_done(void){return stage==4U && bes_gpio_irq_validation_done();}
int bes_gpio_validation_functional(void){return bes_gpio_irq_validation_result();}
void bes_gpio_validation_timing(uint32_t sample,uint32_t rc)
{
 ARG_UNUSED(rc);
 if(functional_reported){(void)bes_gpio_irq_validation_check(1000U+sample);}
}
void bes_gpio_validation_end(void){bes_gpio_irq_validation_end();}
#endif
