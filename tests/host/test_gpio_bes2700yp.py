# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class GpioDriver(unittest.TestCase):
    def test_actual_driver_rejections_errors_and_concurrent_toggle(self):
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            for name in ('zephyr/drivers/gpio.h', 'zephyr/drivers/gpio/gpio_utils.h',
                         'zephyr/kernel.h', 'cmsis_core.h'):
                header = temp / name
                header.parent.mkdir(parents=True, exist_ok=True)
                header.write_text('#include "shim.h"\n')
            binary = temp / 'driver'
            subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror', '-pthread',
                '-fsanitize=undefined', '-fno-sanitize-recover=all', '-I', str(temp),
                '-I', str(ROOT / 'tests/gpio_bes2700yp'),
                '-I', str(ROOT / 'include/bestechnic/bes2700yp'),
                '-I', str(ROOT.parent / 'zephyr/include'),
                str(ROOT / 'tests/gpio_bes2700yp/driver.c'), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True, timeout=10)

    def test_actual_applications_through_driver(self):
        for input_mode in (True, False):
            with tempfile.TemporaryDirectory() as directory:
                temp = Path(directory)
                for name in ('zephyr/drivers/gpio.h', 'zephyr/drivers/gpio/gpio_utils.h',
                             'zephyr/kernel.h', 'cmsis_core.h'):
                    header = temp / name
                    header.parent.mkdir(parents=True, exist_ok=True)
                    header.write_text('#include "shim.h"\n')
                binary = temp / 'application'
                subprocess.run(['cc', '-std=c11', '-Wall', '-Wextra', '-Werror',
                    '-fsanitize=undefined', '-fno-sanitize-recover=all',
                    '-DCONFIG_GPIO_BES2700YP=1',
                    '-DCONFIG_BES2700YP_GPIO_VALIDATION='+str(1 if input_mode else 2),
                    *(['-DINPUT_APPLICATION=1'] if input_mode else []),
                    '-I', str(temp), '-I', str(ROOT / 'tests/gpio_bes2700yp'),
                    '-I', str(ROOT / 'include/bestechnic/bes2700yp'),
                    '-I', str(ROOT.parent / 'zephyr/include'),
                    str(ROOT / 'tests/gpio_bes2700yp/application.c'), '-o', str(binary)], check=True)
                for scenario in range(4):
                    subprocess.run([str(binary), str(scenario)], check=True, timeout=10)
