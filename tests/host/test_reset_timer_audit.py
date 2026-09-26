# SPDX-License-Identifier: Apache-2.0
"""Reject linked reset timing paths that could execute from uncached Flash."""
from pathlib import Path
import unittest
from unittest.mock import patch

from audit_dual import audit_reset_timer, check_resource_contract

ROOT = Path(__file__).resolve().parents[2]


class ResetTimerAudit(unittest.TestCase):
    def test_linked_placement_calls_and_protection(self):
        baseline = dict(__boot_text_sram_start__=0x500180,
                        __boot_text_sram_end__=0x504000,
                        bes_reset_timer_read=0x503000, hold_cpu_reset=0x503100)
        segment = dict(vaddr=0x500180, filesz=0x4000, memsz=0x4000, flags='RE')
        reader = 'mrs r2, PRIMASK\ncpsid i\nldr r3, [r1]\nldr r4, [r1]\nmsr PRIMASK, r2\n'
        waiter = 'bl 503000 <bes_reset_timer_read>\n' * 2
        dispatcher = 'bl 14000010 <__hold_cpu_reset_veneer>\n'
        resources = check_resource_contract(ROOT)
        for case in ('valid', 'flash', 'function_tail', 'noload', 'not_executable',
                     'helper', 'unprotected', 'read_gap', 'wrong_register',
                     'wrong_restore', 'old_reader', 'missing_call',
                     'missing_dispatch', 'diagnostic_overlap'):
            syms, segments = baseline.copy(), [segment.copy()]
            bodies = dict(bes_reset_timer_read=reader, hold_cpu_reset=waiter,
                          dual_dispatch=dispatcher)
            if case == 'flash':
                syms['bes_reset_timer_read'] = 0x14003000
            elif case == 'function_tail':
                syms['hold_cpu_reset'] = 0x503ff0
            elif case == 'noload':
                segments[0]['filesz'] = 0
            elif case == 'not_executable':
                segments[0]['flags'] = 'RW'
            elif case == 'helper':
                bodies['bes_reset_timer_read'] += 'bl 14003000 <helper>\n'
            elif case == 'unprotected':
                bodies['bes_reset_timer_read'] = reader.replace('cpsid', 'nop')
            elif case == 'read_gap':
                bodies['bes_reset_timer_read'] = reader.replace('ldr r4', 'nop\nldr r4')
            elif case == 'wrong_register':
                bodies['bes_reset_timer_read'] = reader.replace('r4, [r1]', 'r4, [r0]')
            elif case == 'wrong_restore':
                bodies['bes_reset_timer_read'] = reader.replace('PRIMASK, r2', 'PRIMASK, r3')
            elif case == 'old_reader':
                bodies['hold_cpu_reset'] += 'bl 14003000 <bth_ticks>\n'
            elif case == 'missing_call':
                bodies['hold_cpu_reset'] = 'bx lr\n'
            elif case == 'missing_dispatch':
                bodies['dual_dispatch'] = 'bx lr\n'
            elif case == 'diagnostic_overlap':
                segments.append(dict(vaddr=0x2055c1a0, filesz=0, memsz=4, flags='RW'))

            def output(command, **kwargs):
                if command[0] == 'nm':
                    return ''.join(f'{syms[n]:08x} 00000040 T {n}\n'
                                   for n in ('bes_reset_timer_read', 'hold_cpu_reset'))
                return bodies[command[2].split('=', 1)[1]]

            with self.subTest(case=case), \
                    patch('audit_dual.symbols', return_value=syms), \
                    patch('audit_dual.run_readelf', return_value=''), \
                    patch('audit_dual.parse_load_segments', return_value=segments), \
                    patch('audit_dual.subprocess.check_output', side_effect=output):
                if case == 'valid':
                    audit = audit_reset_timer(Path('adapter.elf'), '', resources)
                    self.assertEqual(audit['sampler'], 0x503001)
                    self.assertEqual(audit['diagnostic'], [0x2055c1a0, 0x2055c1f0])
                else:
                    with self.assertRaises(ValueError):
                        audit_reset_timer(Path('adapter.elf'), '', resources)
