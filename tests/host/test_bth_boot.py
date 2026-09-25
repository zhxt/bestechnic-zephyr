#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
import copy
import ctypes
import json
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from analyze_bth_boot import analyze
from pack_bth_payload import pack, CODE, DATA, LAYOUT


def fixture():
    elf = bytearray(84)
    elf[:7] = b"\x7fELF\x01\x01\x01"
    struct.pack_into("<H", elf, 18, 40)
    struct.pack_into("<II", elf, 64, DATA + 256, CODE + 9)
    elf[72:80] = b"\x00\xbf" * 4
    segs = [dict(offset=64, paddr=CODE, vaddr=CODE, filesz=16, memsz=16, flags="R E"),
            dict(offset=80, paddr=CODE + 16, vaddr=DATA, filesz=4, memsz=4, flags="RW")]
    return bytes(elf), segs


def good_log(manifest):
    lines = [f"begin version=1 test=5 build={manifest['build']}",
        "stage=adapter_ready", "adapter cpuid=0x41fd2140 ipsr=0 control=0",
        f"image layout={manifest['layout']} verified=1", "uart ibrd=1 fbrd=19",
        "state cache=0 mpu=0 systick=0", "stage=handoff", "stage=reset", "stage=early",
        "cpu cpuid=0x41fd2140 ipsr=0 control=2",
        f"regs vtor={CODE} msp={DATA + 256} psp={DATA + 128}",
        "masks primask=0 basepri=0 faultmask=0", "limits msplim=0 psplim=0",
        "clock cpu_hz=24000000 uart_hz=24000000 timer_hz=6000000",
        "memory data=1 bss=1 guards=1", "stage=main"]
    lines += [f"progress sample={i} timer_ticks={i * 6000000 + 500}" for i in range(60)]
    lines += ["result pass=1 samples=60 rc=0"]
    return "\n".join("zephyr_bth " + line + " !" for line in lines) + "\n"


class PackerTests(unittest.TestCase):
    def setUp(self):
        self.elf, self.segs = fixture()

    def test_valid_payload(self):
        payload, report = pack(self.elf, self.segs, CODE + 9)
        self.assertEqual(len(payload), 84)
        self.assertEqual(report["vector"], CODE)

    def test_invalid_ranges(self):
        for index, key, value in ((0, "paddr", CODE - 4), (1, "vaddr", DATA - 4),
                                  (1, "memsz", 0x20000), (0, "filesz", 100),
                                  (1, "offset", 1000), (1, "paddr", CODE + 4)):
            with self.subTest(index=index, key=key, value=value):
                segs = copy.deepcopy(self.segs)
                segs[index][key] = value
                with self.assertRaises(ValueError):
                    pack(self.elf, segs, CODE + 9)

    def test_bad_vectors_and_entry(self):
        for sp, pc, entry in ((DATA, CODE + 9, CODE + 9),
                (DATA + 2, CODE + 9, CODE + 9), (DATA + 256, CODE + 8, CODE + 8),
                (DATA + 256, CODE + 19, CODE + 19), (DATA + 256, CODE + 9, CODE + 11)):
            with self.subTest(sp=sp, pc=pc, entry=entry):
                elf = bytearray(self.elf)
                struct.pack_into("<II", elf, 64, sp, pc)
                with self.assertRaises(ValueError):
                    pack(bytes(elf), self.segs, entry)

    def test_noload_overlap_and_overflow(self):
        for extra in (dict(vaddr=DATA, paddr=DATA, filesz=0, memsz=16, offset=0, flags="RW"),
                      dict(vaddr=0xfffffffc, paddr=0xfffffffc, filesz=0, memsz=16, offset=0, flags="RW")):
            with self.assertRaises(ValueError):
                pack(self.elf, self.segs + [extra], CODE + 9)


class RuntimeValidatorTests(unittest.TestCase):
    defines = []
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        harness = root / "check.c"
        harness.write_text('#include "image_check.h"\nint check(const void *p, size_t n) { return bth_image_check(p,n); }\n')
        subprocess.run(["cc", "-shared", "-fPIC", "-O2", "-Wall", "-Werror",
                        *cls.defines, "-I", str(Path(__file__).resolve().parents[2] / "platforms/bes2700yp/boot/bootstrap"),
                        str(harness), "-o", str(root / "check.so")], check=True)
        cls.lib = ctypes.CDLL(str(root / "check.so"))
        cls.lib.check.argtypes = [ctypes.c_void_p, ctypes.c_size_t]
        cls.lib.check.restype = ctypes.c_int

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def check(self, payload, size=None):
        buf = ctypes.create_string_buffer(payload)
        return self.lib.check(buf, len(payload) if size is None else size)

    def test_real_c_checker_accepts_packer_output(self):
        elf, segs = fixture()
        payload, _ = pack(elf, segs, CODE + 9)
        self.assertEqual(self.check(payload), 0)

    def test_corruption_truncation_bounds(self):
        elf, segs = fixture()
        payload, _ = pack(elf, segs, CODE + 9)
        for length in (0, 4, 63, 64, len(payload) - 1):
            self.assertNotEqual(self.check(payload, length), 0)
        for word, value in ((0, 0), (1, 2), (2, LAYOUT + 1), (4, 0xffffffff),
                            (6, CODE + 4), (7, DATA), (8, CODE), (9, 26000000),
                            (10, 0), (11, 1), (16, DATA), (17, CODE)):
            with self.subTest(word=word):
                bad = bytearray(payload)
                struct.pack_into("<I", bad, word * 4, value)
                self.assertNotEqual(self.check(bytes(bad)), 0)
        bad = bytearray(payload)
        bad[-1] ^= 1
        self.assertNotEqual(self.check(bytes(bad)), 0)


class RamRuntimeValidatorTests(RuntimeValidatorTests):
    defines = ["-DBES_BTH_BOOT_CRC_RAM"]


class LogTests(unittest.TestCase):
    def setUp(self):
        elf, segs = fixture()
        _, self.manifest = pack(elf, segs, CODE + 9)
        self.log = good_log(self.manifest)

    def status(self, text):
        return analyze(text, self.manifest)["status"]

    def test_pass_with_capture_prefix(self):
        self.assertEqual(self.status(self.log.replace("zephyr_bth", "[18:00:00] zephyr_bth")), "pass")

    def test_missing_and_truncated(self):
        for text in ("", self.log[:80], self.log.rsplit("zephyr_bth result", 1)[0],
                     self.log.replace("zephyr_bth stage=reset !\n", ""), self.log[:-2]):
            self.assertEqual(self.status(text), "incomplete")

    def test_failures(self):
        for old, new in ((self.manifest["build"], "0xffffffff"), ("verified=1", "verified=0"),
                         ("data=1", "data=0"), ("primask=0", "primask=1"),
                         ("sample=1 ", "sample=0 "), ("timer_ticks=6000500", "timer_ticks=1"),
                         (f"vtor={CODE}", "vtor=0"), ("pass=1", "pass=0"),
                         ("fbrd=19", "fbrd=20"), ("stage=early", "stage=fatal")):
            with self.subTest(old=old):
                self.assertEqual(self.status(self.log.replace(old, new)), "fail")

    def test_gap_is_not_pass(self):
        text = "\n".join(line for line in self.log.splitlines() if "sample=10 " not in line)
        self.assertEqual(self.status(text), "incomplete")

    def test_restart_does_not_inherit_prior_pass(self):
        report = analyze(self.log + self.log[:self.log.find("zephyr_bth stage=main")], self.manifest)
        self.assertEqual(report["session_count"], 2)
        self.assertEqual(report["sessions"][0]["status"], "pass")
        self.assertEqual(report["status"], "incomplete")

    def test_fault_after_pass(self):
        self.assertEqual(self.status(self.log + "zephyr_bth stage=fatal !\n"), "fail")


if __name__ == "__main__":
    unittest.main()
