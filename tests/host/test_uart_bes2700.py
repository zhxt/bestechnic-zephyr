# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
import subprocess
import tempfile
import unittest

PORT = Path(__file__).resolve().parents[2]


class UartDriverTests(unittest.TestCase):
    def compile_and_run(self, source, driver=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ('zephyr/device.h', 'zephyr/drivers/uart.h', 'zephyr/irq.h',
                         'zephyr/sys/sys_io.h', 'zephyr/kernel.h', 'cmsis_core.h'):
                header = root / name
                header.parent.mkdir(parents=True, exist_ok=True)
                header.write_text('#include "shim.h"\n')
            binary = root / 'uart_test'
            extra = [f'-DUART_SOURCE="{driver}"'] if driver else []
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-fsanitize=undefined', *extra,
                '-I', str(root), '-I', str(PORT / 'tests/uart_bes2700'), '-I', str(PORT / 'include/bestechnic/bes2700yp'),
                str(PORT / 'tests/uart_bes2700' / source), '-o', str(binary)], check=True)
            result = subprocess.run([str(binary)], capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_actual_driver_fifo_irq_and_error_paths(self):
        self.compile_and_run('test_driver.c')

    def test_rx_progress_during_tx_fill(self):
        self.compile_and_run('test_service.c')

    def test_retained_receive_state_cannot_contaminate_new_transfer(self):
        self.compile_and_run('test_retained_rx.c')


if __name__ == '__main__':
    unittest.main()
