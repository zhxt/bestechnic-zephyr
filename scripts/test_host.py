#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Run the migrated worker, driver, parser and image safety regressions."""
import sys
import unittest
from pathlib import Path

root = Path(__file__).resolve().parents[1]
suite = unittest.defaultTestLoader.discover(str(root / 'tests/host'))
result = unittest.TextTestRunner(verbosity=2).run(suite)
raise SystemExit(0 if result.wasSuccessful() else 1)
