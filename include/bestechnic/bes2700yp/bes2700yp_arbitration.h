/* SPDX-License-Identifier: Apache-2.0 */
#ifndef BES2700YP_ARBITRATION_H
#define BES2700YP_ARBITRATION_H
#include <bes2700yp_resources.h>
/* Independent read-only diagnostics, discovered with operation 9, argument 3. */
#define BES_ARBITRATION_ABI 3U
#define BES_ARBITRATION_CAP 4U
#define BES_ARBITRATION_ID 3U
#define BES_ARBITRATION_BUSY (-12)
#define BES_ARBITRATION_CANCELLED (-13)
#define BES_ARBITRATION_CONTEXT (-14)
#define BES_ARBITRATION_FIELDS(X) \
 X(phase) X(owner) X(pending) X(entered) X(exited) X(busy) \
 X(stop_requests) X(stop_completed) X(last_op) X(last_rc) \
 X(probe_mask) X(probe_errors) X(probe_runs) X(reserved)
struct bes_arbitration_snapshot {
 uint32_t abi, bytes;
#define MEMBER(n) uint32_t n;
 BES_ARBITRATION_FIELDS(MEMBER)
#undef MEMBER
};
struct bes_arbitration_io {
 uint32_t abi, bytes, resource, flags, reserved[4];
 struct bes_arbitration_snapshot snapshot;
};
_Static_assert(sizeof(struct bes_arbitration_snapshot)==64, "arbitration snapshot ABI");
_Static_assert(sizeof(struct bes_arbitration_io)==96, "arbitration request ABI");
int bes_arbitration_descriptor_valid(const struct bes_resource_descriptor *d);
int bes_arbitration_connect(void);
int bes_arbitration_read(struct bes_arbitration_io *io);
#endif
