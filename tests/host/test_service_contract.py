# SPDX-License-Identifier: Apache-2.0
"""Exercise the actual shared C validator and the ELF audit rejection paths."""
import ctypes
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from audit_dual import audit_service_entry, service_validator

ROOT = Path(__file__).resolve().parents[2]


class Service(ctypes.Structure):
    _fields_ = [(name, ctypes.c_uint32) for name in
                ('magic', 'layout', 'dispatch', 'itcm', 'itcm_size',
                 'dtcm', 'dtcm_size', 'mailbox')]


class ServiceContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.generated = Path(cls.temporary.name)
        cls.checks = {}
        cls.validators = {}
        for restart in (False, True):
            output = cls.generated / str(restart)
            cls.checks[restart] = service_validator(ROOT, output, restart)
            validate = ctypes.CDLL(str(output / 'service_validator.so')).dual_service_validate
            validate.argtypes = [ctypes.POINTER(Service)]
            validate.restype = ctypes.c_uint32
            cls.validators[restart] = validate

    def test_flashx_and_sram_boundaries_in_both_profiles(self):
        # 0x140055d9 is the linked Thumb entry rejected by the first R1 image.
        valid = (0x140055d9, 0x14000001, 0x147fffff, 0x00500001, 0x0050ffff)
        invalid = (0, 0x140055d8, 0x340055d9, 0x34000001, 0x004fffff,
                   0x00510001, 0x13ffffff, 0x14800001, 0x20500001, 0xffffffff)
        for restart, check in self.checks.items():
            for address in valid:
                with self.subTest(restart=restart, address=hex(address)):
                    self.assertEqual(check(address), 0)
            for address in invalid:
                with self.subTest(restart=restart, address=hex(address)):
                    self.assertNotEqual(check(address), 0)

    def test_identity_and_memory_checks_are_preserved(self):
        for restart, validate in self.validators.items():
            layout = 0x000a0004 if restart else 0x00080002
            baseline = Service(0x38565342, layout, 0x140055d9, 0xa0000,
                               0x40000, 0x200c0000, 0xa0000, 0x2015ffe0)
            self.assertEqual(validate(ctypes.byref(baseline)), 0)
            cases = [('magic', 0, 1), ('layout', layout ^ 0x20000, 2),
                     ('dispatch', 0x140055d8, 4), ('dispatch', 0x340055d9, 8),
                     ('itcm', 0, 16), ('itcm_size', 0, 16),
                     ('dtcm', 0, 32), ('dtcm_size', 0, 32), ('mailbox', 0, 64)]
            for field, value, error in cases:
                service = Service.from_buffer_copy(baseline)
                setattr(service, field, value)
                with self.subTest(restart=restart, field=field, value=value):
                    self.assertEqual(validate(ctypes.byref(service)), error)

    def audit(self, restart=True, address=0x140055d8, flags='R E', size=32,
              call=True, linked=True):
        bootstrap, bth = Path('adapter.elf'), Path('bth.elf')
        def syms(elf, cross):
            if elf == bootstrap:
                return {'dual_dispatch': address}
            return {'dual_service_validate': 0x510100} if linked else {}
        assembly = ' 510080: f000 bl 510100 <dual_service_validate>\n' if call else ''
        with patch('audit_dual.symbols', side_effect=syms), \
                patch('audit_dual.service_validator', return_value=self.checks[restart]), \
                patch('audit_dual.run_readelf', return_value=''), \
                patch('audit_dual.parse_load_segments', return_value=[
                    dict(vaddr=address, filesz=size, memsz=32, flags=flags)]), \
                patch('audit_dual.subprocess.check_output', return_value=assembly):
            return audit_service_entry(bootstrap, bth, '', ROOT, self.generated, restart)

    def test_final_audit_checks_linked_dispatch_with_actual_c(self):
        for restart in (False, True):
            report = self.audit(restart=restart)
            self.assertEqual(report['dispatch'], '0x140055d9')
            self.assertEqual(report['caller'], 'bes2700_lifecycle_validate' if restart else 'main')
            with self.assertRaisesRegex(ValueError, 'rejected by BTH'):
                self.audit(restart=restart, address=0x340055d8)

    def test_final_audit_rejects_nonexecuting_or_unchecked_entry(self):
        for options in ({'flags': 'RW'}, {'size': 0}, {'call': False}, {'linked': False}):
            with self.subTest(options=options), self.assertRaises(ValueError):
                self.audit(**options)
