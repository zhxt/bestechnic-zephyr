/* SPDX-License-Identifier: Apache-2.0 */
#include <zephyr/kernel.h>
#include <cmsis_core.h>
#include <bes2700_dual_boot.h>
#include <bes2700_dual_trace.h>
#ifdef CONFIG_BES2700_M55_RESTART
#include <bes2700_lifecycle.h>
#include <bes2700_peer_health.h>
#endif
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
#if CONFIG_BES2700_M55_FAULT_CASE > 0
#if !defined(CONFIG_BES2700_M55_RESTART)
#error "M55 fault injection requires lifecycle support"
#endif
static void inject_fault(void)
{
#ifdef CONFIG_BES2700_M55_RECOVERY
 /* Test selection is separate from health policy. Validate the control block
  * before suppressing injection in the one permitted replacement session. */
 if (BES_LIFECYCLE_CTL->magic==BES_LIFECYCLE_MAGIC &&
     BES_LIFECYCLE_CTL->layout==BES_LIFECYCLE_LAYOUT &&
     BES_LIFECYCLE_CTL->guard==BES_LIFECYCLE_GUARD &&
     BES_LIFECYCLE_CTL->session==2) { return; }
#endif
 __disable_irq();
 dual_trace_record(BES_PEER_INJECTION_STAGE,CONFIG_BES2700_M55_FAULT_CASE);
 for (;;) { __NOP(); }
}
#endif
int main(void)
{
 dual_trace_record(4, 0);
 dual_shared.magic = 0; dual_shared.seq = 0; dual_shared.beat = 0;
 dual_shared.layout = DUAL_LAYOUT; dual_shared.build = CONFIG_DUAL_M55_BUILD;
 __DMB(); dual_shared.magic = DUAL_MAGIC;
#if CONFIG_BES2700_M55_FAULT_CASE == 1
 inject_fault();
#endif
 int64_t deadline = k_uptime_get();
 for (;;) {
#ifdef CONFIG_BES2700_M55_RESTART
  if (bes2700_lifecycle_peer_poll()) {
   publish(255,10,0,k_uptime_get_32());return 0;
  }
#endif
#if CONFIG_BES2700_M55_FAULT_CASE == 2
  if (dual_shared.beat >= BES_PEER_INJECTION_BEATS) { inject_fault(); }
#endif
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
