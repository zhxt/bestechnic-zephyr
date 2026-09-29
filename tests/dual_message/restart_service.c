/* SPDX-License-Identifier: Apache-2.0 */
#define _GNU_SOURCE
#include <assert.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>
#include <bestechnic/bes2700yp/hw.h>
/* Architectural and timer shims only; include the actual bootstrap service. */
#define BES2700YP_BOOTSTRAP_ARCH_H
#define BES2700_BTH_CONTRACT_H
#define BES_RESET_HOST_TEST
#define __DSB() __asm__ volatile("" ::: "memory")
#define BTH_TIMER_HZ 6000000U
static struct { uint32_t error; } diag;
#define BTH_DIAG (&diag)
static uint32_t timer=0xf0000000U, reset_release, vector, irq_mask, timer_ctrl=0x82;
static unsigned powers, starts, stops, reads, delay_reads;
static int stuck, timer_stopped, bad_sample, late_bad_sample, reset_pending;
static unsigned timer_reads;
static int repark_error, prepare_error, fail_nested_stop;
static uint32_t ipsr, control;
static void (*interleave)(void);
static void (*stop_interleave)(void);
static uint32_t __get_IPSR(void) { return ipsr; }
static uint32_t __get_CONTROL(void) { return control; }
static uint32_t __get_PRIMASK(void) { return irq_mask; }
static void __disable_irq(void) { irq_mask=1; }
static void __set_PRIMASK(uint32_t mask) { irq_mask=mask; }
static uint32_t timer_value(void)
{
 assert(irq_mask==1);timer_reads++;
 if(timer_stopped || timer_reads%2) { return timer; }
 timer-=(bad_sample || (late_bad_sample && timer_reads>2))?21:2;
 uint32_t value=timer;timer-=598;return value;
}
static uint32_t reset_readback(void)
{
 reads++;
 if(reset_pending && !stuck && delay_reads && reads>=delay_reads) { reset_release=0; }
 return reset_release;
}
#define RESET_VALUE() timer_value()
#define RESET_READBACK() reset_readback()
#define RESET_TIMER_CTRL() timer_ctrl
#include "../../platforms/bes2700yp/boot/bootstrap/reset_timer.c"
int bes2700yp_clocks_are_24m(void) { return 0; }
int bes2700yp_m55_prepare(void) { powers++;return prepare_error; }
void bes2700yp_m55_park_word(uint32_t address,uint32_t value) { *(uint32_t *)(uintptr_t)address=value; }
void bes2700yp_m55_dtcm_enable(void) {}
void bes2700yp_m55_start(uint32_t address) {
 assert(!mprotect((void *)0x200c0000,0x1000,PROT_READ|PROT_WRITE));
 vector=address;reset_release=16;reset_pending=0;starts++;
 if(interleave) { interleave(); }
}
void bes2700yp_m55_stop(void) {
 if(stop_interleave) { void (*call)(void)=stop_interleave;stop_interleave=0;call(); }
 stops++;reads=0;reset_pending=1;if(!stuck && !delay_reads) { reset_release=0; }
 assert(!mprotect((void *)0x200c0000,0x1000,PROT_NONE));
}
/* HAL's actual physical mapping is tested in the producer; this service model
 * deliberately rejects direct TCM access until start, including snapshots. */
int bes2700yp_m55_repark_prepare(struct bes2700yp_repark_result *d)
{
 *d=(struct bes2700yp_repark_result){.reset_before=reset_release,
  .reset_after=reset_release,.reason=reset_release?1U:(uint32_t)repark_error};
 if(d->reason) { return -(20+(int)d->reason); }
 assert(!mprotect((void *)0x200c0000,0x1000,PROT_READ|PROT_WRITE));
 *(uint32_t *)0x200c0000=0x2015ffe0;*(uint32_t *)0x200c0004=0x200c0009;
 *(uint32_t *)0x200c0008=0xe7fdbf30;
 assert(!mprotect((void *)0x200c0000,0x1000,PROT_NONE));
 d->restore_ok=1;d->write_mask=7;return 0;
}
void bes2700yp_snapshot(struct bes2700yp_hw_snapshot *h)
{
 (void)reset_readback();
 *h=(struct bes2700yp_hw_snapshot){.core_vtor=vector,.reset_clr=reset_release,.reset_set=reset_release};
}
#include <bes2700yp_resources.h>
#define BES_RESOURCE_HOST_TEST
#include "../../platforms/bes2700yp/boot/bootstrap/arbitration.c"
#include "../../platforms/bes2700yp/boot/bootstrap/resource_service.c"
#include "../../platforms/bes2700yp/resources/contract.c"
const struct bes_resource_descriptor bes_resource_service={0};
const struct bes_resource_descriptor bes_arbitration_service={0};
const struct bes_resource_descriptor bes_uart_resource_service={0};
#include "../../platforms/bes2700yp/boot/bootstrap/dual_service.c"

static void nested(void)
{
 assert(irq_mask==0 && bes_arbitration_state.owner);
 unsigned before=stops, before_starts=starts;
 assert(dual_dispatch(DUAL_PREPARE,0)==BES_ARBITRATION_BUSY);
 assert(dual_dispatch(DUAL_STOP,0)==BES_ARBITRATION_BUSY);
 assert(bes_arbitration_state.pending && stops==before && starts==before_starts);
 assert(dual_dispatch(DUAL_CHECK_CLOCK,0)==BES_ARBITRATION_BUSY);
 assert(dual_dispatch(DUAL_SNAPSHOT,DUAL_HW_ADDR)==BES_ARBITRATION_BUSY);
 assert(dual_dispatch(0xff,0)==-4);
 struct bes_resource_io *io=(void *)BES_RESOURCE_RAM_START;
 *io=(struct bes_resource_io){.abi=1,.bytes=96,.resource=1};
 struct bes_resource_io old=*io;
 assert(bes_resource_dispatch(1,BES_RESOURCE_RAM_START,96)==BES_RESOURCE_BUSY);
 assert(!memcmp(io,&old,96) && irq_mask==0);
 if(fail_nested_stop) { stuck=1; }
}

int main(void)
{
 assert(mmap((void *)DUAL_DTCM,0x100000,PROT_READ|PROT_WRITE,
  MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0)==(void *)DUAL_DTCM);
 assert(mmap((void *)0x2055c000,4096,PROT_READ|PROT_WRITE,
  MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0)==(void *)0x2055c000);
 assert(mmap((void *)BES_RESOURCE_RAM_START,4096,PROT_READ|PROT_WRITE,
  MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0)==(void *)BES_RESOURCE_RAM_START);
 dual_service_init();assert(((struct dual_service *)DUAL_SERVICE_ADDR)->layout==BES_LIFECYCLE_LAYOUT);
 assert(dual_dispatch(BES_RESOURCE_DISCOVER,4)==BES_RESOURCE_UNSUPPORTED);
 assert(dual_dispatch(BES_RESOURCE_DISCOVER,2)==(int32_t)(uintptr_t)&bes_uart_resource_service);
 assert(dual_dispatch(BES_RESOURCE_DISCOVER,BES_RESOURCE_ABI)==(int32_t)(uintptr_t)&bes_resource_service);
 assert(!dual_service_phase() && !powers && !starts && !stops);
 assert(dual_dispatch(BES_LIFECYCLE_REPARK,0)==-4);
 assert(dual_dispatch(DUAL_RELEASE,DUAL_TRAMPOLINE|1)==-4);
 assert(dual_dispatch(DUAL_PREPARE,0)==0 && powers==1);
 assert(dual_dispatch(DUAL_PREPARE,0)==-4);
 assert(dual_dispatch(DUAL_PARK,0)==0);
 for(unsigned round=0;round<11;round++) {
  assert(phase==2);
  assert(dual_dispatch(DUAL_RELEASE,0)==-4);
  delay_reads=3;
  assert(dual_dispatch(DUAL_RELEASE,DUAL_TRAMPOLINE|1)==0 && phase==3);
  assert(BES_RESET_DIAG->version==1 && BES_RESET_DIAG->op==DUAL_RELEASE);
  assert(BES_RESET_DIAG->reason==0 && BES_RESET_DIAG->service_rc==0);
  assert(BES_RESET_DIAG->reset_before==16 && BES_RESET_DIAG->reset_after==0);
  assert(BES_RESET_DIAG->elapsed<60000 && BES_RESET_DIAG->samples>=2);
  assert(BES_RESET_DIAG->max_attempts==1 && irq_mask==0);
  assert(dual_dispatch(BES_LIFECYCLE_REPARK,0)==-4);
  assert(dual_dispatch(DUAL_STOP,0)==0 && phase==4);
  assert(dual_dispatch(DUAL_STOP,0)==0 && phase==4);
  assert(dual_dispatch(BES_LIFECYCLE_RESET_STATUS,0)==0);
  assert(dual_dispatch(DUAL_SNAPSHOT,DUAL_HW_ADDR)==0 && DUAL_HW->phase==4);
  if(round<10) {
   assert(dual_dispatch(BES_LIFECYCLE_REPARK,0)==0 && phase==2);
   assert(BES_REPARK_DIAG->version==1 && BES_REPARK_DIAG->phase_before==4);
   assert(BES_REPARK_DIAG->phase_after==2 && BES_REPARK_DIAG->service_rc==0);
   assert(*(uint32_t *)DUAL_DTCM==DUAL_MAILBOX);
   assert(*(uint32_t *)(DUAL_DTCM+4)==((DUAL_DTCM+8)|1));
  }
 }
 assert(powers==1 && starts==22 && stops==22);
 for(unsigned dead_timer=0;dead_timer<2;dead_timer++) {
  phase=3;reset_release=16;stuck=1;timer_stopped=dead_timer;
  assert(dual_dispatch(DUAL_STOP,0)==(dead_timer?-9:-8) && phase==5);
  assert(BES_RESET_DIAG->reason==(dead_timer?BES_RESET_POLL_EXHAUSTED:BES_RESET_TIMEOUT));
  assert(BES_RESET_DIAG->polls<=BES_RESET_POLL_LIMIT && reads<=BES_RESET_POLL_LIMIT+2);
  assert(dual_dispatch(BES_LIFECYCLE_REPARK,0)==-4);
  assert(dual_dispatch(DUAL_STOP,0)==-6);
  assert(dual_dispatch(DUAL_SNAPSHOT,DUAL_HW_ADDR)==0 && DUAL_HW->phase==5);
 }
 phase=4;reset_release=16;
 assert(dual_dispatch(BES_LIFECYCLE_RESET_STATUS,0)==-6 && phase==5);
 phase=4;
 assert(dual_dispatch(BES_LIFECYCLE_REPARK,0)==-21 && phase==5);
 for(repark_error=2;repark_error<=6;repark_error++) {
  phase=4;reset_release=0;unsigned prior_starts=starts;
  assert(dual_dispatch(BES_LIFECYCLE_REPARK,0)==-(20+repark_error) && phase==5);
  assert(starts==prior_starts && BES_REPARK_DIAG->reason==(uint32_t)repark_error);
  assert(BES_REPARK_DIAG->phase_after==5);
 }
 repark_error=0;
 /* A failed sampler must still contain the peer, preserve real diagnostics,
  * and leave the independent logging clock usable. */
 bes2700yp_m55_start(0x200c0000); /* Recreate a running PARK core for RELEASE. */
 phase=2;reset_release=16;stuck=0;delay_reads=0;timer_stopped=0;bad_sample=1;
 unsigned prior_stops=stops;
 assert(dual_dispatch(DUAL_RELEASE,DUAL_TRAMPOLINE|1)==-7 && phase==5);
 assert(stops==prior_stops+1 && reset_release==0 && diag.error==0);
 assert(BES_RESET_DIAG->reason==BES_RESET_SAMPLE_FAILED);
 assert(BES_RESET_DIAG->attempts==32 && BES_RESET_DIAG->last_a-BES_RESET_DIAG->last_b==21);
 assert(BES_RESET_DIAG->samples==0 && BES_RESET_DIAG->polls==0 && irq_mask==0);
 phase=3;reset_release=16;bad_sample=0;late_bad_sample=1;timer_reads=0;
 assert(dual_dispatch(DUAL_STOP,0)==-7 && phase==5 && reset_release==0);
 assert(BES_RESET_DIAG->samples==1 && BES_RESET_DIAG->polls==1);
 assert(BES_RESET_DIAG->attempts==33 && BES_RESET_DIAG->raw_end==0 && diag.error==0);
 /* The elapsed subtraction remains valid when the timer wraps after start. */
 phase=3;reset_release=16;late_bad_sample=0;timer=4;timer_reads=0;
 assert(dual_dispatch(DUAL_STOP,0)==0 && phase==4);
 assert(BES_RESET_DIAG->raw_start==0xfffffffeU && BES_RESET_DIAG->raw_end==598);
 assert(BES_RESET_DIAG->elapsed==600 && BES_RESET_DIAG->reason==0);
 phase=3;bad_sample=0;diag.error=91;
 assert(dual_dispatch(DUAL_STOP,0)==-10 && phase==5 && diag.error==91);
 assert(BES_RESET_DIAG->reason==BES_RESET_CLOCK_LATCHED);
 phase=3;diag.error=0;timer_ctrl=0;
 assert(dual_dispatch(DUAL_STOP,0)==-11 && phase==5);
 assert(BES_RESET_DIAG->reason==BES_RESET_TIMER_CONFIG);
 /* Errors and contexts must relinquish ownership without hardware access. */
 diag.error=0;timer_ctrl=0x82;phase=0;
 assert(!mprotect((void *)DUAL_DTCM,0x1000,PROT_READ|PROT_WRITE));
 unsigned before_powers=powers;
 ipsr=1;assert(dual_dispatch(DUAL_PREPARE,0)==BES_ARBITRATION_CONTEXT);ipsr=0;
 control=1;assert(dual_dispatch(DUAL_PREPARE,0)==BES_ARBITRATION_CONTEXT);control=0;
 irq_mask=1;assert(dual_dispatch(DUAL_PREPARE,0)==BES_ARBITRATION_CONTEXT);
 assert(irq_mask==1 && powers==before_powers);irq_mask=0;
 prepare_error=-2;assert(dual_dispatch(DUAL_PREPARE,0)==-2);
 assert(!bes_arbitration_busy());prepare_error=0;
 assert(!dual_dispatch(DUAL_PREPARE,0));assert(!dual_dispatch(DUAL_PARK,0));
 /* Reenter during the real RELEASE start call. STOP is deferred, then confirmed
  * before RELEASE can return; no success with a peer unexpectedly held reset. */
 unsigned completed_before=bes_arbitration_state.stop_completed;
 interleave=nested;
 assert(dual_dispatch(DUAL_RELEASE,DUAL_TRAMPOLINE|1)==BES_ARBITRATION_CANCELLED);
 interleave=0;
 assert(phase==4 && !reset_release && !bes_arbitration_busy());
 assert(!bes_arbitration_state.pending && bes_arbitration_state.stop_completed==completed_before+1);
 assert(bes_arbitration_state.entered==bes_arbitration_state.exited && irq_mask==0);
 assert(!dual_dispatch(BES_LIFECYCLE_REPARK,0));
 interleave=nested;fail_nested_stop=1;
 assert(dual_dispatch(DUAL_RELEASE,DUAL_TRAMPOLINE|1)==-8);
 interleave=0;stuck=0;fail_nested_stop=0;
 assert(phase==5 && !bes_arbitration_busy() && !bes_arbitration_state.pending);
 assert(bes_arbitration_state.entered==bes_arbitration_state.exited);
 phase=3;reset_release=16;bad_sample=1;stop_interleave=nested;
 unsigned completed=bes_arbitration_state.stop_completed;
 assert(dual_dispatch(DUAL_STOP,0)==-7 && phase==5);
 assert(BES_RESET_DIAG->service_rc==(uint32_t)-7);
 assert(!bes_arbitration_busy() && !bes_arbitration_state.pending);
 assert(bes_arbitration_state.stop_completed==completed && irq_mask==0);
 assert(bes_arbitration_state.entered==bes_arbitration_state.exited);
#ifdef BES_ARBITRATION_PROBE
 assert(bes_arbitration_state.probe_runs==1 && bes_arbitration_state.probe_mask==31);
 assert(!bes_arbitration_state.probe_errors);
#endif
 puts("Lifecycle service: 11 sessions, real sampler, bounded faults and peer containment pass");
}
