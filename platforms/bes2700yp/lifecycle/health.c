/* SPDX-License-Identifier: Apache-2.0 */
#include <bes2700_peer_health.h>

void bes_peer_progress_init(struct bes_peer_progress *p, int64_t now)
{
 *p=(struct bes_peer_progress){.progress=now};
}

enum bes_peer_fault bes_peer_progress_poll(struct bes_peer_progress *p,
 int64_t now, bool pending, uint32_t acked, uint32_t handled)
{
 if(now<p->progress || (uint32_t)(acked-p->acked)>=0x80000000U ||
    (uint32_t)(handled-p->handled)>=0x80000000U) { return BES_PEER_INVALID; }
 /* Late progress cannot conceal an already elapsed busy deadline. */
 if(p->pending && now-p->progress>=BES_PEER_IPC_MS) { return BES_PEER_IPC_TIMEOUT; }
 if(!pending || !p->pending || acked!=p->acked || handled!=p->handled) { p->progress=now; }
 p->pending=pending;p->acked=acked;p->handled=handled;return BES_PEER_OK;
}

void bes_peer_health_init(struct bes_peer_health *h, int64_t now)
{
 *h=(struct bes_peer_health){.state=BES_PEER_STARTING,.started=now,.progress=now};
}

enum bes_peer_fault bes_peer_health_poll(struct bes_peer_health *h,
 int64_t now, bool readable, bool valid, uint32_t beat)
{
 if(h->state==BES_PEER_FAULT) { return h->fault; }
 if(now<h->progress) { h->fault=BES_PEER_INVALID; }
 else if(h->state==BES_PEER_STARTING) {
  /* READY arriving after the deadline cannot turn a timeout into success. */
  if(now-h->started>=BES_PEER_READY_MS) { h->fault=BES_PEER_READY_TIMEOUT; }
  else if(readable && valid && beat) {
   h->state=BES_PEER_RUNNING;h->beat=beat;h->progress=now;
  }
 } else if(now-h->progress>=BES_PEER_HEARTBEAT_MS) {
  h->fault=BES_PEER_HEARTBEAT_TIMEOUT;
 } else if(readable) {
  /* Accept uint32 wrap, reject regression and implausible half-range jumps. */
  if(!valid || (uint32_t)(beat-h->beat)>=0x80000000U) { h->fault=BES_PEER_INVALID; }
  else if(beat!=h->beat) { h->beat=beat;h->progress=now; }
 }
 if(h->fault) { h->state=BES_PEER_FAULT; }
 return h->fault;
}

int bes_peer_isolate(const struct bes_peer_isolation_ops *ops, void *context,
 struct bes_peer_isolation *r)
{
 *r=(struct bes_peer_isolation){0};
 r->failed_step=1;r->service_rc=ops->stop_local(context);
 if(r->service_rc) { return -1; }
 r->local_idle=1;
 r->failed_step=2;r->service_rc=ops->hold_reset(context);
 if(r->service_rc) { return -1; }
 r->failed_step=3;r->service_rc=ops->confirm_reset(context);
 if(r->service_rc) { return -1; }
 r->reset_held=1;
 r->failed_step=4;r->service_rc=ops->clear_channel(context);
 if(r->service_rc) { return -1; }
 r->channel_clean=1;r->failed_step=0;
 return 0;
}

int bes_peer_recover(const struct bes_peer_recovery_ops *ops, void *context,
 const struct bes_peer_isolation *isolated, struct bes_peer_recovery *r)
{
 if(r->attempts || isolated->local_idle!=1 || isolated->reset_held!=1 ||
    isolated->channel_clean!=1 || isolated->failed_step || isolated->service_rc) {
  return -1;
 }
 r->attempts=1;r->completed=0;
 int (*const steps[])(void *)={ops->park,ops->rebuild,ops->load,ops->release,ops->run};
 for(unsigned i=0;i<sizeof(steps)/sizeof(steps[0]);i++) {
  r->failed_step=i+1;r->operation_rc=steps[i](context);
  if(r->operation_rc) { return -1; }
 }
 r->failed_step=0;r->completed=1;return 0;
}
