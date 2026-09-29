/* SPDX-License-Identifier: Apache-2.0 */
#ifndef BES2700YP_GPIO_H
#define BES2700YP_GPIO_H
#include <bes2700yp_resources.h>
#define BES_GPIO_ABI 4U
#define BES_GPIO_CAP 8U
#define BES_GPIO_OUTPUT_CAP 16U
#define BES_GPIO_ID 4U
#define BES_GPIO_READ 1U
#define BES_GPIO_INPUT 2U
#define BES_GPIO_OUTPUT 3U
#define BES_GPIO_WRITE 4U
#define BES_GPIO_KEYS (3U << 16)
#define BES_GPIO_LED (1U << 12)
#define BES_GPIO_PINS (BES_GPIO_KEYS | (3U << 12))
#define BES_GPIO_FIELDS(X)  X(pins) X(inputs) X(directions) X(outputs) X(mux_led) X(mux_keys)  X(pull_up) X(pull_down) X(clocks) X(resets) X(irq_enabled) X(control)
/* Fixed board qualification service, not a general GPIO controller.
 * BTH privileged threads only. Masks use bank*8+pin. P2_0/1 input pull-up;
 * optional P1_4 push-pull, P1_5 read-only. No voltage, drive or IRQ changes.
 * Configure only in active/stopped M55 phases 3/4. Snapshot includes complete
 * mux/pull fields for non-target preservation; inputs/direction/data are masked.
 * Wire errors: -1 invalid, -2 unsupported, -3 context, -4 busy,
 * -5 bank/phase unavailable, -6 latched write/readback fault.
 * Failed operations invalidate output. A write failure may have changed its
 * target; firmware stops the scenario and requires a cold reset to retry. */
struct bes_gpio_snapshot {
 uint32_t abi, bytes, phase, fault;
#define MEMBER(n) uint32_t n;
 BES_GPIO_FIELDS(MEMBER)
#undef MEMBER
};
struct bes_gpio_io {
 uint32_t abi, bytes, resource, pin, value, reserved[3];
 struct bes_gpio_snapshot snapshot;
};
_Static_assert(sizeof(struct bes_gpio_io)==96,"GPIO request ABI");
_Static_assert(sizeof(struct bes_gpio_snapshot)==64,"GPIO snapshot ABI");
int bes_gpio_descriptor_valid(const struct bes_resource_descriptor *d);
int bes_gpio_connect(void);
int bes_gpio_call(uint32_t op,uint32_t pin,uint32_t value,struct bes_gpio_io *io);
#endif
