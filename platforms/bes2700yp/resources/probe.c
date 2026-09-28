/* SPDX-License-Identifier: Apache-2.0 */
#include <zephyr/init.h>
#include <cmsis_core.h>
#include <bes2700yp_resources.h>
#include "bth_contract.h"

_Static_assert(BES_RESOURCE_RAM_START == BTH_DATA_BASE && BES_RESOURCE_RAM_END == BTH_DATA_END,
               "resource buffer ownership");
static struct bes_resource_io early;
static int early_rc;

static int resources_init(void)
{
	early_rc = bes_resource_connect();
	if (!early_rc) { early_rc = bes_resource_read(&early); }
	return early_rc;
}
SYS_INIT(resources_init, PRE_KERNEL_1, 0);

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
	return rc;
}
