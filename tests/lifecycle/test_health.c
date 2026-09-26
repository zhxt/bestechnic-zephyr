/* SPDX-License-Identifier: Apache-2.0 */
#include <assert.h>
#include <bes2700_peer_health.h>
static unsigned calls, fail;
static int operation(unsigned step) { assert(++calls==step);return fail==step?-17:0; }
static int local(void *p) { (void)p;return operation(1); }
static int reset(void *p) { (void)p;return operation(2); }
static int confirm(void *p) { (void)p;return operation(3); }
static int clear(void *p) { (void)p;return operation(4); }
int main(void)
{
 struct bes_peer_health h;
 /* No READY, including a permanently odd/unreadable publication. */
 bes_peer_health_init(&h,100);
 assert(!bes_peer_health_poll(&h,5099,false,false,0));
 assert(bes_peer_health_poll(&h,5100,false,false,0)==BES_PEER_READY_TIMEOUT);
 assert(h.state==BES_PEER_FAULT);
 assert(bes_peer_health_poll(&h,5101,true,true,1)==BES_PEER_READY_TIMEOUT);
 /* A late READY cannot repair a deadline already expired. */
 bes_peer_health_init(&h,0);
 assert(bes_peer_health_poll(&h,5000,true,true,1)==BES_PEER_READY_TIMEOUT);
 bes_peer_health_init(&h,0);
 assert(!bes_peer_health_poll(&h,4999,true,true,1));
 assert(h.state==BES_PEER_RUNNING);
 assert(!bes_peer_health_poll(&h,5998,true,true,1));
 assert(bes_peer_health_poll(&h,5999,true,true,1)==BES_PEER_HEARTBEAT_TIMEOUT);
 /* Late progress is not accepted; heartbeat faults remain latched. */
 assert(bes_peer_health_poll(&h,6000,true,true,2)==BES_PEER_HEARTBEAT_TIMEOUT);
 bes_peer_health_init(&h,0);
 assert(!bes_peer_health_poll(&h,1,true,true,1));
 assert(bes_peer_health_poll(&h,1001,true,true,2)==BES_PEER_HEARTBEAT_TIMEOUT);
 /* Healthy idle peer: heartbeat, not business counters, is the liveness input. */
 bes_peer_health_init(&h,0);
 for(unsigned i=1;i<2000;i++) {
  assert(!bes_peer_health_poll(&h,i*100,true,true,i));
 }
 /* Brief unreadability neither fails immediately nor refreshes progress. */
 assert(!bes_peer_health_poll(&h,200000,false,false,0));
 assert(bes_peer_health_poll(&h,200900,false,false,0)==BES_PEER_HEARTBEAT_TIMEOUT);
 /* Natural heartbeat wrap accepted; regression and invalid state rejected. */
 bes_peer_health_init(&h,0);
 assert(!bes_peer_health_poll(&h,1,true,true,0xffffffffU));
 assert(!bes_peer_health_poll(&h,101,true,true,0));
 assert(bes_peer_health_poll(&h,201,true,true,0xffffffffU)==BES_PEER_INVALID);
 bes_peer_health_init(&h,0);
 assert(!bes_peer_health_poll(&h,1,true,true,1));
 assert(bes_peer_health_poll(&h,2,true,false,2)==BES_PEER_INVALID);
 bes_peer_health_init(&h,100);
 assert(bes_peer_health_poll(&h,99,false,false,0)==BES_PEER_INVALID);
 /* Faults in every isolation step block all later hardware actions. */
 const struct bes_peer_isolation_ops ops={local,reset,confirm,clear};
 for(fail=0;fail<=4;fail++) {
  struct bes_peer_isolation r;calls=0;
  assert(bes_peer_isolate(&ops,0,&r)==(fail?-1:0));
  assert(calls==(fail?fail:4));
  assert(r.failed_step==fail && r.service_rc==(fail?-17:0));
  assert(r.local_idle==(fail!=1));
  assert(r.reset_held==(!fail || fail==4));
  assert(r.channel_clean==(!fail));
 }
 return 0;
}
