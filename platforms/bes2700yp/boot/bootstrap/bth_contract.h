/* SPDX-License-Identifier: Apache-2.0 */
#ifndef BES2700_BTH_CONTRACT_H
#define BES2700_BTH_CONTRACT_H
#define BTH_CODE_BASE 0x00510000
#define BTH_CODE_SIZE 0x00030000
#define BTH_CODE_DATA_BASE 0x20510000
#define BTH_DATA_BASE 0x20540000
#define BTH_DATA_END 0x2055c000
#define BTH_DIAG_BASE 0x2055c000
#define BTH_UART_BASE 0x4000b000
/* SDK logical TIMER1 is physical BTH_TIMER0, not physical BTH_TIMER1. */
#define BTH_TIMER_BASE 0x40002000
#define BTH_UCACHE_BASE 0x07ffa000
#define BTH_CPU_HZ 24000000
#define BTH_TIMER_HZ 6000000
#define BTH_LAYOUT 0x00050001
#define BTH_MAGIC 0x35485442
#define BTH_RESET_MAGIC 0x52535435
#define BTH_GUARD 0xc35aa53c
#ifndef _ASMLANGUAGE
#ifndef __ASSEMBLER__
#include <stdint.h>
#include <stddef.h>
/* Exactly 64 bytes, little-endian, followed by size bytes of code/LMA data. */
struct bth_image {
	uint32_t magic, version, layout, build, size, crc;
	uint32_t vector, sp, entry, cpu_hz, timer_hz, reserved[5];
};
struct bth_diag {
	uint32_t magic, build, reset, cpu_hz, timer_hz, uart_hz, error, layout;
	uint32_t guards[16];
};
#define BTH_DIAG ((volatile struct bth_diag *)BTH_DIAG_BASE)
#define BTH_REG(addr) (*(volatile uint32_t *)(uintptr_t)(addr))
/* T1 changes placement only; the CRC instructions and polynomial stay the same. */
#ifdef BES_BTH_BOOT_CRC_RAM
static __attribute__((section(".boot_text_sram.bth_crc32"), noinline, unused))
#else
static inline
#endif
uint32_t bth_crc32(const uint8_t *p, uint32_t len)
{
	uint32_t crc = 0xffffffff;
	while (len--) {
		crc ^= *p++;
		for (unsigned i = 0; i < 8; i++) {
			crc = (crc >> 1) ^ (0xedb88320U & (0U - (crc & 1)));
		}
	}
	return ~crc;
}
/* No allocator, global writable state, interrupts, DMA or vendor trace. */
static inline void bth_putc(char ch)
{
	uint32_t budget = 1000000;
	while ((BTH_REG(BTH_UART_BASE + 0x18) & (1U << 5)) && --budget) {}
	if (!budget) {
		BTH_DIAG->error = 90;
		for (;;) { __asm__ volatile ("nop"); }
	}
	BTH_REG(BTH_UART_BASE) = (uint8_t)ch;
}
static inline void bth_puts(const char *s)
{
	while (*s) { bth_putc(*s++); }
}
static inline void bth_hex(uint32_t value)
{
	bth_puts("0x");
	for (int shift = 28; shift >= 0; shift -= 4) {
		bth_putc("0123456789abcdef"[(value >> shift) & 15]);
	}
}
static inline void bth_dec(uint32_t value)
{
	char digits[10];
	unsigned n = 0;
	do { digits[n++] = '0' + value % 10; value /= 10; } while (value);
	while (n) { bth_putc(digits[--n]); }
}
#if defined(CONFIG_BTH_LOG_PREFIX) || defined(BES_BTH_LOG_PREFIX)
static inline void bth_log_begin(char level, const char *module, const char *context);
static inline void bth_log_end(void);
#else
#define bth_log_begin(level, module, context) ((void)0)
#define bth_log_end() ((void)0)
#endif
static inline void bth_end(void) { bth_puts(" !\r\n"); bth_log_end(); }
static inline void bth_stage(const char *s)
{
	bth_log_begin(s[0]=='f'?'E':'I', s[0]=='f'?"FAULT":"BOOT", s[0]=='f'?"FAULT":s[0]=='m'?"MAIN":"EARLY");
	bth_puts("zephyr_bth stage="); bth_puts(s); bth_end();
}
static inline void bth_field(const char *s, uint32_t v)
{
	bth_puts(s); bth_hex(v);
}
static inline void bth_result(unsigned pass, unsigned samples, unsigned rc)
{
	bth_log_begin(pass?'I':'E', "FAULT", "FAULT");
	bth_puts("zephyr_bth result pass="); bth_dec(pass);
	bth_puts(" samples="); bth_dec(samples);
	bth_puts(" rc="); bth_dec(rc); bth_end();
}
static inline uint32_t bth_ticks(void)
{
	/* Same down-counter sampling rule as SDK CLOCK_SYNC_WORKAROUND,
	 * bounded so a stopped/broken peripheral cannot masquerade as progress. */
	for (unsigned n = 0; n < 10000; n++) {
		uint32_t a = BTH_REG(BTH_TIMER_BASE + 4);
		uint32_t b = BTH_REG(BTH_TIMER_BASE + 4);
		if (a >= b && a - b <= 20) { return 0U - b; }
	}
	BTH_DIAG->error = 91;
	return 0;
}
static inline void bth_dec64(uint64_t value)
{
 char digits[20]; unsigned n=0;
 do { digits[n++]='0'+value%10; value/=10; } while(value);
 while(n) { bth_putc(digits[--n]); }
}
/* Prefix disabled in all historical samples. */
#if defined(CONFIG_BTH_LOG_PREFIX) || defined(BES_BTH_LOG_PREFIX)
#include "bth_log_clock.h"
#define BTH_LOG ((volatile struct bth_log_clock *)BTH_LOG_ADDR)
static inline void bth_log_reset(void) { BTH_LOG->magic=0; BTH_LOG->record=0; }
static inline void bth_log_start(void) { bth_clock_init(BTH_LOG,bth_ticks()); __DMB(); }
static inline int bth_log_time(uint64_t *ticks)
{
 uint32_t key=__get_PRIMASK(); __disable_irq();
 if (BTH_LOG->magic!=BTH_LOG_MAGIC || BTH_LOG->busy) { __set_PRIMASK(key); return 0; }
 BTH_LOG->busy=1; __DMB();
 uint32_t raw=bth_ticks();
 *ticks=bth_clock_add(BTH_LOG,raw);
 __DMB(); BTH_LOG->busy=0; __set_PRIMASK(key);
 return BTH_DIAG->error!=91;
}
static inline void bth_log_poll(void) { uint64_t ticks; (void)bth_log_time(&ticks); }
static inline void bth_log_begin(char level, const char *module, const char *context)
{
 uint64_t ticks;
 int valid=bth_log_time(&ticks);
 /* Fatal may interrupt a partially emitted record: make truncation visible. */
 if (BTH_LOG->record) { bth_puts("\r\n"); }
 BTH_LOG->record=1;
 if(valid) { bth_dec64(ticks/6000U); } else { bth_puts("NA"); }
 bth_putc('/'); bth_putc(level); bth_puts("/BTH/"); bth_puts(module);
 bth_putc('/'); bth_puts(context); bth_puts(" | ");
}
static inline void bth_log_end(void) { BTH_LOG->record=0; }
#else
#define bth_log_reset() ((void)0)
#define bth_log_start() ((void)0)
#define bth_log_poll() ((void)0)
#endif
static inline int bth_guards_ok(void)
{
	if (BTH_DIAG->magic != BTH_MAGIC || BTH_DIAG->layout != BTH_LAYOUT) { return 0; }
	for (unsigned i = 0; i < 16; i++) {
		if (BTH_DIAG->guards[i] != (BTH_GUARD ^ i)) { return 0; }
	}
	return 1;
}
#endif
#endif
#endif
