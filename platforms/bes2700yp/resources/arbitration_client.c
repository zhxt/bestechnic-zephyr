/* SPDX-License-Identifier: Apache-2.0 */
#include <errno.h>
#include <bes2700_dual_boot.h>
#include <bes2700yp_arbitration.h>

static const struct bes_resource_descriptor *service;

int bes_arbitration_connect(void)
{
	service = 0;
	const volatile struct dual_service *root = (void *)DUAL_SERVICE_ADDR;
	if (dual_service_validate(root)) { return -ENODEV; }
	int32_t (*discover)(uint32_t, uint32_t) = (void *)(uintptr_t)root->dispatch;
	int32_t address = discover(BES_RESOURCE_DISCOVER, BES_ARBITRATION_ABI);
	if (address <= 0 || !bes_resource_descriptor_address_valid((uint32_t)address)) {
		return -ENOTSUP;
	}
	const struct bes_resource_descriptor *d = (void *)(uintptr_t)(uint32_t)address;
	if (!bes_arbitration_descriptor_valid(d)) { return -ENOTSUP; }
	service = d;
	return 0;
}

int bes_arbitration_read(struct bes_arbitration_io *io)
{
	if (!service) { return -ENODEV; }
	if (!bes_resource_buffer_valid((uint32_t)(uintptr_t)io, sizeof(*io))) { return -EINVAL; }
	*io = (struct bes_arbitration_io){ .abi = BES_ARBITRATION_ABI, .bytes = sizeof(*io),
		.resource = BES_ARBITRATION_ID };
	int32_t (*dispatch)(uint32_t, uint32_t, uint32_t) = (void *)(uintptr_t)service->dispatch;
	int32_t rc = dispatch(BES_RESOURCE_SNAPSHOT, (uint32_t)(uintptr_t)io, sizeof(*io));
	if (rc == BES_RESOURCE_INVALID) { return -EINVAL; }
	if (rc == BES_RESOURCE_UNSUPPORTED) { return -ENOTSUP; }
	if (rc == BES_RESOURCE_CONTEXT) { return -EPERM; }
	if (rc || io->snapshot.abi != BES_ARBITRATION_ABI ||
	    io->snapshot.bytes != sizeof(io->snapshot) || io->snapshot.phase > 5U ||
	    io->snapshot.reserved) { return -EIO; }
	return 0;
}
