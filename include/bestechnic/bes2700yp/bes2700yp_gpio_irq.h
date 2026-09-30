/* SPDX-License-Identifier: Apache-2.0 */
#ifndef BES2700YP_GPIO_IRQ_H
#define BES2700YP_GPIO_IRQ_H
#include <bes2700yp_resources.h>

#define BES_GPIO_IRQ_ABI 5U
#define BES_GPIO_IRQ_CAP 64U
#define BES_GPIO_IRQ_NUMBER 44U
#define BES_GPIO_IRQ_KEYS (3U << 16)
#define BES_GPIO_IRQ_READ 1U
#define BES_GPIO_IRQ_CLAIM 2U
#define BES_GPIO_IRQ_CONFIG 3U
#define BES_GPIO_IRQ_ACK 4U
#define BES_GPIO_IRQ_FIELDS(X) \
 X(enabled) X(masked) X(edge) X(rising) X(debounce) X(raw) X(pending) X(inputs) \
 X(route) X(bth_status) X(wake_mask) X(wake_status) X(sys_route) X(btc_route) X(sens_route) X(directions)
struct bes_gpio_irq_state {
#define IRQ_MEMBER(n) uint32_t n;
 BES_GPIO_IRQ_FIELDS(IRQ_MEMBER)
#undef IRQ_MEMBER
};
struct bes_gpio_irq_io {
 uint32_t abi, bytes, reserved[6];
 struct bes_gpio_irq_state state;
};
_Static_assert(sizeof(struct bes_gpio_irq_io)==96, "GPIO IRQ request ABI");
/* READ takes a BTH data-RAM request; other operations use scalar arguments.
 * CONFIG(pin, mode): 0 off, 1 falling, 2 rising. ACK(0,0) returns pending pins.
 * Only IRQ 44 may ACK or disable in ISR; enable/claim/read require a thread.
 * Thread operations require IRQ 44 disabled; other IRQs stay enabled.
 * No waiting, NVIC registration, IOMUX configuration or unowned IRQ clearing.
 */
int bes_gpio_irq_descriptor_valid(const struct bes_resource_descriptor *d);
int bes_gpio_irq_connect(void);
int bes_gpio_irq_call(uint32_t op, uint32_t arg, uint32_t value);
int bes_gpio_irq_read(struct bes_gpio_irq_io *io);
/* Driver diagnostics: application-owned copy; query only from a thread. */
struct bes_gpio_irq_stats {
 uint32_t interrupts, events0, events1, spurious, fault, max_ticks, enabled;
};
struct device;
int bes_gpio_irq_get_stats(const struct device *dev, struct bes_gpio_irq_stats *stats);
int bes_gpio_irq_get_state(const struct device *dev, struct bes_gpio_irq_state *state);
#endif
