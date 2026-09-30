/* SPDX-License-Identifier: Apache-2.0 */
#ifndef BES_GPIO_TEST_SHIM_H
#define BES_GPIO_TEST_SHIM_H
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdatomic.h>
#include <stddef.h>
#include <zephyr/dt-bindings/gpio/gpio.h>
#define BIT(n) (1U << (n))
#define MAX(a, b) ((a) > (b) ? (a) : (b))
#define ARG_UNUSED(x) (void)(x)
#define BUILD_ASSERT(c, ...) _Static_assert(c, #c)
#define K_NO_WAIT 0
#define GPIO_INPUT BIT(16)
#define GPIO_OUTPUT BIT(17)
#define GPIO_OUTPUT_INIT_LOW BIT(18)
#define GPIO_OUTPUT_INIT_HIGH BIT(19)
#define GPIO_OUTPUT_INIT_LOGICAL BIT(20)
#define GPIO_OUTPUT_LOW (GPIO_OUTPUT | GPIO_OUTPUT_INIT_LOW)
#define GPIO_OUTPUT_HIGH (GPIO_OUTPUT | GPIO_OUTPUT_INIT_HIGH)
#define GPIO_OUTPUT_INACTIVE (GPIO_OUTPUT_LOW | GPIO_OUTPUT_INIT_LOGICAL)
#define GPIO_DISCONNECTED 0
typedef uint32_t gpio_pin_t;
typedef uint32_t gpio_flags_t;
typedef uint32_t gpio_port_pins_t;
typedef uint32_t gpio_port_value_t;
struct gpio_driver_config { gpio_port_pins_t port_pin_mask; };
struct gpio_driver_data { gpio_port_pins_t invert; };
struct device { const void *config; void *data; };
struct k_sem { atomic_int count; };
enum gpio_int_mode { GPIO_INT_MODE_DISABLED, GPIO_INT_MODE_EDGE };
enum gpio_int_trig { GPIO_INT_TRIG_LOW, GPIO_INT_TRIG_HIGH };
struct gpio_driver_api {
	int (*pin_configure)(const struct device *, gpio_pin_t, gpio_flags_t);
	int (*port_get_raw)(const struct device *, gpio_port_value_t *);
	int (*port_set_masked_raw)(const struct device *, gpio_port_pins_t, gpio_port_value_t);
	int (*port_set_bits_raw)(const struct device *, gpio_port_pins_t);
	int (*port_clear_bits_raw)(const struct device *, gpio_port_pins_t);
	int (*port_toggle_bits)(const struct device *, gpio_port_pins_t);
	int (*pin_interrupt_configure)(const struct device *, gpio_pin_t,
				       enum gpio_int_mode, enum gpio_int_trig);
};
#define DEVICE_API(type, name) const struct gpio_driver_api name
#define DT_INST_FOREACH_STATUS_OKAY(fn)
#define DT_NUM_INST_STATUS_OKAY(compat) 1
static uint32_t irq_mask, basepri, control;
static bool in_isr;
static uint32_t __get_PRIMASK(void) { return irq_mask; }
static uint32_t __get_BASEPRI(void) { return basepri; }
static uint32_t __get_CONTROL(void) { return control; }
static bool k_is_in_isr(void) { return in_isr; }
static void k_sem_init(struct k_sem *sem, unsigned initial, unsigned limit)
{
	assert(initial == 1 && limit == 1);
	atomic_store(&sem->count, 1);
}
static int k_sem_take(struct k_sem *sem, unsigned timeout)
{
	int expected = 1;
	assert(timeout == K_NO_WAIT && !in_isr && !irq_mask && !basepri);
	return atomic_compare_exchange_strong(&sem->count, &expected, 0) ? 0 : -EBUSY;
}
static void k_sem_give(struct k_sem *sem)
{
	assert(atomic_exchange(&sem->count, 1) == 0);
}

/* Minimal host adapter for Zephyr's logical GPIO wrappers. Driver callbacks
 * above are the real implementation; target builds use Zephyr's own wrappers.
 */
extern struct device test_device;
extern const struct gpio_driver_api *test_api;
struct gpio_dt_spec { const struct device *port; gpio_pin_t pin; gpio_flags_t dt_flags; };
#define DT_ALIAS(name) name
#define GPIO_SPEC_sw0 {&test_device, 16, GPIO_ACTIVE_LOW | GPIO_PULL_UP}
#define GPIO_SPEC_sw1 {&test_device, 17, GPIO_ACTIVE_LOW | GPIO_PULL_UP}
#define GPIO_SPEC_led0 {&test_device, 12, GPIO_ACTIVE_LOW}
#define GPIO_SPEC_EXPAND(node) GPIO_SPEC_##node
#define GPIO_DT_SPEC_GET(node, property) GPIO_SPEC_EXPAND(node)
static inline bool gpio_is_ready_dt(const struct gpio_dt_spec *spec)
{
	return spec->port == &test_device;
}
static inline int gpio_pin_configure_dt(const struct gpio_dt_spec *spec, gpio_flags_t flags)
{
	struct gpio_driver_data *data = spec->port->data;
	flags |= spec->dt_flags;
	if ((flags & GPIO_OUTPUT_INIT_LOGICAL) && (flags & GPIO_ACTIVE_LOW) &&
	    (flags & (GPIO_OUTPUT_INIT_LOW | GPIO_OUTPUT_INIT_HIGH))) {
		flags ^= GPIO_OUTPUT_INIT_LOW | GPIO_OUTPUT_INIT_HIGH;
	}
	flags &= ~GPIO_OUTPUT_INIT_LOGICAL;
	data->invert = (data->invert & ~BIT(spec->pin)) |
		((flags & GPIO_ACTIVE_LOW) ? BIT(spec->pin) : 0);
	return test_api->pin_configure(spec->port, spec->pin, flags);
}
static inline int gpio_port_get_raw(const struct device *dev, gpio_port_value_t *value)
{
	return test_api->port_get_raw(dev, value);
}
static inline int gpio_pin_get_dt(const struct gpio_dt_spec *spec)
{
	gpio_port_value_t value;
	int rc = gpio_port_get_raw(spec->port, &value);
	return rc ? rc : (!!(value & BIT(spec->pin)) ^ !!(spec->dt_flags & GPIO_ACTIVE_LOW));
}
static inline int gpio_pin_set_dt(const struct gpio_dt_spec *spec, int value)
{
	value = !!value ^ !!(spec->dt_flags & GPIO_ACTIVE_LOW);
	return test_api->port_set_masked_raw(spec->port, BIT(spec->pin), value ? BIT(spec->pin) : 0);
}
static inline int gpio_pin_toggle_dt(const struct gpio_dt_spec *spec)
{
	return test_api->port_toggle_bits(spec->port, BIT(spec->pin));
}
uint32_t k_uptime_get_32(void);
void k_msleep(uint32_t ms);
#endif
