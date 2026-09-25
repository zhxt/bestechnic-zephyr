/* Copyright The Zephyr Project Contributors */
/* SPDX-License-Identifier: Apache-2.0 */
#ifndef BES2700_IPC_PROTOCOL_H_
#define BES2700_IPC_PROTOCOL_H_

#include <stdint.h>
#include <stddef.h>

#define BI_BASE 0x2015c000U
#define BI_BYTES 0x2000U
#define BI_DIAG 0x2015e100U
#define BI_DIAG_BYTES 0x60U
#define BI_MAGIC 0x42495032U
#define BI_VERSION 1U
#define BI_GUARD 0x91c7a53eU
#define BI_DEPTH 16U
#define BI_PAYLOAD 96U
#define BI_HELLO 1U
#define BI_DATA 2U
#define BI_FINISH 3U
#define BI_QUIESCE 4U
#define BI_READY 10U
#define BI_RUNNING 11U
#define BI_COMPLETE 12U
#define BI_QUIESCED 13U
#define BI_FAILED 255U

/* Only 32-bit little-endian fields cross cores. No pointers or compiler enums. */
struct bi_frame {
	uint32_t magic, version, session, sequence, type, length, crc, reserved;
	uint8_t payload[BI_PAYLOAD];
};

/* One producer and one consumer. Their indices occupy separate 128-byte lines.
 * GO belongs to BTH, and is used only before the initial prefilled batch.
 * M55 initializes both queues before publishing READY. Neither core resets
 * indices until a complete M55 restart and a fresh READY handshake.
 */
struct bi_ring {
	uint32_t head, go, producer_pad[30];
	uint32_t tail, consumer_pad[31];
	struct bi_frame slots[BI_DEPTH];
	uint32_t guards[448];
};
struct bi_shared { struct bi_ring b2m, m2b; };

enum bi_rc { BI_OK, BI_EMPTY, BI_FULL, BI_INDEX, BI_HEADER, BI_CRC, BI_SESSION, BI_SEQ };

/* Firmware supplies CMSIS __DMB(); host tests supply a compiler fence. */
#ifndef BI_BARRIER
#define BI_BARRIER() __DMB()
#endif

static inline uint32_t bi_crc(const struct bi_frame *f)
{
	const uint8_t *p = (const uint8_t *)f;
	uint32_t crc = ~0U;
	for (uint32_t i = 0; i < sizeof(*f); i++) {
		if (i >= 24 && i < 28) { continue; }
		crc ^= p[i];
		for (unsigned int b = 0; b < 8; b++) {
			crc = (crc >> 1) ^ (0xedb88320U & (0U - (crc & 1U)));
		}
	}
	return ~crc;
}

static inline uint8_t bi_pattern(uint32_t seq, uint32_t offset, uint32_t reply)
{
	/* Walking bits, their inverse, alternating bytes and sequence-dependent data. */
	uint32_t x;
	switch ((seq / 16U) % 4U) {
	case 0: x = 1U << ((seq + offset) % 8U); break;
	case 1: x = ~(1U << ((seq + offset) % 8U)); break;
	case 2: x = (seq + offset) & 1U ? 0x55U : 0xaaU; break;
	default: x = seq * 37U + offset * 19U; break;
	}
	return (uint8_t)(x ^ (reply ? 0xa7U : 0U));
}

static inline void bi_make(struct bi_frame *f, uint32_t session, uint32_t sequence,
			   uint32_t type, uint32_t length, uint32_t reply)
{
	f->magic = BI_MAGIC; f->version = BI_VERSION;
	f->session = session; f->sequence = sequence;
	f->type = type; f->length = length; f->reserved = 0;
	for (uint32_t i = 0; i < BI_PAYLOAD; i++) {
		f->payload[i] = i < length ? bi_pattern(sequence, i, reply) : 0;
	}
	f->crc = bi_crc(f);
}

static inline enum bi_rc bi_validate(const struct bi_frame *f, uint32_t session,
				     uint32_t sequence)
{
	if (f->magic != BI_MAGIC || f->version != BI_VERSION || f->reserved != 0 ||
	    f->length > BI_PAYLOAD || f->type < BI_HELLO || f->type > BI_QUIESCE) {
		return BI_HEADER;
	}
	if (f->crc != bi_crc(f)) { return BI_CRC; }
	if (f->session != session) { return BI_SESSION; }
	if (f->sequence != sequence) { return BI_SEQ; }
	return BI_OK;
}

static inline int bi_pattern_ok(const struct bi_frame *f, uint32_t reply)
{
	if (f->length > BI_PAYLOAD) { return 0; }
	for (uint32_t i = 0; i < BI_PAYLOAD; i++) {
		uint8_t expected = i < f->length ? bi_pattern(f->sequence, i, reply) : 0;
		if (f->payload[i] != expected) { return 0; }
	}
	return 1;
}

static inline enum bi_rc bi_push(volatile struct bi_ring *q, const struct bi_frame *f)
{
	uint32_t h = q->head, t = q->tail;
	BI_BARRIER();
	if (h - t > BI_DEPTH) { return BI_INDEX; }
	if (h - t == BI_DEPTH) { return BI_FULL; }
	/* Volatile byte copies have defined aliasing and do not call memcpy on MMIO. */
	volatile uint8_t *d = (volatile uint8_t *)&q->slots[h % BI_DEPTH];
	const uint8_t *s = (const uint8_t *)f;
	for (uint32_t i = 0; i < sizeof(*f); i++) { d[i] = s[i]; }
	BI_BARRIER();
	q->head = h + 1U;
	BI_BARRIER();
	return BI_OK;
}

static inline enum bi_rc bi_pop(volatile struct bi_ring *q, struct bi_frame *f)
{
	uint32_t t = q->tail, h = q->head;
	BI_BARRIER();
	if (h - t > BI_DEPTH) { return BI_INDEX; }
	if (h == t) { return BI_EMPTY; }
	volatile const uint8_t *s = (volatile const uint8_t *)&q->slots[t % BI_DEPTH];
	uint8_t *d = (uint8_t *)f;
	for (uint32_t i = 0; i < sizeof(*f); i++) { d[i] = s[i]; }
	BI_BARRIER();
	q->tail = t + 1U;
	BI_BARRIER();
	return BI_OK;
}

static inline void bi_init(volatile struct bi_ring *q)
{
	q->head = 0; q->tail = 0; q->go = 0;
	for (uint32_t i = 0; i < 30; i++) { q->producer_pad[i] = BI_GUARD; }
	for (uint32_t i = 0; i < 31; i++) { q->consumer_pad[i] = BI_GUARD; }
	for (uint32_t i = 0; i < 448; i++) { q->guards[i] = BI_GUARD; }
	BI_BARRIER();
}

static inline int bi_guards_ok(volatile const struct bi_ring *q)
{
	for (uint32_t i = 0; i < 30; i++) { if (q->producer_pad[i] != BI_GUARD) { return 0; } }
	for (uint32_t i = 0; i < 31; i++) { if (q->consumer_pad[i] != BI_GUARD) { return 0; } }
	for (uint32_t i = 0; i < 448; i++) { if (q->guards[i] != BI_GUARD) { return 0; } }
	return 1;
}

#endif
