# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class WorkerIsolation(unittest.TestCase):
    def test_actual_worker_terminal_stop_preserves_shared_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shim = (ROOT / 'tests/dual_message/shim.h').read_text().replace(
                'static inline void k_thread_abort(void *p) { (void)p; }',
                'void k_thread_abort(void *p);')
            (root / 'shim.h').write_text(shim)
            for name in ('cmsis_core.h', 'zephyr/kernel.h', 'zephyr/drivers/mbox.h', 'zephyr/device.h'):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('#include "shim.h"\n')
            (root / 'm55_payload.h').write_text('#define M55_BUILD_ID 0x87654321\n')
            exe = root / 'worker-isolation'
            subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                            '-Wno-unused-variable', '-Wno-unused-function',
                            '-ffunction-sections', '-fdata-sections', '-Wl,--gc-sections',
                            '-fsanitize=undefined', '-fno-sanitize-recover=all',
                            '-DCONFIG_BES2700_M55_RESTART=1', '-DCONFIG_BES2700_M55_FAULT_CASE=2',
                            '-DCONFIG_DUAL_MSG_MODE=1', '-DCONFIG_DUAL_IPC_SECONDS=600',
                            '-I', str(root), '-I', str(ROOT / 'include/bestechnic/bes2700yp'),
                            '-I', str(ROOT / 'platforms/bes2700yp/ipc'),
                            str(ROOT / 'tests/lifecycle/test_worker_isolation.c'),
                            '-o', str(exe)], check=True)
            subprocess.run([str(exe)], check=True, timeout=10)
