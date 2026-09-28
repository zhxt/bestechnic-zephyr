/* SPDX-License-Identifier: Apache-2.0 */
#include <zephyr/kernel.h>
#include <cmsis_core.h>
#include <bes2700_dual_boot.h>
#include <bes2700_dual_image.h>
#include "bth_contract.h"
#include "m55_payload.h"
#include "message.h"
#include <bes2700_dual_doorbell.h>
#include <bes2700_observation.h>
#define SECONDS CONFIG_DUAL_DURATION_SECONDS
BUILD_ASSERT(SECONDS==(CONFIG_DUAL_MSG_MODE!=2?600:CONFIG_DUAL_IPC_SECONDS+10));
_Static_assert(BTH_LOG_ADDR >= DUAL_HW_ADDR + sizeof(struct dual_hw), "log/hardware overlap");
_Static_assert(BTH_LOG_ADDR + sizeof(struct bth_log_clock) <= BTH_DIAG_BASE + 0x1000, "log page overflow");
static int (*service)(uint32_t, uint32_t);
static uint32_t parked;
static volatile uint32_t timer_count;
static void tick(struct k_timer *t) { ARG_UNUSED(t); timer_count++; bth_log_poll(); }
K_TIMER_DEFINE(timer, tick, NULL);
static void field(const char *name, uint32_t n) { bth_puts(name); bth_dec(n); }
static void stage(uint32_t id, uint32_t rc)
{ bth_log_begin(rc?'E':'I',"LOADER","MAIN"); bth_puts("zephyr_dual stage"); field(" id=",id); field(" rc=",rc); bth_end(); }
static void finish(uint32_t samples, uint32_t rc)
{
 q_stop();
 k_timer_stop(&timer);
 if(CONFIG_DUAL_MSG_MODE==2 || rc) {
  bth_log_begin(rc?'E':'I',"KERN","MAIN");
  bth_puts("zephyr_dual result");field(" pass=",rc==0);field(" samples=",samples);field(" rc=",rc);bth_end();
 }
 /* Do not touch shared RAM after stopping the peer. Power remains enabled. */
 if (parked && service) { (void)service(DUAL_STOP,0); }
 /* The periodic clock sampler has stopped; future faults must print NA. */
 bth_log_reset();
}
static void observe_begin(const char *kind, uint32_t rc)
{
 bth_log_begin(rc?'E':'I',"OBSERVE","MAIN");bth_puts("zephyr_observe ");bth_puts(kind);
}
/* Workers have finished. Read the actual AXI publications again, including
 * their seqlocks, instead of accepting only the cached final report. */
static int observe_traffic(const struct q_report *report)
{
 if(!report->finished || report->rc || !report->session) { return 95; }
 for(unsigned side=0;side<2;side++) {
  volatile struct bi_ring *ring=(void *)(uintptr_t)(BI_BASE+4096U*side);
  if(!bi_guards_ok(ring) || ring->head!=ring->tail) { return 95; }
  volatile struct q_state *shared=&ring->state;
  struct q_state copy;uint32_t seq=shared->seq;__DMB();
  if(seq&1) { return 95; }
  uint32_t *d=(void *)&copy;volatile uint32_t *src=(void *)shared;
  for(unsigned i=0;i<sizeof(copy)/4;i++) { d[i]=src[i]; }
  __DMB();if(seq!=shared->seq || copy.seq!=seq) { return 95; }
  const struct q_state *expected=side?&report->m55:&report->bth;
#define CHECK_TERMINAL(n) if(copy.n!=expected->n) { return 95; }
  Q_FIELDS(CHECK_TERMINAL)
#undef CHECK_TERMINAL
  if(copy.error || copy.guard!=Q_META_GUARD) { return 95; }
 }
 return 0;
}
static int observe_checkpoint(struct bes_observation *o, unsigned scope, uint32_t ms,
                              uint32_t samples, const struct q_report *report)
{
 int rc=observe_traffic(report);
 observe_begin("traffic",rc);field(" scope=",scope);field(" session=",report->session);
 field(" finished=",report->finished);field(" live=",!rc);field(" rc=",rc);bth_end();
 observe_begin("result",rc);field(" version=",BES_OBSERVATION_VERSION);field(" scope=",scope);
 field(" pass=",!rc);field(" session=",report->session);field(" functional_ms=",o->functional_ms);
 field(" ms=",ms);field(" samples=",samples);field(" rc=",rc);bth_end();
 return rc;
}
static int read_peer(struct dual_status *s)
{
 for (unsigned retry=0; retry<1000; retry++) {
  uint32_t seq=DUAL_STATUS->seq;
  if (seq&1) { continue; }
  __DMB();
  uint32_t *dst=(uint32_t *)s; volatile uint32_t *src=(volatile uint32_t *)DUAL_STATUS;
  for (unsigned i=0; i<sizeof(*s)/4; i++) { dst[i]=src[i]; }
  __DMB();
  if (seq==DUAL_STATUS->seq && seq==s->seq) { return 0; }
 }
 return -1;
}
static void diagnostics(uint32_t id, uint32_t elapsed, uint32_t good, uint32_t bad)
{
 int hr=service(DUAL_SNAPSHOT,DUAL_HW_ADDR);
 bth_log_begin(hr?'E':'I',"LOADER","MAIN");
 bth_puts("zephyr_dual hw"); field(" id=",id); field(" rc=",hr?1:0);
 const volatile struct dual_hw *h=DUAL_HW;
#define HW(name) bth_field(" " #name "=",h->name)
 HW(phase); HW(core_vtor); HW(reset_set); HW(reset_clr); HW(ram_sel0); HW(ram_sel1);
 HW(oclk); HW(oreset); HW(sysclk); HW(vector_sp); HW(vector_pc); HW(release_sp); HW(release_pc);
#undef HW
 bth_end();
 /* Trace is for localization. Raw values can change while peer runs. */
 struct dual_trace d;
 volatile uint32_t *src=(void *)DUAL_TRACE;
 uint32_t *dst=(void *)&d;
 for (unsigned i=0;i<sizeof(d)/4;i++) { dst[i]=src[i]; }
 __DMB();
 uint32_t stable=d.stage==DUAL_TRACE->stage;
 bth_log_begin('I',"LOADER","MAIN");
 bth_puts("zephyr_dual diag"); field(" id=",id); field(" elapsed=",elapsed);
 field(" reads=",good); field(" retries=",bad); field(" stable=",stable);
 bth_field(" seq=",DUAL_STATUS->seq); bth_field(" magic=",DUAL_STATUS->magic);
#define TRACE(name) bth_field(" " #name "=",d.name)
 TRACE(stage); TRACE(cpuid); TRACE(vtor); TRACE(msp); TRACE(psp); TRACE(control);
 TRACE(primask); TRACE(basepri); TRACE(ccr); TRACE(mpu); TRACE(cpacr); TRACE(cfsr);
 TRACE(hfsr); TRACE(shcsr); TRACE(mmfar); TRACE(bfar); TRACE(icsr); TRACE(reason);
 TRACE(msplim); TRACE(psplim); TRACE(pc); TRACE(lr); TRACE(xpsr); TRACE(esf_valid);
#undef TRACE
 bth_end();
}
static int peer_ok(const struct dual_status *s)
{
 return s->magic==DUAL_MAGIC && s->layout==DUAL_LAYOUT && s->build==M55_BUILD_ID &&
        s->stage==2 && s->hz==DUAL_HZ && s->guard==DUAL_GUARD && !s->error &&
        (s->cpuid&0xff00fff0U)==0x4100d220U && s->vtor==DUAL_ITCM && s->control==2 &&
        !s->primask && !s->basepri && !s->mpu && !(s->ccr & ((1U<<16)|(1U<<17))) && s->stack>=128;
}
int main(void)
{
 bth_stage("main");
 bth_log_begin('I',"LOADER","MAIN");
 bth_puts("zephyr_dual begin version=3 test=8"); bth_field(" build=",BTH_DIAG->build);
 bth_field(" m55_build=",M55_BUILD_ID); bth_field(" layout=",DUAL_LAYOUT);
 field(" duration=",SECONDS); field(" bth_hz=",BTH_DIAG->cpu_hz); field(" m55_hz=",DUAL_HZ); bth_end();
 if (!bth_guards_ok() || SCB->CPUID!=0x630f1321 || SCB->VTOR!=BTH_CODE_BASE ||
     __get_CONTROL()!=2 || __get_IPSR() || __get_PRIMASK() || __get_BASEPRI() || BTH_DIAG->cpu_hz!=DUAL_HZ) {
  finish(0,80); return 0;
 }
 const volatile struct dual_service *api=(void *)DUAL_SERVICE_ADDR;
 uint32_t fn=api->dispatch;
 if (dual_service_validate(api)) { finish(0,81); return 0; }
 service=(void *)(uintptr_t)fn;
 int rc=dual_image_check(m55_payload,sizeof(m55_payload),M55_PAYLOAD_CRC);
 stage(1,rc); if (rc) { finish(0,82); return 0; }
 stage(2,0); /* before power/clock operations, so a stalled HAL call is visible */
 rc=service(DUAL_PREPARE,0); stage(3,rc ? 1:0);
 if (rc) { finish(0,83); return 0; }
 k_sleep(K_MSEC(2));
 rc=service(DUAL_PARK,0); stage(4,rc ? 1:0);
 if (rc) { finish(0,84); return 0; } parked=1;
 k_sleep(K_MSEC(2));
 volatile uint32_t *clear=(void *)DUAL_SHARED_ADDR;
 for (unsigned i=0;i<sizeof(struct dual_status)/4;i++) { clear[i]=0; }
 clear=(void *)DUAL_TRACE_ADDR;
 for (unsigned i=0;i<sizeof(struct dual_trace)/4;i++) { clear[i]=0; }
 /* Reset the separate IPC region only while the peer remains parked. */
 clear=(void *)BES_DB_ADDR;
 for (unsigned i=0;i<0x80/4;i++) { clear[i]=0; }
 clear[0x7c/4]=0xdb08bafe;
 q_prepare(BTH_DIAG->build,bth_ticks());
 __DSB(); diagnostics(0,0,0,0);
 /* M55 is executing only the DTCM +8 WFI stub. No load segment may overwrite it. */
 uint32_t count=dual_u32(m55_payload+28)/12;
 for (uint32_t i=0; i<count; i++) {
  const uint8_t *map=m55_payload+32+i*12;
  uint32_t dst=dual_u32(map), src=dual_u32(map+4), n=dual_u32(map+8);
  volatile uint32_t *out=(void *)(uintptr_t)dst;
  for (uint32_t j=0;j<n;j+=4) { out[j/4]=dual_u32(m55_payload+src+j); }
  __DSB();
  if (dual_crc((const uint8_t *)(uintptr_t)dst,n)!=dual_crc(m55_payload+src,n)) { stage(5,1);finish(0,85);return 0; }
 }
 __DSB();stage(5,0);
 rc=service(DUAL_RELEASE,DUAL_TRAMPOLINE|1);stage(6,rc?1:0);
 if (rc) { finish(0,86); return 0; }
 diagnostics(1,0,0,0);
 struct dual_status peer={0};
 uint32_t handshake=k_uptime_get_32(), reads=0, retries=0;
 uint64_t deadline=k_uptime_get()+2000;
 while (k_uptime_get()<deadline) {
  int read_rc=read_peer(&peer);
  if (read_rc) { retries++; } else { reads++; }
  if (!read_rc && peer.magic==DUAL_MAGIC && peer.stage==2) { break; }
  if (peer.stage==255) { break; }
  k_sleep(K_MSEC(1));
 }
 bth_log_begin(peer.error?'E':'I',"LOADER","MAIN");
 bth_puts("zephyr_dual peer"); bth_field(" cpuid=",peer.cpuid); bth_field(" vtor=",peer.vtor);
 bth_field(" build=",peer.build);field(" stage=",peer.stage);field(" error=",peer.error);
 field(" mpu=",peer.mpu);bth_field(" ccr=",peer.ccr);field(" control=",peer.control);bth_end();
 diagnostics(2,k_uptime_get_32()-handshake,reads,retries);
 if (!peer_ok(&peer) || service(DUAL_CHECK_CLOCK,0)) { stage(7,1);finish(0,87);return 0; }stage(7,0);
 bth_log_begin('I',"IPC","MAIN");
 bth_puts("zephyr_msg begin version=2 channel=1");field(" duration=",CONFIG_DUAL_IPC_SECONDS);
 field(" progress_period=",10);field(" mode=",CONFIG_DUAL_MSG_MODE);field(" layout=",Q_LAYOUT);
 field(" pair=",CONFIG_DUAL_CC_PAIR);field(" depth=",BI_DEPTH);field(" payload=",BI_PAYLOAD);bth_end();
 q_start();bool db_printed=false;struct bes_observation observation={0};
 uint32_t start_ms=k_uptime_get_32(), start_raw=bth_ticks(), prev_cycles=peer.cycles;
 uint32_t base_peer_ms=peer.ms, base_beat=peer.beat, last_beat=peer.beat;
 uint64_t peer_cycles=0, ticks=0;
 k_timer_start(&timer,K_MSEC(100),K_MSEC(100));
 const uint32_t limit=CONFIG_DUAL_MSG_MODE==2?SECONDS:BES_OBSERVATION_LIMIT_MS/1000;
 for (uint32_t i=0;i<=limit;i++) {
  if (i) { k_sleep(K_TIMEOUT_ABS_MS((uint64_t)start_ms+i*1000)); }
  if (CONFIG_DUAL_MSG_MODE==2 && i==SECONDS) { k_timer_stop(&timer); }
  uint32_t elapsed=k_uptime_get_32()-start_ms, raw=bth_ticks();
  ticks+=(uint32_t)(raw-start_raw); start_raw=raw;
  rc=0;
  if (read_peer(&peer) || !peer_ok(&peer)) { rc=88; }
  peer_cycles+=(uint32_t)(peer.cycles-prev_cycles);prev_cycles=peer.cycles;
  uint32_t pm=peer.ms-base_peer_ms, beat=peer.beat-base_beat;
  int32_t skew=(int32_t)(pm-elapsed);
  uint64_t expect=(uint64_t)elapsed*6000;
  uint64_t diff=ticks>expect ? ticks-expect:expect-ticks;
  uint64_t mexpect=(uint64_t)pm*24000;
  uint64_t mdiff=peer_cycles>mexpect ? peer_cycles-mexpect:mexpect-peer_cycles;
  size_t stack=0;
  if (k_thread_stack_space_get(k_current_get(),&stack) || stack<128 || !bth_guards_ok() || BTH_DIAG->error) { rc=89; }
  if (i && (peer.beat<=last_beat || skew < -250 || skew >250 || elapsed<i*1000 || elapsed>i*1000+100 ||
      diff>expect/100 || mdiff>MAX(24000ULL,mexpect/100) || beat+3<pm/100 || beat>pm/100+3 ||
      timer_count+2<elapsed/100 || timer_count>elapsed/100+2 || service(DUAL_CHECK_CLOCK,0))) { rc=90; }
  last_beat=peer.beat;
  bth_log_begin(rc?'E':'I',"KERN","MAIN");
  bth_puts("zephyr_dual sample");field(" id=",i);field(" ms=",elapsed);bth_puts(" ticks=");bth_dec64(ticks);
  field(" timer=",timer_count);field(" m55_ms=",pm);field(" beat=",beat);
  field(" cycles_hi=",peer_cycles>>32);field(" cycles_lo=",peer_cycles);
  field(" bth_stack=",stack);field(" m55_stack=",peer.stack);
  field(" guards=",bth_guards_ok() && peer.guard==DUAL_GUARD);field(" rc=",rc);bth_end();
  struct q_report db;q_snapshot(&db);
  if(i && i%10==0 && i<CONFIG_DUAL_IPC_SECONDS && CONFIG_DUAL_MSG_MODE==2) {
   const struct q_state *lanes[2]={&db.bth,&db.m55};
   if(db.finished || !db.session || db.bth.elapsed+2500U<elapsed ||
      db.m55.elapsed+2500U<elapsed || db.bth.phase!=Q_RUNNING || db.m55.phase!=Q_RUNNING) { rc=94; }
   for(unsigned side=0;side<2;side++) {
    bth_log_begin(rc?'E':'I',"IPC","MAIN");bth_puts("zephyr_msg progress");
    field(" sample=",i);field(" side=",side);
#define CS_PROGRESS(name) field(" " #name "=",lanes[side]->name);
    Q_FIELDS(CS_PROGRESS)
#undef CS_PROGRESS
    field(" error=",lanes[side]->error);field(" guard=",lanes[side]->guard);bth_end();
   }
  }
  if(db.finished && !db_printed) {
   if(CONFIG_DUAL_MSG_MODE==3) {
    for(unsigned c=0;c<11;c++) {
     bth_log_begin(db.rc?'E':'I',"IPC","MAIN");bth_puts("zephyr_msg case");
     field(" id=",db.cases[c].id);field(" expected=",db.cases[c].expected);
     field(" bth=",db.cases[c].bth);field(" m55=",db.cases[c].m55);bth_end();
    }
   }
   const struct q_state *lanes[2]={&db.bth,&db.m55};
   for(unsigned side=0;side<2;side++) {
    bth_log_begin(db.rc?'E':'I',"IPC","MAIN");bth_puts("zephyr_msg endpoint");field(" side=",side);
#define CC_PRINT(name) field(" " #name "=",lanes[side]->name);
    Q_FIELDS(CC_PRINT)
#undef CC_PRINT
    field(" error=",lanes[side]->error);field(" guard=",lanes[side]->guard);bth_end();
   }
   bth_log_begin(db.rc?'E':'I',"IPC","MAIN");bth_puts("zephyr_msg result");
   field(" finished=",db.finished);field(" rc=",db.rc);field(" session=",db.session);
   bth_end();db_printed=true;
   if(CONFIG_DUAL_MSG_MODE!=2 && !db.rc && !rc) {
    observation.functional_ms=k_uptime_get_32()-start_ms;observation.functional=true;
    observe_begin("functional",0);field(" version=",BES_OBSERVATION_VERSION);
    field(" ms=",observation.functional_ms);field(" session=",db.session);field(" rc=",0);bth_end();
   }
  }
  if(db.finished && db.rc) { rc=92; }
  if(i>=(CONFIG_DUAL_MSG_MODE!=2?590:CONFIG_DUAL_IPC_SECONDS+5) && !db.finished) { rc=93; }
  if(CONFIG_DUAL_MSG_MODE!=2 && !rc) {
   unsigned scope=bes_observation_due(&observation,elapsed);
   if(scope) {
    rc=observe_checkpoint(&observation,scope,elapsed,i+1,&db);
    observation.short_done=true;
    if(!rc && scope==1 && bes_observation_due(&observation,elapsed)==2) {
     scope=2;rc=observe_checkpoint(&observation,scope,elapsed,i+1,&db);
    }
    if(scope==2 || rc) { finish(i+1,rc);return 0; }
   }
  }
  if (rc || i==limit) { finish(i+1,rc?rc:CONFIG_DUAL_MSG_MODE==2?0:96); return 0; }
 }
 return 0;
}
