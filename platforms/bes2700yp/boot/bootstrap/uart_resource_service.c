/* SPDX-License-Identifier: Apache-2.0 */
#include "arch.h"
#include <bes2700yp_uart_resources.h>
#include <bestechnic/bes2700yp/hw.h>
uint32_t dual_service_phase(void);

int32_t bes_uart_resource_dispatch(uint32_t op, uint32_t address, uint32_t bytes)
{
	if (__get_IPSR() || (__get_CONTROL() & 1U)) { return BES_RESOURCE_CONTEXT; }
	if (op != BES_RESOURCE_SNAPSHOT) { return BES_RESOURCE_UNSUPPORTED; }
	if (!bes_resource_buffer_valid(address, bytes)) { return BES_RESOURCE_INVALID; }
	struct bes_uart_resource_io *io = (void *)(uintptr_t)address;
	if (io->abi != BES_UART_RESOURCE_ABI) { return BES_RESOURCE_UNSUPPORTED; }
	if (io->bytes != bytes || io->flags || io->reserved[0] || io->reserved[1] ||
	    io->reserved[2] || io->reserved[3]) { return BES_RESOURCE_INVALID; }
	if (io->resource != BES_UART_RESOURCE_ID) { return BES_RESOURCE_UNSUPPORTED; }
	uint32_t mask = __get_PRIMASK();
	__disable_irq();
	struct bes2700yp_uart0_state state;
	int rc = bes2700yp_uart0_read(&state);
	if (!rc) {
		volatile struct bes_uart_resource_snapshot *out = &io->snapshot;
		out->abi = BES_UART_RESOURCE_ABI;
		out->bytes = sizeof(*out);
		out->phase = dual_service_phase();
#define COPY(n) out->n = state.n;
		BES_UART_RESOURCE_FIELDS(COPY)
#undef COPY
	}
	__set_PRIMASK(mask);
	return rc ? BES_UART_RESOURCE_BUSY : BES_RESOURCE_OK;
}
#ifndef BES_RESOURCE_HOST_TEST
const struct bes_resource_descriptor bes_uart_resource_service = {
	.magic = BES_RESOURCE_MAGIC, .abi = BES_UART_RESOURCE_ABI,
	.bytes = sizeof(struct bes_resource_descriptor), .capabilities = BES_UART_RESOURCE_CAP,
	.dispatch = (uint32_t)(uintptr_t)bes_uart_resource_dispatch,
	.request_bytes = sizeof(struct bes_uart_resource_io),
	.snapshot_bytes = sizeof(struct bes_uart_resource_snapshot),
};
#endif
