/* SPDX-License-Identifier: Apache-2.0 */
#ifndef BES2700_UART_H
#define BES2700_UART_H
#include <zephyr/device.h>
#include <stdbool.h>
#include <stdint.h>
#define BES2700_UART_TX_BURST 8
struct bes2700_uart_stats {
	uint32_t irq, tx_irq, rx_irq, timeout_irq, error_irq;
};
/* First error since entering loopback. source: 0 none, 1 RSR, 2 DR, 3 MIS.
 * DR is only valid for source=2; diagnostics never perform an extra FIFO read. */
struct bes2700_uart_error {
	uint32_t source, rsr, dr, mis, entry_mis, fr, cr, imsc;
	uint32_t rx_index, lcr, ifls, ris;
};
/* Non-destructive register snapshot; never reads DR. */
struct bes2700_uart_state {
	uint32_t fr, rsr, lcr, ifls, cr, ris, imsc, ovsampst, discarded;
};
struct bes2700_uart_rx_trace {
	uint32_t reads, first_dr[8];
};
/* Diagnostics for the exclusively owned validation UART. Disable all UART
 * sources before changing loopback; call only from its owning thread.
 * Returns -EBUSY if not drained/masked. Quiesces RX before changing FIFOs.
 * Internal loopback does not test the board's external TX/RX wiring. */
int bes2700_uart_loopback(const struct device *dev, bool enabled);
void bes2700_uart_get_stats(const struct device *dev, struct bes2700_uart_stats *stats);
void bes2700_uart_get_error(const struct device *dev, struct bes2700_uart_error *error);
void bes2700_uart_get_state(const struct device *dev, struct bes2700_uart_state *state);
void bes2700_uart_get_rx_trace(const struct device *dev, struct bes2700_uart_rx_trace *trace);
#endif
