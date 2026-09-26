# SPDX-License-Identifier: Apache-2.0
from pathlib import Path
import unittest
from unittest.mock import patch
from audit_dual import audit_repark


class ReparkAudit(unittest.TestCase):
    def test_dedicated_hal_path_and_no_power_replay(self):
        for case in ('valid','missing','bridge','dispatch','power','start'):
            syms=dict(repark_cpu=0x14001000,bes2700yp_m55_repark_prepare=0x14002000)
            bodies=dict(repark_cpu='bl 14002000 <bes2700yp_m55_repark_prepare>',
                        dual_dispatch='b.w 14001000 <repark_cpu>',
                        bes2700yp_m55_repark_prepare='bx lr')
            if case=='missing':del syms['repark_cpu']
            elif case in ('bridge','dispatch'):bodies['repark_cpu' if case=='bridge' else 'dual_dispatch']='bx lr'
            elif case=='power':bodies['bes2700yp_m55_repark_prepare']='bl 14003000 <hal_psc_sys_m55_enable>'
            elif case=='start':bodies['bes2700yp_m55_repark_prepare']='bl 14003000 <bes2700yp_m55_start>'
            with self.subTest(case=case), patch('audit_dual.symbols',return_value=syms), \
                 patch('audit_dual.subprocess.check_output',
                       side_effect=lambda args,**kw:bodies[args[2].split('=')[1]]):
                if case=='valid':self.assertEqual(audit_repark(Path('adapter.elf'),'')['bridge_calls_hal'],'pass')
                else:
                    with self.assertRaises(ValueError):audit_repark(Path('adapter.elf'),'')
