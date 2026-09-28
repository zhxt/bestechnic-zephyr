/* SPDX-License-Identifier: Apache-2.0 */
#ifndef BES2700YP_RESOURCES_H
#define BES2700YP_RESOURCES_H
#include <stdint.h>

#define BES_RESOURCE_DISCOVER 9U
#define BES_RESOURCE_MAGIC 0x31534552U
#define BES_RESOURCE_ABI 1U
#define BES_RESOURCE_SNAPSHOT 1U
#define BES_RESOURCE_SYSTEM 1U
#define BES_RESOURCE_CAP_SYSTEM 1U
#define BES_RESOURCE_VALID_PHASE 1U
#define BES_RESOURCE_VALID_HW 2U
#define BES_RESOURCE_VALID_CLOCK 4U
#define BES_RESOURCE_RAM_START 0x20540000U
#define BES_RESOURCE_RAM_END 0x2055c000U
/* Wire statuses are independent of the caller's C library errno values. */
enum bes_resource_status {
	BES_RESOURCE_OK = 0,
	BES_RESOURCE_INVALID = -1,
	BES_RESOURCE_UNSUPPORTED = -2,
	BES_RESOURCE_CONTEXT = -3,
};
struct bes_resource_descriptor {
	uint32_t magic, abi, bytes, capabilities, dispatch, request_bytes, snapshot_bytes, reserved;
};
struct bes_resource_snapshot {
	uint32_t abi, bytes, valid, phase, clocks_24m;
	uint32_t core_vtor, reset_set, reset_clr, ram_sel0, ram_sel1, oclk, oreset, sysclk;
	uint32_t reserved[3];
};
struct bes_resource_io {
	uint32_t abi, bytes, resource, flags, reserved[4];
	struct bes_resource_snapshot snapshot;
};
_Static_assert(sizeof(struct bes_resource_descriptor) == 32, "resource descriptor ABI");
_Static_assert(sizeof(struct bes_resource_snapshot) == 64, "resource snapshot ABI");
_Static_assert(sizeof(struct bes_resource_io) == 96, "resource request ABI");

int bes_resource_buffer_valid(uint32_t address, uint32_t bytes);
int bes_resource_descriptor_address_valid(uint32_t address);
int bes_resource_descriptor_valid(const struct bes_resource_descriptor *descriptor);
/* Single early BTH initializer, before resource drivers. No logging or HAL writes. */
int bes_resource_connect(void);
/* Privileged BTH thread/early context; caller owns the whole request buffer.
 * On error the output is unusable. ISR and unprivileged callers are rejected. */
int bes_resource_read(struct bes_resource_io *io);
/* Application validation hook; caller serializes UART output. */
int bes_resource_probe(uint32_t phase);

#endif
