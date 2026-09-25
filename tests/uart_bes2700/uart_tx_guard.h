/* SPDX-License-Identifier: Apache-2.0 */
#ifndef BTH_VALIDATION_TX_GUARD_H
#define BTH_VALIDATION_TX_GUARD_H
#include <zephyr/irq.h>
#include <zephyr/sys/sys_io.h>
#include <stdbool.h>
#include <stdint.h>
#include <errno.h>

/* Board-local validation helper, not a general pinctrl driver.
 * SDK best1600/hal_iomux_best1600.c: BTH UART0 = P2_2/P2_3, mux 4.
 * SDK reg_gpio_v2.h: GPIO bank 0 has W1S/W1C data/direction aliases.
 * UART must be drained and its interrupts masked for both transitions. */
#define TXG_UART 0x4000b000U
#define TXG_IOMUX 0x4008600cU
#define TXG_GPIO 0x40081000U
#define TXG_PIN (1U << 19)
#define TXG_MUX (15U << 12)
#define TXG_UART_MUX (4U << 12)
struct uart_tx_guard { uint32_t data, direction; bool active; };

static int uart_tx_guard_restore(struct uart_tx_guard *g)
{
	if (!g->active) { return 0; }
	unsigned key = irq_lock();
	/* Restore the idle UART before changing the saved GPIO latch/direction. */
	sys_write32((sys_read32(TXG_IOMUX) & ~TXG_MUX) | TXG_UART_MUX, TXG_IOMUX);
	bool mux_ok = (sys_read32(TXG_IOMUX) & TXG_MUX) == TXG_UART_MUX;
	if (mux_ok) {
		sys_write32(TXG_PIN, TXG_GPIO + (g->direction ? 0x04 : 0x10));
		sys_write32(TXG_PIN, TXG_GPIO + (g->data ? 0x00 : 0x0c));
		g->active = false;
	}
	bool ok = mux_ok && (sys_read32(TXG_GPIO) & TXG_PIN) == g->data &&
		(sys_read32(TXG_GPIO + 4) & TXG_PIN) == g->direction;
	irq_unlock(key);
	return ok ? 0 : -EIO;
}

static int uart_tx_guard_enter(struct uart_tx_guard *g)
{
	unsigned key = irq_lock();
	if (g->active || sys_read32(TXG_UART + 0x38) ||
	    (sys_read32(TXG_UART + 0x18) & (1U << 3))) {
		irq_unlock(key); return -EBUSY;
	}
	if ((sys_read32(TXG_IOMUX) & TXG_MUX) != TXG_UART_MUX ||
	    (sys_read32(TXG_GPIO + 8) & TXG_PIN) ||
	    (sys_read32(TXG_GPIO + 0x30) & TXG_PIN)) {
		irq_unlock(key); return -ENOTSUP;
	}
	g->data = sys_read32(TXG_GPIO) & TXG_PIN;
	g->direction = sys_read32(TXG_GPIO + 4) & TXG_PIN;
	g->active = true;
	/* Set idle high BEFORE connecting GPIO to the pad; leave RX untouched. */
	sys_write32(TXG_PIN, TXG_GPIO);
	sys_write32(TXG_PIN, TXG_GPIO + 4);
	bool high = (sys_read32(TXG_GPIO) & TXG_PIN) &&
		(sys_read32(TXG_GPIO + 4) & TXG_PIN);
	if (high) { sys_write32(sys_read32(TXG_IOMUX) & ~TXG_MUX, TXG_IOMUX); }
	bool ok = high && !(sys_read32(TXG_IOMUX) & TXG_MUX);
	irq_unlock(key);
	if (!ok) { (void)uart_tx_guard_restore(g); }
	return ok ? 0 : -EIO;
}
#endif
