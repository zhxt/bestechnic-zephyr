/* SPDX-License-Identifier: Apache-2.0 */
#ifndef BES2700YP_BOOTSTRAP_ARCH_H
#define BES2700YP_BOOTSTRAP_ARCH_H
/* Architectural operations only; device IRQs are owned by the HAL bootstrap. */
typedef enum {
	NonMaskableInt_IRQn = -14, HardFault_IRQn = -13,
	MemoryManagement_IRQn = -12, BusFault_IRQn = -11, UsageFault_IRQn = -10,
	SecureFault_IRQn = -9, SVCall_IRQn = -5, DebugMonitor_IRQn = -4,
	PendSV_IRQn = -2, SysTick_IRQn = -1,
} IRQn_Type;
#define __CM33_REV 0x0000U
#define __SAUREGION_PRESENT 0U
#define __MPU_PRESENT 1U
#define __VTOR_PRESENT 1U
#define __NVIC_PRIO_BITS 3U
#define __Vendor_SysTickConfig 0U
#define __FPU_PRESENT 1U
#define __DSP_PRESENT 1U
#include <core_cm33.h>
#endif
