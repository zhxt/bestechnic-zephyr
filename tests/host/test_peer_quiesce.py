# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]


class PeerQuiesce(unittest.TestCase):
    def test_real_peer_refuses_only_injected_session(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            (root/'zephyr').mkdir()
            (root/'zephyr/kernel.h').write_text('#define K_FOREVER -1\nvoid k_sleep(int);\n')
            (root/'cmsis_core.h').write_text('#define __DMB() ((void)0)\n#define __DSB() ((void)0)\n')
            source=root/'test.c'
            source.write_text('''#define _GNU_SOURCE
#include <assert.h>
#include <sys/mman.h>
#include <bes2700_lifecycle.h>
static int idle,sleeps;
int q_idle(void) { return idle; }
void k_sleep(int delay) { assert(delay==-1);sleeps++; }
int main(void)
{
 assert(mmap((void *)(BES_LIFECYCLE_ADDR & ~4095U),4096,PROT_READ|PROT_WRITE,
 MAP_PRIVATE|MAP_ANONYMOUS|MAP_FIXED_NOREPLACE,-1,0)!=(void *)-1);
 assert(bes2700_lifecycle_peer_poll()==-1);
 *BES_LIFECYCLE_CTL=(struct bes2700_lifecycle_control){.magic=BES_LIFECYCLE_MAGIC,
  .layout=BES_LIFECYCLE_LAYOUT,.guard=BES_LIFECYCLE_GUARD,.session=1,.quiesce=1};
 idle=1;assert(!bes2700_lifecycle_peer_poll());
 assert(!BES_LIFECYCLE_CTL->idle && !sleeps);
 BES_LIFECYCLE_CTL->session=2;BES_LIFECYCLE_CTL->quiesce=1;
 assert(!bes2700_lifecycle_peer_poll() && !sleeps);
 BES_LIFECYCLE_CTL->quiesce=2;idle=0;
 assert(!bes2700_lifecycle_peer_poll() && !sleeps);
 idle=1;assert(!bes2700_lifecycle_peer_poll());
 assert(sleeps==1 && BES_LIFECYCLE_CTL->idle==2 && BES_LIFECYCLE_CTL->peer_session==2 &&
 BES_LIFECYCLE_CTL->peer_guard==BES_LIFECYCLE_GUARD);
 return 0;
}
''')
            exe=root/'peer'
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',
                '-fsanitize=undefined','-fno-sanitize-recover=all',
                '-DCONFIG_BES2700_M55_FAULT_CASE=4','-I',str(root),
                '-I',str(ROOT/'include/bestechnic/bes2700yp'),str(source),
                str(ROOT/'platforms/bes2700yp/lifecycle/peer.c'),'-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True,timeout=10)
