/* SPDX-License-Identifier: Apache-2.0 */
#include <zephyr/toolchain.h>
.syntax unified
.thumb
.section .text.soc_early_reset_hook,"ax",%progbits
.global soc_early_reset_hook
.type soc_early_reset_hook,%function
.thumb_func
soc_early_reset_hook:
 ldr r0, =0x2015e180
 ldr r1, =0xe000ed00
 ldr r2, [r1]
 str r2, [r0, #4]
 ldr r2, [r1, #8]
 str r2, [r0, #8]
 mrs r2, MSP
 str r2, [r0, #12]
 mrs r2, CONTROL
 str r2, [r0, #20]
 movs r2, #2
 dsb sy
 str r2, [r0]
 dsb sy
 bx lr
.size soc_early_reset_hook, .-soc_early_reset_hook
