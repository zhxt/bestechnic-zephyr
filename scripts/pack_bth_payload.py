#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Strict ELF-to-BTH V05 payload packing; all addresses are checked before copying."""
import argparse
import hashlib
import json
import struct
import zlib
from pathlib import Path
from pack_m55_payload import parse_load_segments, run_readelf, parse_entry

CODE, CODE_END = 0x00510000, 0x00540000
DATA, DATA_END = 0x20540000, 0x2055C000
MAGIC, LAYOUT = 0x35485442, 0x00050001


def within(start, size, low, high):
    return size >= 0 and low <= start <= high and size <= high - start


def pack(elf, segments, entry, build_material=b""):
    if elf[:7] != b"\x7fELF\x01\x01\x01" or struct.unpack_from("<H", elf, 18)[0] != 40:
        raise ValueError("expected little-endian ELF32 ARM")
    loads, vmas = [], []
    for seg in segments:
        p, v, n, m, off = [int(seg[k]) for k in ("paddr", "vaddr", "filesz", "memsz", "offset")]
        if n > m or not within(off, n, 0, len(elf)):
            raise ValueError("invalid ELF file range")
        if not (within(v, m, CODE, CODE_END) or within(v, m, DATA, DATA_END)):
            raise ValueError("ELF VMA overlaps adapter/reserved/outside BTH allocation")
        if m:
            vmas.append((v, v + m))
        if n:
            if not within(p, n, CODE, CODE_END):
                raise ValueError("ELF LMA outside BTH code allocation")
            loads.append((p, elf[off:off + n]))
        elif not within(v, m, DATA, DATA_END):
            raise ValueError("NOLOAD must be in BTH data allocation")
    for a, b in zip(sorted(vmas), sorted(vmas)[1:]):
        if a[1] > b[0]:
            raise ValueError("overlapping ELF VMA segments")
    loads.sort()
    if not loads or loads[0][0] != CODE or len(loads[0][1]) < 8:
        raise ValueError("missing vector table at fixed BTH base")
    for a, b in zip(loads, loads[1:]):
        if a[0] + len(a[1]) > b[0]:
            raise ValueError("overlapping LMA segments")
    blob = bytearray(b"\xff" * (loads[-1][0] + len(loads[-1][1]) - CODE))
    for address, data in loads:
        blob[address - CODE:address - CODE + len(data)] = data
    sp, reset = struct.unpack_from("<II", blob)
    if sp & 7 or not DATA < sp <= DATA_END:
        raise ValueError("invalid initial stack")
    if not reset & 1 or not CODE <= reset - 1 < CODE + len(blob) or reset != entry:
        raise ValueError("invalid Thumb reset/ELF entry")
    if not any("E" in str(s["flags"]) and int(s["vaddr"]) <= reset - 1 <
               int(s["vaddr"]) + int(s["filesz"]) for s in segments):
        raise ValueError("entry is not file-backed executable code")
    # Debug sections and ELF file offsets are not firmware identity. Include the
    # load/zero-init contract and content, plus the explicit source/config lock.
    contract = [{key: seg[key] for key in ("vaddr", "paddr", "filesz", "memsz", "flags")}
                for seg in segments]
    digest = hashlib.sha256(json.dumps(contract, sort_keys=True).encode()
                            + blob + build_material).hexdigest()
    build = int(digest[:8], 16)
    crc = zlib.crc32(blob)
    header = struct.pack("<16I", MAGIC, 1, LAYOUT, build, len(blob), crc,
                         CODE, sp, reset, 24000000, 6000000, *([0] * 5))
    return header + blob, {"build": f"0x{build:08x}", "build_sha256": digest,
        "layout": f"0x{LAYOUT:08x}", "vector": CODE, "initial_sp": sp,
        "entry": reset, "code_bytes": len(blob), "crc32": crc,
        "cpu_hz": 24000000, "timer_hz": 6000000, "uart_hz": 24000000,
        "uart_baud": 1152000, "segments": segments,
        "physical_ranges": {"adapter": [0x20500000, 0x20510000],
            "code": [0x20510000, DATA], "data": [DATA, DATA_END],
            "diagnostics": [DATA_END, 0x2055FFE0], "mailbox": [0x2055FFE0, 0x20560000]}}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("elf", type=Path)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--identity", type=Path, required=True)
    args = ap.parse_args()
    material = args.identity.read_bytes()
    info = run_readelf(args.elf)
    payload, report = pack(args.elf.read_bytes(), parse_load_segments(info), parse_entry(info), material)
    report["payload_sha256"] = hashlib.sha256(payload).hexdigest()
    report["elf_sha256"] = hashlib.sha256(args.elf.read_bytes()).hexdigest()
    args.output.write_bytes(payload)
    args.manifest.write_text(json.dumps(report, indent=2) + "\n")
    print(f"BTH payload {report['build']}: {report['code_bytes']} bytes; layout checked")


if __name__ == "__main__":
    main()
