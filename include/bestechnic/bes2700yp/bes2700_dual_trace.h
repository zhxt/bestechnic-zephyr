/* SPDX-License-Identifier: Apache-2.0 */
#ifndef BES2700_DUAL_TRACE_H
#define BES2700_DUAL_TRACE_H
#include <cmsis_core.h>
#include <bes2700_dual_boot.h>
/* No initialized globals, scheduler or console dependency.
 * Single M55 writer; stage is the final store. BTH snapshots are diagnostic,
 * and are not used as the seqlock-protected heartbeat. */
static inline void dual_trace_record(uint32_t stage, uint32_t reason)
{
 volatile struct dual_trace *d = DUAL_TRACE;
 d->cpuid=SCB->CPUID; d->vtor=SCB->VTOR;
 d->msplim=__get_MSPLIM(); d->psplim=__get_PSPLIM();
 d->msp=__get_MSP(); d->psp=__get_PSP(); d->control=__get_CONTROL();
 d->primask=__get_PRIMASK(); d->basepri=__get_BASEPRI();
 d->ccr=SCB->CCR; d->mpu=MPU->CTRL; d->cpacr=SCB->CPACR;
 d->cfsr=SCB->CFSR; d->hfsr=SCB->HFSR; d->shcsr=SCB->SHCSR;
 d->mmfar=SCB->MMFAR; d->bfar=SCB->BFAR; d->icsr=SCB->ICSR; d->reason=reason;
 __DSB(); d->stage=stage; __DSB();
}
#endif
