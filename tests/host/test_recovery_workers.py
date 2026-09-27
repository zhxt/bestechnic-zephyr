# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class RecoveryWorkers(unittest.TestCase):
    def test_abort_recreate_and_new_session_with_real_workers(self):
        self.run_workers(2)

    def test_stalled_real_peer_worker_is_detected_and_recreated(self):
        self.run_workers(3)

    def run_workers(self, fault_case):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shim = (ROOT/'tests/dual_message/shim.h').read_text().replace(
                '#define q_worker ((void *)0)', '').replace(
                'static inline void k_thread_abort(void *p) { (void)p; }',
                'void k_thread_abort(void *p);')
            shim = shim.rsplit('#endif', 1)[0]
            shim += '''
void k_sleep(int);
#define K_NO_WAIT 0
#define K_THREAD_STACK_DEFINE(n,s) static char n[s]
#define K_THREAD_STACK_SIZEOF(n) sizeof(n)
struct k_thread { int unused; };
typedef struct k_thread *k_tid_t;
k_tid_t k_thread_create(k_tid_t, void *, size_t, void (*)(void *,void *,void *),
                        void *,void *,void *,int,unsigned,int);
void k_thread_start(k_tid_t);
int k_thread_join(k_tid_t,int);
#endif
'''
            (root/'shim.h').write_text(shim)
            for name in ('cmsis_core.h', 'zephyr/kernel.h', 'zephyr/device.h', 'zephyr/drivers/mbox.h'):
                p=root/name;p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text('#include "shim.h"\n')
            (root/'m55_payload.h').write_text('#define M55_BUILD_ID 0x87654321\n')
            for side in ('bth', 'm55'):
                source = ('#define CC_BTH 1\n' if side == 'bth' else '')
                source += f'#define q_idle q_idle_{side}\n#include "{ROOT}/platforms/bes2700yp/ipc/worker.c"\n'
                source += f'void run_{side}(void) {{ worker(0,0,0); }}\n'
                if side == 'm55':
                    source += 'void cold_reset_m55(void) {worker_idle=0;q_received.count=0;own=(struct q_state){0};other=(struct q_state){0};}\n'
                else:
                    source += '''void seed_stale(void) {
 q_started.count=1;q_received.count=1;q_stopped.count=1;
 report.finished=1;report.session=1;report.rc=55;sent_at[0]=999;cases[0].id=99;
}
void check_clean(void) {
 assert(!q_started.count && !q_received.count && !q_stopped.count);
 assert(!report.finished && !report.session && !report.rc && !sent_at[0] && !cases[0].id);
 assert(worker_dormant && !isolated);
}
'''
                (root/(side+'.c')).write_text(source)
            model = (ROOT/'tests/dual_message/restart_model.c').read_text()
            model = model.replace(' setup_task(0);', ' /* BTH creation is driven by q_prepare/q_rearm. */')
            model = model.replace('round<11', 'round<2')
            model = model.replace('  q_prepare(0x12345678,round+1);',
                '  if(round) { assert(q_rearm()==0);check_clean();assert(q_rearm()==-EBUSY); }\n'
                '  else { assert(q_rearm()==-EBUSY); }\n'
                '  q_prepare(0x12345678,round+1);')
            model = model.replace('  if(round) { q_start(); }', '  q_start();')
            model = model.replace('   q_snapshot(&r);assert(steps++<100000);',
                '   q_snapshot(&r);assert(steps++<100000);\n'
                '   if(!round && ((struct bi_ring *)BI_BASE)->state.sent>32) { break; }')
            model = model.replace('  assert(q_wait_idle(0)==0);',
                '  if(!round) {\n'
                '   struct bi_ring *ring=(void *)BI_BASE;uint32_t sent=ring->state.sent;\n'
                '   assert(q_isolate()==0 && q_idle_bth() && task[0].done);\n'
                '   q_start();q_prepare(99,99);\n'
                '   assert(task[0].done && ring->state.session==1 && ring->state.sent==sent);\n'
                '   seed_stale();continue;\n'
                '  }\n'
                '  assert(q_wait_idle(0)==0);')
            model = model.replace('int main(void)', '''
void seed_stale(void);
void check_clean(void);
void k_thread_abort(void *thread) { assert(thread);task[0].done=true; }
int k_thread_join(k_tid_t thread,int timeout)
{ assert(thread && timeout==0);return task[0].done?0:-EBUSY; }
k_tid_t k_thread_create(k_tid_t thread,void *stack,size_t bytes,
 void (*entry)(void *,void *,void *),void *a,void *b,void *c,int priority,unsigned options,int delay)
{
 assert(thread && stack && bytes==4096 && entry && !a && !b && !c);
 assert(priority==5 && !options && delay==K_FOREVER);
 setup_task(0);task[0].done=true;return thread;
}
void k_thread_start(k_tid_t thread) { assert(thread && task[0].done);task[0].done=false; }
int bes2700_mbox_suspend(const struct device *d)
{ ep[d->id].masked=1;ep[d->id].enabled=false;return 0; }
int main(void)''')
            if fault_case == 3:
                model=model.replace('#include "message.h"', '#include "message.h"\n#include <bes2700_peer_health.h>')
                model=model.replace('int main(void)', 'void k_sleep(int delay) { assert(delay==K_FOREVER);task[current].wake=INT64_MAX;task[current].sem=NULL;yield();assert(0); }\nint main(void)')
                model=model.replace('  unsigned steps=0;struct q_report r={0};',
                    '  struct bes_peer_progress health;bes_peer_progress_init(&health,now);\n'
                    '  unsigned steps=0;struct q_report r={0};')
                model=model.replace('if(!round && ((struct bi_ring *)BI_BASE)->state.sent>32) { break; }',
                    'if(!round) {\n'
                    '    bool pending=r.bth.sent>r.bth.acked || r.m55.sent>r.bth.handled;\n'
                    '    enum bes_peer_fault fault=bes_peer_progress_poll(&health,now,pending,r.bth.acked,r.bth.handled);\n'
                    '    if(fault) { assert(fault==BES_PEER_IPC_TIMEOUT && !r.finished && r.bth.acked>=32);break; }\n'
                    '   }')
                model=model.replace('now=INT64_MAX;for(int n=0;', 'now+=20;for(int n=0;')
            (root/'model.c').write_text(model)
            exe=root/'recovery'
            subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-variable',
                '-fsanitize=undefined','-fno-sanitize-recover=all','-DTEST_RECOVERY=1',
                '-DCONFIG_BES2700_M55_RESTART=1',f'-DCONFIG_BES2700_M55_FAULT_CASE={fault_case}',
                '-DCONFIG_BES2700_M55_RECOVERY=1','-DCONFIG_DUAL_MSG_MODE=1','-DCONFIG_DUAL_IPC_SECONDS=600',
                '-I',str(root),'-I',str(ROOT/'include/bestechnic/bes2700yp'),
                '-I',str(ROOT/'platforms/bes2700yp/ipc'),str(root/'bth.c'),str(root/'m55.c'),
                str(root/'model.c'),str(ROOT/'platforms/bes2700yp/lifecycle/health.c'),'-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True,timeout=30)
