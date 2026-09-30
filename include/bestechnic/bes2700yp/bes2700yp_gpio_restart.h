/* SPDX-License-Identifier: Apache-2.0 */
#ifndef BES2700YP_GPIO_RESTART_H
#define BES2700YP_GPIO_RESTART_H
#include <stdint.h>

/* The caller serializes these diagnostic records with lifecycle logging. */
int bes_gpio_restart_checkpoint(uint32_t round, uint32_t stage);
int bes_gpio_restart_observe(uint32_t sample);
void bes_gpio_restart_end(void);
#endif
