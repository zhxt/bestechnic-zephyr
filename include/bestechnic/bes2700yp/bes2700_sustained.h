/* SPDX-License-Identifier: Apache-2.0 */
#ifndef BES2700_SUSTAINED_H
#define BES2700_SUSTAINED_H
#include <stdint.h>
#include <stdbool.h>
#define CC_ADDR 0x2015c000U
#define CC_MAGIC 0x34434342U
#define CC_GUARD 0xcc445aa5U
#define CC_VERSION 4U
#define CC_SEED 0x27003301U
#define CC_LIMIT_REQUESTS 0x0fffffffU
/* Header + two single-writer lanes. Last 128 bytes reserved. */
struct cc_header { uint32_t magic, version, pair, session, bth_build, m55_build, duration, guard; uint32_t reserved[24]; };
#define CC_FIELDS(F) \
 F(magic) F(version) F(pair) F(session) F(build) F(phase) F(req) F(ack) \
 F(acked) F(handled) F(overlap) F(error) F(rx) F(requests) F(kicks) F(done) \
 F(queued) F(spurious) F(stack) F(max_wait) F(pauses) F(burst) F(seed) F(elapsed) F(stop_ms)
struct cc_lane {
 uint32_t seq;
#define CC_MEMBER(n) uint32_t n;
 CC_FIELDS(CC_MEMBER)
#undef CC_MEMBER
 uint32_t reserved[5], guard;
};
_Static_assert(sizeof(struct cc_header)==128,"header ABI");
_Static_assert(sizeof(struct cc_lane)==128,"lane ABI");
enum { CC_READY=1, CC_RUNNING, CC_STOPPING, CC_DRAIN, CC_QUIET, CC_DONE, CC_FAILED=255 };
enum { CC_IDENTITY=1, CC_SEQUENCE, CC_TIMEOUT, CC_SEND, CC_GUARDS, CC_IRQ,
       CC_STACK, CC_PEER, CC_PHASE, CC_SNAPSHOT, CC_LIMIT };

/* Pure transition used by the firmware and the host event-scheduler tests.
 * Duplicated wakeups are harmless; jumping/reversing application sequences is not.
 * Both sides publish request 1 before they can consume/acknowledge peer request 1.
 */
static inline int cc_step(struct cc_lane *s, const struct cc_lane *p,
                          uint32_t peer_build, bool *changed)
{
 *changed=false;
 if(p->magic!=CC_MAGIC || p->version!=CC_VERSION || p->pair!=s->pair ||
    p->session!=s->session || p->build!=peer_build || p->seed!=CC_SEED) { return CC_IDENTITY; }
 if(p->guard!=CC_GUARD) { return CC_GUARDS; }
 if(p->error || p->phase==CC_FAILED) { return CC_PEER; }
 if(p->phase<CC_READY || p->phase>CC_DONE) { return CC_PHASE; }
 if(p->req>CC_LIMIT_REQUESTS || p->ack>s->req || p->ack<s->acked ||
    p->req<s->ack || p->req-s->ack>1) { return CC_SEQUENCE; }
 if(p->req>s->ack) {
  if(s->req>s->acked) { s->overlap++; }
  s->ack=p->req; s->handled++; *changed=true;
 }
 s->acked=p->ack;
 if(s->req==s->acked && s->phase==CC_RUNNING) {
  if(s->req==CC_LIMIT_REQUESTS) { return CC_LIMIT; }
  s->req++; *changed=true;
 }
 return 0;
}
#endif
