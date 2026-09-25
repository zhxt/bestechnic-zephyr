/* Copyright The Zephyr Project Contributors */
/* SPDX-License-Identifier: Apache-2.0 */
#ifndef BES2700_MESSAGE_H_
#define BES2700_MESSAGE_H_

#include <stdint.h>
#include <stddef.h>

#define BI_BASE 0x2015c000U
#define BI_BYTES 0x2000U
#define BI_MAGIC 0x35514d42U
#define BI_VERSION 2U
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


#define Q_LAYOUT 0x00090001U
#define Q_META_MAGIC 0x35534d42U
#define Q_META_GUARD 0x91c75a35U
#define Q_FIELDS(F) \
 F(magic) F(version) F(layout) F(pair) F(build) F(session) F(phase) F(stage) \
 F(sent) F(acked) F(handled) F(rejected) F(full) F(depth) F(max_wait) \
 F(rx) F(requests) F(kicks) F(done) F(queued) F(spurious) F(stack) \
 F(elapsed) F(stop_ms) F(len0) F(len1) F(len2) F(len3) F(pauses)
struct q_state {
 uint32_t seq;
#define MEMBER(n) uint32_t n;
 Q_FIELDS(MEMBER)
#undef MEMBER
 uint32_t error, guard;
};
struct q_consumer { uint32_t completed, rejected, fault, observed, reserved[28]; };
enum { Q_READY=1, Q_RUNNING, Q_STOPPING, Q_DRAIN, Q_QUIET, Q_DONE, Q_FAILED=255 };
enum { Q_IDENTITY=1, Q_SEQUENCE, Q_TIMEOUT, Q_SEND, Q_GUARDS, Q_IRQ,
 Q_STACK, Q_PEER, Q_PHASE, Q_SNAPSHOT, Q_FRAME, Q_PATTERN, Q_COVERAGE };

/* Only 32-bit little-endian fields cross cores. No pointers or compiler enums. */
struct bi_frame {
	uint32_t magic, version, session, sequence, type, length, crc, reserved;
	uint8_t payload[BI_PAYLOAD];
};

/* One producer and one consumer. Their indices occupy separate 128-byte lines.
 * BTH initializes while M55 is parked. Runtime head/tail and state/consumer
 * each have one writer. Completed is published after validation, separately
 * from slot release. No old diagnostic area is used.
 */
struct bi_ring {
	uint32_t head, go, producer_pad[30];
	uint32_t tail, consumer_pad[31];
	struct bi_frame slots[BI_DEPTH];
	struct q_state state;
	struct q_consumer consumer;
	uint32_t guards[384];
};
struct bi_shared { struct bi_ring b2m, m2b; };
_Static_assert(sizeof(struct bi_frame)==128,"frame ABI");
_Static_assert(sizeof(struct q_state)==128,"state ABI");
_Static_assert(sizeof(struct q_consumer)==128,"consumer ABI");
_Static_assert(sizeof(struct bi_ring)==4096,"ring ABI");
_Static_assert(offsetof(struct bi_ring,state)==0x900,"state offset");
_Static_assert(offsetof(struct bi_ring,consumer)==0x980,"consumer offset");
_Static_assert(sizeof(struct bi_shared)==BI_BYTES,"shared ABI");

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
	for (uint32_t i = 0; i < 384; i++) { q->guards[i] = BI_GUARD; }
	BI_BARRIER();
}

static inline int bi_guards_ok(volatile const struct bi_ring *q)
{
	for (uint32_t i = 0; i < 30; i++) { if (q->producer_pad[i] != BI_GUARD) { return 0; } }
	for (uint32_t i = 0; i < 31; i++) { if (q->consumer_pad[i] != BI_GUARD) { return 0; } }
	for (uint32_t i = 0; i < 384; i++) { if (q->guards[i] != BI_GUARD) { return 0; } }
	return 1;
}

#endif
