/* SPDX-License-Identifier: Apache-2.0 */
#include <zephyr/drivers/gpio.h>
#include <zephyr/kernel.h>
#include <bes2700yp_gpio.h>
#include <bes2700yp_gpio_restart.h>
#include "bth_contract.h"

static const struct gpio_dt_spec led = GPIO_DT_SPEC_GET(DT_ALIAS(led0), gpios);
static struct bes_gpio_io io;
static struct bes_gpio_snapshot baseline;
static uint32_t transitions, max_ticks, mask_errors;
static bool configured;

static void field(const char *key, uint32_t value)
{
	bth_puts(key);
	bth_dec(value);
}

static int snapshot(void)
{
	return bes_gpio_call(BES_GPIO_READ, 0, 0, &io);
}

static int preserved(uint32_t phase, uint32_t level)
{
	const struct bes_gpio_snapshot *s = &io.snapshot;

	return s->phase == phase && s->fault == 0 &&
		s->clocks == baseline.clocks && s->resets == baseline.resets &&
		s->irq_enabled == baseline.irq_enabled && s->control == baseline.control &&
		s->mux_keys == baseline.mux_keys &&
		!((s->mux_led ^ baseline.mux_led) & ~(15U << 16)) &&
		!((s->pull_up ^ baseline.pull_up) & ~BES_GPIO_LED) &&
		!((s->pull_down ^ baseline.pull_down) & ~BES_GPIO_LED) &&
		!((s->directions ^ baseline.directions) & ~BES_GPIO_LED) &&
		!((s->outputs ^ baseline.outputs) & ~BES_GPIO_LED) &&
		(s->directions & BES_GPIO_LED) && !(s->mux_led & (15U << 16)) &&
		!((s->pull_up | s->pull_down) & BES_GPIO_LED) &&
		!!(s->outputs & BES_GPIO_LED) == level;
}

static void record(const char *kind, uint32_t round, uint32_t stage,
		   uint32_t sample, int rc)
{
	bth_log_begin(rc ? 'E' : 'I', "GPIO", "MAIN");
	bth_puts("zephyr_gpio_api ");
	bth_puts(kind);
	field(" version=", 1);
	field(" round=", round);
	field(" stage=", stage);
	field(" sample=", sample);
	field(" phase=", io.snapshot.phase);
	field(" fault=", io.snapshot.fault);
#define PRINT(n) bth_field(" " #n "=", io.snapshot.n);
	BES_GPIO_FIELDS(PRINT)
#undef PRINT
	field(" transitions=", transitions);
	field(" max_ticks=", max_ticks);
	field(" mask_errors=", mask_errors);
	field(" rc=", rc < 0 ? (uint32_t)-rc : (uint32_t)rc);
	bth_end();
}

static int check_pad(uint32_t phase, uint32_t level)
{
	int logical = gpio_pin_get_dt(&led);
	int rc = snapshot();

	if (logical < 0) {
		return logical;
	}
	if (rc != 0) {
		return rc;
	}
	if (!preserved(phase, level) || logical != (int)!level ||
	    !!(io.snapshot.inputs & BES_GPIO_LED) != level) {
		return -EIO;
	}
	return 0;
}

int bes_gpio_restart_checkpoint(uint32_t round, uint32_t stage)
{
	uint32_t phase = stage == 0 ? 3 : 4;
	uint32_t ticks;
	int rc;

	if (!gpio_is_ready_dt(&led)) {
		return -ENODEV;
	}
	if (!configured) {
		if (round != 0 || stage != 0) {
			return -EINVAL;
		}
		rc = snapshot();
		if (rc != 0) {
			return rc;
		}
		baseline = io.snapshot;
		record("baseline", 0, 0, 0, 0);
		rc = gpio_pin_configure_dt(&led, GPIO_OUTPUT_INACTIVE);
		if (rc != 0) {
			record("checkpoint", round, stage, 0, rc);
			return rc;
		}
		configured = true;
		k_msleep(10);
	}
	/* Check retention before a new write can conceal a reset-induced change. */
	rc = check_pad(phase, stage == 0 ? 1 : 0);
	if (rc == 0) {
		mask_errors += !!__get_PRIMASK() || !!__get_BASEPRI();
		ticks = bth_ticks();
		rc = stage == 0 ? gpio_pin_toggle_dt(&led) : gpio_pin_set_dt(&led, 0);
		ticks = bth_ticks() - ticks;
		max_ticks = MAX(max_ticks, ticks);
		mask_errors += !!__get_PRIMASK() || !!__get_BASEPRI();
		if (rc == 0) {
			transitions++;
			k_msleep(10);
			rc = check_pad(phase, stage == 0 ? 0 : 1);
		}
	}
	if (mask_errors != 0 && rc == 0) {
		rc = -EPERM;
	}
	record("checkpoint", round, stage, 0, rc);
	return rc;
}

int bes_gpio_restart_observe(uint32_t sample)
{
	int rc = configured && transitions == 22 ? check_pad(4, 1) : -EINVAL;

	record("observe", 10, 2, sample, rc);
	return rc;
}

void bes_gpio_restart_end(void)
{
	if (configured) {
		(void)gpio_pin_set_dt(&led, 0);
	}
}
