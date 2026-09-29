/* SPDX-License-Identifier: Apache-2.0 */
#include <errno.h>
#include <bes2700_dual_boot.h>
#include <bes2700yp_uart_resources.h>

static const struct bes_resource_descriptor *service;

int bes_uart_resource_connect(void)
{
	service = 0;
	const volatile struct dual_service *root = (void *)DUAL_SERVICE_ADDR;
	if (dual_service_validate(root)) { return -ENODEV; }
	int32_t (*discover)(uint32_t, uint32_t) = (void *)(uintptr_t)root->dispatch;
	int32_t address = discover(BES_RESOURCE_DISCOVER, BES_UART_RESOURCE_ABI);
	if (address <= 0 || !bes_resource_descriptor_address_valid((uint32_t)address)) {
		return -ENOTSUP;
	}
	const struct bes_resource_descriptor *d = (void *)(uintptr_t)(uint32_t)address;
	if (!bes_uart_resource_descriptor_valid(d)) { return -ENOTSUP; }
	service = d;
	return 0;
}

int bes_uart_resource_read(struct bes_uart_resource_io *io)
{
	if (!service) { return -ENODEV; }
	if (!bes_resource_buffer_valid((uint32_t)(uintptr_t)io, sizeof(*io))) { return -EINVAL; }
	*io = (struct bes_uart_resource_io){ .abi = BES_UART_RESOURCE_ABI, .bytes = sizeof(*io),
		.resource = BES_UART_RESOURCE_ID };
	int32_t (*dispatch)(uint32_t, uint32_t, uint32_t) = (void *)(uintptr_t)service->dispatch;
	int32_t rc = dispatch(BES_RESOURCE_SNAPSHOT, (uint32_t)(uintptr_t)io, sizeof(*io));
	if (rc == BES_RESOURCE_INVALID) { return -EINVAL; }
	if (rc == BES_RESOURCE_UNSUPPORTED) { return -ENOTSUP; }
	if (rc == BES_RESOURCE_CONTEXT) { return -EPERM; }
	const struct bes_uart_resource_snapshot *s = &io->snapshot;
	if (rc == BES_UART_RESOURCE_BUSY) { return -EBUSY; }
	if (rc || s->abi != BES_UART_RESOURCE_ABI || s->bytes != sizeof(*s) || s->phase > 5U ||
	    (s->valid & ~7U) || !(s->valid & 2U) || s->source < 1U || s->source > 3U ||
	    s->clocks > 3U || s->reset_released > 3U || s->rx_pin != 18U || s->tx_pin != 19U ||
	    s->rx_mux > 15U || s->tx_mux > 15U || s->pull_up > 3U || s->pull_down > 3U ||
	    (s->source == 3U ? (s->divider < 2U || s->divider > 5U) : s->divider != 1U) ||
	    ((s->valid & 1U) ? (s->source == 3U || !s->source_hz || s->configured_hz != s->source_hz) :
	                        (s->source_hz || s->configured_hz))) { return -EIO; }
	return 0;
}
