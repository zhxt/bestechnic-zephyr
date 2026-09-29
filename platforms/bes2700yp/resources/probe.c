/* SPDX-License-Identifier: Apache-2.0 */
#include <zephyr/init.h>
#include <cmsis_core.h>
#include <bes2700yp_resources.h>
#include <bes2700yp_uart_resources.h>
#include "bth_contract.h"

_Static_assert(BES_RESOURCE_RAM_START == BTH_DATA_BASE && BES_RESOURCE_RAM_END == BTH_DATA_END,
               "resource buffer ownership");
static struct bes_resource_io early;
static int early_rc;
static struct bes_uart_resource_io uart_early;
static int uart_early_rc;

static int resources_init(void)
{
	early_rc = bes_resource_connect();
	if (!early_rc) { early_rc = bes_resource_read(&early); }
	uart_early_rc = bes_uart_resource_connect();
	if (!uart_early_rc) { uart_early_rc = bes_uart_resource_read(&uart_early); }
	return early_rc ? early_rc : uart_early_rc;
}
SYS_INIT(resources_init, PRE_KERNEL_1, 0);

static int uart_probe(uint32_t phase)
{
	struct bes_uart_resource_io io;
	int rc = uart_early_rc;
	if (!phase) { io = uart_early; }
	else { io = (struct bes_uart_resource_io){0}; if (!rc) { rc = bes_uart_resource_read(&io); } }
	const struct bes_uart_resource_snapshot *s = &io.snapshot;
	if (!rc && (s->phase != phase || s->valid != 7U || s->source != 1U ||
	    s->source_hz != 24000000U || s->configured_hz != 24000000U || s->divider != 1U ||
	    s->clocks != 3U || s->reset_released != 3U || s->rx_mux != 4U || s->tx_mux != 4U ||
	    s->pull_up != 1U || s->pull_down)) { rc = -1; }
	bth_log_begin(rc ? 'E' : 'I', "RESOURCE", "MAIN");
	bth_puts("zephyr_uart_resource snapshot");
#define FIELD(n, value) bth_field(" " n "=", (uint32_t)(value))
	FIELD("version", BES_UART_RESOURCE_ABI); FIELD("build", BTH_DIAG->build);
	FIELD("expected", phase); FIELD("rc", rc);
	FIELD("abi", s->abi); FIELD("bytes", s->bytes); FIELD("phase", s->phase);
#define SNAP(n) FIELD(#n, s->n);
	BES_UART_RESOURCE_FIELDS(SNAP)
#undef SNAP
#undef FIELD
	bth_end();
	return rc;
}

int bes_resource_probe(uint32_t phase)
{
	struct bes_resource_io io;
	int rc = early_rc;
	if (!phase) { io = early; }
	else { io = (struct bes_resource_io){0}; if (!rc) { rc = bes_resource_read(&io); } }
	const struct bes_resource_snapshot *s = &io.snapshot;
	if (!rc && (s->phase != phase || s->valid != (phase ? 7U : 1U) ||
	    s->clocks_24m != (phase ? 1U : 0U))) { rc = -1; }
	bth_log_begin(rc ? 'E' : 'I', "RESOURCE", "MAIN");
	bth_puts("zephyr_resource snapshot");
#define FIELD(n, value) bth_field(" " n "=", (uint32_t)(value))
	FIELD("version", BES_RESOURCE_ABI); FIELD("build", BTH_DIAG->build);
	FIELD("expected", phase); FIELD("rc", rc);
#define SNAP(n) FIELD(#n, s->n)
	SNAP(abi); SNAP(bytes); SNAP(valid); SNAP(phase); SNAP(clocks_24m);
	SNAP(core_vtor); SNAP(reset_set); SNAP(reset_clr); SNAP(ram_sel0); SNAP(ram_sel1);
	SNAP(oclk); SNAP(oreset); SNAP(sysclk);
#undef SNAP
#undef FIELD
	bth_end();
	int uart_rc = uart_probe(phase);
	return rc ? rc : uart_rc;
}
