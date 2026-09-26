/* SPDX-License-Identifier: Apache-2.0 */
#ifndef TEST_DUAL_SHIM_H
#define TEST_DUAL_SHIM_H
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <errno.h>
#define BUILD_ASSERT(x) _Static_assert(x,#x)
#define ARG_UNUSED(x) (void)(x)
#define K_SECONDS(x) ((x)*1000)
#define K_MSEC(x) (x)
#define K_FOREVER (-1)
#define K_SEM_DEFINE(name,initial,max) static struct k_sem name={initial,max}
#define K_THREAD_DEFINE(...)
#define q_worker ((void *)0)
#define CONFIG_DUAL_CC_PAIR 0x12344321U
#define MIN(a,b) ((a)<(b)?(a):(b))
#define MAX(a,b) ((a)>(b)?(a):(b))
#define __DSB() __DMB()
void k_yield(void);
static inline void k_thread_abort(void *p) { (void)p; }
#define DT_NODELABEL(x) 0
#define DEVICE_DT_GET(x) (&devices[SIDE])
#define CONFIG_DUAL_M55_BUILD 0x87654321
#define CONFIG_SYS_CLOCK_HW_CYCLES_PER_SEC 24000000
#ifndef __DMB
#define __DMB() __asm__ volatile("" ::: "memory")
#endif
struct fake_scb { uint32_t CPUID,CCR,TYPE; };
extern struct fake_scb scb;
#define SCB (&scb)
#define MPU (&scb)
struct k_sem { unsigned count,limit; };
struct k_spinlock { int unused; };
typedef int k_spinlock_key_t;
static inline int k_spin_lock(struct k_spinlock *l) { (void)l;return 0; }
static inline void k_spin_unlock(struct k_spinlock *l,int k) { (void)l;(void)k; }
struct device { int id; };
struct mbox_msg { int unused; };
extern struct device devices[2];
typedef void (*mbox_callback_t)(const struct device *,uint32_t,void *,struct mbox_msg *);
int k_sem_take(struct k_sem *,int64_t);
void k_sem_give(struct k_sem *);
static inline void k_sem_reset(struct k_sem *s) { s->count=0; }
void k_msleep(int);
int64_t k_uptime_get(void);
uint32_t k_uptime_get_32(void);
unsigned irq_lock(void);
void irq_unlock(unsigned);
static inline uint32_t sys_read32(uintptr_t p) { (void)p;return 0; }
static inline bool device_is_ready(const struct device *d) { (void)d;return true; }
static inline void *k_current_get(void) { return NULL; }
static inline int k_thread_stack_space_get(void *t,size_t *n) { (void)t;*n=1500;return 0; }
int mbox_send(const struct device *,uint32_t,struct mbox_msg *);
int mbox_register_callback(const struct device *,uint32_t,mbox_callback_t,void *);
int mbox_set_enabled(const struct device *,uint32_t,bool);
#endif
