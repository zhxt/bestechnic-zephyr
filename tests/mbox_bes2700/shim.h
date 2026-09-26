/* Copyright The Zephyr Project Contributors */
/* SPDX-License-Identifier: Apache-2.0 */
#ifndef BES2700_TEST_SHIM_H_
#define BES2700_TEST_SHIM_H_

#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <errno.h>
#include <string.h>

#define BIT(n) (1U << (n))
#define ARG_UNUSED(arg) (void)(arg)
#define DT_INST_FOREACH_STATUS_OKAY(fn)
#define DEVICE_API(type, name) const struct mbox_driver_api name

struct device { const void *config; void *data; };
struct mbox_msg { const void *data; size_t size; };
typedef void (*mbox_callback_t)(const struct device *, uint32_t, void *, struct mbox_msg *);
struct mbox_driver_api {
	int (*send)(const struct device *, uint32_t, const struct mbox_msg *);
	int (*register_callback)(const struct device *, uint32_t, mbox_callback_t, void *);
	int (*mtu_get)(const struct device *);
	uint32_t (*max_channels_get)(const struct device *);
	int (*set_enabled)(const struct device *, uint32_t, bool);
};
struct k_spinlock { int held; };
typedef int k_spinlock_key_t;
static inline int k_spin_lock(struct k_spinlock *lock)
{
	assert(lock->held == 0);
	lock->held = 1;
	return 0;
}
static inline void k_spin_unlock(struct k_spinlock *lock, int key)
{
	(void)key;
	assert(lock->held == 1);
	lock->held = 0;
}
static inline void barrier_dsync_fence_full(void) {}
static void irq_enable(unsigned int irq);
static void irq_disable(unsigned int irq);
#ifdef CONFIG_BES2700_M55_RESTART
static void NVIC_ClearPendingIRQ(unsigned int irq);
#endif
static void sys_write32(uint32_t value, uintptr_t addr);
static uint32_t sys_read32(uintptr_t addr);

#endif
