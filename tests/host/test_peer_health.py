# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class PeerHealth(unittest.TestCase):
    def test_actual_policy_deadlines_fault_latch_and_isolation_failures(self):
        with tempfile.TemporaryDirectory() as directory:
            executable = Path(directory) / 'health'
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                            '-fsanitize=undefined', '-fno-sanitize-recover=all',
                            '-I', str(ROOT / 'include/bestechnic/bes2700yp'),
                            str(ROOT / 'platforms/bes2700yp/lifecycle/health.c'),
                            str(ROOT / 'tests/lifecycle/test_health.c'),
                            '-o', str(executable)], check=True)
            subprocess.run([str(executable)], check=True, timeout=10)
