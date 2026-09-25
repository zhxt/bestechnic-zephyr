/* Copyright The Zephyr Project Contributors */
/* SPDX-License-Identifier: Apache-2.0 */
#ifndef BES2700_MBOX_H_
#define BES2700_MBOX_H_

#include <stdint.h>

struct device;

struct bes2700_mbox_stats {
	uint32_t rx;
	uint32_t requests;
	uint32_t kicks;
	uint32_t done;
	uint32_t queued;
	uint32_t spurious;
};

/* Diagnostic snapshot for the local test worker; never a wire ABI. */
void bes2700_mbox_get_stats(const struct device *dev, struct bes2700_mbox_stats *out);

#endif
