/* SPDX-License-Identifier: Apache-2.0 */
#include <bes2700yp_resources.h>
#include <bes2700_dual_boot.h>

static int span(uint32_t address, uint32_t bytes, uint32_t start, uint32_t end)
{
	return !(address & 3U) && bytes && address >= start && address < end && bytes <= end - address;
}

int bes_resource_buffer_valid(uint32_t address, uint32_t bytes)
{
	return bytes == sizeof(struct bes_resource_io) &&
		span(address, bytes, BES_RESOURCE_RAM_START, BES_RESOURCE_RAM_END);
}

int bes_resource_descriptor_address_valid(uint32_t address)
{
	return span(address, sizeof(struct bes_resource_descriptor), 0x34000000U, 0x34800000U) ||
		span(address, sizeof(struct bes_resource_descriptor), 0x14000000U, 0x14800000U);
}

int bes_resource_descriptor_valid(const struct bes_resource_descriptor *d)
{
	uint32_t code = d->dispatch & ~1U;
	return d->magic == BES_RESOURCE_MAGIC && d->abi == BES_RESOURCE_ABI &&
		d->bytes == sizeof(*d) && d->capabilities == BES_RESOURCE_CAP_SYSTEM &&
		d->request_bytes == sizeof(struct bes_resource_io) &&
		d->snapshot_bytes == sizeof(struct bes_resource_snapshot) && !d->reserved &&
		(d->dispatch & 1U) &&
		((code >= DUAL_SERVICE_FLASHX_START && code < DUAL_SERVICE_FLASHX_END) ||
		 (code >= DUAL_SERVICE_SRAM_START && code < DUAL_SERVICE_SRAM_END));
}
