/* SPDX-License-Identifier: Apache-2.0 */
#define DT_DRV_COMPAT bestechnic_bes2700yp_gpio

#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/gpio/gpio_utils.h>
#include <zephyr/kernel.h>
#include <cmsis_core.h>
#include <bes2700yp_gpio.h>

#define INPUT_PINS BES_GPIO_KEYS
#define OUTPUT_PINS BES_GPIO_LED

struct bes_gpio_config {
	struct gpio_driver_config common;
};

struct bes_gpio_data {
	struct gpio_driver_data common;
	struct k_sem lock;
	/* The service accepts requests only in BTH data RAM, not caller stacks. */
	struct bes_gpio_io io;
	bool output_configured;
};

static int gpio_bes_enter(const struct device *dev)
{
	struct bes_gpio_data *data = dev->data;

	/* Do not wrap slow AON accesses in a spinlock or an IRQ-disabled region. */
	if (k_is_in_isr() || __get_PRIMASK() || __get_BASEPRI()) {
		return -EWOULDBLOCK;
	}
	if (__get_CONTROL() & 1U) {
		return -EPERM;
	}
	return k_sem_take(&data->lock, K_NO_WAIT) == 0 ? 0 : -EWOULDBLOCK;
}

static int __attribute__((noinline)) gpio_bes_call(struct bes_gpio_data *data, uint32_t op,
						uint32_t pin, uint32_t value)
{
	int rc = bes_gpio_call(op, pin, value, &data->io);

	if (rc == -EBUSY) {
		return -EWOULDBLOCK;
	}
	if (rc == 0 && data->io.snapshot.fault != 0U) {
		return -EIO;
	}
	return rc;
}

static int gpio_bes_pin_configure(const struct device *dev, gpio_pin_t pin, gpio_flags_t flags)
{
	const struct bes_gpio_config *config = dev->config;
	struct bes_gpio_data *data = dev->data;
	uint32_t op, value = 0;
	int rc;

	if (pin >= 32U || (config->common.port_pin_mask & BIT(pin)) == 0U) {
		return -EINVAL;
	}
	flags &= ~GPIO_ACTIVE_LOW;
	if ((INPUT_PINS & BIT(pin)) != 0U && flags == (GPIO_INPUT | GPIO_PULL_UP)) {
		op = BES_GPIO_INPUT;
	} else if ((OUTPUT_PINS & BIT(pin)) != 0U &&
		   (flags == GPIO_OUTPUT || flags == GPIO_OUTPUT_HIGH ||
		    flags == GPIO_OUTPUT_LOW)) {
		op = BES_GPIO_OUTPUT;
		/* Unspecified output initialization defaults to the inactive LED level. */
		value = (flags & GPIO_OUTPUT_INIT_LOW) == 0U;
	} else {
		return -ENOTSUP;
	}
	rc = gpio_bes_enter(dev);
	if (rc != 0) {
		return rc;
	}
	rc = gpio_bes_call(data, op, pin, value);
	if (op == BES_GPIO_OUTPUT) {
		data->output_configured = rc == 0;
	}
	k_sem_give(&data->lock);
	return rc;
}

static int gpio_bes_port_get_raw(const struct device *dev, gpio_port_value_t *value)
{
	const struct bes_gpio_config *config = dev->config;
	struct bes_gpio_data *data = dev->data;
	int rc = gpio_bes_enter(dev);

	if (rc != 0) {
		return rc;
	}
	rc = gpio_bes_call(data, BES_GPIO_SAMPLE, 0, 0);
	if (rc == 0) {
		*value = data->io.snapshot.inputs & config->common.port_pin_mask;
	}
	k_sem_give(&data->lock);
	return rc;
}

static int gpio_bes_port_write(const struct device *dev, gpio_port_pins_t mask,
			       gpio_port_value_t value, bool toggle)
{
	const struct bes_gpio_config *config = dev->config;
	struct bes_gpio_data *data = dev->data;
	int rc;

	/* Reject a mixed valid/invalid mask before making any hardware change. */
	if ((mask & ~config->common.port_pin_mask) != 0U) {
		return -EINVAL;
	}
	if ((mask & ~OUTPUT_PINS) != 0U) {
		return -ENOTSUP;
	}
	rc = gpio_bes_enter(dev);
	if (rc != 0) {
		return rc;
	}
	if (mask == 0U) {
		rc = 0;
	} else if (!data->output_configured) {
		rc = -EACCES;
	} else {
		/* Serialize read-modify-write across all driver callers. Read the
		 * latch, not the pad or a shadow that can survive a failed write.
		 * Lifecycle changes between calls are rejected by the write service.
		 */
		if (toggle) {
			rc = gpio_bes_call(data, BES_GPIO_READ, 0, 0);
			value = data->io.snapshot.outputs ^ mask;
		}
		if (rc == 0) {
			rc = gpio_bes_call(data, BES_GPIO_WRITE, 12, (value & OUTPUT_PINS) != 0U);
		}
	}
	k_sem_give(&data->lock);
	return rc;
}

static int gpio_bes_port_set_masked_raw(const struct device *dev, gpio_port_pins_t mask,
			       gpio_port_value_t value)
{
	return gpio_bes_port_write(dev, mask, value, false);
}

static int gpio_bes_port_set_bits_raw(const struct device *dev, gpio_port_pins_t pins)
{
	return gpio_bes_port_write(dev, pins, pins, false);
}

static int gpio_bes_port_clear_bits_raw(const struct device *dev, gpio_port_pins_t pins)
{
	return gpio_bes_port_write(dev, pins, 0, false);
}

static int gpio_bes_port_toggle_bits(const struct device *dev, gpio_port_pins_t pins)
{
	return gpio_bes_port_write(dev, pins, 0, true);
}

static int gpio_bes_pin_interrupt_configure(const struct device *dev, gpio_pin_t pin,
				   enum gpio_int_mode mode, enum gpio_int_trig trig)
{
	ARG_UNUSED(dev);
	ARG_UNUSED(pin);
	ARG_UNUSED(mode);
	ARG_UNUSED(trig);
	return -ENOTSUP;
}

static int gpio_bes_init(const struct device *dev)
{
	struct bes_gpio_data *data = dev->data;

	k_sem_init(&data->lock, 1, 1);
	/* Device initialization discovers the service without touching GPIO.
	 * Configuration is deferred until the application has started M55.
	 */
	return bes_gpio_connect();
}

BUILD_ASSERT(sizeof(gpio_port_pins_t) == 4, "32-bit GPIO bank");

static DEVICE_API(gpio, bes_gpio_api) = {
	.pin_configure = gpio_bes_pin_configure,
	.port_get_raw = gpio_bes_port_get_raw,
	.port_set_masked_raw = gpio_bes_port_set_masked_raw,
	.port_set_bits_raw = gpio_bes_port_set_bits_raw,
	.port_clear_bits_raw = gpio_bes_port_clear_bits_raw,
	.port_toggle_bits = gpio_bes_port_toggle_bits,
	.pin_interrupt_configure = gpio_bes_pin_interrupt_configure,
};

#define BES_GPIO_DEFINE(n)                                                                  \
	BUILD_ASSERT((GPIO_PORT_PIN_MASK_FROM_DT_INST(n) & ~(INPUT_PINS | OUTPUT_PINS)) == 0,  \
		     "GPIO service grant excludes these pins");                                    \
	static const struct bes_gpio_config gpio_bes_config_##n = {                                  \
		.common = {.port_pin_mask = GPIO_PORT_PIN_MASK_FROM_DT_INST(n)},              \
	};                                                                                  \
	static struct bes_gpio_data gpio_bes_data_##n;                                                \
	DEVICE_DT_INST_DEFINE(n, gpio_bes_init, NULL, &gpio_bes_data_##n, &gpio_bes_config_##n, POST_KERNEL,              \
			      CONFIG_GPIO_INIT_PRIORITY, &bes_gpio_api);

BUILD_ASSERT(DT_NUM_INST_STATUS_OKAY(DT_DRV_COMPAT) == 1, "One AON GPIO service owner");
DT_INST_FOREACH_STATUS_OKAY(BES_GPIO_DEFINE)
