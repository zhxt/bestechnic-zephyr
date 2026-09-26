/* SPDX-License-Identifier: Apache-2.0 */
#ifndef BES2700_RESET_TIMER_H
#define BES2700_RESET_TIMER_H
#include "bes2700_lifecycle.h"
#define BES_RESET_RAM __attribute__((section(".boot_text_sram.reset_timer"), noinline, noclone))
int bes_reset_timer_read(struct bes_reset_diag *diag, uint32_t *value);
#endif
