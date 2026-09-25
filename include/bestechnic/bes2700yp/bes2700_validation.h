/* SPDX-License-Identifier: Apache-2.0 */
#ifndef BES2700_VALIDATION_H
#define BES2700_VALIDATION_H

#include <stdint.h>

#define BES_KV_ADDR 0x2015e100u
#define BES_KV_MAGIC 0x5a4d3535u
#define BES_KV_VERSION 3u
#define BES_KV_STAGE_RUNNING 2u
#define BES_KV_FIELDS(X) \
	X(build_id) X(stage) X(publish_count) X(uptime_ms) \
	X(configured_hz) X(raw_cycles) \
	X(fast_count) X(fast_last_ms) X(fast_max_gap_ms) \
	X(slow_count) X(slow_last_ms) X(slow_max_gap_ms) \
	X(tx) X(rx) X(ack) X(queue_full) X(seq_errors) X(ack_timeouts)

/* Little-endian fixed-width ABI; seq is odd while M55 publishes a snapshot. */
struct bes2700_validation {
	uint32_t magic;
	uint32_t version;
	uint32_t size;
	uint32_t seq;
#define BES_KV_MEMBER(name) uint32_t name;
	BES_KV_FIELDS(BES_KV_MEMBER)
#undef BES_KV_MEMBER
};

#if defined(__cplusplus)
static_assert(sizeof(struct bes2700_validation) == 88, "BES validation ABI");
#else
_Static_assert(sizeof(struct bes2700_validation) == 88, "BES validation ABI");
#endif
#endif
