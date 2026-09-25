# SPDX-License-Identifier: Apache-2.0
import subprocess
import tempfile
import unittest
from pathlib import Path
PORT = Path(__file__).resolve().parents[2]


class MessageWorkers(unittest.TestCase):
    def test_snapshot_writer_preemption(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in ('cmsis_core.h', 'zephyr/kernel.h', 'zephyr/drivers/mbox.h', 'zephyr/device.h'):
                f=root/name;f.parent.mkdir(parents=True,exist_ok=True)
                f.write_text('#include "shim.h"\n')
            exe=root/'snapshot'
            subprocess.run(['cc','-std=gnu11','-O2','-Wall','-Wextra','-Werror',
                '-Wno-unused-variable','-Wno-unused-function','-ffunction-sections','-fdata-sections',
                '-Wl,--gc-sections','-fsanitize=undefined','-fno-sanitize-recover=all',
                '-DCONFIG_DUAL_MSG_MODE=2','-DCONFIG_DUAL_IPC_SECONDS=600',
                '-I',str(root),'-I',str(PORT/'tests/dual_message'),'-I',str(PORT/'include/bestechnic/bes2700yp'),
                '-I',str(PORT/'platforms/bes2700yp/ipc'),'-I',str(PORT/'platforms/bes2700yp/ipc'),
                str(PORT/'tests/dual_message/snapshot.c'),'-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True,timeout=10)

    def test_new_layout_protocol(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'protocol.c';exe=root/'protocol'
            source.write_text((PORT/'tests/ipc_protocol/test_protocol.c').read_text()
                .replace('bes2700_ipc_protocol.h','bes2700_message.h').replace('guards[447]','guards[383]'))
            subprocess.run(['cc','-std=c11','-O2','-Wall','-Wextra','-Werror','-fsanitize=undefined',
                '-fno-sanitize-recover=all','-I',str(PORT/'include/bestechnic/bes2700yp'),str(source),'-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True,timeout=30)

    def test_actual_workers(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('cmsis_core.h', 'zephyr/kernel.h', 'zephyr/drivers/mbox.h', 'zephyr/device.h'):
                f=root/name; f.parent.mkdir(parents=True, exist_ok=True)
                f.write_text('#include "shim.h"\n')
            (root/'m55_payload.h').write_text('#define M55_BUILD_ID 0x87654321\n')
            for side in ('bth','m55'):
                head='#define CC_BTH 1\n' if side=='bth' else ''
                start='q_start();' if side=='bth' else ''
                (root/(side+'.c')).write_text(head+f'#include "{PORT}/platforms/bes2700yp/ipc/worker.c"\n'
                    +f'void run_{side}(void) {{{start}worker(0,0,0);}}\n')
            normal_faults=list(range(8))+[9,10,11]
            for variant,duration,modes in ((1,600,normal_faults),(2,12,normal_faults),(3,600,normal_faults),(2,3600,(8,))):
                exe=root/f'workers-{variant}-{duration}'
                subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-variable',
                    '-fsanitize=undefined','-fno-sanitize-recover=all',f'-DCONFIG_DUAL_MSG_MODE={variant}',
                    f'-DCONFIG_DUAL_IPC_SECONDS={duration}','-I',str(root),'-I',str(PORT/'tests/dual_message'),
                    '-I',str(PORT/'include/bestechnic/bes2700yp'),'-I',str(PORT/'platforms/bes2700yp/ipc'),
                    str(root/'bth.c'),str(root/'m55.c'),str(PORT/'tests/dual_message/model.c'),'-o',str(exe)],check=True)
                for mode in modes:
                    with self.subTest(variant=variant,duration=duration,mode=mode):
                        subprocess.run([str(exe),str(mode)],check=True,timeout=30)
