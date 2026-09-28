# SPDX-License-Identifier: Apache-2.0
"""Run the actual checkpoint reader against mutated AXI terminal publications."""
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class ObservationTraffic(unittest.TestCase):
    def test_checkpoint_rejects_live_corruption_despite_cached_success(self):
        text=(ROOT/'apps/bes2700yp/bth/src/main.c').read_text()
        function=text[text.index('static int observe_traffic('):text.index('static int observe_checkpoint(')]
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            source=root/'traffic.c'
            source.write_text('''#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <sys/mman.h>
#define __DMB() __asm__ volatile("" ::: "memory")
#include "message.h"
'''+function+'''
int main(void) {
 void *mapped=mmap((void *)(uintptr_t)BI_BASE,BI_BYTES,PROT_READ|PROT_WRITE,
                   MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED,-1,0);
 assert(mapped==(void *)(uintptr_t)BI_BASE);
 struct q_report report={.finished=1,.session=7};
 for(unsigned side=0;side<2;side++) {
  volatile struct bi_ring *ring=(void *)(uintptr_t)(BI_BASE+4096U*side);
  bi_init(ring);
  ring->state=(struct q_state){.seq=2,.session=7,.phase=Q_DONE,
   .sent=10000,.acked=10000,.handled=10000,.guard=Q_META_GUARD};
  if(side) { report.m55=ring->state; } else { report.bth=ring->state; }
 }
 assert(observe_traffic(&report)==0);
 for(unsigned side=0;side<2;side++) {
  volatile struct bi_ring *ring=(void *)(uintptr_t)(BI_BASE+4096U*side);
  ring->state.handled--;assert(observe_traffic(&report)!=0);ring->state.handled++;
  ring->state.seq++;assert(observe_traffic(&report)!=0);ring->state.seq++;
  ring->state.guard^=1;assert(observe_traffic(&report)!=0);ring->state.guard^=1;
  ring->state.error=1;assert(observe_traffic(&report)!=0);ring->state.error=0;
  ring->guards[383]^=1;assert(observe_traffic(&report)!=0);ring->guards[383]^=1;
  ring->head++;assert(observe_traffic(&report)!=0);ring->head--;
  assert(observe_traffic(&report)==0);
 }
 report.finished=0;assert(observe_traffic(&report)!=0);
 return 0;
}
''')
            binary=root/'traffic'
            subprocess.run(['cc','-std=c11','-D_GNU_SOURCE','-Wall','-Wextra','-Werror',
                            '-I'+str(ROOT/'platforms/bes2700yp/ipc'),
                            '-I'+str(ROOT/'include/bestechnic/bes2700yp'),str(source),'-o',str(binary)],check=True)
            subprocess.run([str(binary)],check=True)
