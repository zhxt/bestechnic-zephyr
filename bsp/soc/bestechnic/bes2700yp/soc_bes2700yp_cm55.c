/*
 * SPDX-License-Identifier: Apache-2.0
 */

#include <cmsis_core.h>
#ifdef CONFIG_BES2700_DUAL_DIAGNOSTICS
#include <bes2700_dual_trace.h>
#endif

void soc_early_init_hook(void)
{
	/*
	 * The first M55 Zephyr payload is released by the BES BTH firmware.
	 * Clocks, power domains and TCM accessibility must already be prepared
	 * by the BTH-side loader before this hook runs.
	 */
#ifdef CONFIG_BES2700_DUAL_DIAGNOSTICS
	dual_trace_record(3, 0);
#endif
	__DSB();
	__ISB();
}
