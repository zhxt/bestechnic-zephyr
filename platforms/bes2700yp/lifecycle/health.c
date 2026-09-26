/* SPDX-License-Identifier: Apache-2.0 */
#include <bes2700_peer_health.h>

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
