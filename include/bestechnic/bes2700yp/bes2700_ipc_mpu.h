/* Copyright The Zephyr Project Contributors */
/* SPDX-License-Identifier: Apache-2.0 */
#ifndef BES2700_IPC_MPU_H_
#define BES2700_IPC_MPU_H_

/* Call with local interrupts locked; leave RNR unchanged. Require exactly one
 * covering region, Normal non-cacheable (MAIR 0x44), writable and XN.
 */
static inline int bi_mpu_nc(uint32_t base, uint32_t size)
{
	uint32_t saved = MPU->RNR, hits = 0, valid = 0;
	if ((MPU->CTRL & 1U) == 0) { return 0; }
	for (uint32_t i = 0; i < ((MPU->TYPE >> 8) & 0xffU); i++) {
		MPU->RNR = i;
		uint32_t b = MPU->RBAR, l = MPU->RLAR;
		if (!(l & 1U) || (b & ~31U) >= base + size || (l | 31U) < base) { continue; }
		hits++;
		uint32_t idx = (l >> 1) & 7U;
		uint32_t mair = idx < 4 ? MPU->MAIR0 : MPU->MAIR1;
		valid = (b & ~31U) <= base && (l | 31U) >= base + size - 1U &&
			((mair >> ((idx % 4) * 8)) & 255U) == 0x44U &&
			(b & 1U) != 0 && (b & 4U) == 0;
	}
	MPU->RNR = saved;
	return hits == 1 && valid;
}
#endif
