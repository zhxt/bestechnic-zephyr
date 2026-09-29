/* SPDX-License-Identifier: Apache-2.0 */
#ifndef BES2700YP_UART_RESOURCES_H
#define BES2700YP_UART_RESOURCES_H
#include <bes2700yp_resources.h>
/* Operation 9, argument 2 discovers this independent UART descriptor.
 * Operation 9, argument 1 and the system snapshot remain unchanged. */
#define BES_UART_RESOURCE_ABI 2U
#define BES_UART_RESOURCE_CAP 2U
#define BES_UART_RESOURCE_ID 2U
#define BES_UART_RESOURCE_BUSY (-4)
#define BES_UART_RESOURCE_FIELDS(X) \
 X(valid) \
 X(source) \
 X(source_hz) \
 X(divider) \
 X(configured_hz) \
 X(clocks) \
 X(reset_released) \
 X(rx_pin) \
 X(tx_pin) \
 X(rx_mux) \
 X(tx_mux) \
 X(pull_up) \
 X(pull_down)
/* valid bits: 0 configured clock, 1 gate/reset, 2 digital AON pin route.
 * source: crystal=1, crystal x2=2, PLL=3 (frequency unavailable).
 * clocks/reset_released: bit0 bus, bit1 functional block.
 * pins: bank*8+index; pull masks: bit0 RX, bit1 TX.
 * Privileged BTH early/thread only, sole configuration owner. Snapshot is
 * sampled twice under a restored local IRQ mask, not globally atomic.
 * Failure invalidates all output; -EBUSY means samples changed.
 * Gate state is separate from configured frequency; no voltage/calibration. */
struct bes_uart_resource_snapshot {
	uint32_t abi, bytes, phase;
#define MEMBER(n) uint32_t n;
	BES_UART_RESOURCE_FIELDS(MEMBER)
#undef MEMBER
};
struct bes_uart_resource_io {
	uint32_t abi, bytes, resource, flags, reserved[4];
	struct bes_uart_resource_snapshot snapshot;
};
_Static_assert(sizeof(struct bes_uart_resource_snapshot) == 64, "UART snapshot ABI");
_Static_assert(sizeof(struct bes_uart_resource_io) == 96, "UART request ABI");
int bes_uart_resource_descriptor_valid(const struct bes_resource_descriptor *d);
int bes_uart_resource_connect(void);
int bes_uart_resource_read(struct bes_uart_resource_io *io);
#endif
