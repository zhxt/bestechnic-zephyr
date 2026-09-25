/* SPDX-License-Identifier: Apache-2.0 */
#ifndef BES_BOOT_PROFILE_H
#define BES_BOOT_PROFILE_H
#include <stdint.h>
#define BP_ADDR 0x2055c200U
#define BP_END 0x2055c800U
#define BP_GUARD 0xb007cafeU
#define BP_MAGIC 0x42503031U
#define BP_POINTS 12U
#define BP_FIELDS(F) \
 F(id) F(fast0) F(slow) F(fast1) F(fast_end) F(error) F(fast_ctrl) F(fast_load) \
 F(periph) F(sysclk) F(sysdiv) F(cache) F(mpu) F(primask) F(basepri) \
 F(log_last) F(log_lo) F(log_hi) F(crc) F(demcr) F(dwt_ctrl) F(dwt_cycles) F(dwt_valid)
struct boot_profile_point {
#define WORD(n) uint32_t n;
 BP_FIELDS(WORD)
#undef WORD
};
struct boot_profile {
 uint32_t magic,count,error,bytes,crc,slow_hz,slow_nominal,slow_calibrated;
 struct boot_profile_point point[BP_POINTS];
};
_Static_assert(sizeof(struct boot_profile)<=BP_END-BP_ADDR-4,"profile overflow");
#ifdef BES_BTH_BOOT_PROFILE
void bootprof_reset(void);
void bootprof_init(uint32_t bytes,uint32_t crc);
void bootprof_mark(uint32_t id,uint32_t crc);
void bootprof_dump(void);
#else
#define bootprof_reset() ((void)0)
#define bootprof_init(bytes,crc) ((void)0)
#define bootprof_mark(id,crc) ((void)0)
#define bootprof_dump() ((void)0)
#endif
#endif
