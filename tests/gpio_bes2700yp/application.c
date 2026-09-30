/* SPDX-License-Identifier: Apache-2.0 */
#include <stdlib.h>
#include "shim.h"
#include "bth_contract.h"
#include <bes2700yp_gpio.h>
#include "../../bsp/drivers/gpio/gpio_bes2700yp.c"

static struct bes_gpio_config config = {.common = {.port_pin_mask = BIT(12) | BIT(16) | BIT(17)}};
static struct bes_gpio_data driver_data;
struct device test_device = {.config = &config, .data = &driver_data};
const struct gpio_driver_api *test_api = &bes_gpio_api;
static struct test_systick systick = {.LOAD = 23999, .VAL = 12000};
static struct test_scb scb;
static struct test_diag diag;
struct test_systick *SysTick = &systick;
struct test_scb *SCB = &scb;
struct test_diag *BTH_DIAG = &diag;
static uint32_t now, ticks, fail_op, writes, sample_calls;
static int failure = -EIO;
static struct bes_gpio_snapshot hardware = {.abi = 4, .bytes = 64, .phase = 3,
	.pins = BES_GPIO_PINS, .inputs = BES_GPIO_PINS, .mux_led = 0xffffffff,
	.mux_keys = 0xffffffff, .clocks = 0x4002, .resets = 0x4002};

uint32_t k_uptime_get_32(void) { return now; }
void k_msleep(uint32_t ms) { now += ms; }
uint32_t bth_ticks(void) { return ticks++; }
void bth_puts(const char *value) { (void)value; }
void bth_dec(uint32_t value) { (void)value; }
void bth_field(const char *key, uint32_t value) { (void)key; (void)value; }
void bth_log_begin(char level, const char *component, const char *context)
{
	(void)level; (void)component; (void)context;
}
void bth_end(void) {}
int bes_gpio_connect(void) { return 0; }
int bes_gpio_call(uint32_t op, uint32_t pin, uint32_t value, struct bes_gpio_io *request)
{
	assert(!irq_mask && !basepri);
	ticks += op == BES_GPIO_SAMPLE ? 100 : 24000;
	if (op == fail_op) { return failure; }
	if (op == BES_GPIO_INPUT) {
		hardware.pull_up |= BIT(pin);
		hardware.mux_keys &= ~(15U << ((pin - 16) * 4));
	}
	if (op == BES_GPIO_OUTPUT || op == BES_GPIO_WRITE) {
		assert(pin == 12);
		hardware.outputs = (hardware.outputs & ~BIT(pin)) | (value << pin);
		hardware.inputs = (hardware.inputs & ~BIT(pin)) | (value << pin);
		writes++;
	}
	if (op == BES_GPIO_OUTPUT) {
		hardware.mux_led &= ~0xf0000U;
		hardware.directions |= BIT(pin);
	}
	if (op == BES_GPIO_SAMPLE) { sample_calls++; }
	request->snapshot = hardware;
	return 0;
}

#ifdef INPUT_APPLICATION
#include "../../apps/bes2700yp/bth/src/gpio_validation.c"
static int poll_for(uint32_t ms)
{
	for (uint32_t end = now + ms; now < end; now += 10) {
		int rc = bes_gpio_validation_poll();
		if (rc) { return rc; }
	}
	return 0;
}
#else
#include "../../apps/bes2700yp/bth/src/gpio_restart.c"
#endif

int main(int argc, char **argv)
{
	assert(argc == 2);
	int scenario = atoi(argv[1]);
	assert(gpio_bes_init(&test_device) == 0);
#ifdef INPUT_APPLICATION
	assert(bes_gpio_validation_init() == 0 && writes == 0);
	assert(!poll_for(5000) && !bes_gpio_validation_done());
	if (scenario == 1) {
		fail_op = BES_GPIO_SAMPLE;
		assert(poll_for(20) == 99);
	} else if (scenario == 2) {
		hardware.mux_led ^= 1;
		assert(poll_for(1100) == 98);
	} else if (scenario == 3) {
		fail_op = BES_GPIO_SAMPLE; failure = -EBUSY;
		assert(poll_for(120) == 99);
	} else {
		for (unsigned i = 0; i < 10; i++) {
			hardware.inputs &= ~BES_GPIO_KEYS; assert(!poll_for(500));
			hardware.inputs |= BES_GPIO_KEYS; assert(!poll_for(500));
		}
		assert(bes_gpio_validation_done());
		assert(!bes_gpio_validation_functional());
		assert(!poll_for(60000) && writes == 0 && sample_calls == 7500);
		bes_gpio_validation_timing(60, 0);
	}
	bes_gpio_validation_end();
#else
	assert(!bes_gpio_restart_checkpoint(0, 0));
	hardware.phase = 4;
	assert(!bes_gpio_restart_checkpoint(0, 1));
	unsigned before = writes;
	if (scenario == 1) {
		hardware.mux_keys ^= 1;
	} else if (scenario == 2) {
		hardware.outputs &= ~BES_GPIO_LED;
	} else if (scenario == 3) {
		fail_op = BES_GPIO_SAMPLE;
	}
	hardware.phase = 3;
	if (scenario) {
		assert(bes_gpio_restart_checkpoint(1, 0) == -EIO && writes == before);
	} else {
		for (unsigned round = 1; round < 11; round++) {
			hardware.phase = 3; assert(!bes_gpio_restart_checkpoint(round, 0));
			hardware.phase = 4; assert(!bes_gpio_restart_checkpoint(round, 1));
		}
		assert(transitions == 22 && writes == 23);
		for (unsigned i = 0; i < 60; i++) {
			assert(!bes_gpio_restart_observe(i));
		}
		assert((hardware.outputs & BES_GPIO_LED) && writes == 23);
	}
	bes_gpio_restart_end();
#endif
	return 0;
}
