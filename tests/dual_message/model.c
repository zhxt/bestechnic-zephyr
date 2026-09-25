/* SPDX-License-Identifier: Apache-2.0 */
/* Deterministic cooperative host scheduler runs the actual two worker sources.
 * Models signalling semantics only, not silicon IRQ timing or MMIO behavior. */
#define _GNU_SOURCE
#include "shim.h"
#include <bes2700_mbox.h>
#include "message.h"
#include <ucontext.h>
#include <sys/mman.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
struct fake_scb scb={0x411fd221,0,0};
struct device devices[2]={{0},{1}};
struct endpoint { struct bes2700_mbox_stats s; bool enabled,busy,pending,ack;
 mbox_callback_t cb;void *ctx;unsigned masked; } ep[2];
struct task { ucontext_t ctx;char stack[65536];int64_t wake;struct k_sem *sem;bool done; } task[2];
static ucontext_t scheduler;
static int current,mode;
static int64_t now;
static unsigned disabled_held[2];
static uint32_t last_acked[2];
static unsigned progress_samples;
static bool injected;
void run_bth(void);
void run_m55(void);
static void pump(void)
{
 /* Inject after both lanes have initialized, while real workers are live. */
 if((mode==3 || mode==4 || mode==5) && ((struct bi_ring *)(BI_BASE+4096))->state.sent>32) {
  struct bi_ring *ring=(void *)(BI_BASE+4096);
  if(mode==3) { ring->guards[0]=0; }
  if(mode==4) { ring->state.session++; }
  if(mode==5) { ring->head=ring->tail+17; }
 }
 if(mode==11 && !injected) {
  struct bi_ring *ring=(void *)(BI_BASE+4096);
  if(ring->state.sent>32 && ring->head!=ring->tail) {
   ring->slots[ring->tail%BI_DEPTH].payload[0]^=1;injected=true;
  }
 }
 for(unsigned pass=0;pass<8;pass++) for(int n=0;n<2;n++) {
  struct endpoint *s=&ep[n],*r=&ep[1-n];
  if(s->busy && !s->ack && !r->enabled) { disabled_held[1-n]++; }
  if(s->busy && !s->ack && r->enabled && !r->masked && mode!=1 && !(mode==9 && now>500)) {
   r->s.rx++;s->ack=true;
   if(r->cb) {
    r->cb(&devices[1-n],0,r->ctx,NULL);
    if(mode==7) { r->cb(&devices[1-n],0,r->ctx,NULL); }
   }
  }
  if(s->ack && !s->masked && mode!=2 && !(mode==10 && now>500)) {
   s->ack=false;s->s.done++;s->busy=s->pending;s->pending=false;
   if(s->busy) { s->s.kicks++; }
  }
 }
}
void bes2700_mbox_get_stats(const struct device *d,struct bes2700_mbox_stats *s) { pump();*s=ep[d->id].s; }
int mbox_send(const struct device *d,uint32_t ch,struct mbox_msg *msg)
{
 assert(!ch && !msg);struct endpoint *e=&ep[d->id];e->s.requests++;
 if(e->busy) { e->pending=true;e->s.queued++; } else { e->busy=true;e->s.kicks++; }
 pump();return 0;
}
int mbox_register_callback(const struct device *d,uint32_t ch,mbox_callback_t cb,void *ctx)
{ assert(!ch);ep[d->id].cb=cb;ep[d->id].ctx=ctx;return 0; }
int mbox_set_enabled(const struct device *d,uint32_t ch,bool en)
{ assert(!ch);ep[d->id].enabled=en;pump();return 0; }
unsigned irq_lock(void) { unsigned old=ep[current].masked;ep[current].masked=1;return old; }
void irq_unlock(unsigned k) { ep[current].masked=k;pump(); }
static void yield(void) { assert(swapcontext(&task[current].ctx,&scheduler)==0); }
int k_sem_take(struct k_sem *s,int64_t ms)
{
 pump();
 if(s->count) { s->count--;return 0; }
 task[current].sem=s;task[current].wake=ms<0?INT64_MAX:now+ms;yield();
 task[current].sem=NULL;
 if(s->count) { s->count--;return 0; }
 return -EAGAIN;
}
void k_sem_give(struct k_sem *s) { if(s->count<s->limit) { s->count++; } }
void k_msleep(int ms) { task[current].wake=now+ms;task[current].sem=NULL;yield(); }
void k_yield(void) { task[current].wake=now;task[current].sem=NULL;yield(); }
int64_t k_uptime_get(void) { return now; }
uint32_t k_uptime_get_32(void) { return now; }
static void start(int n)
{
 if(n==0) { run_bth(); } else { run_m55(); }
 task[n].done=true;
}
int main(int argc,char **argv)
{
 mode=argc>1?atoi(argv[1]):0;
 assert(mmap((void *)BI_BASE,BI_BYTES,PROT_READ|PROT_WRITE,MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0)==(void *)BI_BASE);
 q_prepare(0x12345678,0x123);
 for(int n=0;n<2;n++) {
  assert(getcontext(&task[n].ctx)==0);
  task[n].ctx.uc_stack.ss_sp=task[n].stack;task[n].ctx.uc_stack.ss_size=sizeof(task[n].stack);
  task[n].ctx.uc_link=&scheduler;makecontext(&task[n].ctx,(void (*)(void))start,1,n);
 }
 unsigned steps=0;
 while(!task[0].done) {
  bool progress=false;
  for(int order=0;order<2;order++) {
   int n=mode==6?1-order:order;
   if(!task[n].done && (now>=task[n].wake || (task[n].sem && task[n].sem->count))) {
   current=n;task[n].wake=now;assert(swapcontext(&scheduler,&task[n].ctx)==0);progress=true;
   }
  }
  if(!progress) { now=INT64_MAX;for(int n=0;n<2;n++) if(!task[n].done && task[n].wake<now) { now=task[n].wake; } }
  else { now+=mode==8?100:1; }
  if(CONFIG_DUAL_MSG_MODE==2 && (mode==0 || mode==6 || mode==7 || mode==8)) {
   struct q_report ongoing;q_snapshot(&ongoing);
   if(!ongoing.finished && ongoing.session && ongoing.bth.elapsed/2000>progress_samples) {
    assert(ongoing.bth.acked>last_acked[0] && ongoing.m55.acked>last_acked[1]);
    last_acked[0]=ongoing.bth.acked;last_acked[1]=ongoing.m55.acked;
    progress_samples=ongoing.bth.elapsed/2000;
   }
  }
  assert(now<(int64_t)CONFIG_DUAL_IPC_SECONDS*1000+40000 && steps++<2000000);
 }
 struct q_report r;q_snapshot(&r);
 assert(r.finished);printf("result mode=%d rc=%u state=%u/%u stage=%u/%u sent=%u/%u ack=%u/%u handled=%u/%u time=%lld\\n",mode,r.rc,r.bth.phase,r.m55.phase,r.bth.stage,r.m55.stage,r.bth.sent,r.m55.sent,r.bth.acked,r.m55.acked,r.bth.handled,r.m55.handled,(long long)now);fflush(stdout);
 if((mode>=1 && mode<=5) || mode>=9) { assert(r.rc!=0); } else {
  assert(r.rc==0 && r.bth.phase==Q_DONE && r.m55.phase==Q_DONE);
  assert(r.bth.sent==r.bth.acked && r.m55.sent==r.m55.acked);
  assert(r.bth.handled==r.m55.sent && r.m55.handled==r.bth.sent);
  assert(r.bth.sent>=10000 && r.m55.sent>=10000);
  if(CONFIG_DUAL_MSG_MODE==2) {
   assert(r.bth.stop_ms>=CONFIG_DUAL_IPC_SECONDS*1000U && r.m55.stop_ms>=CONFIG_DUAL_IPC_SECONDS*1000U);
   assert(progress_samples>=CONFIG_DUAL_IPC_SECONDS/2-2);
   assert(r.bth.pauses==1 && r.m55.pauses==1 && r.bth.full && r.m55.full);
  }
  assert(r.bth.rx==r.m55.kicks && r.m55.rx==r.bth.kicks);
  if(CONFIG_DUAL_MSG_MODE==3) {
   assert(r.bth.rejected==11 && r.m55.rejected==11);
   for(unsigned i=0;i<11;i++) {
    assert(r.cases[i].id==i+1 && r.cases[i].expected==r.cases[i].bth && r.cases[i].expected==r.cases[i].m55);
   }
  }

 }
 printf("message mode=%d duration=%u rc=%u acked=%u/%u bth_rx=%u m55_rx=%u time=%lld\n",mode,CONFIG_DUAL_IPC_SECONDS,r.rc,r.bth.acked,r.m55.acked,r.bth.rx,r.m55.rx,(long long)now);
 return 0;
}
