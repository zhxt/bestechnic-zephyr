/* SPDX-License-Identifier: Apache-2.0 */
#define DT_DRV_COMPAT bestechnic_bes2700yp_gpio

#include <zephyr/drivers/gpio.h>
#include <zephyr/drivers/gpio/gpio_utils.h>
#include <zephyr/kernel.h>
#include <cmsis_core.h>
#include <bes2700yp_gpio.h>
#ifdef CONFIG_GPIO_BES2700YP_IRQ
#include <zephyr/irq.h>
#include <bes2700yp_gpio_irq.h>
#endif

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
#ifdef CONFIG_GPIO_BES2700YP_IRQ
	sys_slist_t callbacks;
	struct bes_gpio_irq_io irq_io;
	struct bes_gpio_irq_stats stats;
	uint32_t rate_start, rate_count, empty_count;
	bool irq_claimed;
#endif
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

#ifdef CONFIG_GPIO_BES2700YP_IRQ
/* IRQ 44 is the PSC/AON aggregate. This restricted owner never acknowledges
 * another source. An unexpected source or storm quarantines the NVIC entry. */
static void gpio_bes_irq_fault(struct bes_gpio_data *data, int rc)
{
	data->stats.fault = (uint32_t)-rc;
	irq_disable(BES_GPIO_IRQ_NUMBER);
}

static void gpio_bes_isr(const void *arg)
{
	const struct device *dev = arg;
	struct bes_gpio_data *data = dev->data;
	uint32_t start = k_cycle_get_32(), now = k_uptime_get_32();
	int pending = bes_gpio_irq_call(BES_GPIO_IRQ_ACK, 0, 0);

	data->stats.interrupts++;
	if ((uint32_t)(now - data->rate_start) >= 100U) {
		data->rate_start = now;
		data->rate_count = 0;
	}
	if (++data->rate_count > 256U) {
		gpio_bes_irq_fault(data, -EOVERFLOW);
	} else if (pending < 0 || ((uint32_t)pending & ~data->stats.enabled)) {
		gpio_bes_irq_fault(data, pending < 0 ? pending : -EIO);
	} else if (!pending) {
		data->stats.spurious++;
		if (++data->empty_count >= 8U) {
			gpio_bes_irq_fault(data, -EIO);
		}
	} else {
		data->empty_count = 0;
		data->stats.events0 += !!(pending & BIT(16));
		data->stats.events1 += !!(pending & BIT(17));
		gpio_fire_callbacks(&data->callbacks, dev, (uint32_t)pending);
	}
	data->stats.max_ticks = MAX(data->stats.max_ticks, k_cycle_get_32() - start);
}

static int gpio_bes_manage_callback(const struct device *dev, struct gpio_callback *cb,
				    bool set)
{
	struct bes_gpio_data *data = dev->data;
	unsigned key = irq_lock();
	int rc = gpio_manage_callback(&data->callbacks, cb, set);

	irq_unlock(key);
	return rc;
}

static int gpio_bes_pin_interrupt_configure(const struct device *dev, gpio_pin_t pin,
				   enum gpio_int_mode mode, enum gpio_int_trig trig)
{
	const struct bes_gpio_config *config = dev->config;
	struct bes_gpio_data *data = dev->data;
	uint32_t value = 0;
	int rc;

	if (pin >= 32U || !(config->common.port_pin_mask & BIT(pin))) {
		return -EINVAL;
	}
	if (!(INPUT_PINS & BIT(pin)) ||
	    (mode != GPIO_INT_MODE_DISABLED &&
	     (mode != GPIO_INT_MODE_EDGE ||
	      (trig != GPIO_INT_TRIG_LOW && trig != GPIO_INT_TRIG_HIGH)))) {
		return -ENOTSUP;
	}
	if (mode != GPIO_INT_MODE_DISABLED) {
		value = trig == GPIO_INT_TRIG_HIGH ? 2U : 1U;
	}
	/* Callback disable has a separate scalar fast path. The thread path
	 * masks only this entry before touching the same state or service. */
	if (k_is_in_isr()) {
		if (__get_IPSR() != BES_GPIO_IRQ_NUMBER + 16U || value ||
		    __get_PRIMASK() || !data->irq_claimed) {
			return -EWOULDBLOCK;
		}
		rc = bes_gpio_irq_call(BES_GPIO_IRQ_CONFIG, pin, 0);
		if (!rc) { data->stats.enabled &= ~BIT(pin); }
		else { gpio_bes_irq_fault(data, rc); }
		return rc;
	}
	rc = gpio_bes_enter(dev);
	if (rc) { return rc; }
	irq_disable(BES_GPIO_IRQ_NUMBER);
	if (value && data->stats.fault) { rc = -EIO; }
	if (!rc && !data->irq_claimed && value) {
		rc = bes_gpio_irq_call(BES_GPIO_IRQ_CLAIM, 0, 0);
		data->irq_claimed = !rc;
	}
	if (!rc && data->irq_claimed) {
		rc = bes_gpio_irq_call(BES_GPIO_IRQ_CONFIG, pin, value);
		if (!rc) {
			data->stats.enabled = (data->stats.enabled & ~BIT(pin)) |
				(value ? BIT(pin) : 0U);
		} else { gpio_bes_irq_fault(data, rc); }
	}
	if (data->stats.enabled && !data->stats.fault) { irq_enable(BES_GPIO_IRQ_NUMBER); }
	k_sem_give(&data->lock);
	return rc;
}

int bes_gpio_irq_get_stats(const struct device *dev, struct bes_gpio_irq_stats *stats)
{
	struct bes_gpio_data *data = dev->data;
	if (!stats || k_is_in_isr()) { return -EINVAL; }
	unsigned key = irq_lock();
	*stats = data->stats;
	irq_unlock(key);
	return 0;
}

int bes_gpio_irq_get_state(const struct device *dev, struct bes_gpio_irq_state *state)
{
	struct bes_gpio_data *data = dev->data;
	if (!state) { return -EINVAL; }
	int rc = gpio_bes_enter(dev);
	if (rc) { return rc; }
	/* READ shares bootstrap state with ACK. Exclude IRQ 44, never all IRQs,
	 * while reading slow AON registers. Events stay pending for the ISR. */
	irq_disable(BES_GPIO_IRQ_NUMBER);
	rc = bes_gpio_irq_read(&data->irq_io);
	if (!rc) { *state = data->irq_io.state; }
	if (data->stats.enabled && !data->stats.fault) { irq_enable(BES_GPIO_IRQ_NUMBER); }
	k_sem_give(&data->lock);
	return rc;
}
#else
static int gpio_bes_pin_interrupt_configure(const struct device *dev, gpio_pin_t pin,
				   enum gpio_int_mode mode, enum gpio_int_trig trig)
{
	ARG_UNUSED(dev);
	ARG_UNUSED(pin);
	ARG_UNUSED(mode);
	ARG_UNUSED(trig);
	return -ENOTSUP;
}
#endif

static int gpio_bes_init(const struct device *dev)
{
	struct bes_gpio_data *data = dev->data;

	k_sem_init(&data->lock, 1, 1);
	/* Device initialization discovers the service without touching GPIO.
	 * Configuration is deferred until the application has started M55.
	 */
	int rc = bes_gpio_connect();
#ifdef CONFIG_GPIO_BES2700YP_IRQ
	if (!rc) { rc = bes_gpio_irq_connect(); }
	if (!rc) {
		BUILD_ASSERT(DT_INST_IRQN(0) == BES_GPIO_IRQ_NUMBER, "BTH PSC/AON route");
		IRQ_CONNECT(DT_INST_IRQN(0), DT_INST_IRQ(0, priority), gpio_bes_isr,
			    DEVICE_DT_INST_GET(0), 0);
	}
#endif
	return rc;
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
#ifdef CONFIG_GPIO_BES2700YP_IRQ
	.manage_callback = gpio_bes_manage_callback,
#endif
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
