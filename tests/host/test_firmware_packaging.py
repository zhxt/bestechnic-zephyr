# SPDX-License-Identifier: Apache-2.0
import struct
import unittest

from firmware import check_pair, fill_build_info


class PackagingTests(unittest.TestCase):
    def test_pair_hex_leading_zeros_and_mismatch(self):
        for text in ('0x0bc711e9', '0xBC711E9'):
            check_pair('CONFIG_DUAL_CC_PAIR=' + text + '\n', 0x0bc711e9)
        for config in ('CONFIG_DUAL_CC_PAIR=0x0bc711e8\n', '',
                       'CONFIG_DUAL_CC_PAIR=0x0bc711e90\n'):
            with self.assertRaises(ValueError):
                check_pair(config, 0x0bc711e9)

    def setUp(self):
        self.syms = dict(sys_build_info=0x34000020, __userdata_start=0x307fc000,
                         __aud_start=0x307fe000, __factory_start=0x307ff000)
        info = b'\n__userdata_start=<##BASE##>\n__aud_start=<##BASE##>\n__factory_start=<##BASE##>\n'
        self.data = (struct.pack('<4I', 0xffffffff, 0x40000, 0, 0x34000020) + bytes(16)
                     + info + b'\0' + struct.pack('<I', 0x34000000))

    def test_only_placeholders_change(self):
        result = fill_build_info(self.data, self.syms)
        self.assertEqual(len(result), len(self.data))
        self.assertEqual(result[:32], self.data[:32])
        self.assertEqual(result[-5:], self.data[-5:])
        for name in ('__userdata_start', '__aud_start', '__factory_start'):
            self.assertIn(f'{name}=0x{self.syms[name]:08X}'.encode(), result)
        self.assertNotIn(b'<##BASE##>', result)

    def test_truncated_and_invalid_headers(self):
        for data in (self.data[:15], self.data[:-1], bytes(20),
                     b'\0\0\0\0' + self.data[4:]):
            with self.subTest(data=data[:16]), self.assertRaises(ValueError):
                fill_build_info(data, self.syms)

    def test_bad_info_pointer(self):
        for pointer in (0x34000004, 0x34010000, 0xffffffff):
            data = bytearray(self.data)
            struct.pack_into('<I', data, 12, pointer)
            with self.subTest(pointer=pointer), self.assertRaises(ValueError):
                fill_build_info(bytes(data), dict(self.syms, sys_build_info=pointer))

    def test_missing_or_bad_symbols(self):
        for name in self.syms:
            syms = dict(self.syms)
            del syms[name]
            with self.subTest(name=name), self.assertRaises(ValueError):
                fill_build_info(self.data, syms)
        with self.assertRaises(ValueError):
            fill_build_info(self.data, dict(self.syms, __aud_start=0x2015c000))

    def test_missing_duplicate_unterminated_placeholders(self):
        for data in (self.data.replace(b'__aud_start', b'__bad_start'),
                     self.data[:-5] + b'__aud_start=<##BASE##>\n' + self.data[-5:],
                     self.data[:-5] + b'x' + self.data[-4:]):
            with self.subTest(data=data), self.assertRaises(ValueError):
                fill_build_info(data, self.syms)

    def test_second_fill_rejected(self):
        with self.assertRaises(ValueError):
            fill_build_info(fill_build_info(self.data, self.syms), self.syms)
