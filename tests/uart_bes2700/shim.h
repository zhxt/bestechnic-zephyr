/* SPDX-License-Identifier: Apache-2.0 */
#ifndef BES_UART_TEST_SHIM_H
#define BES_UART_TEST_SHIM_H
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <errno.h>
#include <string.h>
#define BIT(n) (1U << (n))
#define ARG_UNUSED(x) (void)(x)
#define CONFIG_UART_INTERRUPT_DRIVEN 1
#define DT_INST_FOREACH_STATUS_OKAY(fn)
#define DEVICE_API(type, name) const struct uart_driver_api name
#define UART_ERROR_OVERRUN BIT(0)
#define UART_ERROR_PARITY BIT(1)
#define UART_ERROR_FRAMING BIT(2)
#define UART_BREAK BIT(3)
struct device { const void *config; void *data; };
typedef void (*uart_irq_callback_user_data_t)(const struct device *, void *);
struct uart_driver_api {
	int (*poll_in)(const struct device *, unsigned char *);
	void (*poll_out)(const struct device *, unsigned char);
	int (*err_check)(const struct device *);
	int (*fifo_fill)(const struct device *, const uint8_t *, int);
	int (*fifo_read)(const struct device *, uint8_t *, int);
	void (*irq_tx_enable)(const struct device *);
	void (*irq_tx_disable)(const struct device *);
	int (*irq_tx_ready)(const struct device *);
	int (*irq_tx_complete)(const struct device *);
	void (*irq_rx_enable)(const struct device *);
	void (*irq_rx_disable)(const struct device *);
	int (*irq_rx_ready)(const struct device *);
	void (*irq_err_enable)(const struct device *);
	void (*irq_err_disable)(const struct device *);
	int (*irq_is_pending)(const struct device *);
	int (*irq_update)(const struct device *);
	void (*irq_callback_set)(const struct device *, uart_irq_callback_user_data_t, void *);
};
static unsigned irq_depth;
static bool in_isr;
static unsigned irq_lock(void) { return irq_depth++; }
static void irq_unlock(unsigned key) { assert(irq_depth > key); irq_depth = key; }
static bool k_is_in_isr(void) { return in_isr; }
static void k_busy_wait(uint32_t us) { assert(us >= 100 && irq_depth == 0); }
static void k_irq_clear_pending(unsigned irq) { assert(irq == 17); }
static void NVIC_SetPendingIRQ(int irq);
static uint32_t sys_read32(uintptr_t addr);
static void sys_write32(uint32_t value, uintptr_t addr);
#endif
