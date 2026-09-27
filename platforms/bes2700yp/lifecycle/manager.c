/* SPDX-License-Identifier: Apache-2.0 */
#include <zephyr/kernel.h>
#include <zephyr/device.h>
#include <cmsis_core.h>
#include <bes2700_dual_boot.h>
#include <bes2700_dual_image.h>
#include <bes2700_mbox.h>
#include <bes2700_lifecycle.h>
#include <bes2700_peer_health.h>
#include "bth_contract.h"
#include "m55_payload.h"
#include "message.h"
_Static_assert(BES_PEER_READY_MS==BES_LIFECYCLE_READY_MS,"READY budget contract");
static const struct device *const mailbox=DEVICE_DT_GET(DT_NODELABEL(mbox_peer));
static int (*service)(uint32_t,uint32_t);
static uint32_t generation;
#if CONFIG_BES2700_M55_FAULT_CASE > 0
static uint32_t releases;
#endif
static struct dual_hw retained;
static volatile uint32_t monitor_samples, monitor_error;
static volatile uint32_t timer_count;
K_MUTEX_DEFINE(log_lock);
K_SEM_DEFINE(monitor_start,0,1);
K_SEM_DEFINE(monitor_done,0,1);
static void tick(struct k_timer *t) { ARG_UNUSED(t);timer_count++;bth_log_poll(); }
K_TIMER_DEFINE(timer,tick,NULL);
static void begin(const char *kind,uint32_t rc)
{
 k_mutex_lock(&log_lock,K_FOREVER);bth_log_begin(rc?'E':'I',"R1","MAIN");
 bth_puts("zephyr_r1 ");bth_puts(kind);
}
static void field(const char *key,uint32_t n) { bth_puts(key);bth_dec(n); }
static void end(void) { bth_end();k_mutex_unlock(&log_lock); }
static void event(uint32_t round,uint32_t step,uint32_t rc,uint32_t elapsed)
{
 begin("event",rc);field(" round=",round);field(" session=",generation);
 field(" step=",step);field(" rc=",rc);field(" elapsed=",elapsed);end();
}
static int reset_call(unsigned round,uint32_t op,uint32_t failure)
{
 volatile uint32_t *words=(void *)BES_RESET_DIAG;
 for(unsigned i=0;i<sizeof(*BES_RESET_DIAG)/4;i++) { words[i]=0; }
 BES_RESET_DIAG->op=op;__DMB();
 int rc=service(op,op==DUAL_RELEASE?DUAL_TRAMPOLINE|1U:0);
 BES_RESET_DIAG->service_rc=(uint32_t)rc;__DMB();
#if CONFIG_BES2700_M55_FAULT_CASE > 0
 if(op==DUAL_RELEASE && !rc) { releases++; }
#endif
 begin("reset",rc?failure:0);field(" round=",round);field(" session=",generation);
#define PRINT_RESET(n) field(" " #n "=",BES_RESET_DIAG->n);
 BES_RESET_FIELDS(PRINT_RESET)
#undef PRINT_RESET
 field(" rc=",rc?failure:0);end();
 return rc;
}
static int repark_call(unsigned round)
{
 volatile uint32_t *words=(void *)BES_REPARK_DIAG;
 for(unsigned i=0;i<sizeof(*BES_REPARK_DIAG)/4;i++) { words[i]=0; }
 __DMB();int rc=service(BES_LIFECYCLE_REPARK,0);
 BES_REPARK_DIAG->service_rc=(uint32_t)rc;__DMB();
 begin("repark",rc?12:0);field(" round=",round);field(" session=",generation);
#define PRINT_PARK(n) field(" " #n "=",BES_REPARK_DIAG->n);
 BES_REPARK_FIELDS(PRINT_PARK)
#undef PRINT_PARK
 field(" rc=",rc?12:0);end();return rc;
}
/* Independent liveness while manager copies/CRCs peer memory. UART serialized. */
static void monitor(void *a,void *b,void *c)
{
 ARG_UNUSED(a);ARG_UNUSED(b);ARG_UNUSED(c);k_sem_take(&monitor_start,K_FOREVER);
 int64_t start=k_uptime_get();uint32_t raw=bth_ticks();uint64_t ticks=0;
 for(unsigned i=0;i<=BES_LIFECYCLE_OBSERVE_SECONDS;i++) {
  if(i) { k_sleep(K_TIMEOUT_ABS_MS(start+i*1000)); }
  uint32_t now=bth_ticks(),ms=(uint32_t)(k_uptime_get()-start);
  ticks+=(uint32_t)(now-raw);raw=now;size_t stack=0;
  uint64_t expected=(uint64_t)ms*6000,delta=ticks>expected?ticks-expected:expected-ticks;
  uint32_t rc=!bth_guards_ok() || BTH_DIAG->error ||
   k_thread_stack_space_get(k_current_get(),&stack) || stack<128 ||
   ms<i*1000 || ms>i*1000+100 || (i && delta>expected/100) ||
   timer_count+2<ms/100 || timer_count>ms/100+2;
  begin("sample",rc);field(" id=",i);field(" ms=",ms);
  bth_puts(" ticks=");bth_dec64(ticks);field(" timer=",timer_count);
  field(" stack=",stack);field(" guards=",bth_guards_ok());field(" rc=",rc);end();
  monitor_samples=i+1;if(rc) { monitor_error=rc;break; }
 }
 k_sem_give(&monitor_done);
}
K_THREAD_DEFINE(r1_monitor,2048,monitor,NULL,NULL,NULL,-1,0,0);
static int peer_read(struct dual_status *out)
{
 int64_t until=k_uptime_get()+20;
 do {
  struct dual_status copy;uint32_t seq=DUAL_STATUS->seq;
  if(!(seq&1)) {
   __DMB();uint32_t *d=(void *)&copy;volatile uint32_t *s=(void *)DUAL_STATUS;
   for(unsigned i=0;i<sizeof(copy)/4;i++) { d[i]=s[i]; }
   __DMB();if(seq==copy.seq && seq==DUAL_STATUS->seq) { *out=copy;return 0; }
  }
  k_msleep(1);
 } while(k_uptime_get()<until);
 return -1;
}
static int peer_ok(const struct dual_status *p)
{
 return p->magic==DUAL_MAGIC && p->layout==DUAL_LAYOUT && p->build==M55_BUILD_ID &&
  p->stage==2 && !p->error && p->guard==DUAL_GUARD && p->hz==DUAL_HZ &&
  p->vtor==DUAL_ITCM && p->control==2 && !p->primask && !p->basepri && !p->mpu &&
  !(p->ccr&((1U<<16)|(1U<<17))) && p->stack>=128 &&
  (p->cpuid&0xff00fff0U)==0x4100d220U;
}
static void control_init(void)
{
 volatile uint32_t *p=(void *)BES_LIFECYCLE_CTL;
 for(unsigned i=0;i<sizeof(*BES_LIFECYCLE_CTL)/4;i++) { p[i]=0; }
 BES_LIFECYCLE_CTL->layout=BES_LIFECYCLE_LAYOUT;BES_LIFECYCLE_CTL->session=generation;BES_LIFECYCLE_CTL->guard=BES_LIFECYCLE_GUARD;
 __DMB();BES_LIFECYCLE_CTL->magic=BES_LIFECYCLE_MAGIC;__DSB();
}
static int load(void)
{
 volatile uint32_t *p=(void *)DUAL_STATUS;
 for(unsigned i=0;i<sizeof(struct dual_status)/4;i++) { p[i]=0; }
 p=(void *)DUAL_TRACE;
 for(unsigned i=0;i<sizeof(struct dual_trace)/4;i++) { p[i]=0; }
 control_init();q_prepare(BTH_DIAG->build,generation);
 uint32_t count=dual_u32(m55_payload+28)/12;
 for(unsigned i=0;i<count;i++) {
  const uint8_t *map=m55_payload+32+i*12;
  uint32_t dst=dual_u32(map),src=dual_u32(map+4),n=dual_u32(map+8);
  volatile uint32_t *out=(void *)(uintptr_t)dst;
  for(uint32_t j=0;j<n;j+=4) { out[j/4]=dual_u32(m55_payload+src+j); }
  __DSB();
  if(dual_crc((const uint8_t *)(uintptr_t)dst,n)!=dual_crc(m55_payload+src,n)) { return 1; }
 }
 return 0;
}
static int session_park(unsigned round,uint32_t start)
{
 generation=round+1;event(round,1,0,0);
 if(round==0) {
  if(service(DUAL_PREPARE,0)) { return 10; }
  k_msleep(2);if(service(DUAL_PARK,0)) { return 11; }
 } else if(repark_call(round)) { return 12; }
 k_msleep(2);event(round,2,0,k_uptime_get_32()-start);
 if(service(DUAL_SNAPSHOT,DUAL_HW_ADDR)) { return 25; }
 if(!round) { retained=*DUAL_HW; }
 if(DUAL_HW->ram_sel0!=retained.ram_sel0 || DUAL_HW->ram_sel1!=retained.ram_sel1) { return 26; }
 return 0;
}
static int session_load(unsigned round,uint32_t start)
{
 if(load()) { return 13; }
 event(round,3,0,k_uptime_get_32()-start);return 0;
}
static int session_release(unsigned round,uint32_t start)
{
 if(bes2700_mbox_resume(mailbox)) { return 14; }
 if(reset_call(round,DUAL_RELEASE,15)) { return 15; }
 event(round,4,0,k_uptime_get_32()-start);
 return 0;
}
static int session_start(unsigned round,uint32_t start)
{
 int rc=session_park(round,start);
 if(!rc) { rc=session_load(round,start); }
 if(!rc) { rc=session_release(round,start); }
 return rc;
}
static enum bes_peer_fault wait_ready(struct bes_peer_health *health,struct dual_status *peer)
{
 bes_peer_health_init(health,k_uptime_get());
 do {
  bool readable=peer_read(peer)==0;
  bes_peer_health_poll(health,k_uptime_get(),readable,readable && peer_ok(peer),peer->beat);
  if(health->state!=BES_PEER_STARTING) { break; }
  k_msleep(1);
 } while(true);
 return health->fault;
}
#if CONFIG_BES2700_M55_FAULT_CASE == 0 || defined(CONFIG_BES2700_M55_RECOVERY)
static int session_finish(unsigned round,uint32_t start)
{
 struct dual_status peer={0};struct bes_peer_health health;
 if(wait_ready(&health,&peer) || service(DUAL_CHECK_CLOCK,0)) { return 16; }
 int64_t deadline;
 begin("ready",0);field(" round=",round);field(" session=",generation);
 field(" peer_ms=",peer.ms);field(" beat=",peer.beat);field(" stack=",peer.stack);
 field(" elapsed=",k_uptime_get_32()-start);field(" rc=",0);end();
 q_start();deadline=k_uptime_get()+BES_LIFECYCLE_MESSAGE_MS;
 struct q_report r={0};uint32_t base_ms=peer.ms;
 uint32_t base_beat=peer.beat,base_cycles=peer.cycles,ready_ms=k_uptime_get_32();
 while(k_uptime_get()<deadline) {
  q_snapshot(&r);if(r.finished) { break; }
  k_msleep(100);
  bool readable=peer_read(&peer)==0;
  if(bes_peer_health_poll(&health,k_uptime_get(),readable,readable && peer_ok(&peer),peer.beat) ||
     monitor_error) { return 17; }
 }
 if(!r.finished || r.rc || r.session!=generation || q_wait_idle(1000)) { return 18; }
 for(unsigned side=0;side<2;side++) {
  const struct q_state *s=side?&r.m55:&r.bth;
  begin("endpoint",0);field(" round=",round);field(" side=",side);
#define PRINT(n) field(" " #n "=",s->n);
  Q_FIELDS(PRINT)
#undef PRINT
  field(" error=",s->error);field(" guard=",s->guard);end();
 }
 if(r.bth.sent!=BES_LIFECYCLE_TARGET || r.m55.sent!=BES_LIFECYCLE_TARGET ||
    r.bth.acked!=BES_LIFECYCLE_TARGET || r.m55.acked!=BES_LIFECYCLE_TARGET ||
    r.bth.handled!=BES_LIFECYCLE_TARGET || r.m55.handled!=BES_LIFECYCLE_TARGET ||
    peer.ms<=base_ms) { return 19; }
 if(peer_read(&peer) || !peer_ok(&peer)) { return 23; }
 uint32_t peer_ms=peer.ms-base_ms,beats=peer.beat-base_beat,cycles=peer.cycles-base_cycles;
 uint32_t elapsed=k_uptime_get_32()-ready_ms;
 int32_t skew=(int32_t)(peer_ms-elapsed);
 uint64_t expected=(uint64_t)peer_ms*24000,delta=cycles>expected?cycles-expected:expected-cycles;
 if(skew < -250 || skew>250 || !beats || beats+3<peer_ms/100 || beats>peer_ms/100+3 ||
    delta>MAX(24000ULL,expected/100)) { return 24; }
 begin("peer",0);field(" round=",round);field(" session=",generation);
 field(" ms=",peer_ms);field(" beat=",beats);field(" cycles=",cycles);
 field(" elapsed=",elapsed);field(" stack=",peer.stack);field(" guards=",1);field(" rc=",0);end();
 event(round,5,0,k_uptime_get_32()-start);
 BES_LIFECYCLE_CTL->quiesce=generation;__DSB();deadline=k_uptime_get()+BES_LIFECYCLE_QUIESCE_MS;
 while(BES_LIFECYCLE_CTL->idle!=generation && k_uptime_get()<deadline) { k_msleep(1); }
 __DMB();
 if(BES_LIFECYCLE_CTL->idle!=generation || BES_LIFECYCLE_CTL->peer_session!=generation ||
    BES_LIFECYCLE_CTL->peer_guard!=BES_LIFECYCLE_GUARD) { return 20; }
 event(round,6,0,k_uptime_get_32()-start);
 if(reset_call(round,DUAL_STOP,21) || service(BES_LIFECYCLE_RESET_STATUS,0)) { return 21; }
 event(round,7,0,k_uptime_get_32()-start);
 if(service(DUAL_SNAPSHOT,DUAL_HW_ADDR)) { return 25; }
 if(DUAL_HW->ram_sel0!=retained.ram_sel0 || DUAL_HW->ram_sel1!=retained.ram_sel1) { return 26; }
 begin("hardware",0);field(" round=",round);field(" session=",generation);
 field(" phase=",DUAL_HW->phase);field(" reset_clr=",DUAL_HW->reset_clr);
 field(" ram_sel0=",DUAL_HW->ram_sel0);field(" ram_sel1=",DUAL_HW->ram_sel1);
 field(" core_vtor=",DUAL_HW->core_vtor);field(" rc=",0);end();
 if(bes2700_mbox_reset(mailbox)) { return 22; }
 event(round,8,0,k_uptime_get_32()-start);
 begin("session",0);field(" round=",round);field(" session=",generation);
 field(" elapsed=",k_uptime_get_32()-start);field(" reset_held=",1);
 field(" peer_idle=",1);field(" channel_clean=",1);field(" rc=",0);end();return 0;
}
#endif
#if CONFIG_BES2700_M55_FAULT_CASE == 0
static int session_run(unsigned round)
{
 uint32_t start=k_uptime_get_32();int rc=session_start(round,start);
 return rc?rc:session_finish(round,start);
}
#endif
#ifdef CONFIG_BES2700_M55_RECOVERY
static uint32_t recovery_start;
static int recover_park(void *ctx)
{
 ARG_UNUSED(ctx);recovery_start=k_uptime_get_32();
 return session_park(1,recovery_start);
}
static int recover_rebuild(void *ctx)
{
 ARG_UNUSED(ctx);int rc=q_rearm();
 begin("worker_rebuilt",rc?44:0);field(" session=",generation);
 field(" rc=",rc?44:0);end();return rc;
}
static int recover_load(void *ctx) { ARG_UNUSED(ctx);return session_load(1,recovery_start); }
static int recover_release(void *ctx) { ARG_UNUSED(ctx);return session_release(1,recovery_start); }
static int recover_run(void *ctx) { ARG_UNUSED(ctx);return session_finish(1,recovery_start); }
#endif
#if CONFIG_BES2700_M55_FAULT_CASE > 0
static int stop_local(void *ctx) { ARG_UNUSED(ctx);return q_isolate(); }
static int hold_peer(void *ctx) { ARG_UNUSED(ctx);return reset_call(generation?generation-1:0,DUAL_STOP,41); }
static int confirm_peer(void *ctx) { ARG_UNUSED(ctx);return service(BES_LIFECYCLE_RESET_STATUS,0); }
static int clear_channel(void *ctx) { ARG_UNUSED(ctx);return bes2700_mbox_reset(mailbox); }

static int isolation_run(void)
{
 uint32_t start=k_uptime_get_32();int rc=session_start(0,start);
 struct dual_status peer={0};struct bes_peer_health health;
 enum bes_peer_fault fault=BES_PEER_OK;
 if(!rc) {
  fault=wait_ready(&health,&peer);
  if(!fault) {
   begin("ready",0);field(" round=",0);field(" session=",generation);
   field(" peer_ms=",peer.ms);field(" beat=",peer.beat);field(" stack=",peer.stack);
   field(" elapsed=",k_uptime_get_32()-start);field(" rc=",0);end();
   if(service(DUAL_CHECK_CLOCK,0)) { rc=16; }
   else {
    q_start();int64_t deadline=k_uptime_get()+BES_LIFECYCLE_READY_MS;
    while(!fault && !monitor_error && k_uptime_get()<deadline) {
     k_msleep(BES_PEER_POLL_MS);
     bool readable=peer_read(&peer)==0;
     fault=bes_peer_health_poll(&health,k_uptime_get(),readable,
                                readable && peer_ok(&peer),peer.beat);
    }
   }
  }
  /* AXI shared diagnostics only, never peer DTCM. Injection is evidence,
   * not an input to the reusable health decision. */
  uint32_t stage=DUAL_TRACE->stage;__DMB();uint32_t injection=DUAL_TRACE->reason;
  uint32_t age=(uint32_t)(k_uptime_get()-health.progress);
  begin("detected",0);field(" session=",generation);field(" reason=",fault);
  field(" age=",age);field(" beat=",health.beat);field(" trace_stage=",stage);
  field(" injection=",injection);field(" elapsed=",k_uptime_get_32()-start);field(" rc=",0);end();
  if(fault!=CONFIG_BES2700_M55_FAULT_CASE || stage!=BES_PEER_INJECTION_STAGE ||
     injection!=CONFIG_BES2700_M55_FAULT_CASE || monitor_error) { rc=40; }
 }
 /* Always attempt containment, including wrong injection/early failures.
  * No QUIESCE acknowledgement is required from the broken peer. */
 const struct bes_peer_isolation_ops ops={stop_local,hold_peer,confirm_peer,clear_channel};
 struct bes_peer_isolation contained;
 int containment_rc=bes_peer_isolate(&ops,NULL,&contained);
 if(containment_rc && !rc) { rc=41; }
 begin("isolated",containment_rc?41:0);field(" session=",generation);
 field(" local_idle=",contained.local_idle);field(" reset_held=",contained.reset_held);
 field(" channel_clean=",contained.channel_clean);field(" failed_step=",contained.failed_step);
 field(" service_rc=",(uint32_t)contained.service_rc);field(" rc=",containment_rc?41:0);end();
 if(!containment_rc) {
  int hw=service(DUAL_SNAPSHOT,DUAL_HW_ADDR);
  bool hw_bad=hw || DUAL_HW->phase!=4 || DUAL_HW->ram_sel0!=retained.ram_sel0 ||
              DUAL_HW->ram_sel1!=retained.ram_sel1;
  if(hw_bad && !rc) { rc=42; }
  begin("hardware",hw_bad?42:0);field(" round=",0);field(" session=",generation);
  field(" phase=",DUAL_HW->phase);field(" reset_clr=",DUAL_HW->reset_clr);
  field(" ram_sel0=",DUAL_HW->ram_sel0);field(" ram_sel1=",DUAL_HW->ram_sel1);
  field(" core_vtor=",DUAL_HW->core_vtor);field(" rc=",hw_bad?42:0);end();
 }
#ifdef CONFIG_BES2700_M55_RECOVERY
 struct bes_peer_recovery recovery={0};
 if(!rc && !containment_rc) {
  begin("recovery_begin",0);field(" old_session=",generation);
  field(" new_session=",generation+1);field(" limit=",1);field(" rc=",0);end();
  const struct bes_peer_recovery_ops recovery_ops={recover_park,recover_rebuild,
                                                  recover_load,recover_release,recover_run};
  if(bes_peer_recover(&recovery_ops,NULL,&contained,&recovery)) {
   rc=44;
   /* No second attempt, even if the peer reached READY before failing. */
   containment_rc=bes_peer_isolate(&ops,NULL,&contained);
   begin("recovery_failed",rc);field(" session=",generation);
   field(" step=",recovery.failed_step);field(" operation_rc=",(uint32_t)recovery.operation_rc);
   field(" local_idle=",contained.local_idle);field(" reset_held=",contained.reset_held);
   field(" channel_clean=",contained.channel_clean);field(" containment_rc=",(uint32_t)containment_rc);
   field(" rc=",rc);end();
  }
 }
#endif
 /* Keep independent BTH liveness after both expected and unexpected faults. */
 if(k_sem_take(&monitor_done,K_SECONDS(BES_LIFECYCLE_OBSERVE_SECONDS+1)) && !rc) { rc=31; }
 if(monitor_error && !rc) { rc=32; }
 if(!containment_rc) {
  struct bes2700_mbox_raw raw;bes2700_mbox_get_raw(mailbox,&raw);
  int held=service(BES_LIFECYCLE_RESET_STATUS,0);
  bool held_bad=held || ((raw.local|raw.peer)&0xaU);
  if(held_bad && !rc) { rc=43; }
  begin("held",held_bad?43:0);field(" session=",generation);field(" reset_held=",!held);
  field(" local_irq=",raw.local);field(" peer_irq=",raw.peer);
  field(" rc=",held_bad?43:0);end();
 }
#ifdef CONFIG_BES2700_M55_RECOVERY
 begin("recovery_result",rc);field(" pass=",!rc);field(" session=",generation);
 field(" reason=",fault);field(" samples=",monitor_samples);field(" releases=",releases);
 field(" attempts=",recovery.attempts);field(" recoveries=",recovery.completed);
#else
 begin("isolation_result",rc);field(" pass=",!rc);field(" session=",generation);
 field(" reason=",fault);field(" samples=",monitor_samples);field(" releases=",releases);
 field(" recoveries=",0);
#endif
 field(" rc=",rc);end();
 return rc;
}
#endif
int bes2700_lifecycle_validate(void)
{
 bth_stage("main");const volatile struct dual_service *api=(void *)DUAL_SERVICE_ADDR;
 uint32_t fn=api->dispatch;int rc=0;unsigned completed=0;
 uint32_t service_errors=dual_service_validate(api);
 uint32_t cpuid=SCB->CPUID,vtor=SCB->VTOR,control=__get_CONTROL(),ipsr=__get_IPSR();
 uint32_t primask=__get_PRIMASK(),basepri=__get_BASEPRI();
 uint32_t hz=BTH_DIAG->cpu_hz,guards=bth_guards_ok();
 uint32_t state_errors=(cpuid!=0x630f1321U?1U:0U) | (vtor!=BTH_CODE_BASE?2U:0U) |
  (control!=2U?4U:0U) | (ipsr?8U:0U) | (primask?16U:0U) | (basepri?32U:0U) |
  (hz!=DUAL_HZ?64U:0U) | (!guards?128U:0U);
 if(service_errors || state_errors) { rc=1; }
 if(!rc) { service=(void *)(uintptr_t)fn; }
 if(!rc && dual_image_check(m55_payload,sizeof(m55_payload),M55_PAYLOAD_CRC)) { rc=2; }
#if CONFIG_BES2700_M55_FAULT_CASE > 0
 begin("isolation_begin",rc);field(" version=",1);field(" layout=",BES_LIFECYCLE_LAYOUT);
 field(" build=",BTH_DIAG->build);field(" m55_build=",M55_BUILD_ID);field(" pair=",CONFIG_DUAL_CC_PAIR);
 field(" fault_case=",CONFIG_BES2700_M55_FAULT_CASE);field(" ready_ms=",BES_PEER_READY_MS);
 field(" heartbeat_ms=",BES_PEER_HEARTBEAT_MS);field(" duration=",BES_LIFECYCLE_OBSERVE_SECONDS);
 field(" rc=",rc);end();
#else
 begin("begin",rc);field(" version=",4);field(" layout=",BES_LIFECYCLE_LAYOUT);
 field(" build=",BTH_DIAG->build);field(" m55_build=",M55_BUILD_ID);
 field(" pair=",CONFIG_DUAL_CC_PAIR);field(" rounds=",BES_LIFECYCLE_ROUNDS);
 field(" restarts=",BES_LIFECYCLE_ROUNDS-1);field(" target=",BES_LIFECYCLE_TARGET);field(" duration=",BES_LIFECYCLE_OBSERVE_SECONDS);field(" rc=",rc);end();
#endif
 if(rc==1) {
  begin("precheck",rc);field(" dispatch=",fn);field(" service_layout=",api->layout);
  field(" service_errors=",service_errors);field(" state_errors=",state_errors);
  field(" cpuid=",cpuid);field(" vtor=",vtor);field(" control=",control);
  field(" ipsr=",ipsr);field(" primask=",primask);field(" basepri=",basepri);
  field(" hz=",hz);field(" guards=",guards);field(" rc=",rc);end();
 }
 if(!rc) {
  k_timer_start(&timer,K_MSEC(100),K_MSEC(100));k_sem_give(&monitor_start);
#if CONFIG_BES2700_M55_FAULT_CASE > 0
  (void)isolation_run();
  k_timer_stop(&timer);bth_log_reset();return 0;
#else
  for(unsigned i=0;i<BES_LIFECYCLE_ROUNDS;i++) {
   rc=session_run(i);if(rc || monitor_error) { if(!rc) { rc=30; }break; }completed++;
  }
  /* Peer held reset after all sessions; observe BTH to fixed 600s. */
  if(!rc && k_sem_take(&monitor_done,K_SECONDS(BES_LIFECYCLE_OBSERVE_SECONDS+1))) { rc=31; }
  if(!rc && monitor_error) { rc=32; }
#endif
 }
 k_timer_stop(&timer);k_thread_abort(r1_monitor);q_stop();
 if(rc && service) {
  /* Preserve failure evidence before the final attempt to hold CPU reset. */
  int snapshot_rc=service(DUAL_SNAPSHOT,DUAL_HW_ADDR);
  begin("fault",rc);field(" session=",generation);field(" rc=",rc);
  field(" snapshot_rc=",(uint32_t)snapshot_rc);
  if(!snapshot_rc) {
   /* SYS registers are accessible only after successful prepare/park. */
   struct bes2700_mbox_raw raw;
   bes2700_mbox_get_raw(mailbox,&raw);
   field(" phase=",DUAL_HW->phase);field(" reset_clr=",DUAL_HW->reset_clr);
   field(" ram_sel0=",DUAL_HW->ram_sel0);field(" ram_sel1=",DUAL_HW->ram_sel1);
   field(" local_irq=",raw.local);field(" peer_irq=",raw.peer);
  }
  end();
 }
 if(service) { (void)service(DUAL_STOP,0); }
 begin("result",rc);field(" pass=",!rc);field(" sessions=",completed);
 field(" restarts=",completed?completed-1:0);field(" samples=",monitor_samples);
 field(" rc=",rc);end();bth_log_reset();return 0;
}
