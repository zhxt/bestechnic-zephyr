/* SPDX-License-Identifier: Apache-2.0 */
#include "shim.h"
#include <bes2700yp_gpio_irq.h>
#include "../../bsp/drivers/gpio/gpio_bes2700yp.c"
static struct bes_gpio_config config={.common={.port_pin_mask=0x30000}};
static struct bes_gpio_data data;
struct device test_device={.config=&config,.data=&data};
const struct gpio_driver_api *test_api=&bes_gpio_api;
static uint32_t now, pending, configured, calls, observed, behavior;
static int error;
uint32_t k_uptime_get_32(void){return now;}
int bes_gpio_connect(void){return 0;}
int bes_gpio_call(uint32_t op,uint32_t pin,uint32_t value,struct bes_gpio_io *io)
{(void)op;(void)pin;(void)value;io->snapshot.fault=0;return 0;}
int bes_gpio_irq_connect(void){return 0;}
int bes_gpio_irq_call(uint32_t op,uint32_t arg,uint32_t value)
{
 assert(!irq_mask);calls++;
 if(error){return error;}
 if(op==BES_GPIO_IRQ_CLAIM){assert(!in_isr && !nvic_enabled);return 0;}
 if(op==BES_GPIO_IRQ_CONFIG){
  assert((arg==16||arg==17) && value<=2);
  assert(!in_isr || !value);assert(in_isr || !nvic_enabled);
  configured=(configured&~BIT(arg))|(value?BIT(arg):0);return 0;
 }
 assert(op==BES_GPIO_IRQ_ACK && in_isr && !arg && !value);
 int result=pending;pending=0;return result;
}
int bes_gpio_irq_read(struct bes_gpio_irq_io *io)
{
 assert(!nvic_enabled && !irq_mask && !in_isr);
 io->state.enabled=configured;pending=BIT(17);return 0;
}
static void callback_fn(const struct device *dev,struct gpio_callback *cb,uint32_t pins)
{
 assert(in_isr && !irq_mask);observed|=pins;
 if(behavior==1){
  assert(!gpio_bes_pin_interrupt_configure(dev,16,GPIO_INT_MODE_DISABLED,GPIO_INT_TRIG_LOW));
  assert(!gpio_bes_manage_callback(dev,cb,false));
 }
}
static void fire(uint32_t pins){pending=pins;in_isr=true;gpio_bes_isr(&test_device);in_isr=false;}
int main(void)
{
 assert(!gpio_bes_init(&test_device));
 assert(gpio_bes_pin_interrupt_configure(&test_device,12,GPIO_INT_MODE_EDGE,GPIO_INT_TRIG_LOW)==-EINVAL);
 assert(gpio_bes_pin_interrupt_configure(&test_device,16,GPIO_INT_MODE_LEVEL,GPIO_INT_TRIG_LOW)==-ENOTSUP);
 assert(gpio_bes_pin_interrupt_configure(&test_device,16,GPIO_INT_MODE_EDGE,GPIO_INT_TRIG_BOTH)==-ENOTSUP);
 assert(!calls);irq_mask=1;
 assert(gpio_bes_pin_interrupt_configure(&test_device,16,GPIO_INT_MODE_EDGE,GPIO_INT_TRIG_LOW)==-EWOULDBLOCK);
 irq_mask=0;assert(!calls);
 assert(!gpio_bes_pin_interrupt_configure(&test_device,16,GPIO_INT_MODE_EDGE,GPIO_INT_TRIG_LOW));
 assert(!gpio_bes_pin_interrupt_configure(&test_device,17,GPIO_INT_MODE_EDGE,GPIO_INT_TRIG_HIGH));
 assert(nvic_enabled && configured==0x30000);
 struct gpio_callback cb={.handler=callback_fn,.pin_mask=0x30000};
 assert(!gpio_bes_manage_callback(&test_device,&cb,true));
 fire(BIT(16));assert(observed==BIT(16) && data.stats.events0==1);
 struct bes_gpio_irq_state state;
 assert(!bes_gpio_irq_get_state(&test_device,&state) && state.enabled==0x30000);
 assert(nvic_enabled && pending==BIT(17));fire(pending);assert(observed==0x30000);
 behavior=1;fire(BIT(16));assert(configured==BIT(17) && nvic_enabled && !data.callbacks.head);
 observed=0;fire(BIT(17));assert(!observed);
 assert(!gpio_bes_manage_callback(&test_device,&cb,true));behavior=0;
 in_isr=true;
 assert(gpio_bes_pin_interrupt_configure(&test_device,16,GPIO_INT_MODE_EDGE,GPIO_INT_TRIG_LOW)==-EWOULDBLOCK);
 in_isr=false;
 /* Unknown source is preserved by HAL; driver quarantines without a second ACK. */
 error=-EIO;uint32_t before=calls;fire(BIT(17));
 assert(calls==before+1 && data.stats.fault==EIO && !nvic_enabled);error=0;
 assert(gpio_bes_pin_interrupt_configure(&test_device,16,GPIO_INT_MODE_EDGE,GPIO_INT_TRIG_LOW)==-EIO);
 assert(!gpio_bes_pin_interrupt_configure(&test_device,17,GPIO_INT_MODE_DISABLED,GPIO_INT_TRIG_LOW));
 /* Explicit bounded-storm behavior and period reset. */
 data.stats.fault=0;data.rate_count=0;data.empty_count=0;data.stats.enabled=BIT(17);nvic_enabled=true;
 for(unsigned i=0;i<256;i++){fire(BIT(17));}assert(!data.stats.fault);
 now=100;fire(BIT(17));assert(!data.stats.fault && data.rate_count==1);
 for(unsigned i=0;i<256;i++){fire(BIT(17));}
 assert(data.stats.fault==EOVERFLOW && !nvic_enabled);
 data.stats.fault=0;now=200;data.empty_count=0;
 for(unsigned i=0;i<8;i++){fire(0);}assert(data.stats.fault==EIO);
 struct bes_gpio_irq_stats stats;assert(!bes_gpio_irq_get_stats(&test_device,&stats));
 assert(stats.fault==EIO && stats.spurious==8);
 return 0;
}
