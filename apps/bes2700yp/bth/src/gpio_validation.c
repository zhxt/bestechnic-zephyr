/* SPDX-License-Identifier: Apache-2.0 */
#include <zephyr/kernel.h>
#include <errno.h>
#include "bth_contract.h"
#include <bes2700yp_gpio.h>
#include <bes2700yp_gpio_validation.h>
#define MODE CONFIG_BES2700YP_GPIO_VALIDATION
#define TARGET 10U
#define LIMIT_MS 300000U
static struct bes_gpio_io io, sample_io;
static struct bes_gpio_snapshot baseline;
static struct bes_gpio_button keys[2];
static uint32_t start, next_poll, next_snapshot, led_steps, led_changed, led_level=1;
static uint32_t samples, pad_checks, reported, busy_count, busy_since;
static uint32_t calls[3], max_ticks[3], mask_errors;
static int done, error, led_claimed;
static void field(const char *name,uint32_t n){bth_puts(name);bth_dec(n);}
static void begin(const char *kind,int rc)
{
 bth_log_begin(rc?'E':'I',"GPIO","MAIN");bth_puts("zephyr_gpio ");bth_puts(kind);
}
/* Measure the actual call with the independent fast timer. Never read SysTick
 * CTRL: reading COUNTFLAG would disturb the kernel timer's wrap accounting. */
static int __attribute__((noinline)) gpio_access(uint32_t op,uint32_t pin,uint32_t value,struct bes_gpio_io *out)
{
 uint32_t before_mask=__get_PRIMASK(), before=bth_ticks();
 int rc=bes_gpio_call(op,pin,value,out);
 uint32_t elapsed=bth_ticks()-before, after_mask=__get_PRIMASK();
 unsigned kind=op==BES_GPIO_SAMPLE?0:op==BES_GPIO_READ?1:2;
 calls[kind]++;if(elapsed>max_ticks[kind]){max_ticks[kind]=elapsed;}
 if(before_mask || after_mask){mask_errors++;return -EPERM;}
 return rc;
}
void bes_gpio_validation_timing(uint32_t sample,uint32_t rc)
{
 if(!sample || (!rc && sample!=1U && sample%10U)){return;}
 uint32_t load=SysTick->LOAD,val=SysTick->VAL;
 uint32_t pending=!!(SCB->ICSR&SCB_ICSR_PENDSTSET_Msk);
 uint32_t maximum=MAX(max_ticks[0],MAX(max_ticks[1],max_ticks[2]));
 begin("timing",rc);field(" version=",2);field(" sample=",sample);
 field(" ms=",k_uptime_get_32()-start);field(" calls=",calls[0]+calls[1]+calls[2]);
 field(" sample_calls=",calls[0]);field(" read_calls=",calls[1]);field(" write_calls=",calls[2]);
 field(" max_ticks=",maximum);field(" sample_max_ticks=",max_ticks[0]);
 field(" read_max_ticks=",max_ticks[1]);field(" write_max_ticks=",max_ticks[2]);
 field(" mask_errors=",mask_errors);field(" systick_load=",load);
 field(" systick_val=",val);field(" systick_pending=",pending);field(" rc=",rc);bth_end();
}
static void snapshot(uint32_t stage)
{
 begin("snapshot",0);field(" stage=",stage);field(" phase=",io.snapshot.phase);
 field(" fault=",io.snapshot.fault);
#define PRINT(n) bth_field(" " #n "=",io.snapshot.n);
 BES_GPIO_FIELDS(PRINT)
#undef PRINT
 bth_end();
}
static int preserved(void)
{
 const struct bes_gpio_snapshot *s=&io.snapshot;
 uint32_t changed=BES_GPIO_KEYS|(MODE==2?BES_GPIO_LED:0);
 uint32_t led_mux=MODE==2?(15U<<16):0;
 return !s->fault && s->clocks==baseline.clocks && s->resets==baseline.resets &&
  s->irq_enabled==baseline.irq_enabled && s->control==baseline.control &&
  !((s->mux_led^baseline.mux_led)&~led_mux) &&
  !((s->mux_keys^baseline.mux_keys)&~0xffU) &&
  !((s->pull_up^baseline.pull_up)&~changed) &&
  !((s->pull_down^baseline.pull_down)&~changed) &&
  !((s->directions^baseline.directions)&~changed) &&
  !((s->outputs^baseline.outputs)&~(MODE==2?BES_GPIO_LED:0)) &&
  !(s->directions&BES_GPIO_KEYS) && !(s->mux_keys&0xffU) &&
  (s->pull_up&BES_GPIO_KEYS)==BES_GPIO_KEYS && !(s->pull_down&BES_GPIO_KEYS) &&
  (MODE!=2 || ((s->directions&BES_GPIO_LED) && !(s->mux_led&(15U<<16)) &&
   !((s->pull_up|s->pull_down)&BES_GPIO_LED)));
}
static void result(uint32_t ms,int rc)
{
 begin("result",rc);field(" version=",2);field(" mode=",MODE);field(" pass=",!rc);
 field(" ms=",ms);field(" samples=",samples);
 field(" p0=",keys[0].presses);field(" r0=",keys[0].releases);
 field(" p1=",keys[1].presses);field(" r1=",keys[1].releases);
 field(" led_steps=",led_steps);field(" pad_checks=",pad_checks);
 field(" busy=",busy_count);field(" rc=",rc);bth_end();reported=1;
}
int bes_gpio_validation_init(void)
{
 begin("begin",0);field(" version=",2);bth_field(" build=",BTH_DIAG->build);
 field(" mode=",MODE);field(" target=",TARGET);field(" poll_ms=",10);
 field(" snapshot_ms=",1000);field(" debounce_ms=",50);field(" timeout_ms=",LIMIT_MS);bth_end();
 int rc=bes_gpio_connect();
 if(!rc){rc=gpio_access(BES_GPIO_READ,0,0,&io);}
 if(rc){begin("error",rc);field(" stage=",0);field(" rc=",-rc);bth_end();return 97;}
 baseline=io.snapshot;snapshot(0);
 rc=gpio_access(BES_GPIO_INPUT,16,0,&io);
 if(!rc){rc=gpio_access(BES_GPIO_INPUT,17,0,&io);}
 if(!rc && MODE==2){rc=gpio_access(BES_GPIO_OUTPUT,12,1,&io);led_claimed=!rc;}
 if(rc){begin("error",rc);field(" stage=",1);field(" rc=",-rc);bth_end();return 97;}
 snapshot(1);
 if(!preserved()){return 98;}
 start=k_uptime_get_32();next_snapshot=1000;
 begin("waiting",0);field(" pins=",BES_GPIO_KEYS);field(" cycles_each=",TARGET);bth_end();
 return 0;
}
int bes_gpio_validation_poll(void)
{
 uint32_t ms=k_uptime_get_32()-start;
 if(error){return error;}
 if(ms<next_poll){return 0;}next_poll=ms+10;
 int rc=gpio_access(BES_GPIO_SAMPLE,0,0,&sample_io);
 if(rc==-EBUSY){
  if(!busy_since){busy_since=ms+1;}busy_count++;
  if(ms+1-busy_since<100U){return 0;}
 }
 if(rc){error=99;}
 else {
  ms=k_uptime_get_32()-start;busy_since=0;samples++;
  if(sample_io.snapshot.fault || sample_io.snapshot.phase!=3){error=98;}
  if(ms>=next_snapshot && !error){
   rc=gpio_access(BES_GPIO_READ,0,0,&io);
   if(rc){error=99;}else if(!preserved()){error=98;}
   next_snapshot=ms+1000;
  }
  if(MODE==2 && ms-led_changed>=10U){
   if(!!(sample_io.snapshot.inputs&BES_GPIO_LED)!=led_level){error=100;}
   else {pad_checks++;}
  }
  for(unsigned i=0;i<2 && !done && !error;i++){
   uint32_t level=(sample_io.snapshot.inputs>>(16U+i))&1U;
   if(bes_gpio_button_update(&keys[i],level,ms)){
    begin("key",0);field(" pin=",16U+i);field(" ms=",ms);field(" level=",level);
    field(" presses=",keys[i].presses);field(" releases=",keys[i].releases);bth_end();
   }
  }
  if(MODE==2 && led_steps<20U && ms>=(led_steps+1U)*1000U && !error){
   led_level^=1U;rc=gpio_access(BES_GPIO_WRITE,12,led_level,&io);
   if(rc){error=101;}else if(!preserved()){error=98;}else {
    led_steps++;led_changed=ms;
    begin("led",0);field(" ms=",ms);field(" step=",led_steps);
    field(" pin=",12);field(" level=",led_level);bth_end();
   }
  }
 }
 if(!done && !error && keys[0].releases>=TARGET && keys[1].releases>=TARGET &&
    keys[0].stable && keys[1].stable && (MODE!=2 ||
     (led_steps==20 && pad_checks>=20 && ms-led_changed>=10U))){done=1;}
 if(!done && ms>=LIMIT_MS && !error){error=110;}
 if(error && !reported){result(ms,error);}
 return error;
}
int bes_gpio_validation_done(void){return done && !error;}
int bes_gpio_validation_functional(void)
{
 if(done && !reported){
  int rc=gpio_access(BES_GPIO_READ,0,0,&io);
  if(rc){error=99;}else if(!preserved()){error=98;}
  if(!error){snapshot(2);}result(k_uptime_get_32()-start,error);
 }
 return error;
}
void bes_gpio_validation_end(void)
{
 if(led_claimed){(void)gpio_access(BES_GPIO_WRITE,12,1,&io);}
}
