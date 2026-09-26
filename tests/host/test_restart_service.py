# SPDX-License-Identifier: Apache-2.0
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class RestartService(unittest.TestCase):
    def test_actual_timer_reader(self):
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / 'timer'
            subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=undefined', '-fno-sanitize-recover=all',
                            '-I', str(ROOT / 'include/bestechnic/bes2700yp'),
                            str(ROOT / 'tests/dual_message/reset_timer.c'),
                            '-o', str(executable)], check=True)
            subprocess.run([str(executable)], check=True, timeout=10)

    def test_actual_hal_bridge(self):
        with tempfile.TemporaryDirectory() as temporary:
            executable = Path(temporary) / 'service'
            subprocess.run(['cc', '-std=gnu11', '-Wall', '-Wextra', '-Werror',
                            '-Wno-pointer-to-int-cast', '-Wno-int-to-pointer-cast',
                            '-fsanitize=undefined', '-fno-sanitize-recover=all',
                            '-DBES_BTH_M55_RESTART=1',
                            '-I', str(ROOT / 'include/bestechnic/bes2700yp'),
                            '-I', str(ROOT.parent / 'modules/hal/bestechnic/include'),
                            str(ROOT / 'tests/dual_message/restart_service.c'),
                            '-o', str(executable)], check=True)
            subprocess.run([str(executable)], check=True, timeout=10)
