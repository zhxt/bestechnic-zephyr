/* SPDX-License-Identifier: Apache-2.0 */
#include <stdio.h>
#include "shim.h"
#ifndef UART_SOURCE
#define UART_SOURCE "../../bsp/drivers/serial/uart_bes2700.c"
#endif
#include UART_SOURCE

/* Fault model: a receive holding byte survives the FEN toggle. This checks
 * recovery of a possible residual state, not a claim about BES silicon. */
#define BASE 0x4000b000U
static uint32_t regs[0x60 / 4];
static unsigned retained, reads;
static bool stuck;
static struct bes_data data;
static void connect_mock(void) { }
static const struct bes_config config = {
	.base = BASE, .clock = 24000000, .baud = 1152000, .irq = 17, .connect = connect_mock,
};
static const struct device dev = {.config = &config, .data = &data};
static void NVIC_SetPendingIRQ(int irq) { assert(irq == 17); }
static uint32_t sys_read32(uintptr_t address)
{
	unsigned reg = address - BASE;
	assert(reg < sizeof(regs));
	if (reg == FR) { return BIT(7) | (retained ? 0 : RXFE); }
	if (reg == DR) {
		assert(retained);
		reads++;
		if (!stuck) { retained--; }
		return 0x87c;
	}
	return regs[reg / 4];
}
static void sys_write32(uint32_t value, uintptr_t address)
{
	unsigned reg = address - BASE;
	assert(reg < sizeof(regs));
	if (reg == ECR) { regs[ECR / 4] = 0; return; }
	regs[reg / 4] = value;
}
int main(void)
{
	assert(init(&dev) == 0);
	isr(&dev);
	retained = 1; regs[ECR / 4] = BIT(3);
	int rc = bes2700_uart_loopback(&dev, true);
	printf("entry_rc=%d retained=%u reads=%u\n", rc, retained, reads); fflush(stdout);
	assert(rc == 0 && retained == 0 && reads == 1);
	uint8_t byte;
	assert(api.fifo_read(&dev, &byte, 1) == 0 && api.err_check(&dev) == 0);
	retained = 1; stuck = true;
	rc = bes2700_uart_loopback(&dev, true);
	printf("stuck_rc=%d reads=%u cr=%x\n", rc, reads, regs[CR / 4]); fflush(stdout);
	assert(rc == -EIO && reads == 33 && !(regs[CR / 4] & BIT(7)));
	return 0;
}
