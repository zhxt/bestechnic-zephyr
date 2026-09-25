/* SPDX-License-Identifier: Apache-2.0 */
#define DT_DRV_COMPAT bestechnic_bes2700_bth_uart
#include <zephyr/drivers/uart.h>
#include <zephyr/irq.h>
#include <zephyr/kernel.h>
#include <zephyr/sys/sys_io.h>
#include <cmsis_core.h>
#include <bes2700_uart.h>

/* SDK v2.8 platform/hal/reg_uart.h. CR.LBE is the internal loopback bit. */
enum { DR = 0x00, ECR = 0x04, FR = 0x18, IBRD = 0x24, FBRD = 0x28,
	LCR = 0x2c, CR = 0x30, IFLS = 0x34, IMSC = 0x38, RIS = 0x3c, MIS = 0x40,
	ICR = 0x44, DMACR = 0x48, OVSAMP = 0x4c, OVSAMPST = 0x50, RXEXT = 0x54 };
#define BUSY BIT(3)
#define RXFE BIT(4)
#define TXFF BIT(5)
#define RX_INT BIT(4)
#define TX_INT BIT(5)
#define RT_INT BIT(6)
#define ERR_INT (BIT(7) | BIT(8) | BIT(9) | BIT(10))
struct bes_config { uintptr_t base; uint32_t clock, baud; int irq; void (*connect)(void); };
struct bes_data {
	uint32_t rx_errors;
	uint32_t entry_mis;
	struct bes2700_uart_error first_error;
	struct bes2700_uart_rx_trace trace;
	uint32_t discarded;
#ifdef CONFIG_UART_INTERRUPT_DRIVEN
	uart_irq_callback_user_data_t cb;
	void *arg;
	bool kick, active_tx;
#endif
	struct bes2700_uart_stats stats;
};
static uint32_t rd(const struct device *dev, unsigned reg)
{ return sys_read32(((const struct bes_config *)dev->config)->base + reg); }
static void wr(const struct device *dev, unsigned reg, uint32_t value)
{ sys_write32(value, ((const struct bes_config *)dev->config)->base + reg); }
static void save_error(const struct device *dev, uint32_t source, uint32_t rsr, uint32_t dr)
{
	struct bes_data *data = dev->data;
	if (!data->first_error.source) {
		data->first_error = (struct bes2700_uart_error) {
			.source = source, .rsr = rsr, .dr = dr, .mis = rd(dev, MIS),
			.entry_mis = data->entry_mis, .fr = rd(dev, FR),
			.cr = rd(dev, CR), .imsc = rd(dev, IMSC),
			.rx_index = data->trace.reads, .lcr = rd(dev, LCR),
			.ifls = rd(dev, IFLS), .ris = rd(dev, RIS),
		};
	}
}
static uint32_t receive(const struct device *dev)
{
	struct bes_data *data = dev->data;
	uint32_t value = rd(dev, DR);
	if (value & 0xf00) { save_error(dev, 2, rd(dev, ECR), value); }
	if (data->trace.reads < 8) { data->trace.first_dr[data->trace.reads] = value; }
	data->trace.reads++;
	data->rx_errors |= (value >> 8) & 15;
	return value;
}
static void mask(const struct device *dev, uint32_t set, uint32_t clear)
{
	unsigned key = irq_lock();
	wr(dev, IMSC, (rd(dev, IMSC) & ~clear) | set);
	irq_unlock(key);
}
static int poll_in(const struct device *dev, unsigned char *ch)
{
	if (rd(dev, FR) & RXFE) { return -1; }
	*ch = receive(dev);
	return 0;
}
static void poll_out(const struct device *dev, unsigned char ch)
{
	while (rd(dev, FR) & TXFF) { }
	wr(dev, DR, ch);
}
static int err_check(const struct device *dev)
{
	unsigned key = irq_lock();
	struct bes_data *data = dev->data;
	uint32_t rsr = rd(dev, ECR);
	uint32_t error = (rsr & 15) | data->rx_errors;
	if (error) { save_error(dev, 1, rsr, 0); }
	data->rx_errors = 0;
	/* Match SDK hal_uart_clear_status(), and don't clear a newly arriving
	 * error when the RSR read reported no error at all. */
	if (rsr & 15) { wr(dev, ECR, 0); }
	irq_unlock(key);
	return ((error & BIT(0)) ? UART_ERROR_FRAMING : 0) |
	       ((error & BIT(1)) ? UART_ERROR_PARITY : 0) |
	       ((error & BIT(2)) ? UART_BREAK : 0) |
	       ((error & BIT(3)) ? UART_ERROR_OVERRUN : 0);
}
#ifdef CONFIG_UART_INTERRUPT_DRIVEN
static int fifo_fill(const struct device *dev, const uint8_t *buf, int len)
{
	struct bes_data *data = dev->data;
	int n = 0;
	data->active_tx = false;
	uint32_t sources = rd(dev, IMSC);
	bool rx_pending = (sources & RX_INT) && !(rd(dev, FR) & RXFE);
	/* TX drains concurrently. Waiting only for TXFF does not bound how
	 * long we exclude RX servicing. Return after at most half the SDK's
	 * 16-byte FIFO budget, even when TXFF never asserts. */
	if (!rx_pending) {
		while (n < len && n < BES2700_UART_TX_BURST && !(rd(dev, FR) & TXFF)) {
			wr(dev, DR, buf[n++]);
		}
	}
	/* Only short/blocked fills need a software kick. An eight-byte burst
	 * arms the 1/8 TX threshold: let real hardware request its refill. */
	if (len > 0 && n <= 4 && !(rd(dev, FR) & TXFF) && (sources & TX_INT)) {
		data->kick = true;
		NVIC_SetPendingIRQ(((const struct bes_config *)dev->config)->irq);
	}
	return n;
}
static int fifo_read(const struct device *dev, uint8_t *buf, int len)
{
	int n = 0;
	while (n < len && !(rd(dev, FR) & RXFE)) {
		buf[n++] = receive(dev);
	}
	return n;
}
static void tx_enable(const struct device *dev)
{
	struct bes_data *data = dev->data;
	unsigned key = irq_lock();
	mask(dev, TX_INT, 0);
	/* PL011 TX interrupt needs a FIFO threshold transition. Seed from ISR,
	 * never count this software kick as a hardware TX interrupt. */
	data->kick = true;
	NVIC_SetPendingIRQ(((const struct bes_config *)dev->config)->irq);
	irq_unlock(key);
}
static void tx_disable(const struct device *dev)
{
	struct bes_data *data = dev->data;
	unsigned key = irq_lock();
	mask(dev, 0, TX_INT);
	data->kick = data->active_tx = false;
	irq_unlock(key);
}
static int tx_ready(const struct device *dev)
{
	struct bes_data *data = dev->data;
	return (rd(dev, IMSC) & TX_INT) && !(rd(dev, FR) & TXFF) &&
	       (data->active_tx || (rd(dev, MIS) & TX_INT) || (rd(dev, FR) & BIT(7)));
}
static int tx_complete(const struct device *dev) { return !(rd(dev, FR) & BUSY); }
static void rx_enable(const struct device *dev) { mask(dev, RX_INT | RT_INT, 0); }
static void rx_disable(const struct device *dev) { mask(dev, 0, RX_INT | RT_INT); }
static int rx_ready(const struct device *dev)
{ return (rd(dev, IMSC) & RX_INT) && !(rd(dev, FR) & RXFE); }
static void err_enable(const struct device *dev) { mask(dev, ERR_INT, 0); }
static void err_disable(const struct device *dev) { mask(dev, 0, ERR_INT); }
static int pending(const struct device *dev)
{ return rd(dev, MIS) || ((struct bes_data *)dev->data)->active_tx; }
static int update(const struct device *dev) { ARG_UNUSED(dev); return 1; }
static void callback_set(const struct device *dev, uart_irq_callback_user_data_t cb, void *arg)
{
	unsigned key = irq_lock();
	struct bes_data *data = dev->data;
	data->cb = cb; data->arg = arg;
	irq_unlock(key);
}
static void isr(const struct device *dev)
{
	struct bes_data *data = dev->data;
	uint32_t status = rd(dev, MIS);
	data->entry_mis = status;
	if (status & ERR_INT) {
		/* Preserve evidence before ICR can acknowledge the hardware error. */
		save_error(dev, 3, rd(dev, ECR), 0);
		data->rx_errors |= (status & ERR_INT) >> 7;
	}
	data->stats.irq++;
	data->stats.tx_irq += !!(status & TX_INT);
	data->stats.rx_irq += !!(status & RX_INT);
	data->stats.timeout_irq += !!(status & RT_INT);
	data->stats.error_irq += !!(status & ERR_INT);
	data->active_tx = !!(status & TX_INT) || (data->kick && (rd(dev, IMSC) & TX_INT));
	data->kick = false;
	wr(dev, ICR, status & (TX_INT | RT_INT | ERR_INT));
	if (data->cb) { data->cb(dev, data->arg); }
	else { wr(dev, IMSC, 0); }
	data->active_tx = false;
}
#endif
int bes2700_uart_loopback(const struct device *dev, bool enabled)
{
	if (k_is_in_isr()) { return -EWOULDBLOCK; }
	unsigned key = irq_lock();
	if (rd(dev, IMSC) || (rd(dev, FR) & BUSY)) { irq_unlock(key); return -EBUSY; }
	uint32_t control = rd(dev, CR);
	wr(dev, CR, control & ~(BIT(0) | BIT(8) | BIT(9)));
	irq_unlock(key);
	/* FR.BUSY describes TX, not an in-progress RX frame. SDK flush waits
	 * after disabling UART. Allow >1 frame at 1.152 Mbaud, without holding
	 * the global IRQ lock during the quiet interval. */
	k_busy_wait(150);
	key = irq_lock();
	uint32_t lcr = rd(dev, LCR);
	wr(dev, LCR, lcr & ~BIT(4)); /* Flush both FIFOs while disabled. */
	/* A disabled receiver cannot add a new frame after the quiet interval.
	 * Explicitly empty any retained receive holding data before clearing
	 * status: toggling FEN alone is not evidence of an empty receiver. */
	struct bes_data *data = dev->data;
	data->discarded = 0;
	while (!(rd(dev, FR) & RXFE) && data->discarded < 32) {
		(void)rd(dev, DR);
		data->discarded++;
	}
	bool empty = (rd(dev, FR) & RXFE) != 0;
	wr(dev, ECR, 0); wr(dev, ICR, 0x7ff);
	data->rx_errors = data->entry_mis = 0;
#ifdef CONFIG_UART_INTERRUPT_DRIVEN
	data->kick = data->active_tx = false;
#endif
	if (enabled) {
		data->first_error = (struct bes2700_uart_error) {0};
		data->trace = (struct bes2700_uart_rx_trace) {0};
	}
	k_irq_clear_pending(((const struct bes_config *)dev->config)->irq);
	wr(dev, LCR, lcr);
	uint32_t next = enabled ? (control | BIT(7)) : (control & ~BIT(7));
	wr(dev, CR, next);
	/* A software write is not proof that FIFO reset/configuration took
	 * effect. Reject a dirty start rather than attributing it to new data.
	 * On entry failure restore the external mode so diagnostics can print. */
	bool valid = empty && rd(dev, LCR) == lcr && rd(dev, CR) == next;
	if (enabled) {
		valid = valid && (lcr & BIT(4)) && (rd(dev, FR) & RXFE) &&
			!(rd(dev, FR) & BUSY) && !(rd(dev, ECR) & 15);
	}
	if (!valid) { wr(dev, CR, control & ~BIT(7)); }
	irq_unlock(key);
	return valid ? 0 : -EIO;
}
void bes2700_uart_get_stats(const struct device *dev, struct bes2700_uart_stats *stats)
{
	unsigned key = irq_lock();
	*stats = ((struct bes_data *)dev->data)->stats;
	irq_unlock(key);
}
void bes2700_uart_get_error(const struct device *dev, struct bes2700_uart_error *error)
{
	unsigned key = irq_lock();
	*error = ((struct bes_data *)dev->data)->first_error;
	irq_unlock(key);
}
void bes2700_uart_get_state(const struct device *dev, struct bes2700_uart_state *state)
{
	unsigned key = irq_lock();
	*state = (struct bes2700_uart_state) {
		.fr = rd(dev, FR), .rsr = rd(dev, ECR), .lcr = rd(dev, LCR),
		.ifls = rd(dev, IFLS), .cr = rd(dev, CR), .ris = rd(dev, RIS),
		.imsc = rd(dev, IMSC), .ovsampst = rd(dev, OVSAMPST),
		.discarded = ((struct bes_data *)dev->data)->discarded,
	};
	irq_unlock(key);
}
void bes2700_uart_get_rx_trace(const struct device *dev, struct bes2700_uart_rx_trace *trace)
{
	unsigned key = irq_lock();
	*trace = ((struct bes_data *)dev->data)->trace;
	irq_unlock(key);
}
static int init(const struct device *dev)
{
	const struct bes_config *cfg = dev->config;
	/* Clock selection and pinmux remain part of the adapter contract. */
	if (!cfg->baud || !cfg->clock) { return -EINVAL; }
	uint32_t divisor = ((uint64_t)cfg->clock * 4 + cfg->baud / 2) / cfg->baud;
	if (divisor < 64 || (divisor >> 6) > 0xffff) { return -EINVAL; }
	uint32_t budget = 1000000;
	while ((rd(dev, FR) & BUSY) && --budget) { }
	if (!budget) { return -ETIMEDOUT; }
	wr(dev, IMSC, 0); wr(dev, CR, 0); wr(dev, LCR, 0); wr(dev, DMACR, 0);
	wr(dev, ECR, 0); wr(dev, ICR, 0x7ff);
	/* SDK: 16x oversampling starts at sample 8. Do not inherit a prior
	 * bootloader's start offset if this driver programs the ratio itself. */
	wr(dev, OVSAMP, 15); wr(dev, OVSAMPST, 8);
	wr(dev, IBRD, divisor >> 6); wr(dev, FBRD, divisor & 63);
	wr(dev, RXEXT, 3); wr(dev, IFLS, 0); wr(dev, LCR, (3 << 5) | BIT(4));
	wr(dev, CR, BIT(0) | BIT(8) | BIT(9));
	cfg->connect();
	return 0;
}
static DEVICE_API(uart, api) = {
	.poll_in = poll_in, .poll_out = poll_out, .err_check = err_check,
#ifdef CONFIG_UART_INTERRUPT_DRIVEN
	.fifo_fill = fifo_fill, .fifo_read = fifo_read,
	.irq_tx_enable = tx_enable, .irq_tx_disable = tx_disable, .irq_tx_ready = tx_ready,
	.irq_tx_complete = tx_complete, .irq_rx_enable = rx_enable, .irq_rx_disable = rx_disable,
	.irq_rx_ready = rx_ready, .irq_err_enable = err_enable, .irq_err_disable = err_disable,
	.irq_is_pending = pending, .irq_update = update, .irq_callback_set = callback_set,
#endif
};
#ifdef CONFIG_UART_INTERRUPT_DRIVEN
#define CONNECT(n) \
	IRQ_CONNECT(DT_INST_IRQN(n), DT_INST_IRQ(n, priority), isr, DEVICE_DT_INST_GET(n), 0); \
	k_irq_clear_pending(DT_INST_IRQN(n)); irq_enable(DT_INST_IRQN(n))
#else
#define CONNECT(n)
#endif
#define DEFINE(n) \
	BUILD_ASSERT(!DT_INST_PROP(n, hw_flow_control), "Flow control not supported"); \
	static void connect_##n(void) { CONNECT(n); } \
	static struct bes_data data_##n; \
	static const struct bes_config config_##n = { \
		.base = DT_INST_REG_ADDR(n), .clock = DT_INST_PROP(n, clock_frequency), \
		.baud = DT_INST_PROP(n, current_speed), .irq = DT_INST_IRQN(n), .connect = connect_##n }; \
	DEVICE_DT_INST_DEFINE(n, init, NULL, &data_##n, &config_##n, PRE_KERNEL_1, \
		CONFIG_SERIAL_INIT_PRIORITY, &api);
DT_INST_FOREACH_STATUS_OKAY(DEFINE)
