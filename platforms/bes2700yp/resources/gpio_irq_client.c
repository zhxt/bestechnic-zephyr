/* SPDX-License-Identifier: Apache-2.0 */
#include <errno.h>
#include <bes2700_dual_boot.h>
#include <bes2700yp_gpio_irq.h>
static const struct bes_resource_descriptor *irq_service;
int bes_gpio_irq_connect(void)
{
 irq_service=0;
 const volatile struct dual_service *root=(void *)DUAL_SERVICE_ADDR;
 if(dual_service_validate(root)){return -ENODEV;}
 int32_t (*discover)(uint32_t,uint32_t)=(void *)(uintptr_t)root->dispatch;
 int32_t address=discover(BES_RESOURCE_DISCOVER,BES_GPIO_IRQ_ABI);
 if(address<=0 || !bes_resource_descriptor_address_valid((uint32_t)address)){return -ENOTSUP;}
 const struct bes_resource_descriptor *d=(void *)(uintptr_t)(uint32_t)address;
 if(!bes_gpio_irq_descriptor_valid(d)){return -ENOTSUP;}
 irq_service=d;return 0;
}
int bes_gpio_irq_call(uint32_t op,uint32_t arg,uint32_t value)
{
 if(!irq_service){return -ENODEV;}
 int32_t (*dispatch)(uint32_t,uint32_t,uint32_t)=(void *)(uintptr_t)irq_service->dispatch;
 int32_t rc=dispatch(op,arg,value);
 if(rc==-1){return -EINVAL;}if(rc==-2){return -EBUSY;}
 if(rc==-3){return -ENODEV;}if(rc==-4){return -EIO;}
 if(rc==-5){return -EACCES;}if(rc==-6){return -EWOULDBLOCK;}
 if(rc<0 || (op!=BES_GPIO_IRQ_ACK && rc) || (rc&~BES_GPIO_IRQ_KEYS)){return -EIO;}
 return rc;
}
int bes_gpio_irq_read(struct bes_gpio_irq_io *io)
{
 if(!bes_resource_buffer_valid((uint32_t)(uintptr_t)io,sizeof(*io))){return -EINVAL;}
 *io=(struct bes_gpio_irq_io){.abi=BES_GPIO_IRQ_ABI,.bytes=sizeof(*io)};
 return bes_gpio_irq_call(BES_GPIO_IRQ_READ,(uint32_t)(uintptr_t)io,sizeof(*io));
}
