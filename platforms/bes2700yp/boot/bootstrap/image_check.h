/* SPDX-License-Identifier: Apache-2.0 */
#include "bth_contract.h"
static inline int bth_image_check(const struct bth_image *h, size_t available)
{
	if (available < sizeof(*h)) { return 1; }
	if (h->magic != BTH_MAGIC || h->version != 1 || h->layout != BTH_LAYOUT) { return 2; }
	if (h->size < 8 || h->size > BTH_CODE_SIZE || h->size != available - sizeof(*h)) { return 3; }
	if (h->vector != BTH_CODE_BASE || (h->sp & 7) ||
	    h->sp <= BTH_DATA_BASE || h->sp > BTH_DATA_END ||
	    !(h->entry & 1) || (h->entry & ~1U) < BTH_CODE_BASE ||
	    (h->entry & ~1U) - BTH_CODE_BASE >= h->size) { return 4; }
	if (h->cpu_hz != BTH_CPU_HZ || h->timer_hz != BTH_TIMER_HZ) { return 5; }
	for (unsigned i = 0; i < 5; i++) { if (h->reserved[i]) { return 6; } }
	const uint8_t *data = (const uint8_t *)(h + 1);
	const uint32_t *vectors = (const uint32_t *)data;
	if (vectors[0] != h->sp || vectors[1] != h->entry) { return 7; }
	return bth_crc32(data, h->size) != h->crc ? 8 : 0;
}
