/* SPDX-License-Identifier: Apache-2.0 */
#include <bes2700yp_gpio.h>
#include <bes2700_dual_boot.h>
int bes_gpio_descriptor_valid(const struct bes_resource_descriptor *d)
{
 uint32_t code=d->dispatch&~1U;
 return d->magic==BES_RESOURCE_MAGIC && d->abi==BES_GPIO_ABI &&
  d->bytes==sizeof(*d) && (d->capabilities==(BES_GPIO_CAP|BES_GPIO_SAMPLE_CAP) ||
   d->capabilities==(BES_GPIO_CAP|BES_GPIO_SAMPLE_CAP|BES_GPIO_OUTPUT_CAP)) &&
  d->request_bytes==sizeof(struct bes_gpio_io) && d->snapshot_bytes==64 &&
  !d->reserved && (d->dispatch&1U) &&
  ((code>=DUAL_SERVICE_FLASHX_START && code<DUAL_SERVICE_FLASHX_END) ||
   (code>=DUAL_SERVICE_SRAM_START && code<DUAL_SERVICE_SRAM_END));
}
