#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0

"""Host regression tests for BES loader destinations and XIP initialization."""

import struct
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import pack_m55_payload as pack


class SegmentImageTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.elf = Path(self.tmp.name) / "fixture.elf"
        self.elf.write_bytes(b"CODEDATA")
        self.segments = [
            dict(offset=0, vaddr=0xA0000, paddr=0xA0000, filesz=4, memsz=4),
            dict(offset=4, vaddr=0x200C0000, paddr=0xA0004, filesz=4, memsz=4),
            dict(offset=0, vaddr=0x2015E100, paddr=0x2015E100, filesz=0, memsz=16),
        ]

    def build(self):
        with patch.object(pack, "build_trampoline", return_value=b"TRMP"):
            return pack.build_bes_segment_image(
                self.elf, self.segments, 0xA0000, 0xA0001, 0x2015E000, ""
            )[0]

    def test_loader_populates_xip_source_and_skips_noload(self):
        image = self.build()
        version, kind, _, size, code_offset, map_size = struct.unpack_from(
            "<HBBIII", image, 16
        )
        self.assertEqual((version, kind, size), (0, 1, len(image)))
        self.assertEqual(code_offset, 32 + map_size)
        memory = {}
        destinations = []
        for pos in range(32, 32 + map_size, 12):
            dst, src, count = struct.unpack_from("<III", image, pos)
            self.assertLessEqual(src + count, len(image))
            destinations.append(dst)
            memory.update((dst + i, value) for i, value in enumerate(image[src:src + count]))
        self.assertEqual(destinations, [0x2015E000, 0xA0000, 0xA0004])
        self.assertNotIn(0x200C0000, memory)
        self.assertNotIn(0x2015E100, memory)
        # Model Zephyr arch_data_copy after the BES loader has finished.
        for i in range(4):
            memory[0x200C0000 + i] = memory[0xA0004 + i]
        self.assertEqual(bytes(memory[0x200C0000 + i] for i in range(4)), b"DATA")

    def test_rejects_truncated_segment(self):
        self.segments[1]["offset"] = 6
        with self.assertRaisesRegex(ValueError, "file bounds"):
            self.build()

    def test_rejects_lma_overlap(self):
        self.segments[1]["paddr"] = 0xA0000
        with self.assertRaisesRegex(ValueError, "overlap"):
            self.build()

    def test_rejects_trampoline_overlap(self):
        self.segments[1]["paddr"] = 0x2015E000
        with self.assertRaisesRegex(ValueError, "overlap"):
            self.build()

    def test_rejects_unaligned_destination(self):
        self.segments[1]["paddr"] = 0xA0005
        with self.assertRaisesRegex(ValueError, "load address"):
            self.build()


if __name__ == "__main__":
    unittest.main()
