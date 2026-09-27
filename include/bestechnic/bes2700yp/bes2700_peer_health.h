/* SPDX-License-Identifier: Apache-2.0 */
#ifndef BES2700_PEER_HEALTH_H
#define BES2700_PEER_HEALTH_H
#include <stdbool.h>
#include <stdint.h>

#define BES_PEER_READY_MS 5000U
#define BES_PEER_HEARTBEAT_MS 1000U
#define BES_PEER_POLL_MS 20U
#define BES_PEER_INJECTION_STAGE 6U
#define BES_PEER_INJECTION_BEATS 10U

enum bes_peer_state { BES_PEER_STARTING, BES_PEER_RUNNING, BES_PEER_FAULT };
enum bes_peer_fault {
 BES_PEER_OK, BES_PEER_READY_TIMEOUT, BES_PEER_HEARTBEAT_TIMEOUT,
 BES_PEER_INVALID,
};
/* BTH-owned state; independent of Zephyr, HAL and fault-injection selection. */
struct bes_peer_health {
 enum bes_peer_state state;
 enum bes_peer_fault fault;
 int64_t started, progress;
 uint32_t beat;
};
void bes_peer_health_init(struct bes_peer_health *health, int64_t now);
enum bes_peer_fault bes_peer_health_poll(struct bes_peer_health *health,
 int64_t now, bool readable, bool valid, uint32_t beat);

/* Each operation is synchronous and bounded. A failure stops the sequence.
 * No reload, shared-memory reinitialization or CPU release is possible here. */
struct bes_peer_isolation_ops {
 int (*stop_local)(void *context);
 int (*hold_reset)(void *context);
 int (*confirm_reset)(void *context);
 int (*clear_channel)(void *context);
};
struct bes_peer_isolation {
 uint32_t local_idle, reset_held, channel_clean, failed_step;
 int service_rc;
};
int bes_peer_isolate(const struct bes_peer_isolation_ops *ops, void *context,
 struct bes_peer_isolation *result);
/* One attempt per BTH boot, consumed even when an operation fails. The caller
 * must contain the peer again on failure; none of these operations retries. */
struct bes_peer_recovery_ops {
 int (*park)(void *context);
 int (*rebuild)(void *context);
 int (*load)(void *context);
 int (*release)(void *context);
 int (*run)(void *context);
};
struct bes_peer_recovery {
 uint32_t attempts, completed, failed_step;
 int operation_rc;
};
int bes_peer_recover(const struct bes_peer_recovery_ops *ops, void *context,
 const struct bes_peer_isolation *isolated, struct bes_peer_recovery *result);
#endif
