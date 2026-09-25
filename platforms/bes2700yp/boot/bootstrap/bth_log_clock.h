/* SPDX-License-Identifier: Apache-2.0 */
#ifndef BES2700_BTH_LOG_CLOCK_H
#define BES2700_BTH_LOG_CLOCK_H
#include <stdint.h>
/* BTH diagnostic page: diag [0,0x60), service [0x100,0x120),
 * hardware [0x140,0x174), logger [0x180,0x1a0). Not normal BSS. */
#define BTH_LOG_ADDR 0x2055c180U
#define BTH_LOG_MAGIC 0x4c470001U
struct bth_log_clock {
 uint32_t magic, busy, last, record;
 uint64_t ticks;
 uint32_t reserved[2];
};
_Static_assert(sizeof(struct bth_log_clock)==32, "log state ABI");
static inline void bth_clock_init(volatile struct bth_log_clock *s, uint32_t raw)
{
 s->magic=0; s->busy=0; s->last=raw; s->record=0;
 s->ticks=0; s->reserved[0]=0; s->reserved[1]=0;
 s->magic=BTH_LOG_MAGIC;
}
/* Caller serializes updates. Sample at least once per 32-bit hardware wrap. */
static inline uint64_t bth_clock_add(volatile struct bth_log_clock *s, uint32_t raw)
{
 s->ticks+=(uint32_t)(raw-s->last); s->last=raw;
 return s->ticks;
}
#endif
