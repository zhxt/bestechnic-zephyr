/* SPDX-License-Identifier: Apache-2.0 */
#include "arch.h"
#include <bes2700yp_gpio_irq.h>
#include <bestechnic/bes2700yp/hw.h>
_Static_assert(BES2700YP_GPIO_IRQ_API==1 && BES_GPIO_IRQ_NUMBER==BES2700YP_GPIO_IRQ_NUMBER,
               "GPIO IRQ HAL contract");
uint32_t dual_service_phase(void);
static volatile uint32_t irq_busy;
int32_t bes_gpio_irq_dispatch(uint32_t op,uint32_t arg,uint32_t value)
{
 uint32_t isr=__get_IPSR();
 if((__get_CONTROL()&1U) || __get_PRIMASK() ||
    (isr && isr!=BES_GPIO_IRQ_NUMBER+16U)){return -6;}
 if(!isr && (__get_BASEPRI() || (NVIC->ISER[1]&(1U<<12)))){return -6;}
 if(op<BES_GPIO_IRQ_READ || op>BES_GPIO_IRQ_ACK){return -1;}
 if(isr && op!=BES_GPIO_IRQ_ACK && !(op==BES_GPIO_IRQ_CONFIG && !value)){return -6;}
 if(op==BES_GPIO_IRQ_ACK && (!isr || arg || value)){return -1;}
 if(op==BES_GPIO_IRQ_CLAIM && (arg || value)){return -1;}
 if(op==BES_GPIO_IRQ_CONFIG && ((arg!=16U && arg!=17U) || value>2U)){return -1;}
 if((op==BES_GPIO_IRQ_CLAIM || (op==BES_GPIO_IRQ_CONFIG && value)) &&
    dual_service_phase()!=3U && dual_service_phase()!=4U){return -5;}
 if(op==BES_GPIO_IRQ_READ){
  if(!bes_resource_buffer_valid(arg,value)){return -1;}
  const struct bes_gpio_irq_io *io=(void *)(uintptr_t)arg;
  if(io->abi!=BES_GPIO_IRQ_ABI || io->bytes!=96 || io->reserved[0] || io->reserved[1] ||
     io->reserved[2] || io->reserved[3] || io->reserved[4] || io->reserved[5]){return -1;}
 }
 /* Protect only RAM ownership. The driver excludes IRQ 44 during hardware
  * configuration; other IRQs stay enabled, and nested service use fails. */
 uint32_t mask=__get_PRIMASK();__disable_irq();
 if(irq_busy){__set_PRIMASK(mask);return -6;}
 irq_busy=1;__set_PRIMASK(mask);
 int32_t rc;
 if(op==BES_GPIO_IRQ_ACK){rc=bes2700yp_gpio_irq_ack();}
 else if(op==BES_GPIO_IRQ_CLAIM){rc=bes2700yp_gpio_irq_claim();}
 else if(op==BES_GPIO_IRQ_CONFIG){rc=bes2700yp_gpio_irq_config(arg,value);}
 else {
  struct bes2700yp_gpio_irq_state state;
  rc=bes2700yp_gpio_irq_read(&state);
  if(!rc){
   volatile struct bes_gpio_irq_io *io=(void *)(uintptr_t)arg;
#define COPY(n) io->state.n=state.n;
   BES_GPIO_IRQ_FIELDS(COPY)
#undef COPY
  }
 }
 mask=__get_PRIMASK();__disable_irq();irq_busy=0;__set_PRIMASK(mask);
 return rc;
}
#ifndef BES_RESOURCE_HOST_TEST
const struct bes_resource_descriptor bes_gpio_irq_service={
 .magic=BES_RESOURCE_MAGIC,.abi=BES_GPIO_IRQ_ABI,.bytes=32,.capabilities=BES_GPIO_IRQ_CAP,
 .dispatch=(uint32_t)(uintptr_t)bes_gpio_irq_dispatch,.request_bytes=96,.snapshot_bytes=64,
};
#endif
