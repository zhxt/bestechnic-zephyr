/* SPDX-License-Identifier: Apache-2.0 */
#ifndef BES2700_DUAL_IMAGE_H
#define BES2700_DUAL_IMAGE_H
#include <stdint.h>
#include <stddef.h>
#include "bes2700_dual_boot.h"
static inline uint32_t dual_u32(const uint8_t *p)
{ return p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24; }
static inline int dual_range(uint32_t start, uint32_t size, uint32_t low, uint32_t high)
{ return size && start >= low && start < high && size <= high - start; }
static inline uint32_t dual_crc(const uint8_t *p, uint32_t size)
{
 uint32_t crc = ~0U;
 while (size--) { crc ^= *p++; for (unsigned i=0; i<8; i++) { crc=(crc>>1)^(0xedb88320U & (0U-(crc&1))); } }
 return ~crc;
}
/* No destination access occurs until this validates the WHOLE image. */
static inline int dual_image_check(const uint8_t *p, uint32_t size, uint32_t crc)
{
 if (size < 56 || size > 0x20000 || dual_crc(p,size) != crc) { return 1; }
 if (dual_u32(p) != 0xbe57ec1c || dual_u32(p+4) || dual_u32(p+8) || dual_u32(p+12) ||
     dual_u32(p+16) != 0x00010000 || dual_u32(p+20) != size) { return 2; }
 uint32_t offset=dual_u32(p+24), map=dual_u32(p+28), count=map/12;
 if (map%12 || count<2 || count>8 || offset != 32+map || offset>=size) { return 3; }
 int vector=0, entry_loaded=0; uint32_t entry=0;
 for (uint32_t i=0; i<count; i++) {
  const uint8_t *s=p+32+i*12; uint32_t dst=dual_u32(s), src=dual_u32(s+4), n=dual_u32(s+8);
  if ((dst|src|n)&3 || src<offset || src>=size || n>size-src || !n) { return 4; }
  if (!i) { if (dst != DUAL_TRAMPOLINE || n>0x100) { return 5; } }
  else if (!dual_range(dst,n,DUAL_ITCM,DUAL_ITCM_END) &&
           !dual_range(dst,n,DUAL_DTCM+16,DUAL_DTCM_END)) { return 5; }
  for (uint32_t j=0; j<i; j++) {
   const uint8_t *t=p+32+j*12; uint32_t a=dual_u32(t), b=dual_u32(t+4), len=dual_u32(t+8);
   if ((dst < a+len && a < dst+n) || (src < b+len && b < src+n)) { return 6; }
  }
  if (dst == DUAL_ITCM) {
   if (n<8) { return 7; }
   uint32_t sp=dual_u32(p+src); entry=dual_u32(p+src+4);
   if ((sp&7) || sp<=DUAL_DTCM || sp>DUAL_DTCM_END || !(entry&1)) { return 7; }
   vector=1;
  }
 }
 for (uint32_t i=1; i<count; i++) {
  const uint8_t *s=p+32+i*12;
  if (dual_range(entry&~1U,2,dual_u32(s),dual_u32(s)+dual_u32(s+8)) &&
      dual_range(entry&~1U,2,DUAL_ITCM,DUAL_ITCM_END)) { entry_loaded=1; }
 }
 return vector && entry_loaded ? 0 : 7;
}
#endif
