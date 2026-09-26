/* SPDX-License-Identifier: Apache-2.0 */
#ifndef BES2700_LIFECYCLE_H
#define BES2700_LIFECYCLE_H
#include <stdint.h>
#define BES_LIFECYCLE_LAYOUT 0x000a0004U
#define BES_LIFECYCLE_MAGIC 0x31525342U
#define BES_LIFECYCLE_ADDR 0x2015e280U
#define BES_LIFECYCLE_GUARD 0xa135c79bU
#define BES_LIFECYCLE_REPARK 7U
#define BES_LIFECYCLE_RESET_STATUS 8U
#define BES_LIFECYCLE_ROUNDS 11U
#define BES_LIFECYCLE_TARGET 1000U
#define BES_LIFECYCLE_OBSERVE_SECONDS 600U
#define BES_LIFECYCLE_READY_MS 5000U
#define BES_LIFECYCLE_MESSAGE_MS 30000U
#define BES_LIFECYCLE_QUIESCE_MS 5000U
#define BES_LIFECYCLE_RESET_MS 10U
#define BES_RESET_DIAG_ADDR 0x2055c1a0U
#define BES_RESET_DIAG_VERSION 1U
#define BES_RESET_READ_ATTEMPTS 32U
#define BES_RESET_POLL_LIMIT 1024U
enum bes_reset_reason {
 BES_RESET_OK, BES_RESET_SAMPLE_FAILED, BES_RESET_TIMEOUT,
 BES_RESET_POLL_EXHAUSTED, BES_RESET_CLOCK_LATCHED, BES_RESET_TIMER_CONFIG,
};
#define BES_RESET_FIELDS(X) \
 X(version) X(op) X(reason) X(service_rc) X(polls) X(samples) X(attempts) \
 X(max_attempts) X(last_a) X(last_b) X(max_delta) X(elapsed) \
 X(reset_before) X(reset_after) X(timer_ctrl) X(diag_error) X(sampler) \
 X(raw_start) X(raw_end) X(primask)
/* Bootstrap publishes synchronously; BTH reads only after dispatch returns.
 * Dedicated space between logger [c180,c1a0) and profile [c200,c800). */
struct bes_reset_diag {
#define BES_RESET_MEMBER(n) uint32_t n;
 BES_RESET_FIELDS(BES_RESET_MEMBER)
#undef BES_RESET_MEMBER
};
_Static_assert(sizeof(struct bes_reset_diag)==80,"reset diagnostic ABI");
_Static_assert(BES_RESET_DIAG_ADDR+sizeof(struct bes_reset_diag)<=0x2055c200U,
               "reset diagnostics overlap profile");
#define BES_RESET_DIAG ((volatile struct bes_reset_diag *)BES_RESET_DIAG_ADDR)
#define BES_REPARK_DIAG_ADDR 0x2055c800U
#define BES_REPARK_DIAG_VERSION 1U
#define BES_REPARK_HW_FIELDS(X) \
 X(reason) X(reset_before) X(reset_after) \
 X(sel0_before) X(sel1_before) X(sel0_axi) X(sel1_axi) X(sel0_after) X(sel1_after) \
 X(phys0) X(phys1) X(phys2) X(expected0) X(expected1) X(expected2) \
 X(read0) X(read1) X(read2) X(restore_ok) X(write_mask)
#define BES_REPARK_FIELDS(X) \
 X(version) X(op) X(service_rc) X(phase_before) X(phase_after) BES_REPARK_HW_FIELDS(X)
struct bes_repark_diag {
#define BES_REPARK_MEMBER(n) uint32_t n;
 BES_REPARK_FIELDS(BES_REPARK_MEMBER)
#undef BES_REPARK_MEMBER
};
_Static_assert(sizeof(struct bes_repark_diag)==100,"repark diagnostic ABI");
#define BES_REPARK_DIAG ((volatile struct bes_repark_diag *)BES_REPARK_DIAG_ADDR)
/* BTH writes the first 64 bytes only while M55 is parked, except quiesce.
 * M55 publishes idle only after its worker and heartbeat stop shared access. */
struct bes2700_lifecycle_control {
 uint32_t magic, layout, session, quiesce, guard, reserved[11];
 uint32_t idle, peer_session, peer_guard, unused[13];
};
_Static_assert(sizeof(struct bes2700_lifecycle_control)==128,"R1 control ABI");
#define BES_LIFECYCLE_CTL ((volatile struct bes2700_lifecycle_control *)BES_LIFECYCLE_ADDR)
int bes2700_lifecycle_validate(void);
int bes2700_lifecycle_peer_poll(void);
int q_idle(void);
int q_wait_idle(int milliseconds);
#endif
