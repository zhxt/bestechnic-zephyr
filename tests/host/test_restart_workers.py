# SPDX-License-Identifier: Apache-2.0
import subprocess
import tempfile
import unittest
from pathlib import Path
PORT=Path(__file__).resolve().parents[2]

class RestartWorkers(unittest.TestCase):
    def test_eleven_real_worker_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            for name in ('cmsis_core.h','zephyr/kernel.h','zephyr/drivers/mbox.h','zephyr/device.h'):
                f=root/name;f.parent.mkdir(parents=True,exist_ok=True);f.write_text('#include "shim.h"\n')
            (root/'m55_payload.h').write_text('#define M55_BUILD_ID 0x87654321\n')
            for side in ('bth','m55'):
                text=('#define CC_BTH 1\n' if side=='bth' else '')+f'#define q_idle q_idle_{side}\n#include "{PORT}/platforms/bes2700yp/ipc/worker.c"\n'
                text+=f'void run_{side}(void) {{'+('q_start();' if side=='bth' else '')+'worker(0,0,0);}\n'
                if side=='m55':text+='void cold_reset_m55(void) { worker_idle=0;q_received.count=0;own=(struct q_state){0};other=(struct q_state){0}; }\n'
                (root/(side+'.c')).write_text(text)
            exe=root/'restart'
            subprocess.run(['cc','-std=gnu11','-Wall','-Wextra','-Werror','-Wno-unused-variable',
                '-fsanitize=undefined','-fno-sanitize-recover=all','-DCONFIG_BES2700_M55_RESTART=1',
                '-DCONFIG_DUAL_MSG_MODE=1','-DCONFIG_DUAL_IPC_SECONDS=600',
                '-I',str(root),'-I',str(PORT/'tests/dual_message'),'-I',str(PORT/'include/bestechnic/bes2700yp'),
                '-I',str(PORT/'platforms/bes2700yp/ipc'),str(root/'bth.c'),str(root/'m55.c'),
                str(PORT/'tests/dual_message/restart_model.c'),'-o',str(exe)],check=True)
            subprocess.run([str(exe)],check=True,timeout=30)
