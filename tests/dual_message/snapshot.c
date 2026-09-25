/* SPDX-License-Identifier: Apache-2.0 */
/* Exercise the actual snapshot reader with deterministic writer preemption.
 * Barrier hooks model a peer publishing between the reader's copies. */
#define _GNU_SOURCE
#include <string.h>
#include <sys/mman.h>
#include <stdio.h>
static void barrier(void);
#define __DMB() barrier()
#include "worker.c"
struct device devices[2]={{0},{1}};
static int64_t now, release_at;
static unsigned sleeps, barriers;
static int scenario;
int64_t k_uptime_get(void) { return now; }
void k_msleep(int ms)
{
 assert(ms==1);now++;sleeps++;
 if(scenario==1 && now==release_at) { IN->state.seq++; }
}
static void barrier(void)
{
 barriers++;
 /* Change the writer after the copy, once or continuously. */
 if((scenario==2 && barriers==2) || (scenario==3 && !(barriers&1))) {
  IN->state.seq+=2;IN->state.sent++;
 }
}
static void reset(int kind)
{
 memset((void *)BI_BASE,0,BI_BYTES);memset(&other,0xa5,sizeof(other));
 now=100;release_at=105;sleeps=barriers=0;scenario=kind;
 own=(struct q_state){.session=123};peer_build=456;
 IN->state=(struct q_state){.seq=2,.magic=Q_META_MAGIC,.version=BI_VERSION,
  .layout=Q_LAYOUT,.pair=CONFIG_DUAL_CC_PAIR,.session=123,.build=456,
  .phase=Q_RUNNING,.guard=Q_META_GUARD,.sent=50};
}
int main(void)
{
 assert(mmap((void *)BI_BASE,BI_BYTES,PROT_READ|PROT_WRITE,
  MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0)==(void *)BI_BASE);
 reset(0);assert(snapshot()==0 && sleeps==0 && other.sent==50 && valid()==0);
 reset(1);IN->state.seq=3;
 assert(snapshot()==0 && now==105 && sleeps==5 && other.seq==4);
 reset(2);assert(snapshot()==0 && sleeps==1 && other.sent==51 && other.seq==4);
 reset(3);struct q_state saved=other;
 assert(snapshot()==Q_SNAPSHOT && now==120 && sleeps==20);
 assert(memcmp(&other,&saved,sizeof(other))==0);
 reset(0);IN->state.seq=3;saved=other;
 assert(snapshot()==Q_SNAPSHOT && now==120 && sleeps==20);
 assert(memcmp(&other,&saved,sizeof(other))==0);
 reset(1);IN->state.seq=3;
 assert(snapshot_until(103)==Q_SNAPSHOT && now==103 && sleeps==3);
 reset(0);IN->state.seq=3;
 assert(snapshot_until(100)==Q_SNAPSHOT && sleeps==0);
 reset(1);IN->state.seq=3;release_at=120;
 assert(snapshot()==0 && now==120); /* coherent at the retry boundary */
 reset(0);IN->state.seq=0xfffffffe;
 scenario=2;assert(snapshot()==0 && other.seq==0 && other.sent==51);
 reset(0);IN->state.session++;assert(snapshot()==0 && valid()==Q_IDENTITY);
 reset(0);IN->state.guard=0;assert(snapshot()==0 && valid()==Q_GUARDS);
 reset(0);IN->state.error=Q_SNAPSHOT;IN->state.phase=Q_FAILED;
 assert(snapshot()==0 && valid()==Q_PEER);
 puts("snapshot: 12 preemption/deadline/coherence/fault cases passed");
 return 0;
}
