/* SPDX-License-Identifier: Apache-2.0 */
#ifndef BES2700_DUAL_BOOT_H
#define BES2700_DUAL_BOOT_H
#include <stdint.h>
#define DUAL_LAYOUT 0x00080002U
#define DUAL_SERVICE_ADDR 0x2055c100U
#define DUAL_SERVICE_MAGIC 0x38565342U
#define DUAL_SHARED_ADDR 0x2015e100U
#define DUAL_MAGIC 0x384d3535U
#define DUAL_GUARD 0x4e5b08a1U
#define DUAL_ITCM 0x000a0000U
#define DUAL_ITCM_END 0x000e0000U
#define DUAL_DTCM 0x200c0000U
#define DUAL_DTCM_END 0x2015c000U
#define DUAL_TRAMPOLINE 0x2015e000U
#define DUAL_MAILBOX 0x2015ffe0U
#define DUAL_HZ 24000000U
#define DUAL_TRACE_ADDR 0x2015e180U
#define DUAL_HW_ADDR 0x2055c140U
#define DUAL_SNAPSHOT 6U
#define DUAL_PREPARE 1U
#define DUAL_PARK 2U
#define DUAL_RELEASE 3U
#define DUAL_STOP 4U
#define DUAL_CHECK_CLOCK 5U
struct dual_trace {
 uint32_t stage, cpuid, vtor, msp, psp, control, primask, basepri;
 uint32_t ccr, mpu, cpacr, cfsr, hfsr, shcsr, mmfar, bfar, icsr, reason;
 uint32_t msplim, psplim, pc, lr, xpsr, esf_valid;
};
struct dual_hw {
 uint32_t phase, core_vtor, reset_set, reset_clr, ram_sel0, ram_sel1;
 uint32_t oclk, oreset, sysclk, vector_sp, vector_pc, release_sp, release_pc;
};
#define DUAL_TRACE ((volatile struct dual_trace *)DUAL_TRACE_ADDR)
#define DUAL_HW ((volatile struct dual_hw *)DUAL_HW_ADDR)
struct dual_service {
 uint32_t magic, layout, dispatch, itcm, itcm_size, dtcm, dtcm_size, mailbox;
};
/* Single M55 writer; odd seq means in progress, even seq publishes a snapshot. */
struct dual_status {
 uint32_t seq, magic, layout, build, stage, beat, ms, cycles;
 uint32_t hz, cpuid, vtor, control, primask, basepri, mpu, ccr;
 uint32_t stack, error, guard;
};
_Static_assert(sizeof(struct dual_status) <= 0x80, "heartbeat overlaps trace");
_Static_assert(sizeof(struct dual_trace) <= 0x80, "trace outside reserved range");
_Static_assert(sizeof(struct dual_hw) <= 0x40, "HAL snapshot too large");
#define DUAL_STATUS ((volatile struct dual_status *)DUAL_SHARED_ADDR)
#endif
