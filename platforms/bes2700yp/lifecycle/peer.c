/* SPDX-License-Identifier: Apache-2.0 */
#include <zephyr/kernel.h>
#include <cmsis_core.h>
#include <bes2700_lifecycle.h>

/* Called by the last shared-memory publisher, after the worker stops. */
int bes2700_lifecycle_peer_poll(void)
{
	if (BES_LIFECYCLE_CTL->magic != BES_LIFECYCLE_MAGIC ||
	    BES_LIFECYCLE_CTL->layout != BES_LIFECYCLE_LAYOUT ||
	    !BES_LIFECYCLE_CTL->session || BES_LIFECYCLE_CTL->guard != BES_LIFECYCLE_GUARD) {
		return -1;
	}
#if CONFIG_BES2700_M55_FAULT_CASE == 4
	/* Deliberately refuse QUIESCE while the independent heartbeat continues. */
	if (BES_LIFECYCLE_CTL->session == 1) { return 0; }
#endif
	if (q_idle() && BES_LIFECYCLE_CTL->quiesce == BES_LIFECYCLE_CTL->session) {
		BES_LIFECYCLE_CTL->peer_session = BES_LIFECYCLE_CTL->session;
		BES_LIFECYCLE_CTL->peer_guard = BES_LIFECYCLE_GUARD;
		__DMB();
		BES_LIFECYCLE_CTL->idle = BES_LIFECYCLE_CTL->session;
		__DSB();
		k_sleep(K_FOREVER);
	}
	return 0;
}
