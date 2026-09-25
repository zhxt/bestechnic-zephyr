/* SPDX-License-Identifier: Apache-2.0 */
#include "arch.h"
#include <bestechnic/bes2700yp/hw.h>
#include "image_check.h"
#include "boot_profile.h"
#ifdef BES_BTH_BOOT_COPY_RAM
void bth_copy_bytes(const uint8_t *source, uint32_t length);
#endif
extern const uint8_t bth_payload_start[], bth_payload_end[];
static volatile uint32_t adapter_data_probe = 0x5a1234a5;
static volatile uint32_t adapter_bss_probe;
extern void bth_enter_zephyr(uint32_t vector, uint32_t sp, uint32_t entry)
	__attribute__((noreturn));
static void fail(unsigned rc) __attribute__((noreturn));
static void fail(unsigned rc)
{
	BTH_DIAG->error = rc;
	bootprof_dump();
	bth_result(0, 0, rc);
	__disable_irq();
	for (;;) { __NOP(); }
}
void bth_boot_adapter_main(void) __attribute__((noreturn));
void bth_boot_adapter_main(void)
{
	const struct bth_image *h = (const void *)bth_payload_start;
	bth_log_reset();
	bootprof_reset();
	BTH_DIAG->magic = BTH_MAGIC;
	BTH_DIAG->build = h->build;
	BTH_DIAG->reset = 0;
	BTH_DIAG->error = 0;
	BTH_DIAG->layout = BTH_LAYOUT;
	for (unsigned i = 0; i < 16; i++) { BTH_DIAG->guards[i] = BTH_GUARD ^ i; }
	if (bes2700yp_uart_open()) {
		BTH_DIAG->error = 1;
		for (;;) { __NOP(); }
	}
#ifdef BES_BTH_DUAL_BOOT
	bth_puts("\r\n");
	bth_log_begin('I', "BOOT", "EARLY");
	bth_puts("zephyr_bth begin version=1 test=8 build=");
#elif defined(BES_BTH_KERNEL_VALIDATION)
	bth_puts("\r\nzephyr_bth begin version=1 test=6 build=");
#else
	bth_puts("\r\nzephyr_bth begin version=1 test=5 build=");
#endif
	bth_hex(h->build); bth_end();
	/* BootInit has run on BTH, data/bss are ready, but no C runtime/RTOS entered. */
	bth_stage("adapter_ready");
	if (adapter_data_probe != 0x5a1234a5 || adapter_bss_probe) { fail(7); }
	bth_log_begin('I', "BOOT", "EARLY");
	bth_field("zephyr_bth adapter cpuid=", SCB->CPUID);
	bth_field(" ipsr=", __get_IPSR()); bth_field(" control=", __get_CONTROL()); bth_end();
	if (__get_IPSR() || __get_CONTROL()) { fail(2); }
	if (bes2700yp_pmu_open()) { fail(3); }
	bes2700yp_watchdogs_stop();
	if (bes2700yp_bth_clock_24m() ||
	    bes2700yp_crystal_hz() != BTH_CPU_HZ) { fail(4); }
	BTH_DIAG->cpu_hz = bes2700yp_crystal_hz();
	BTH_DIAG->uart_hz = bes2700yp_crystal_hz();
	BTH_DIAG->timer_hz = bes2700yp_fast_timer_hz();
	if (BTH_DIAG->timer_hz != BTH_TIMER_HZ) { fail(5); }
	bes2700yp_timer_open();
	if ((BTH_REG(BTH_TIMER_BASE + 8) & 0x82) != 0x82) { fail(9); }
	bootprof_init(h->size,h->crc);
	bootprof_mark(0,0);
	bth_log_start();
	bootprof_mark(1,0);
	int rc = bth_image_check(h, bth_payload_end - bth_payload_start);
	if (rc) { fail(10 + rc); }
	bootprof_mark(2,h->crc);
	/* BES Ucache is outside the architectural Cortex-M cache interface. */
	__disable_irq();
	bes2700yp_dcache_disable();
	bootprof_mark(3,0);
	bes2700yp_icache_disable();
	bootprof_mark(4,0);
	MPU->CTRL = 0;
	__DSB(); __ISB();
	if ((BTH_REG(BTH_UCACHE_BASE) & 1) || MPU->CTRL) { fail(8); }
	bootprof_mark(5,0);
	const uint8_t *src = (const uint8_t *)(h + 1);
#ifdef BES_BTH_BOOT_COPY_RAM
	bth_copy_bytes(src, h->size);
#else
	volatile uint8_t *dst = (volatile void *)BTH_CODE_DATA_BASE;
	for (uint32_t i = 0; i < h->size; i++) { dst[i] = src[i]; }
#endif
	__DSB(); __ISB();
#ifdef BES_BTH_BOOT_PROFILE
	bootprof_mark(6,0);
	uint32_t data_crc=bth_crc32((const uint8_t *)BTH_CODE_DATA_BASE,h->size);
	bootprof_mark(7,data_crc);
	if(data_crc!=h->crc) { fail(19); }
	uint32_t exec_crc=bth_crc32((const uint8_t *)BTH_CODE_BASE,h->size);
	bootprof_mark(8,exec_crc);
	if(exec_crc!=h->crc || !bth_guards_ok()) { fail(19); }
	bootprof_mark(9,1);
	bootprof_mark(10,0); /* Back-to-back empty probes estimate instrumentation cost. */
	bootprof_mark(11,0);
#else
	if (bth_crc32((const uint8_t *)BTH_CODE_DATA_BASE, h->size) != h->crc ||
	    bth_crc32((const uint8_t *)BTH_CODE_BASE, h->size) != h->crc ||
	    !bth_guards_ok()) { fail(19); }
#endif
	bth_log_begin('I', "BOOT", "EARLY");
	bth_field("zephyr_bth image layout=", h->layout);
	bth_puts(" verified=1"); bth_end();
	bootprof_dump();
	bth_log_begin('I', "BOOT", "EARLY");
	bth_field("zephyr_bth uart ibrd=", BTH_REG(BTH_UART_BASE + 0x24));
	bth_field(" fbrd=", BTH_REG(BTH_UART_BASE + 0x28)); bth_end();
	SysTick->CTRL = 0; SysTick->LOAD = 0; SysTick->VAL = 0;
	/* Read implemented NVIC bank count, not a fixed guessed IRQ count. */
	unsigned banks = (SCnSCB->ICTR & 15) + 1;
	for (unsigned i = 0; i < banks; i++) {
		NVIC->ICER[i] = 0xffffffff;
		NVIC->ICPR[i] = 0xffffffff;
	}
	SCB->ICSR = SCB_ICSR_PENDSTCLR_Msk | SCB_ICSR_PENDSVCLR_Msk;
	BTH_REG(BTH_UART_BASE + 0x38) = 0;
	BTH_REG(BTH_UART_BASE + 0x44) = 0x7ff;
	BTH_REG(BTH_UART_BASE + 0x48) = 0;
	bth_log_begin('I', "BOOT", "EARLY");
	bth_field("zephyr_bth state cache=", BTH_REG(BTH_UCACHE_BASE));
	bth_field(" mpu=", MPU->CTRL);
	bth_field(" systick=", SysTick->CTRL & 1); bth_end();
#ifdef BES_BTH_DUAL_BOOT
	extern void dual_service_init(void);
	dual_service_init();
#endif
	bth_stage("handoff");
	uint32_t budget = 1000000;
	while ((BTH_REG(BTH_UART_BASE + 0x18) & (1U << 3)) && --budget) {}
	if (!budget) { fail(6); }
	bth_enter_zephyr(h->vector, h->sp, h->entry);
}
