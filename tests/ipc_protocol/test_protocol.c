/* SPDX-License-Identifier: Apache-2.0 */
#include <assert.h>
#include <stdatomic.h>
#include <stdio.h>
#include <string.h>
#define BI_BARRIER() atomic_thread_fence(memory_order_seq_cst)
#include "bes2700_ipc_protocol.h"

_Static_assert(sizeof(struct bi_ring) == 4096, "ring ABI");
_Static_assert(sizeof(struct bi_frame) == 128, "frame ABI");
_Static_assert(offsetof(struct bi_ring, tail) == 128, "separate index lines");
_Static_assert(offsetof(struct bi_ring, slots) == 256, "slot alignment");

int main(void)
{
	struct bi_ring q;
	struct bi_frame f, r;
	memset(&q, 0xa5, sizeof(q));
	bi_init(&q);
	assert(bi_guards_ok(&q));
	assert(bi_pop(&q, &r) == BI_EMPTY);
	for (uint32_t n = 0; n <= BI_PAYLOAD; n++) {
		bi_make(&f, 7, n + 1, BI_DATA, n, 0);
		assert(bi_validate(&f, 7, n + 1) == BI_OK);
		assert(bi_pattern_ok(&f, 0));
		assert(bi_validate(&f, 8, n + 1) == BI_SESSION);
		assert(bi_validate(&f, 7, n + 2) == BI_SEQ);
		/* Corrupt every byte, including headers, CRC and unused padding. */
		for (uint32_t i = 0; i < sizeof(f); i++) {
			r = f; ((uint8_t *)&r)[i] ^= 0x80;
			assert(bi_validate(&r, 7, n + 1) != BI_OK);
		}
		f.length = 97; f.crc = bi_crc(&f);
		assert(bi_validate(&f, 7, n + 1) == BI_HEADER);
		assert(!bi_pattern_ok(&f, 0));
	}
	/* Full is bounded and does not change the head or overwrite an old slot. */
	for (uint32_t i = 0; i < BI_DEPTH; i++) {
		bi_make(&f, 1, i, BI_DATA, 96, 0);
		assert(bi_push(&q, &f) == BI_OK);
	}
	struct bi_ring saved = q;
	assert(bi_push(&q, &f) == BI_FULL);
	assert(memcmp(&q, &saved, sizeof(q)) == 0);
	for (uint32_t i = 0; i < BI_DEPTH; i++) {
		assert(bi_pop(&q, &r) == BI_OK);
		assert(bi_validate(&r, 1, i) == BI_OK);
	}
	assert(bi_pop(&q, &r) == BI_EMPTY);
	q.head = 99; q.tail = 0;
	assert(bi_pop(&q, &r) == BI_INDEX && bi_push(&q, &f) == BI_INDEX);
	bi_init(&q);
	q.head = q.tail = UINT32_MAX - 8U;
	/* Model a bursty producer/consumer, crossing uint32 wrap and 100k frames. */
	uint32_t put = 1, get = 1, rng = 1;
	while (get <= 100000U) {
		rng = rng * 1664525U + 1013904223U;
		for (uint32_t j = 0; j < (rng & 31U) && put <= 100000U; j++) {
			bi_make(&f, 3, put, BI_DATA, put % 97U, 1);
			enum bi_rc rc = bi_push(&q, &f);
			if (rc == BI_FULL) { break; }
			assert(rc == BI_OK); put++;
		}
		for (uint32_t j = 0; j < ((rng >> 8) & 31U); j++) {
			enum bi_rc rc = bi_pop(&q, &r);
			if (rc == BI_EMPTY) { break; }
			assert(rc == BI_OK && bi_validate(&r, 3, get) == BI_OK);
			assert(bi_pattern_ok(&r, 1)); get++;
		}
	}
	assert(put == 100001 && q.head == q.tail && bi_guards_ok(&q));
	q.guards[447] ^= 1; assert(!bi_guards_ok(&q));
	bi_init(&q); q.consumer_pad[0] ^= 1; assert(!bi_guards_ok(&q));
	bi_init(&q); q.producer_pad[29] ^= 1; assert(!bi_guards_ok(&q));
	puts("PASS: ABI, all 97 lengths, 12416 corruptions, full, wrap, 100000 frames, guards");
	return 0;
}
