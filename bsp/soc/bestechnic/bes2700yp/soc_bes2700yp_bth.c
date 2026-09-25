/* SPDX-License-Identifier: Apache-2.0 */
#include <zephyr/kernel.h>
#include <cmsis_core.h>
#include "bth_contract.h"
void soc_early_init_hook(void)
{
	if (BTH_DIAG->reset != BTH_RESET_MAGIC || !bth_guards_ok()) {
		bth_result(0, 0, 20);
		for (;;) { __NOP(); }
	}
	bth_stage("reset");
	bth_stage("early");
}
void k_sys_fatal_error_handler(unsigned int reason, const struct arch_esf *esf)
{
	(void)esf;
#ifdef CONFIG_UART_BES2700
	/* A fault during V06 loopback must remain visible on the external TX pin. */
	BTH_REG(BTH_UART_BASE + 0x38) = 0;
	BTH_REG(BTH_UART_BASE + 0x30) &= ~(1U << 7);
#endif
	BTH_DIAG->error = 100 + reason;
	bth_stage("fatal");
	bth_log_begin('E', "FAULT", "FAULT");
	bth_field("zephyr_bth fault cfsr=", SCB->CFSR);
	bth_field(" hfsr=", SCB->HFSR); bth_end();
	bth_result(0, 0, 100 + reason);
	__disable_irq();
	for (;;) { __NOP(); }
}
