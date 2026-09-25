/* SPDX-License-Identifier: Apache-2.0 */
#include <zephyr/toolchain.h>
#include "bth_contract.h"
.syntax unified
.thumb
.section .text.soc_early_reset_hook,"ax",%progbits
.global soc_early_reset_hook
.type soc_early_reset_hook,%function
.thumb_func
soc_early_reset_hook:
	ldr r0, =BTH_DIAG_BASE
	ldr r1, =BTH_RESET_MAGIC
	str r1, [r0, #8]
	dsb sy
	bx lr
.size soc_early_reset_hook, .-soc_early_reset_hook
