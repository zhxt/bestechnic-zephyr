/* SPDX-License-Identifier: Apache-2.0 */
#ifndef BES_BOOTSTRAP_ARBITRATION_H
#define BES_BOOTSTRAP_ARBITRATION_H
#include <bes2700yp_arbitration.h>
/* BTH-only state, never mapped as an M55-owned object. State writes and reads
 * below require the caller's short, saved/restored PRIMASK critical section. */
extern volatile struct bes_arbitration_snapshot bes_arbitration_state;
uint32_t bes_arbitration_busy(void);
int bes_arbitration_enter(uint32_t op, uint32_t phase);
void bes_arbitration_leave(int rc);
#endif
