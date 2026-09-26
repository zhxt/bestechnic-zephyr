/* SPDX-License-Identifier: Apache-2.0 */
#define _GNU_SOURCE
#include "shim.h"
#include <bes2700_mbox.h>
#include <sys/mman.h>
#define CC_BTH 1
#include "../../platforms/bes2700yp/ipc/worker.c"
struct device devices[2]={{0},{1}};
static unsigned sequence, aborted;
static int suspend_rc;
void k_sem_give(struct k_sem *s) { if(s->count<s->limit) { s->count++; } }
void k_thread_abort(void *thread) { assert(thread==q_worker && sequence==1);sequence=2;aborted++; }
int bes2700_mbox_suspend(const struct device *d) { assert(d==&devices[0]);sequence=1;return suspend_rc; }
int main(void)
{
 assert(mmap((void *)BI_BASE,BI_BYTES,PROT_READ|PROT_WRITE,
             MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0)==(void *)BI_BASE);
 for(unsigned failed=0;failed<2;failed++) {
  /* Separate cold-boot models, with an in-flight local worker or pending start. */
  isolated=false;worker_idle=0;q_started.count=0;suspend_rc=failed?-5:0;
  q_prepare(123,7);q_start();assert(q_started.count==1);
  RING(0)->state.sent=55;RING(1)->state.handled=54;
  assert(q_isolate()==suspend_rc && sequence==2 && q_idle());
  assert(aborted==failed+1);
  q_started.count=0;q_start();assert(!q_started.count);
  q_prepare(999,8);
  assert(RING(0)->state.session==7 && RING(0)->state.sent==55 && RING(1)->state.handled==54);
 }
 return 0;
}
