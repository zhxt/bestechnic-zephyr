/* SPDX-License-Identifier: Apache-2.0 */
#include "shim.h"
#include "../../bsp/drivers/serial/uart_bes2700.c"
#include "uart_tx_guard.h"

/* Deliberately small FIFO models threshold transitions, not mere writes to
 * a RAM register. No claim about BES silicon timing is made by this test. */
#define BASE 0x4000b000U
#define DEPTH 16
static uint32_t regs[0x60 / 4], ris, data_error;
static uint8_t tx_fifo[DEPTH], rx_fifo[DEPTH];
static unsigned nt, nr, callbacks, received;
static bool nvic_pending, forced_busy;
static bool inject_error_after_rsr_read;
static bool fail_flush, fail_mux, stuck_rx;
static uint32_t pinmux = 0xabcd4400, gpio_data = 0x12345678, gpio_dir = 0x87654321;
static struct bes_data data;
static void connect_mock(void) { }
static struct bes_config config = {.base=BASE, .clock=24000000, .baud=1152000, .irq=17, .connect=connect_mock};
static const struct device dev = {.config=&config, .data=&data};
static uint32_t sys_read32(uintptr_t address)
{
	if (address == TXG_IOMUX) { return pinmux; }
	if (address == TXG_GPIO) { return gpio_data; }
	if (address == TXG_GPIO + 4) { return gpio_dir; }
	if (address == TXG_GPIO + 8 || address == TXG_GPIO + 0x30) { return 0; }
	unsigned reg = address - BASE;
	assert(reg < sizeof(regs) && reg % 4 == 0);
	if (reg == FR) { return ((nt || forced_busy) ? BUSY : BIT(7)) | (nr ? 0 : RXFE) | (nt == DEPTH ? TXFF : 0); }
	if (reg == MIS) { return (ris | (nr >= 2 ? RX_INT : 0)) & regs[IMSC/4]; }
	if (reg == ECR && inject_error_after_rsr_read) {
		uint32_t prior = regs[ECR/4];
		regs[ECR/4] |= BIT(3); inject_error_after_rsr_read = false;
		return prior;
	}
	if (reg == DR) {
		assert(nr);
		uint8_t value = rx_fifo[0];
		if (!stuck_rx) { memmove(rx_fifo, rx_fifo + 1, --nr); }
		uint32_t result = value | data_error;
		data_error = 0;
		return result;
	}
	return regs[reg/4];
}
static void sys_write32(uint32_t value, uintptr_t address)
{
	if (address == TXG_IOMUX) {
		assert((value & ~TXG_MUX) == (pinmux & ~TXG_MUX));
		if (!(value & TXG_MUX)) { assert((gpio_data & gpio_dir & TXG_PIN) != 0); }
		if (!fail_mux) { pinmux = value; }
		return;
	}
	if (address == TXG_GPIO) { gpio_data |= value; return; }
	if (address == TXG_GPIO + 4) { gpio_dir |= value; return; }
	if (address == TXG_GPIO + 0x0c) { gpio_data &= ~value; return; }
	if (address == TXG_GPIO + 0x10) { gpio_dir &= ~value; return; }
	unsigned reg = address - BASE;
	assert(reg < sizeof(regs) && reg % 4 == 0);
	if (reg == DR) { assert(nt < DEPTH); tx_fifo[nt++] = value; return; }
	if (reg == ICR) { ris &= ~value; return; }
	if (reg == ECR) { assert(value == 0); regs[ECR/4] = 0; return; }
	if (reg == LCR && !(value & BIT(4)) && !fail_flush) { nt = nr = 0; }
	regs[reg/4] = value;
}
static void NVIC_SetPendingIRQ(int irq) { assert(irq == 17); nvic_pending = true; }
static void shift(void)
{
	assert(nt && nr < DEPTH);
	if (regs[CR/4] & BIT(7)) { rx_fifo[nr++] = tx_fifo[0]; }
	memmove(tx_fifo, tx_fifo + 1, --nt);
	if (nt == 2) { ris |= TX_INT; }
}
static void cb(const struct device *device, void *arg)
{
	assert(device == &dev && arg == &callbacks);
	callbacks++;
	uint8_t bytes[32];
	int n = api.fifo_read(device, bytes, sizeof(bytes));
	for (int i = 0; i < n; i++) { assert(bytes[i] == (uint8_t)received++); }
	if (api.irq_tx_ready(device)) {
		static uint8_t sent;
		for (unsigned i = 0; i < sizeof(bytes); i++) { bytes[i] = sent + i; }
		int count = api.fifo_fill(device, bytes, sizeof(bytes));
		sent += count;
		if (sent >= 128) { api.irq_tx_disable(device); }
	}
}
static void tiny_cb(const struct device *device, void *arg)
{
	unsigned *left = arg;
	uint8_t byte = 0x55;
	if (api.irq_tx_ready(device)) {
		assert(*left && api.fifo_fill(device, &byte, 1) == 1);
		if (!--*left) { api.irq_tx_disable(device); }
	}
}
int main(void)
{
	assert(init(&dev) == 0);
	assert(regs[IBRD/4] == 1 && regs[FBRD/4] == 19 && regs[RXEXT/4] == 3);
	assert(regs[OVSAMP/4] == 15 && regs[OVSAMPST/4] == 8);
	assert(regs[DMACR/4] == 0 && regs[IMSC/4] == 0);
	/* Real board helper: idle high first, only P2_3 changes, exact restore,
	 * and failed mux writes/unknown routing do not start a transfer. */
	for (unsigned value = 0; value < 4; value++) {
		gpio_data = (gpio_data & ~TXG_PIN) | ((value & 1) ? TXG_PIN : 0);
		gpio_dir = (gpio_dir & ~TXG_PIN) | ((value & 2) ? TXG_PIN : 0);
		uint32_t saved_data = gpio_data, saved_dir = gpio_dir, saved_mux = pinmux;
		struct uart_tx_guard guard = {0};
		assert(uart_tx_guard_enter(&guard) == 0 && guard.active);
		assert(!(pinmux & TXG_MUX) && (gpio_data & gpio_dir & TXG_PIN));
		assert(uart_tx_guard_enter(&guard) == -EBUSY);
		assert(uart_tx_guard_restore(&guard) == 0 && !guard.active);
		assert(pinmux == saved_mux && gpio_data == saved_data && gpio_dir == saved_dir);
		fail_mux = true;
		assert(uart_tx_guard_enter(&guard) == -EIO && !guard.active);
		assert(pinmux == saved_mux && gpio_data == saved_data && gpio_dir == saved_dir);
		fail_mux = false;
		pinmux ^= TXG_UART_MUX;
		assert(uart_tx_guard_enter(&guard) == -ENOTSUP);
		pinmux = saved_mux;
		forced_busy = true;
		assert(uart_tx_guard_enter(&guard) == -EBUSY);
		forced_busy = false;
	}
	unsigned char ch;
	assert(api.poll_in(&dev, &ch) == -1);
	api.poll_out(&dev, 0xa5); assert(nt == 1 && tx_fifo[0] == 0xa5);
	assert(bes2700_uart_loopback(&dev, true) == -EBUSY);
	shift(); assert(api.irq_tx_complete(&dev));
	assert(bes2700_uart_loopback(&dev, true) == 0);
	api.irq_callback_set(&dev, cb, &callbacks);
	api.irq_rx_enable(&dev); api.irq_err_enable(&dev); api.irq_tx_enable(&dev);
	assert(nvic_pending && !sys_read32(BASE + MIS));
	isr(&dev); nvic_pending = false;
	assert(nt == 8 && callbacks == 1 && data.stats.tx_irq == 0 && data.stats.irq == 1);
	assert(bes2700_uart_loopback(&dev, false) == -EBUSY);
	for (unsigned i = 0; i < 256 && (nt || nr); i++) {
		if (nt) { shift(); }
		if (!nt && nr) { ris |= RT_INT; }
		if (sys_read32(BASE + MIS)) { isr(&dev); }
	}
	assert(received >= 128 && data.stats.tx_irq && data.stats.rx_irq && nt == 0 && nr == 0);
	api.irq_rx_disable(&dev); api.irq_err_disable(&dev);
	assert(!api.irq_is_pending(&dev));
	assert(bes2700_uart_loopback(&dev, false) == 0 && !(regs[CR/4] & BIT(7)));
	/* Error translation and clearing, not just counters. */
	regs[ECR/4] = BIT(0) | BIT(3);
	assert(api.err_check(&dev) == (UART_ERROR_FRAMING | UART_ERROR_OVERRUN));
	assert(api.err_check(&dev) == 0);
	struct bes2700_uart_error error;
	bes2700_uart_get_error(&dev, &error);
	assert(error.source == 1 && error.rsr == (BIT(0) | BIT(3)));
	assert(bes2700_uart_loopback(&dev, true) == 0);
	bes2700_uart_get_error(&dev, &error); assert(error.source == 0);
	/* An error on an earlier FIFO byte must survive later good bytes. */
	rx_fifo[0] = 0x11; rx_fifo[1] = 0x22; nr = 2; data_error = BIT(9);
	uint8_t bytes[2]; assert(api.fifo_read(&dev, bytes, 2) == 2);
	assert(bytes[0] == 0x11 && bytes[1] == 0x22);
	assert(api.err_check(&dev) == UART_ERROR_PARITY && api.err_check(&dev) == 0);
	bes2700_uart_get_error(&dev, &error);
	assert(error.source == 2 && error.dr == (BIT(9) | 0x11));
	assert(error.rx_index == 0 && error.lcr == 0x70 && error.ifls == 0);
	struct bes2700_uart_rx_trace trace;
	bes2700_uart_get_rx_trace(&dev, &trace);
	assert(trace.reads == 2 && trace.first_dr[0] == (BIT(9) | 0x11) && trace.first_dr[1] == 0x22);
	struct bes2700_uart_state snapshot;
	unsigned reads_before = data.trace.reads;
	bes2700_uart_get_state(&dev, &snapshot);
	assert(snapshot.lcr == 0x70 && data.trace.reads == reads_before);
	/* A retained holding byte is explicitly drained; a stuck receiver
	 * must fail within the budget without admitting stale RX to the test. */
	fail_flush = true; rx_fifo[0] = 0xee; nr = 1;
	assert(bes2700_uart_loopback(&dev, true) == 0 && nr == 0 && data.discarded == 1);
	stuck_rx = true; nr = 1;
	assert(bes2700_uart_loopback(&dev, true) == -EIO && !(regs[CR/4] & BIT(7)));
	assert(data.discarded == 32);
	fail_flush = stuck_rx = false; nr = 0;
	assert(bes2700_uart_loopback(&dev, true) == 0);
	api.irq_err_enable(&dev); ris = BIT(10); isr(&dev);
	assert(data.stats.error_irq == 1 && !(ris & BIT(10)));
	bes2700_uart_get_error(&dev, &error);
	assert(error.source == 3 && error.entry_mis == BIT(10) && error.mis == BIT(10));
	assert(api.err_check(&dev) == UART_ERROR_OVERRUN);
	api.irq_err_disable(&dev);
	/* Disabling TX before the software kick must prevent a spurious fill. */
	api.irq_tx_enable(&dev); api.irq_tx_disable(&dev); isr(&dev);
	assert(nt == 0 && !api.irq_tx_ready(&dev));
	assert(bes2700_uart_loopback(&dev, false) == 0);
	struct bes2700_uart_stats stats;
	bes2700_uart_get_stats(&dev, &stats); assert(stats.irq == data.stats.irq);
	unsigned left = 3, hardware_before = stats.tx_irq;
	api.irq_callback_set(&dev, tiny_cb, &left); api.irq_tx_enable(&dev);
	for (unsigned i = 0; i < 5 && nvic_pending; i++) {
		nvic_pending = false; isr(&dev);
	}
	assert(left == 0 && nt == 3 && data.stats.tx_irq == hardware_before);
	while (nt) { shift(); }
	api.irq_rx_enable(&dev); api.irq_tx_enable(&dev);
	rx_fifo[0] = 0x42; nr = 1; nvic_pending = false;
	assert(api.fifo_fill(&dev, bytes, 2) == 0 && nr == 1 && nvic_pending);
	assert(api.fifo_read(&dev, bytes, 2) == 1 && bytes[0] == 0x42);
	api.irq_rx_disable(&dev); api.irq_tx_disable(&dev);
	in_isr = true; assert(bes2700_uart_loopback(&dev, true) == -EWOULDBLOCK); in_isr = false;
	/* A zero-status poll must not clear an error arriving after its read. */
	inject_error_after_rsr_read = true;
	assert(api.err_check(&dev) == 0);
	assert(api.err_check(&dev) == UART_ERROR_OVERRUN);
	forced_busy = true; assert(init(&dev) == -ETIMEDOUT); forced_busy = false;
	config.baud = 50000000; assert(init(&dev) == -EINVAL);
	config.baud = 0; assert(init(&dev) == -EINVAL);
	return 0;
}
