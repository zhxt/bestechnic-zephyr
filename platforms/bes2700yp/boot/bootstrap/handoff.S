/* SPDX-License-Identifier: Apache-2.0 */
.syntax unified
.thumb
.section .text.bth_enter_zephyr,"ax",%progbits
.global bth_enter_zephyr
.type bth_enter_zephyr,%function
.thumb_func
/* r0 = VTOR, r1 = initial MSP, r2 = Thumb entry. Never uses the new C stack. */
bth_enter_zephyr:
	cpsid i
	ldr r3, =0xe000ed08
	str r0, [r3]
	movs r3, #0
	msr control, r3
	isb sy
	msr basepri, r3
	msr faultmask, r3
	msr msplim, r3
	msr psplim, r3
	msr psp, r3
	msr msp, r1
	dsb sy
	isb sy
	/* Zephyr reset runs with PRIMASK=1 and arch init unlocks it. */
	bx r2
.size bth_enter_zephyr, .-bth_enter_zephyr
