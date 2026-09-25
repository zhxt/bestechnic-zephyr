/* Copyright The Zephyr Project Contributors */
/* SPDX-License-Identifier: Apache-2.0 */
#ifndef BES2700_DUAL_DOORBELL_H_
#define BES2700_DUAL_DOORBELL_H_

#include <stdint.h>

#define BES_DB_ADDR 0x2015e200U
#define BES_DB_MAGIC 0x44424c32U
#define BES_DB_VERSION 2U
#define BES_DB_ROUNDS CONFIG_DUAL_DB_ROUNDS
#define BES_DB_BURST 32U
#define BES_DB_READY 1U
#define BES_DB_INITIATOR 2U
#define BES_DB_RX_PAUSED 3U
#define BES_DB_BURST_READY 4U
#define BES_DB_PASS 5U
#define BES_DB_BTH_BURST 6U
#define BES_DB_FAIL 255U

#define BES_DB_FIELDS(F) \
	F(build) F(stage) F(uptime) F(progress) F(error) F(rx) F(requests) \
	F(kicks) F(done) F(queued) F(spurious) F(cpuid) F(ictr) F(ccr) F(mpu) F(hz) F(reserved0) F(reserved1)

/* Independent 88-byte IPC status; M55 owns it after the loader clears the region. */
struct bes2700_doorbell {
	uint32_t magic;
	uint32_t version;
	uint32_t size;
	uint32_t seq;
#define BES_DB_MEMBER(name) uint32_t name;
	BES_DB_FIELDS(BES_DB_MEMBER)
#undef BES_DB_MEMBER
};

#endif
