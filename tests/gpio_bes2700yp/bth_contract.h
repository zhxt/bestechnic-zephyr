/* SPDX-License-Identifier: Apache-2.0 */
#ifndef BES_GPIO_TEST_CONTRACT_H
#define BES_GPIO_TEST_CONTRACT_H
#include "shim.h"
struct test_systick { uint32_t LOAD, VAL; };
struct test_scb { uint32_t ICSR; };
struct test_diag { uint32_t build; };
extern struct test_systick *SysTick;
extern struct test_scb *SCB;
extern struct test_diag *BTH_DIAG;
#define SCB_ICSR_PENDSTSET_Msk BIT(26)
uint32_t bth_ticks(void);
void bth_puts(const char *value);
void bth_dec(uint32_t value);
void bth_field(const char *key, uint32_t value);
void bth_log_begin(char level, const char *component, const char *context);
void bth_end(void);
#endif
