/* SPDX-License-Identifier: Apache-2.0 */
#include "arch.h"
#include "arbitration.h"
#include <bes2700yp_gpio.h>
#include <bestechnic/bes2700yp/hw.h>
_Static_assert(BES2700YP_GPIO_API==2U,"GPIO requires the IRQ-enabled HAL contract");
uint32_t dual_service_phase(void);
static volatile uint32_t gpio_fault;
int32_t bes_gpio_dispatch(uint32_t op,uint32_t address,uint32_t bytes)
{
 if(__get_IPSR() || (__get_CONTROL()&1U) || __get_PRIMASK()){return -3;}
 if(op<BES_GPIO_READ || op>BES_GPIO_SAMPLE){return -2;}
 if(!bes_resource_buffer_valid(address,bytes)){return -1;}
 struct bes_gpio_io *io=(void *)(uintptr_t)address;
 if(io->abi!=BES_GPIO_ABI || io->resource!=BES_GPIO_ID){return -2;}
 if(io->bytes!=bytes || io->reserved[0] || io->reserved[1] || io->reserved[2] || io->value>1U ||
    ((op==BES_GPIO_READ || op==BES_GPIO_SAMPLE) && (io->pin || io->value)) ||
    (op==BES_GPIO_INPUT && ((io->pin!=16U && io->pin!=17U) || io->value)) ||
    ((op==BES_GPIO_OUTPUT || op==BES_GPIO_WRITE) && io->pin!=12U)){return -1;}
#if BES_GPIO_MODE != 2
 if(op==BES_GPIO_OUTPUT || op==BES_GPIO_WRITE){return -2;}
#endif
 /* Keep ownership across preemption, not PRIMASK across slow AON MMIO.
  * Every supported runtime writer/lifecycle entry honors this guard; ISR
  * calls are rejected before acquisition. MEMSC remains nonblocking. */
 int rc=bes_arbitration_enter(64U+op,dual_service_phase());
 if(rc){return rc==BES_ARBITRATION_BUSY?-4:-3;}
 uint32_t phase=dual_service_phase();
 int write=op>=BES_GPIO_INPUT && op<=BES_GPIO_WRITE;
 if(write && gpio_fault){rc=-6;}
 else if(write && phase!=3U && phase!=4U){rc=-5;}
 else {
  struct bes2700yp_gpio_state s;
  int hw;
  if(op==BES_GPIO_SAMPLE){
   /* Explicit volatile stores keep the audited bridge free of libc calls. */
   volatile struct bes2700yp_gpio_state *clear=&s;
#define ZERO(n) clear->n=0;
   BES_GPIO_FIELDS(ZERO)
#undef ZERO
   s.pins=BES_GPIO_PINS;
   hw=bes2700yp_gpio_sample(&s.inputs);
  }else{hw=bes2700yp_gpio_access(op,io->pin,io->value,&s);}
  if(hw==-4){gpio_fault=1;rc=-6;}
  else if(hw==-3){rc=-5;}else if(hw==-2){rc=-4;}else if(hw){rc=-1;}
  if(!rc){
   volatile struct bes_gpio_snapshot *out=&io->snapshot;
   out->abi=BES_GPIO_ABI;out->bytes=64;out->phase=phase;out->fault=gpio_fault;
#define COPY(n) out->n=s.n;
   BES_GPIO_FIELDS(COPY)
#undef COPY
  }
 }
 /* Only RAM guard bookkeeping is interrupt-excluded. */
 uint32_t mask=__get_PRIMASK();__disable_irq();
 bes_arbitration_leave(rc);__set_PRIMASK(mask);return rc;
}
#ifndef BES_RESOURCE_HOST_TEST
const struct bes_resource_descriptor bes_gpio_service={
 .magic=BES_RESOURCE_MAGIC,.abi=BES_GPIO_ABI,.bytes=32,
 .capabilities=BES_GPIO_CAP|BES_GPIO_SAMPLE_CAP|(BES_GPIO_MODE==2?BES_GPIO_OUTPUT_CAP:0),
 .dispatch=(uint32_t)(uintptr_t)bes_gpio_dispatch,.request_bytes=96,.snapshot_bytes=64,
};
#endif
