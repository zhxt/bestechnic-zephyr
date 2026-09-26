/* SPDX-License-Identifier: Apache-2.0 */
#ifndef BES2700_DUAL_BOOT_H
#define BES2700_DUAL_BOOT_H
#include <stdint.h>
#if defined(CONFIG_BES2700_M55_RESTART) || defined(BES_BTH_M55_RESTART)
#include "bes2700_lifecycle.h"
#define DUAL_LAYOUT BES_LIFECYCLE_LAYOUT
#else
#define DUAL_LAYOUT 0x00080002U
#endif
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
_Static_assert(sizeof(struct dual_service) == 32, "service ABI size");
/* Service code uses FLASHX, not the 0x34000000 flash data/load alias. */
#define DUAL_SERVICE_FLASHX_START 0x14000000U
#define DUAL_SERVICE_FLASHX_END 0x14800000U
#define DUAL_SERVICE_SRAM_START 0x00500000U
#define DUAL_SERVICE_SRAM_END 0x00510000U
enum dual_service_error {
	DUAL_SERVICE_BAD_MAGIC = 1U << 0,
	DUAL_SERVICE_BAD_LAYOUT = 1U << 1,
	DUAL_SERVICE_BAD_THUMB = 1U << 2,
	DUAL_SERVICE_BAD_EXEC = 1U << 3,
	DUAL_SERVICE_BAD_ITCM = 1U << 4,
	DUAL_SERVICE_BAD_DTCM = 1U << 5,
	DUAL_SERVICE_BAD_MAILBOX = 1U << 6,
};
/* Shared by BTH applications and the final ELF audit's host-compiled check. */
uint32_t dual_service_validate(const volatile struct dual_service *service);
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
