/* SPDX-License-Identifier: Apache-2.0 */
/* Fixed BTH destination, byte semantics, non-overlapping source and destination.
 * The seven-instruction hot loop is byte-identical to the frozen T1 adapter.
 * r0=source, r1=length; length/range validation remains in bth_image_check.
 */
.syntax unified
.thumb
.section .boot_text_sram.bth_copy_bytes,"ax",%progbits
.balign 4
.global bth_copy_bytes
.type bth_copy_bytes,%function
.thumb_func
bth_copy_bytes:
    push {r5, lr}
    mov r2, r0
    mov r0, r1
    mov r1, r2
    movs r3, #0
    b.n bth_copy_loop_compare
.global bth_copy_loop_start
bth_copy_loop_start:
    add.w r2, r3, #0x20400000
    ldrb.w r5, [r1], #1
    add.w r2, r2, #0x110000
    adds r3, #1
    strb r5, [r2]
bth_copy_loop_compare:
    cmp r0, r3
    bne.n bth_copy_loop_start
.global bth_copy_loop_end
bth_copy_loop_end:
    pop {r5, pc}
.size bth_copy_bytes, .-bth_copy_bytes
