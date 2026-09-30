/* SPDX-License-Identifier: Apache-2.0 */
#include <pthread.h>
#include <sched.h>
#include "shim.h"
#include <bes2700yp_gpio.h>
#include "../../bsp/drivers/gpio/gpio_bes2700yp.c"

static struct bes_gpio_config config = {.common = {.port_pin_mask = BIT(12) | BIT(16) | BIT(17)}};
static struct bes_gpio_data data;
static struct device dev = {.config = &config, .data = &data};
static struct bes_gpio_snapshot hardware = {.pins = BES_GPIO_PINS, .phase = 3};
static unsigned calls, writes;
static uint32_t fail_op;
static int fail_rc;
static bool reenter, phase_change;

int bes_gpio_connect(void) { return 0; }

int bes_gpio_call(uint32_t op, uint32_t pin, uint32_t value, struct bes_gpio_io *io)
{
	assert(!irq_mask && !basepri && !in_isr);
	assert(io == &data.io && atomic_load(&data.lock.count) == 0);
	calls++;
	if (reenter) {
		gpio_port_value_t ignored = 0;
		reenter = false;
		assert(bes_gpio_api.port_get_raw(&dev, &ignored) == -EWOULDBLOCK);
		assert(bes_gpio_api.port_toggle_bits(&dev, BIT(12)) == -EWOULDBLOCK);
	}
	if (op == fail_op) {
		return fail_rc;
	}
	if (op == BES_GPIO_OUTPUT || op == BES_GPIO_WRITE) {
		if (hardware.phase != 3 && hardware.phase != 4) {
			return -ENODEV;
		}
		assert(pin == 12);
		hardware.outputs = value << 12;
		writes++;
	}
	if (op == BES_GPIO_INPUT) {
		assert(pin == 16 || pin == 17);
	}
	io->snapshot = hardware;
	if (phase_change && op == BES_GPIO_READ) {
		hardware.phase = 2;
	}
	return 0;
}

static void *toggle_worker(void *unused)
{
	(void)unused;
	for (unsigned i = 0; i < 101;) {
		int rc = bes_gpio_api.port_toggle_bits(&dev, BIT(12));
		if (rc == -EWOULDBLOCK) {
			sched_yield();
		} else {
			assert(rc == 0);
			i++;
		}
	}
	return NULL;
}

int main(void)
{
	assert(gpio_bes_init(&dev) == 0 && calls == 0);
	assert(bes_gpio_api.port_set_bits_raw(&dev, BIT(12)) == -EACCES);
	assert(calls == 0);
	for (unsigned pin = 0; pin < 40; pin++) {
		if (pin != 12 && pin != 16 && pin != 17) {
			assert(bes_gpio_api.pin_configure(&dev, pin, GPIO_OUTPUT) == -EINVAL);
		}
	}
	assert(bes_gpio_api.pin_configure(&dev, 16, GPIO_OUTPUT) == -ENOTSUP);
	assert(bes_gpio_api.pin_configure(&dev, 16, GPIO_INPUT) == -ENOTSUP);
	assert(bes_gpio_api.pin_configure(&dev, 16, GPIO_INPUT | GPIO_PULL_DOWN) == -ENOTSUP);
	assert(bes_gpio_api.pin_configure(&dev, 12, GPIO_INPUT | GPIO_PULL_UP) == -ENOTSUP);
	assert(bes_gpio_api.pin_configure(&dev, 12, GPIO_DISCONNECTED) == -ENOTSUP);
	assert(bes_gpio_api.pin_configure(&dev, 12, GPIO_OUTPUT | GPIO_OPEN_DRAIN) == -ENOTSUP);
	assert(bes_gpio_api.pin_configure(&dev, 12, GPIO_OUTPUT | GPIO_OUTPUT_INIT_HIGH |
					GPIO_OUTPUT_INIT_LOW) == -ENOTSUP);
	assert(calls == 0);
	assert(bes_gpio_api.pin_configure(&dev, 16, GPIO_INPUT | GPIO_PULL_UP | GPIO_ACTIVE_LOW) == 0);
	assert(bes_gpio_api.pin_configure(&dev, 17, GPIO_INPUT | GPIO_PULL_UP) == 0);
	assert(bes_gpio_api.pin_configure(&dev, 12, GPIO_OUTPUT_HIGH) == 0);
	assert(hardware.outputs == BIT(12));
	unsigned before = calls;
	assert(bes_gpio_api.port_set_masked_raw(&dev, BIT(12) | BIT(13), 0) == -EINVAL);
	assert(bes_gpio_api.port_clear_bits_raw(&dev, BIT(12) | BIT(16)) == -ENOTSUP);
	assert(bes_gpio_api.port_toggle_bits(&dev, BIT(17)) == -ENOTSUP);
	assert(bes_gpio_api.port_clear_bits_raw(&dev, 0) == 0);
	assert(calls == before && hardware.outputs == BIT(12));
	assert(bes_gpio_api.port_set_masked_raw(&dev, BIT(12), BIT(13)) == 0);
	assert(hardware.outputs == 0);
	assert(bes_gpio_api.port_set_bits_raw(&dev, BIT(12)) == 0);
	assert(bes_gpio_api.port_clear_bits_raw(&dev, BIT(12)) == 0);
	/* A pad held high externally must not change the output-latch toggle. */
	hardware.inputs = BES_GPIO_PINS;
	assert(bes_gpio_api.port_toggle_bits(&dev, BIT(12)) == 0);
	assert(hardware.outputs == BIT(12));
	assert(bes_gpio_api.port_toggle_bits(&dev, BIT(12)) == 0);
	assert(hardware.outputs == 0);
	gpio_port_value_t value = 0;
	assert(bes_gpio_api.port_get_raw(&dev, &value) == 0);
	assert(value == config.common.port_pin_mask); /* D3 remains inaccessible. */
	before = calls;
	in_isr = true;
	assert(bes_gpio_api.port_get_raw(&dev, &value) == -EWOULDBLOCK);
	in_isr = false; irq_mask = 1;
	assert(bes_gpio_api.port_set_bits_raw(&dev, BIT(12)) == -EWOULDBLOCK);
	irq_mask = 0; basepri = 1;
	assert(bes_gpio_api.port_toggle_bits(&dev, BIT(12)) == -EWOULDBLOCK);
	basepri = 0; control = 1;
	assert(bes_gpio_api.pin_configure(&dev, 12, GPIO_OUTPUT_LOW) == -EPERM);
	control = 0;
	assert(calls == before);
	assert(bes_gpio_api.pin_interrupt_configure(&dev, 12, GPIO_INT_MODE_EDGE,
						 GPIO_INT_TRIG_HIGH) == -ENOTSUP);
	reenter = true;
	assert(bes_gpio_api.port_get_raw(&dev, &value) == 0);
	assert(calls == before + 1);
	fail_op = BES_GPIO_SAMPLE; fail_rc = -EBUSY; value = 0xdeadbeef;
	assert(bes_gpio_api.port_get_raw(&dev, &value) == -EWOULDBLOCK && value == 0xdeadbeef);
	fail_rc = -EIO;
	assert(bes_gpio_api.port_get_raw(&dev, &value) == -EIO && value == 0xdeadbeef);
	fail_op = BES_GPIO_READ; before = writes;
	assert(bes_gpio_api.port_toggle_bits(&dev, BIT(12)) == -EIO && writes == before);
	fail_op = 0; hardware.fault = 1;
	assert(bes_gpio_api.port_toggle_bits(&dev, BIT(12)) == -EIO && writes == before);
	hardware.fault = 0; phase_change = true;
	assert(bes_gpio_api.port_toggle_bits(&dev, BIT(12)) == -ENODEV && writes == before);
	phase_change = false; hardware.phase = 4;
	assert(bes_gpio_api.port_set_bits_raw(&dev, BIT(12)) == 0);
	fail_op = BES_GPIO_OUTPUT; fail_rc = -EIO;
	assert(bes_gpio_api.pin_configure(&dev, 12, GPIO_OUTPUT_LOW) == -EIO);
	assert(bes_gpio_api.port_toggle_bits(&dev, BIT(12)) == -EACCES);
	fail_op = 0;
	assert(bes_gpio_api.pin_configure(&dev, 12, GPIO_OUTPUT_LOW) == 0);
	pthread_t workers[3];
	before = writes;
	for (unsigned i = 0; i < 3; i++) {
		assert(pthread_create(&workers[i], NULL, toggle_worker, NULL) == 0);
	}
	for (unsigned i = 0; i < 3; i++) {
		assert(pthread_join(workers[i], NULL) == 0);
	}
	assert(writes == before + 303 && hardware.outputs == BIT(12));
	assert(atomic_load(&data.lock.count) == 1);
	return 0;
}
