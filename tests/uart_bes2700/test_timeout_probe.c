/* SPDX-License-Identifier: Apache-2.0 */
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <string.h>
#include <errno.h>
struct device {
	int dummy;
};
struct bes2700_uart_stats {
	uint32_t irq, tx_irq, rx_irq, timeout_irq, error_irq;
};
struct bes2700_uart_error {
	uint32_t source;
};
struct bes2700_uart_rx_trace {
	uint32_t reads, first_dr[8];
};
struct bes2700_uart_state {
	uint32_t fr, rsr, lcr, ifls, cr, ris, imsc, ovsampst, discarded;
};
struct uart_tx_guard {
	bool active;
};
static struct device dev;
static const struct device *const uart = &dev;
static int uart_done;
static uint32_t ticks, reg_cr;
static int mode, restored_count, exit_count, waits, written;
static bool isolated, looped;
static struct bes2700_uart_state state;
#define BTH_TIMER_HZ  6000000U
#define BTH_UART_BASE 0U
#define BTH_REG(x)    reg_cr
#define K_MSEC(x)     (x)
enum {
	GOOD,
	WAKE,
	EARLY,
	LATE,
	SHORT,
	NO_RX,
	UART_ERROR,
	IRQ,
	CLEAN_FAIL,
	PIN_FAIL,
	ENTRY_FAIL,
	DIRTY_START,
	LONG_TOTAL,
	DRAIN_FAIL
};
static uint32_t bth_ticks(void)
{
	return ticks;
}
static int drain(void)
{
	return mode == DRAIN_FAIL ? -ETIMEDOUT : 0;
}
static int uart_tx_guard_enter(struct uart_tx_guard *g)
{
	if (mode == ENTRY_FAIL) {
		return -EIO;
	}
	g->active = isolated = true;
	return 0;
}
static int uart_tx_guard_restore(struct uart_tx_guard *g)
{
	if (g->active) {
		restored_count++;
		g->active = isolated = false;
	}
	return mode == PIN_FAIL ? -EIO : 0;
}
static int bes2700_uart_loopback(const struct device *d, bool on)
{
	assert(d == uart && isolated);
	looped = on;
	state = (struct bes2700_uart_state){.fr = 0x90, .cr = on ? 0x381 : 0x301, .lcr = 0x70};
	ticks += 900;
	if (on && mode == DIRTY_START) {
		state.imsc = 0x10;
	}
	if (!on) {
		exit_count++;
		if (mode == CLEAN_FAIL) {
			state.fr = 0x80;
			return -EIO;
		}
	}
	return 0;
}
static void bes2700_uart_get_state(const struct device *d, struct bes2700_uart_state *out)
{
	assert(d == uart);
	*out = state;
}
static void bes2700_uart_get_stats(const struct device *d, struct bes2700_uart_stats *out)
{
	assert(d == uart);
	*out = (struct bes2700_uart_stats){.irq = mode == IRQ && waits ? 1 : 0};
}
static void bes2700_uart_get_rx_trace(const struct device *d, struct bes2700_uart_rx_trace *out)
{
	assert(d == uart);
	memset(out, 0, sizeof(*out));
}
static void bes2700_uart_get_error(const struct device *d, struct bes2700_uart_error *out)
{
	assert(d == uart);
	out->source = mode == UART_ERROR ? 1 : 0;
}
static int uart_err_check(const struct device *d)
{
	assert(d == uart);
	return mode == UART_ERROR;
}
static void k_sem_reset(int *sem)
{
	assert(sem == &uart_done);
	*sem = 0;
}
static int uart_fifo_fill(const struct device *d, const uint8_t *data, int len)
{
	assert(d == uart && isolated && looped && state.imsc == 0 && len == 8 && data[0] == 0x5a);
	written = mode == SHORT ? 7 : 8;
	state.fr = 8;
	return written;
}
static int k_sem_take(int *sem, int ms)
{
	assert(sem == &uart_done && *sem == 0 && ms == 200 && written == 8 && isolated && looped);
	waits++;
	ticks += mode == EARLY ? 600000 : mode == LATE ? 1800000 : 1200000;
	state.fr = mode == NO_RX ? 0x90 : 0x80;
	state.ris = mode == NO_RX ? 0 : 0x50;
	if (mode == UART_ERROR) {
		state.rsr = 8;
		state.ris |= 0x400;
	}
	return mode == WAKE ? 0 : -EAGAIN;
}
static void uart_irq_tx_disable(const struct device *d)
{
	assert(d == uart);
	if (mode == LONG_TOTAL) {
		ticks += 3000000;
	}
}
static void uart_irq_rx_disable(const struct device *d)
{
	assert(d == uart);
}
static void uart_irq_err_disable(const struct device *d)
{
	assert(d == uart);
}
#include "../../samples/bth_kernel_validation/src/uart_timeout_probe.h"
int main(void)
{
	const int expected[] = {0, 52, 52, 52, 51, 53, 53, 55, 54, 54, 50, 50, 52, 50};
	for (mode = GOOD; mode <= DRAIN_FAIL; mode++) {
		ticks = reg_cr = 0;
		restored_count = exit_count = waits = written = 0;
		isolated = looped = false;
		state = (struct bes2700_uart_state){0};
		int rc = timeout_probe(1);
		assert(rc == expected[mode]);
		assert(!isolated && !looped);
		assert(restored_count == (mode != ENTRY_FAIL && mode != DRAIN_FAIL));
		assert(exit_count == restored_count);
		if (!rc) {
			assert(last_probe.tx == 8 && last_probe.wait_rc == -EAGAIN &&
			       last_probe.restored == 1);
		}
	}
	mode = GOOD;
	for (unsigned n = 1; n <= 120; n++) {
		assert(timeout_probe(n) == 0 && last_probe.round == n);
		assert(!isolated && !looped);
	}
	return 0;
}
