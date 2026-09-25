/* SPDX-License-Identifier: Apache-2.0 */
#include <zephyr/kernel.h>
#include <cmsis_core.h>
#include <bes2700_dual_boot.h>
#include <bes2700_dual_trace.h>
__attribute__((section(".bes2700_m55_shared"))) volatile struct dual_status dual_shared;
static volatile uint32_t initialized_probe = 0x5aa55aa5;
static volatile uint32_t zero_probe;
/* Keep the epoch fixed: relative sleeps accumulate work and tick rounding. */
#define HEARTBEAT_PERIOD_MS 100
#define HEARTBEAT_MAX_LATE_MS 20
static void publish(uint32_t stage, uint32_t error, size_t stack, uint32_t ms)
{
 dual_shared.seq++; __DMB();
 dual_shared.stage = stage; dual_shared.error = error;
 if (!error) { dual_shared.beat++; }
 dual_shared.ms = ms;
 dual_shared.cycles = k_cycle_get_32(); dual_shared.hz = CONFIG_SYS_CLOCK_HW_CYCLES_PER_SEC;
 dual_shared.cpuid = SCB->CPUID; dual_shared.vtor = SCB->VTOR;
 dual_shared.control = __get_CONTROL(); dual_shared.primask = __get_PRIMASK();
 dual_shared.basepri = __get_BASEPRI(); dual_shared.mpu = MPU->CTRL; dual_shared.ccr = SCB->CCR;
 dual_shared.stack = stack; dual_shared.guard = DUAL_GUARD;
 __DMB(); dual_shared.seq++; __DMB();
}
void k_sys_fatal_error_handler(unsigned int reason, const struct arch_esf *esf)
{
 if (esf) {
  DUAL_TRACE->pc=esf->basic.pc; DUAL_TRACE->lr=esf->basic.lr;
  DUAL_TRACE->xpsr=esf->basic.xpsr; DUAL_TRACE->esf_valid=1;
 }
 dual_trace_record(255, reason);
 dual_shared.seq |= 1U;
 dual_shared.stage = 255; dual_shared.error = 100 + reason;
 dual_shared.guard = DUAL_GUARD;
 __DMB(); dual_shared.seq++; __DSB();
 __disable_irq(); for (;;) { __NOP(); }
}
int main(void)
{
 dual_trace_record(4, 0);
 dual_shared.magic = 0; dual_shared.seq = 0; dual_shared.beat = 0;
 dual_shared.layout = DUAL_LAYOUT; dual_shared.build = CONFIG_DUAL_M55_BUILD;
 __DMB(); dual_shared.magic = DUAL_MAGIC;
 int64_t deadline = k_uptime_get();
 for (;;) {
  size_t free = 0;
  uint32_t error = initialized_probe != 0x5aa55aa5 || zero_probe ? 1 : 0;
  if (k_thread_stack_space_get(k_current_get(), &free) || free < 128) { error = 2; }
  if (MPU->CTRL || (SCB->CCR & ((1U << 16) | (1U << 17))) ||
      SCB->VTOR != DUAL_ITCM || __get_PRIMASK() || __get_BASEPRI() || __get_CONTROL() != 2) { error = 3; }
  int64_t now = k_uptime_get();
  /* Check after self-tests, immediately before publishing. Never catch up by
   * emitting several heartbeats after a stall. Existing failures keep priority. */
  if (!error && (now < deadline || now - deadline > HEARTBEAT_MAX_LATE_MS)) { error = 4; }
  publish(error ? 255 : 2, error, free, (uint32_t)now);
  if (error || DUAL_TRACE->stage!=5) { dual_trace_record(error ? 255 : 5, error); }
  if (error) { return 0; }
  deadline += HEARTBEAT_PERIOD_MS;
  k_sleep(K_TIMEOUT_ABS_MS(deadline));
 }
}
