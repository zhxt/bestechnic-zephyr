# Copyright The Zephyr Project Contributors
# SPDX-License-Identifier: Apache-2.0

from pathlib import Path
import json
import re
import subprocess
import tempfile
import unittest

PORT = Path(__file__).resolve().parents[2]


class MboxDriverTests(unittest.TestCase):
    def test_register_fields_against_frozen_vendor_contract(self):
        source = (PORT / "bsp/drivers/mbox/mbox_bes2700.c").read_text()
        fixture = json.loads((PORT / "tests/fixtures/mbox-registers.json").read_text())
        for name, expected in fixture['bits'].items():
            actual = int(re.search(rf"#define {name} BIT\((\d+)\)", source)[1])
            self.assertEqual(actual, expected['bit'], name)

    def test_actual_bth_driver_with_register_model(self):
        self.run_model(["-DTEST_BTH=1"])

    def test_actual_driver_with_register_model(self):
        self.run_model([])

    def test_bth_restart_and_failed_clear(self):
        self.run_model(["-DTEST_BTH=1", "-DCONFIG_BES2700_M55_RESTART=1"])

    def test_m55_restart_and_failed_clear(self):
        self.run_model(["-DCONFIG_BES2700_M55_RESTART=1"])

    def run_model(self, options):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ["device.h", "drivers/mbox.h", "irq.h", "kernel.h",
                         "sys/barrier.h", "sys/sys_io.h"]:
                header = root / "zephyr" / name
                header.parent.mkdir(parents=True, exist_ok=True)
                header.write_text('#include "shim.h"\n')
            executable = root / "test_driver"
            (root / "cmsis_core.h").write_text('#include "shim.h"\n')
            subprocess.run(["cc", "-std=c11", "-Wall", "-Wextra", "-Werror",
                            "-fsanitize=undefined", *options, "-I", str(root),
                            "-I", str(PORT / "tests/mbox_bes2700"),
                            "-I", str(PORT / "include/bestechnic/bes2700yp"),
                            str(PORT / "tests/mbox_bes2700/test_driver.c"),
                            "-o", str(executable)], check=True)
            subprocess.run([str(executable)], check=True, timeout=10)


if __name__ == "__main__":
    unittest.main()
