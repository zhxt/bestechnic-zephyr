/* SPDX-License-Identifier: Apache-2.0 */
#include "arch.h"
#include "arbitration.h"
#include <bes2700yp_resources.h>
#include <bestechnic/bes2700yp/hw.h>

uint32_t dual_service_phase(void);

int32_t bes_resource_dispatch(uint32_t op, uint32_t address, uint32_t bytes)
{
	if (__get_IPSR() || (__get_CONTROL() & 1U)) { return BES_RESOURCE_CONTEXT; }
	if (op != BES_RESOURCE_SNAPSHOT) { return BES_RESOURCE_UNSUPPORTED; }
	if (!bes_resource_buffer_valid(address, bytes)) { return BES_RESOURCE_INVALID; }
	struct bes_resource_io *io = (void *)(uintptr_t)address;
	if (io->abi != BES_RESOURCE_ABI) { return BES_RESOURCE_UNSUPPORTED; }
	if (io->bytes != bytes || io->flags || io->reserved[0] || io->reserved[1] ||
	    io->reserved[2] || io->reserved[3]) { return BES_RESOURCE_INVALID; }
	if (io->resource != BES_RESOURCE_SYSTEM) { return BES_RESOURCE_UNSUPPORTED; }
	/* Volatile field stores avoid a compiler-generated call to a runtime
	 * memset/memcpy implementation across this freestanding ABI. */
	volatile struct bes_resource_snapshot *out = &io->snapshot;
	/* No waiting or output in this bounded read section. Exclude BTH preemption
	 * during a lifecycle transition, preserving the caller's interrupt mask. */
	uint32_t mask = __get_PRIMASK();
	__disable_irq();
	if (bes_arbitration_busy()) {
		__set_PRIMASK(mask);
		return BES_RESOURCE_BUSY;
	}
	out->abi = BES_RESOURCE_ABI;
	out->bytes = sizeof(*out);
	out->valid = BES_RESOURCE_VALID_PHASE;
	uint32_t phase = dual_service_phase();
	out->phase = phase;
	out->clocks_24m = 0;
	out->core_vtor = 0;
	out->reset_set = 0;
	out->reset_clr = 0;
	out->ram_sel0 = 0;
	out->ram_sel1 = 0;
	out->oclk = 0;
	out->oreset = 0;
	out->sysclk = 0;
	out->reserved[0] = 0;
	out->reserved[1] = 0;
	out->reserved[2] = 0;
	if (phase >= 2U && phase <= 5U) {
		struct bes2700yp_hw_snapshot hw;
		bes2700yp_snapshot(&hw);
		out->clocks_24m = bes2700yp_clocks_are_24m() == 0;
		out->core_vtor = hw.core_vtor;
		out->reset_set = hw.reset_set;
		out->reset_clr = hw.reset_clr;
		out->ram_sel0 = hw.ram_sel0;
		out->ram_sel1 = hw.ram_sel1;
		out->oclk = hw.oclk;
		out->oreset = hw.oreset;
		out->sysclk = hw.sysclk;
		out->valid |= BES_RESOURCE_VALID_HW | BES_RESOURCE_VALID_CLOCK;
	}
	__set_PRIMASK(mask);
	return BES_RESOURCE_OK;
}

#ifndef BES_RESOURCE_HOST_TEST
const struct bes_resource_descriptor bes_resource_service = {
	.magic = BES_RESOURCE_MAGIC, .abi = BES_RESOURCE_ABI,
	.bytes = sizeof(struct bes_resource_descriptor), .capabilities = BES_RESOURCE_CAP_SYSTEM,
	.dispatch = (uint32_t)(uintptr_t)bes_resource_dispatch,
	.request_bytes = sizeof(struct bes_resource_io),
	.snapshot_bytes = sizeof(struct bes_resource_snapshot),
};
#endif
