/* SPDX-License-Identifier: Apache-2.0 */
.section .rodata.bth_payload,"a",%progbits
.balign 4
.global bth_payload_start, bth_payload_end
bth_payload_start:
.incbin BTH_PAYLOAD_FILE
bth_payload_end:
