/* SPDX-License-Identifier: Apache-2.0 */
#include <stdio.h>
#include "shim.h"
#include "../../bsp/drivers/serial/uart_bes2700.c"

/* Worst-case APB/CPU-to-line ratio: one character can arrive while a TX
 * register write completes. The old FIFO-fill loop never returned while
 * TX kept draining, so RX overflowed even with a correct RX ISR. */
#define BASE 0x4000b000U
#define DEPTH 16
static uint32_t registers[0x60 / 4];
static uint8_t incoming[DEPTH];
static unsigned received, overflows;
static struct bes_data state;
static void connect_mock(void) { }
static const struct bes_config config = {
	.base = BASE, .clock = 24000000, .baud = 1152000, .irq = 17, .connect = connect_mock,
};
static const struct device dev = {.config = &config, .data = &state};
static void NVIC_SetPendingIRQ(int irq) { assert(irq == 17); }
static uint32_t sys_read32(uintptr_t address)
{
	unsigned reg = address - BASE;
	assert(reg < sizeof(registers));
	if (reg == FR) { return received ? 0 : RXFE; }
	if (reg == DR) {
		assert(received);
		uint8_t byte = incoming[0];
		memmove(incoming, incoming + 1, --received);
		return byte;
	}
	return registers[reg / 4];
}
static void sys_write32(uint32_t value, uintptr_t address)
{
	unsigned reg = address - BASE;
	assert(reg < sizeof(registers));
	if (reg == ECR) { registers[ECR / 4] = 0; return; }
	if (reg == DR) {
		if (received == DEPTH) { overflows++; registers[ECR / 4] |= BIT(3); }
		else { incoming[received++] = value; }
		return;
	}
	registers[reg / 4] = value;
}
int main(void)
{
	assert(init(&dev) == 0);
	isr(&dev); /* Exercise the no-callback path before enabling sources. */
	api.irq_rx_enable(&dev); api.irq_tx_enable(&dev);
	uint8_t tx[256], rx[256];
	for (unsigned i = 0; i < sizeof(tx); i++) { tx[i] = (i * 73 + 4 * 31) ^ (i >> 2); }
	unsigned sent = 0, read = 0, calls = 0;
	while (sent < sizeof(tx)) {
		int n = api.fifo_fill(&dev, tx + sent, sizeof(tx) - sent);
		calls++;
		printf("fill=%d buffered=%u overflows=%u\n", n, received, overflows);
		fflush(stdout);
		assert(n > 0 && n <= 8 && overflows == 0);
		sent += n;
		read += api.fifo_read(&dev, rx + read, sizeof(rx) - read);
	}
	assert(calls > 1 && read == sizeof(tx) && memcmp(tx, rx, sizeof(tx)) == 0);
	assert(api.err_check(&dev) == 0);
	return 0;
}
