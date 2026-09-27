/* SPDX-License-Identifier: Apache-2.0 */
#include <cmsis_core.h>
#include <zephyr/kernel.h>
#include <zephyr/drivers/mbox.h>
#include <bes2700_mbox.h>
#include "message.h"
#ifdef CC_BTH
#include "m55_payload.h"
#define SIDE 0
#else
#define SIDE 1
#endif
#define RING(n) ((volatile struct bi_ring *)(BI_BASE+4096U*(n)))
#define OUT RING(SIDE)
#define IN RING(1-SIDE)
#ifdef CONFIG_BES2700_M55_RESTART
#include <bes2700_lifecycle.h>
#define Q_TARGET BES_LIFECYCLE_TARGET
static volatile uint32_t worker_idle;
int q_idle(void) { __DMB();return worker_idle; }
#ifdef CC_BTH
K_SEM_DEFINE(q_stopped,0,1);
int q_wait_idle(int milliseconds) { return k_sem_take(&q_stopped,K_MSEC(milliseconds)); }
#endif
#else
#define Q_TARGET 10000U
#endif
K_SEM_DEFINE(q_received,0,1);
#ifdef CC_BTH
K_SEM_DEFINE(q_started,0,1);
static struct k_spinlock report_lock;
static struct q_report report;
#if CONFIG_BES2700_M55_FAULT_CASE > 0
static bool isolated;
#endif
#endif
static const struct device *const mailbox=DEVICE_DT_GET(DT_NODELABEL(mbox_peer));
static struct q_state own, other;
static int64_t active_start, sent_at[BI_DEPTH];
static uint32_t peer_build;
static struct q_case cases[11];

static void publish(void)
{
 volatile struct q_state *s=&OUT->state;
 s->seq++;__DMB();
#define STORE(n) s->n=own.n;
 Q_FIELDS(STORE)
#undef STORE
 s->error=own.error;s->guard=own.guard;__DMB();s->seq++;__DMB();
}
/* A writer may be preempted with seq odd. CPU-speed-dependent spin counts
 * cannot distinguish that transient condition from a stalled peer. Retry at
 * most 20 ms, yielding between attempts, and never extend a caller deadline. */
static int snapshot_until(int64_t deadline)
{
 volatile struct q_state *s=&IN->state;
 const int64_t end=MIN(deadline,k_uptime_get()+20);
 for(;;) {
  struct q_state candidate;
  uint32_t seq=s->seq;
  if(!(seq&1)) {
   __DMB();uint32_t *d=(void *)&candidate;const volatile uint32_t *p=(void *)s;
   for(unsigned i=0;i<sizeof(candidate)/4;i++) { d[i]=p[i]; }
   __DMB();
   if(seq==s->seq && seq==candidate.seq) { other=candidate;return 0; }
  }
  if(k_uptime_get()>=end) { return Q_SNAPSHOT; }
  k_msleep(1);
 }
}
static int snapshot(void) { return snapshot_until(k_uptime_get()+20); }
static int valid(void)
{
 if(other.magic!=Q_META_MAGIC || other.version!=BI_VERSION || other.layout!=Q_LAYOUT ||
    other.pair!=CONFIG_DUAL_CC_PAIR || other.session!=own.session || other.build!=peer_build) { return Q_IDENTITY; }
 if(other.guard!=Q_META_GUARD) { return Q_GUARDS; }
 if(other.error || other.phase==Q_FAILED) { return Q_PEER; }
 if(other.phase<Q_READY || other.phase>Q_DONE) { return Q_PHASE; }
 return 0;
}
static void callback(const struct device *d,uint32_t c,void *ctx,struct mbox_msg *msg)
{ ARG_UNUSED(d);ARG_UNUSED(c);ARG_UNUSED(ctx);ARG_UNUSED(msg);k_sem_give(&q_received); }
static int notify(void) { return mbox_send(mailbox,0,NULL)?Q_SEND:0; }
static int wait_event(int64_t end)
{
 int64_t left=end-k_uptime_get();
 if(left<=0 || k_sem_take(&q_received,K_MSEC(left))) { return Q_TIMEOUT; }
 int rc=snapshot_until(end);return rc?rc:valid();
}
static int stats(void)
{
 struct bes2700_mbox_stats s;bes2700_mbox_get_stats(mailbox,&s);
 own.rx=s.rx;own.requests=s.requests;own.kicks=s.kicks;own.done=s.done;
 own.queued=s.queued;own.spurious=s.spurious;
 size_t free=0;if(k_thread_stack_space_get(k_current_get(),&free) || free<128) { return Q_STACK; }
 own.stack=free;own.elapsed=(uint32_t)(k_uptime_get()-active_start);
 return s.spurious?Q_IRQ:0;
}
static void update_report(uint32_t finished,uint32_t rc)
{
#ifdef CC_BTH
 struct q_report r={.finished=finished,.rc=rc,.session=own.session,.bth=own,.m55=other};
 for(unsigned i=0;i<11;i++) { r.cases[i]=cases[i]; }
 k_spinlock_key_t key=k_spin_lock(&report_lock);report=r;k_spin_unlock(&report_lock,key);
#else
 ARG_UNUSED(finished);ARG_UNUSED(rc);
#endif
}
static int quiet(void)
{
 own.phase=Q_DRAIN;publish();int rc=notify();if(rc) { return rc; }
 int64_t end=k_uptime_get()+2000;
 if((rc=snapshot()) || (rc=valid())) { return rc; }
 while(other.stage==own.stage && other.phase<Q_DRAIN) { if((rc=wait_event(end))) { return rc; } }
 /* Requests are already completed. Poll only final IRQ/statistics publication. */
 do {
  if((rc=stats())) { return rc; }
  if(own.kicks==own.done) { break; }
  if(k_uptime_get()>=end) { return Q_TIMEOUT; }k_msleep(1);
 } while(true);
 own.phase=Q_QUIET;publish();
 do {
  if((rc=snapshot()) || (rc=valid())) { return rc; }
  if(other.stage>own.stage || other.phase>=Q_QUIET) { break; }
  if(k_uptime_get()>=end) { return Q_TIMEOUT; }k_msleep(1);
 } while(true);
 if((rc=stats())) { return rc; }
 own.phase=Q_DONE;publish();
 do {
  if((rc=snapshot()) || (rc=valid())) { return rc; }
  if(other.stage>own.stage || other.phase==Q_DONE) { break; }
  if(k_uptime_get()>=end) { return Q_TIMEOUT; }k_msleep(1);
 } while(true);
 return 0;
}
static int negative(unsigned id)
{
 /* Both queue directions inject the same named case. No normal data producer
  * runs during a case. Control words are restored only by their owner after
  * the peer has explicitly acknowledged detection. */
 int rc;unsigned stage=id+2;own.stage=stage;own.phase=Q_READY;publish();if((rc=notify())) { return rc; }
 int64_t end=k_uptime_get()+2000;
 if((rc=snapshot()) || (rc=valid())) { return rc; }
 while(other.stage<stage) { if((rc=wait_event(end))) { return rc; } }
 if(other.stage!=stage) { return Q_PHASE; }
 own.phase=Q_RUNNING;publish();
 uint32_t expected=BI_HEADER,head=OUT->head,bit=1U<<(id-1);
 if(id<=9) {
  struct bi_frame f;bi_make(&f,own.session,own.sent+1,BI_DATA,32,SIDE);
  switch(id) {
  case 1: f.crc^=1;expected=BI_CRC;break;
  case 2: f.length=97;break;
  case 3: f.session++;expected=BI_SESSION;break;
  case 4: bi_make(&f,own.session,own.sent,BI_DATA,0,SIDE);expected=BI_SEQ;break;
  case 5: f.sequence=own.sent+2;expected=BI_SEQ;break;
  case 6: f.version++;break;
  case 7: f.magic^=1;break;
  case 8: f.type=255;break;
  case 9: f.reserved=1;break;
  }
  if(id!=1) { f.crc=bi_crc(&f); }
  if(bi_push(OUT,&f)!=BI_OK) { return Q_SEQUENCE; }
 } else if(id==10) { OUT->head=OUT->tail+BI_DEPTH+1;expected=BI_INDEX; }
 else { OUT->guards[0]^=1;expected=Q_GUARDS; }
 __DMB();if((rc=notify())) { return rc; }
 uint32_t observed=0;
 for(;;) {
  if((rc=wait_event(end))) { return rc; }
  if(id==10) { if(IN->head-IN->tail<=BI_DEPTH) { continue; }observed=BI_INDEX; }
  else if(id==11) { if(bi_guards_ok(IN)) { continue; }observed=Q_GUARDS; }
  else {
   struct bi_frame f;enum bi_rc br=bi_pop(IN,&f);
   if(br==BI_EMPTY) { continue; }
   if(br!=BI_OK) { return Q_SEQUENCE; }
   observed=bi_validate(&f,own.session,own.handled+1);
  }
  if(observed!=expected) { return Q_FRAME; }
  break;
 }
 own.rejected++;IN->consumer.rejected=own.rejected;IN->consumer.observed=observed;__DMB();
 IN->consumer.fault|=bit;__DMB();publish();if((rc=notify())) { return rc; }
 while(!(OUT->consumer.fault&bit)) { if((rc=wait_event(end))) { return rc; } }
 if(id==10) { OUT->head=head; }
 if(id==11) { OUT->guards[0]^=1; }
 __DMB();own.phase=Q_STOPPING;publish();if((rc=notify())) { return rc; }
 if((rc=snapshot()) || (rc=valid())) { return rc; }
 while(other.stage==stage && other.phase<Q_STOPPING) { if((rc=wait_event(end))) { return rc; } }
 if(!bi_guards_ok(OUT) || !bi_guards_ok(IN) || OUT->head!=OUT->tail || IN->head!=IN->tail) { return Q_SEQUENCE; }
 if((rc=quiet())) { return rc; }
 uint32_t peer_observed=OUT->consumer.observed;
 if(peer_observed!=expected) { return Q_FRAME; }
 cases[id-1]=(struct q_case){id,expected,SIDE?peer_observed:observed,SIDE?observed:peer_observed};
 return 0;
}
static int run_stage(unsigned stage,unsigned direction,uint32_t target)
{
 int rc;uint32_t base_sent=own.sent,base_handled=own.handled;
 bool sequential=CONFIG_DUAL_MSG_MODE!=2;
 bool sender=!sequential || SIDE==direction;
 bool receiver=!sequential || SIDE!=direction;
 own.stage=stage;own.phase=Q_READY;publish();if((rc=notify())) { return rc; }
 int64_t end=k_uptime_get()+2000;
 if((rc=snapshot()) || (rc=valid())) { return rc; }
 while(other.stage<stage) { if((rc=wait_event(end))) { return rc; } }
 if(other.stage!=stage) { return Q_PHASE; }
 own.phase=Q_RUNNING;publish();if((rc=notify())) { return rc; }
 int64_t progress=k_uptime_get(),reported=progress;
 const int64_t stop=active_start+(int64_t)CONFIG_DUAL_IPC_SECONDS*1000;
 bool first=true,paused=false;
 for(;;) {
  int64_t now=k_uptime_get();bool changed=false;
  if(!first) {
   int64_t deadline=progress+2000;
   if(own.sent>own.acked) { deadline=MIN(deadline,sent_at[own.acked%BI_DEPTH]+2000); }
   if(!sequential && own.phase==Q_RUNNING) { deadline=MIN(deadline,stop); }
   rc=wait_event(deadline);
   if(rc && !(rc==Q_TIMEOUT && !sequential && own.phase==Q_RUNNING && deadline==stop && k_uptime_get()>=stop)) { return rc; }
   now=k_uptime_get();
  }
  first=false;
  if(!bi_guards_ok(OUT) || !bi_guards_ok(IN)) { return Q_GUARDS; }
  if(OUT->head-OUT->tail>BI_DEPTH || IN->head-IN->tail>BI_DEPTH) { return Q_SEQUENCE; }
  uint32_t completed=OUT->consumer.completed;__DMB();
  if(completed<own.acked || completed>own.sent || completed-own.acked>BI_DEPTH) { return Q_SEQUENCE; }
  while(own.acked<completed) {
   uint32_t wait=(uint32_t)(now-sent_at[own.acked%BI_DEPTH]);
   if(wait>2000) { return Q_TIMEOUT; }
   own.max_wait=MAX(own.max_wait,wait);own.acked++;progress=now;changed=true;
  }
  /* Force a real full queue before receiver starts consuming it. Producer must
   * continue servicing the reverse queue while its own queue is full. */
  if(!sequential && !paused && IN->head-IN->tail==BI_DEPTH) {
   k_msleep(200);paused=true;own.pauses++;now=k_uptime_get();
  }
  for(unsigned budget=0;budget<BI_DEPTH && (sequential || paused);budget++) {
   struct bi_frame frame;enum bi_rc br=bi_pop(IN,&frame);
   if(br==BI_EMPTY) { break; }
   if(br!=BI_OK || !receiver) { return Q_SEQUENCE; }
   if(bi_validate(&frame,own.session,own.handled+1)!=BI_OK || frame.type!=BI_DATA) { return Q_FRAME; }
   if(!bi_pattern_ok(&frame,1-SIDE)) { return Q_PATTERN; }
   uint32_t bit=1U<<(frame.length%32);
   switch(frame.length/32) {
   case 0: own.len0|=bit;break;case 1: own.len1|=bit;break;
   case 2: own.len2|=bit;break;default: own.len3|=bit;break;
   }
   own.handled++;__DMB();IN->consumer.completed=own.handled;__DMB();
   progress=now;changed=true;
  }
  if(own.phase==Q_RUNNING && ((!sequential && now>=stop) ||
      (sequential && (!sender || own.sent-base_sent==target) &&
       (!receiver || own.handled-base_handled==target) && own.acked==own.sent))) {
   own.phase=Q_STOPPING;own.stop_ms=(uint32_t)(now-active_start);changed=true;
  }
  if(own.phase==Q_RUNNING && sender) {
   for(unsigned budget=0;budget<=BI_DEPTH;budget++) {
    if(sequential && own.sent-base_sent>=target) { break; }
    /* Application ACK, not tail alone, returns send-window credit. */
    if(own.sent-own.acked==BI_DEPTH) { own.full++;break; }
    if(own.sent==0x7fffffffU) { return Q_SEQUENCE; }
    struct bi_frame frame;bi_make(&frame,own.session,own.sent+1,BI_DATA,own.sent%97,SIDE);
    enum bi_rc br=bi_push(OUT,&frame);if(br==BI_FULL) { own.full++;break; }
    if(br!=BI_OK) { return Q_SEQUENCE; }
    sent_at[own.sent%BI_DEPTH]=now;own.sent++;own.depth=MAX(own.depth,own.sent-own.acked);changed=true;
   }
  }
  own.elapsed=(uint32_t)(now-active_start);
  if(now-reported>=1000 && (rc=stats())) { return rc; }
  if(changed) { publish();if((rc=notify())) { return rc; } }
  if(now-reported>=1000) { publish();update_report(0,0);reported=now; }
  if(own.phase==Q_STOPPING && other.stage==stage && other.phase>=Q_STOPPING &&
     own.sent==own.acked && own.handled==other.sent && IN->head==IN->tail && OUT->head==OUT->tail) {
   return quiet();
  }
  if(now-progress>2000 || (!sequential && now>stop+5000)) { return Q_TIMEOUT; }
 }
}
static int exercise(void)
{
 /* BTH publishes the boot identity before releasing M55. */
 volatile struct q_state *b=&RING(0)->state;
 if(b->magic!=Q_META_MAGIC || b->version!=BI_VERSION || b->layout!=Q_LAYOUT ||
    b->pair!=CONFIG_DUAL_CC_PAIR || !b->session || b->guard!=Q_META_GUARD) { return Q_IDENTITY; }
 own=(struct q_state){.magic=Q_META_MAGIC,.version=BI_VERSION,.layout=Q_LAYOUT,
  .pair=CONFIG_DUAL_CC_PAIR,.session=b->session,.phase=Q_READY,.guard=Q_META_GUARD};
#ifdef CC_BTH
 own.build=b->build;peer_build=M55_BUILD_ID;
#else
 own.build=CONFIG_DUAL_M55_BUILD;peer_build=b->build;
#endif
 active_start=k_uptime_get();
 if(!device_is_ready(mailbox) || mbox_register_callback(mailbox,0,callback,NULL) ||
    mbox_set_enabled(mailbox,0,true)) { return Q_IRQ; }
 publish();int rc=notify();if(rc) { return rc; }
 int64_t end=k_uptime_get()+30000;
 if((rc=snapshot())) { return rc; }
 while(!other.magic) {
  int64_t remain=end-k_uptime_get();
  if(remain<=0 || k_sem_take(&q_received,K_MSEC(remain))) { return Q_TIMEOUT; }
  if((rc=snapshot())) { return rc; }
 }
 if((rc=valid())) { return rc; }
 active_start=k_uptime_get();
 if(CONFIG_DUAL_MSG_MODE==3) {
  /* Deliver one real frame per direction before injecting a byte-identical
   * duplicate of that frame. Then prove traffic resumes after all rejections. */
  if((rc=run_stage(1,0,1)) || (rc=run_stage(2,1,1))) { return rc; }
  for(unsigned id=1;id<=11;id++) { if((rc=negative(id))) { return rc; } }
 }
 unsigned first=CONFIG_DUAL_MSG_MODE==3?14:1;
 unsigned stages=CONFIG_DUAL_MSG_MODE==2?1:2;
 for(unsigned stage=first;stage<first+stages;stage++) {
  if((rc=run_stage(stage,stage-first,Q_TARGET-(CONFIG_DUAL_MSG_MODE==3?1:0)))) { return rc; }
 }
 if(own.len0!=0xffffffffU || own.len1!=0xffffffffU || own.len2!=0xffffffffU || own.len3!=1) { return Q_COVERAGE; }
#ifdef CC_BTH
 if(own.sent!=other.handled || own.handled!=other.sent || own.acked!=own.sent || other.acked!=other.sent ||
    own.rx!=other.kicks || own.kicks!=other.rx || own.done!=own.kicks || other.done!=other.kicks) { return Q_SEQUENCE; }
#endif
 return 0;
}
static void worker(void *a,void *b,void *c)
{
 ARG_UNUSED(a);ARG_UNUSED(b);ARG_UNUSED(c);
#if defined(CONFIG_BES2700_M55_RESTART) && defined(CC_BTH)
 for(;;) {
#endif
#ifdef CC_BTH
 k_sem_take(&q_started,K_FOREVER);
#endif
#ifdef CONFIG_BES2700_M55_RESTART
 worker_idle=0;
#endif
 int rc=exercise();
 if(rc) { own.error=rc;own.phase=Q_FAILED;(void)stats();publish();(void)notify(); }
 update_report(1,rc);
#ifdef CONFIG_BES2700_M55_RESTART
 (void)mbox_set_enabled(mailbox,0,false);
 __DSB();worker_idle=1;__DMB();
#ifdef CC_BTH
 k_sem_give(&q_stopped);
 }
#endif
#endif
}
#if defined(CC_BTH) && defined(CONFIG_BES2700_M55_RECOVERY)
K_THREAD_STACK_DEFINE(q_stack,4096);
static struct k_thread q_thread;
static k_tid_t const q_worker=&q_thread;
static bool worker_created, worker_dormant;
static void create_worker(void)
{
 k_thread_create(q_worker,q_stack,K_THREAD_STACK_SIZEOF(q_stack),worker,
                 NULL,NULL,NULL,5,0,K_FOREVER);
 worker_created=true;worker_dormant=true;
}
#else
K_THREAD_DEFINE(q_worker,4096,worker,NULL,NULL,NULL,5,0,0);
#endif
#ifdef CC_BTH
void q_prepare(uint32_t build,uint32_t session)
{
#if CONFIG_BES2700_M55_FAULT_CASE > 0
 if(isolated) { return; }
#endif
#ifdef CONFIG_BES2700_M55_RECOVERY
 if(!worker_created) { create_worker(); }
#endif
#ifdef CONFIG_BES2700_M55_RESTART
 /* Caller has consumed q_stopped before later sessions. Worker is blocked. */
 k_sem_reset(&q_received);
 k_spinlock_key_t key=k_spin_lock(&report_lock);
 report=(struct q_report){0};
 k_spin_unlock(&report_lock,key);
 own=(struct q_state){0};other=(struct q_state){0};
 for(unsigned i=0;i<BI_DEPTH;i++) { sent_at[i]=0; }
#endif
 volatile uint32_t *p=(void *)BI_BASE;
 for(unsigned i=0;i<BI_BYTES/4;i++) { p[i]=0; }
 bi_init(RING(0));bi_init(RING(1));
 RING(0)->state=(struct q_state){.magic=Q_META_MAGIC,.version=BI_VERSION,.layout=Q_LAYOUT,
  .pair=CONFIG_DUAL_CC_PAIR,.build=build,.session=session?session:1,.phase=Q_READY,.guard=Q_META_GUARD};
 __DSB();
}
void q_start(void)
{
#if CONFIG_BES2700_M55_FAULT_CASE > 0
 if(isolated) { return; }
#endif
#ifdef CONFIG_BES2700_M55_RECOVERY
 if(!worker_created) { return; }
 if(worker_dormant) { worker_idle=0;worker_dormant=false;k_thread_start(q_worker); }
#endif
 k_sem_give(&q_started);
}
#if CONFIG_BES2700_M55_FAULT_CASE > 0
/* UP only: abort returns after the worker can no longer access shared RAM.
 * This worker owns no mutexes or allocated resources. IRQs are masked first;
 * its callback only posts q_received, and cannot outlive this UP call. */
#ifdef CONFIG_SMP
#error "Worker isolation requires a uniprocessor Zephyr image"
#endif
int q_isolate(void)
{
 isolated=true;
 int rc=bes2700_mbox_suspend(mailbox);
#ifdef CONFIG_BES2700_M55_RECOVERY
 if(worker_created) { k_thread_abort(q_worker); }
#else
 k_thread_abort(q_worker);
#endif
 __DSB();worker_idle=1;__DMB();
 return rc;
}
#endif
#ifdef CONFIG_BES2700_M55_RECOVERY
/* Called after successful containment and REPARK, with mailbox still masked.
 * Does not touch shared RAM. The new thread remains dormant until q_start(). */
int q_rearm(void)
{
 if(!isolated || !worker_idle || !worker_created || k_thread_join(q_worker,K_NO_WAIT)) {
  return -EBUSY;
 }
 k_sem_reset(&q_started);k_sem_reset(&q_stopped);k_sem_reset(&q_received);
 k_spinlock_key_t key=k_spin_lock(&report_lock);
 report=(struct q_report){0};k_spin_unlock(&report_lock,key);
 own=(struct q_state){0};other=(struct q_state){0};active_start=0;peer_build=0;
 for(unsigned i=0;i<BI_DEPTH;i++) { sent_at[i]=0; }
 for(unsigned i=0;i<11;i++) { cases[i]=(struct q_case){0}; }
 create_worker();isolated=false;return 0;
}
#endif
void q_stop(void)
{
#ifdef CONFIG_BES2700_M55_RECOVERY
 if(worker_created) { k_thread_abort(q_worker); }
#else
 k_thread_abort(q_worker);
#endif
 (void)mbox_set_enabled(mailbox,0,false);
}
void q_snapshot(struct q_report *out)
{ k_spinlock_key_t key=k_spin_lock(&report_lock);*out=report;k_spin_unlock(&report_lock,key); }
#endif
