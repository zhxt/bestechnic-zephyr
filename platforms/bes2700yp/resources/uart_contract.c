/* SPDX-License-Identifier: Apache-2.0 */
#include <bes2700yp_uart_resources.h>
#include <bes2700_dual_boot.h>

int bes_uart_resource_descriptor_valid(const struct bes_resource_descriptor *d)
{
	uint32_t code = d->dispatch & ~1U;
	return d->magic == BES_RESOURCE_MAGIC && d->abi == BES_UART_RESOURCE_ABI &&
		d->bytes == sizeof(*d) && d->capabilities == BES_UART_RESOURCE_CAP &&
		d->request_bytes == sizeof(struct bes_uart_resource_io) &&
		d->snapshot_bytes == sizeof(struct bes_uart_resource_snapshot) && !d->reserved &&
		(d->dispatch & 1U) &&
		((code >= DUAL_SERVICE_FLASHX_START && code < DUAL_SERVICE_FLASHX_END) ||
		 (code >= DUAL_SERVICE_SRAM_START && code < DUAL_SERVICE_SRAM_END));
}
