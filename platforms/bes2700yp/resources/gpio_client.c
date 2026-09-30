/* SPDX-License-Identifier: Apache-2.0 */
#include <errno.h>
#include <bes2700_dual_boot.h>
#include <bes2700yp_gpio.h>
static const struct bes_resource_descriptor *service;
int bes_gpio_connect(void)
{
 service=0;
 const volatile struct dual_service *root=(void *)DUAL_SERVICE_ADDR;
 if(dual_service_validate(root)){return -ENODEV;}
 int32_t (*discover)(uint32_t,uint32_t)=(void *)(uintptr_t)root->dispatch;
 int32_t address=discover(BES_RESOURCE_DISCOVER,BES_GPIO_ABI);
 if(address<=0 || !bes_resource_descriptor_address_valid((uint32_t)address)){return -ENOTSUP;}
 const struct bes_resource_descriptor *d=(void *)(uintptr_t)(uint32_t)address;
 if(!bes_gpio_descriptor_valid(d)){return -ENOTSUP;}
 service=d;return 0;
}
int bes_gpio_call(uint32_t op,uint32_t pin,uint32_t value,struct bes_gpio_io *io)
{
 if(!service){return -ENODEV;}
 if(!bes_resource_buffer_valid((uint32_t)(uintptr_t)io,sizeof(*io))){return -EINVAL;}
 if((op==BES_GPIO_OUTPUT || op==BES_GPIO_WRITE) &&
    !(service->capabilities&BES_GPIO_OUTPUT_CAP)){return -ENOTSUP;}
 *io=(struct bes_gpio_io){.abi=BES_GPIO_ABI,.bytes=sizeof(*io),.resource=BES_GPIO_ID,
                         .pin=pin,.value=value};
 int32_t (*dispatch)(uint32_t,uint32_t,uint32_t)=(void *)(uintptr_t)service->dispatch;
 int32_t rc=dispatch(op,(uint32_t)(uintptr_t)io,sizeof(*io));
 if(rc==-1){return -EINVAL;}if(rc==-2){return -ENOTSUP;}
 if(rc==-3){return -EPERM;}if(rc==-4){return -EBUSY;}
 if(rc==-5){return -ENODEV;}if(rc){return -EIO;}
 const struct bes_gpio_snapshot *s=&io->snapshot;
 if(s->abi!=BES_GPIO_ABI || s->bytes!=64 || s->phase>5 || s->fault>1 ||
    s->pins!=BES_GPIO_PINS || ((s->inputs|s->directions|s->outputs)&~BES_GPIO_PINS)){
  return -EIO;
 }
 if(op==BES_GPIO_SAMPLE && (s->directions || s->outputs || s->mux_led || s->mux_keys ||
    s->pull_up || s->pull_down || s->clocks || s->resets || s->irq_enabled || s->control)){
  return -EIO;
 }
 return 0;
}
