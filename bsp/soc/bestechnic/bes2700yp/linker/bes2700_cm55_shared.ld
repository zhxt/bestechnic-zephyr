/*
 * SPDX-License-Identifier: Apache-2.0
 */

GROUP_START(M55SHARED)

SECTION_PROLOGUE(.bes2700_m55_shared,(NOLOAD),)
{
	. = ALIGN(4);
	__bes2700_m55_shared_start = .;
	KEEP(*(.bes2700_m55_shared))
	KEEP(*(".bes2700_m55_shared.*"))
	. = ALIGN(4);
	__bes2700_m55_shared_end = .;
} GROUP_LINK_IN(M55SHARED)

GROUP_END(M55SHARED)

ASSERT(__bes2700_m55_shared_start == 0x2015e100, "heartbeat address changed")
ASSERT(__bes2700_m55_shared_end <= 0x2015e180, "heartbeat overlaps reset trace")
