# SPDX-License-Identifier: Apache-2.0
import unittest
from check_bth_layout import audit_early_ram


class EarlyBootRam(unittest.TestCase):
    def test_flash_code_and_late_initialized_state_are_rejected(self):
        syms = dict(__boot_text_sram_start__=0x500180, __boot_text_sram_end__=0x501000,
                    __boot_data_sram_start__=0x20501000, __boot_data_sram_end__=0x20501200,
                    __boot_bss_sram_start__=0x20501200, __boot_bss_sram_end__=0x20501400,
                    memcpy=0x500180, hal_norflash_init=0x500200,
                    norflash_set_mode=0x500300, norflash_match_chip=0x500400,
                    norflash_cfg=0x20501000, norflash_ctx=0x20501200)
        self.assertEqual(len(audit_early_ram(syms)), 6)
        for name, value in [('memcpy', 0x14005b84), ('hal_norflash_init', 0x1400b7fc),
                            ('norflash_cfg', 0x14010000), ('norflash_ctx', 0x20502000)]:
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, name):
                audit_early_ram(dict(syms, **{name: value}))
