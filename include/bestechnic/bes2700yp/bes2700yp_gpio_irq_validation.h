/* SPDX-License-Identifier: Apache-2.0 */
#ifndef BES_GPIO_IRQ_VALIDATION_H
#define BES_GPIO_IRQ_VALIDATION_H
#include <stdint.h>
int bes_gpio_irq_validation_start(uint32_t stage);
int bes_gpio_irq_validation_poll(void);
int bes_gpio_irq_validation_done(void);
int bes_gpio_irq_validation_check(uint32_t checkpoint);
int bes_gpio_irq_validation_result(void);
void bes_gpio_irq_validation_end(void);
#endif
