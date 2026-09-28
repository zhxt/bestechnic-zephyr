# SPDX-License-Identifier: Apache-2.0
"""Reject conflicting resource declarations and implicit shared BSS growth."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from audit_dual import audit_lifecycle, check_resource_contract

ROOT = Path(__file__).resolve().parents[2]


class LifecycleMemory(unittest.TestCase):
    def test_contract_rejects_overlap_size_and_budget_drift(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ('platforms/bes2700yp/resources.json',
                         'include/bestechnic/bes2700yp/bes2700_lifecycle.h',
                         'include/bestechnic/bes2700yp/bes2700_observation.h',
                         'include/bestechnic/bes2700yp/bes2700_dual_boot.h'):
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, target)
            manifest = root / 'platforms/bes2700yp/resources.json'
            baseline = manifest.read_text()
            check_resource_contract(root)
            for field in ('overlap', 'bytes', 'ready_ms', 'layout', 'reset_address', 'reset_attempts'):
                data = json.loads(baseline)
                if field == 'overlap':
                    data['regions'][5]['start'] -= 4
                elif field.startswith('reset_'):
                    data['reset_diagnostic']['address' if field == 'reset_address' else 'read_attempts'] += 4
                else:
                    data['lifecycle'][field] += 4
                manifest.write_text(json.dumps(data))
                with self.subTest(field=field), self.assertRaises(ValueError):
                    check_resource_contract(root)

    def test_noload_and_bss_cannot_enter_control_or_reserved_tail(self):
        resources = check_resource_contract(ROOT)
        syms = {'__bes2700_m55_shared_start': 0x2015e100,
                '__bes2700_m55_shared_end': 0x2015e14c}
        with tempfile.TemporaryDirectory() as temporary:
            elfs = [Path(temporary) / core / 'zephyr.elf' for core in ('bth', 'm55')]
            for elf in elfs:
                elf.parent.mkdir()
                elf.with_suffix('.dts').write_text(
                    'lifecycle_control: memory@2015e280 { reg = <0x2015e280 0x80>; };')
            with patch('audit_dual.run_readelf', return_value=''), \
                    patch('audit_dual.symbols', return_value=syms), \
                    patch('audit_dual.parse_load_segments') as segments:
                segments.return_value = [dict(vaddr=0x2015e100, memsz=0x4c, filesz=0)]
                audit_lifecycle(elfs, '', resources)
                for address, size in ((0x2015e100, 0x100), (0x2015e280, 4),
                                      (0x2015e300, 4), (0x2015ffe0, 32),
                                      (0x2055c1a0, 80), (0x0055c19c, 8),
                                      (0x2055c800, 100), (0x0055c85c, 16)):
                    segments.return_value = [dict(vaddr=address, memsz=size, filesz=0)]
                    with self.subTest(address=address), self.assertRaisesRegex(ValueError, 'overlaps'):
                        audit_lifecycle(elfs, '', resources)
                segments.return_value = []
                syms['__bes2700_m55_shared_end'] = 0x2015e184
                with self.assertRaisesRegex(ValueError, 'heartbeat'):
                    audit_lifecycle(elfs, '', resources)
