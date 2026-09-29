/* SPDX-License-Identifier: Apache-2.0 */
#include <bes2700yp_arbitration.h>
#include <bes2700_dual_boot.h>

int bes_arbitration_descriptor_valid(const struct bes_resource_descriptor *d)
{
	uint32_t code = d->dispatch & ~1U;
	return d->magic == BES_RESOURCE_MAGIC && d->abi == BES_ARBITRATION_ABI &&
		d->bytes == sizeof(*d) && d->capabilities == BES_ARBITRATION_CAP &&
		d->request_bytes == sizeof(struct bes_arbitration_io) &&
		d->snapshot_bytes == sizeof(struct bes_arbitration_snapshot) && !d->reserved &&
		(d->dispatch & 1U) &&
		((code >= DUAL_SERVICE_FLASHX_START && code < DUAL_SERVICE_FLASHX_END) ||
		 (code >= DUAL_SERVICE_SRAM_START && code < DUAL_SERVICE_SRAM_END));
}
