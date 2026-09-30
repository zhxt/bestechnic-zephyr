/* SPDX-License-Identifier: Apache-2.0 */
#include <bes2700yp_gpio_irq.h>
#include <bes2700_dual_boot.h>
int bes_gpio_irq_descriptor_valid(const struct bes_resource_descriptor *d)
{
 uint32_t code=d->dispatch&~1U;
 return d->magic==BES_RESOURCE_MAGIC && d->abi==BES_GPIO_IRQ_ABI && d->bytes==32 &&
  d->capabilities==BES_GPIO_IRQ_CAP && d->request_bytes==96 && d->snapshot_bytes==64 &&
  !d->reserved && (d->dispatch&1U) &&
  ((code>=DUAL_SERVICE_FLASHX_START && code<DUAL_SERVICE_FLASHX_END) ||
   (code>=DUAL_SERVICE_SRAM_START && code<DUAL_SERVICE_SRAM_END));
}
