#!/usr/bin/env python3
#
# SPDX-License-Identifier: Apache-2.0

"""Package a Zephyr CM55 ELF for the BES2700 BTH dsp_m55_open() loader.

BES SDK v2.8 dsp_m55_open() expects the embedded M55 image to use the
SUBSYS_IMAGE_TYPE_SEGMENT format:

    struct boot_hdr_t             // 16 bytes
    struct SUBSYS_IMAGE_DESC_T    // 16 bytes
    struct CODE_SEG_MAP_ITEM_T[]  // 12 bytes each
    payload bytes

The BTH loader also treats the first segment exec_addr as the CPU entry point.
A Zephyr ELF's first loadable bytes are the vector table, not executable code,
so this packer prepends a tiny CM55 trampoline segment. The trampoline sets
SCB->VTOR to Zephyr's vector table and branches to Zephyr's reset vector.

File-backed ELF segments are loaded at p_paddr (LMA). Zephyr's XIP startup
copies initialized data from LMA to p_vaddr (VMA); NOLOAD memory is not loaded.
"""

from __future__ import annotations

import argparse
import json
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

BOOT_MAGIC_NUMBER = 0xBE57EC1C
SUBSYS_IMAGE_DESC_VERSION = 0
SUBSYS_IMAGE_TYPE_SEGMENT = 1
BOOT_HDR_SIZE = 16
SUBSYS_IMAGE_DESC_SIZE = 16
CODE_SEG_MAP_ITEM_SIZE = 12
DEFAULT_TRAMPOLINE_ADDR = 0x2015E000


def align_up(value: int, alignment: int) -> int:
    return (value + alignment - 1) & ~(alignment - 1)


def read_u32_le(data: bytes, offset: int) -> int:
    return struct.unpack_from("<I", data, offset)[0]


def run(cmd: list[str]) -> None:
    subprocess.run(cmd, check=True)


def run_readelf(elf: Path) -> str:
    result = subprocess.run(
        ["readelf", "-W", "-l", str(elf)],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return result.stdout


def parse_int(text: str) -> int:
    return int(text, 16 if text.startswith("0x") else 10)


def parse_entry(readelf_output: str) -> int | None:
    for line in readelf_output.splitlines():
        line = line.strip()
        if line.startswith("Entry point"):
            return parse_int(line.rsplit(" ", 1)[1])

    return None


def parse_load_segments(readelf_output: str) -> list[dict[str, object]]:
    segments: list[dict[str, object]] = []

    for line in readelf_output.splitlines():
        fields = line.split()
        if len(fields) < 8 or fields[0] != "LOAD":
            continue

        segments.append(
            {
                "offset": parse_int(fields[1]),
                "vaddr": parse_int(fields[2]),
                "paddr": parse_int(fields[3]),
                "filesz": parse_int(fields[4]),
                "memsz": parse_int(fields[5]),
                "flags": " ".join(fields[6:-1]),
                "align": parse_int(fields[-1]),
            }
        )

    return segments


def hexify_segments(segments: list[dict[str, object]]) -> list[dict[str, str]]:
    return [
        {
            "offset": f"0x{int(segment['offset']):x}",
            "vaddr": f"0x{int(segment['vaddr']):08x}",
            "paddr": f"0x{int(segment['paddr']):08x}",
            "filesz": f"0x{int(segment['filesz']):x}",
            "memsz": f"0x{int(segment['memsz']):x}",
            "flags": str(segment["flags"]),
            "align": f"0x{int(segment['align']):x}",
        }
        for segment in segments
    ]


def resolve_tool(cross_compile: str, name: str) -> str:
    tool = f"{cross_compile}{name}" if cross_compile else name
    found = shutil.which(tool)
    if found:
        return found
    if Path(tool).exists():
        return tool
    raise FileNotFoundError(f"cannot find tool: {tool}")


def build_trampoline(cross_compile: str, vector_addr: int, reset_vector: int, boot_trace: bool = False) -> bytes:
    gcc = resolve_tool(cross_compile, "gcc")
    objcopy = resolve_tool(cross_compile, "objcopy")

    trace = """
    ldr r0, =0x2015e180
    movs r1, #1
    str r1, [r0]
    dsb sy
""" if boot_trace else ""
    source = f"""
.syntax unified
.cpu cortex-m33
.thumb
.section .text.trampoline,\"ax\",%progbits
.global _start
.thumb_func
_start:
{trace}    ldr r0, =0xE000ED08
    ldr r1, =0x{vector_addr:08x}
    str r1, [r0]
    dsb sy
    isb sy
    ldr r0, =0x{reset_vector:08x}
    bx r0
"""

    with tempfile.TemporaryDirectory(prefix="bes2700_m55_trampoline_") as tmp:
        tmp_dir = Path(tmp)
        asm = tmp_dir / "trampoline.S"
        obj = tmp_dir / "trampoline.o"
        binary = tmp_dir / "trampoline.bin"
        asm.write_text(source)
        run([
            gcc,
            "-x",
            "assembler-with-cpp",
            "-mcpu=cortex-m33",
            "-mthumb",
            "-nostdlib",
            "-c",
            str(asm),
            "-o",
            str(obj),
        ])
        run([objcopy, "-O", "binary", "-j", ".text.trampoline", str(obj), str(binary)])
        return binary.read_bytes()


def padded(data: bytes, alignment: int = 4) -> bytes:
    return data + (b"\x00" * (align_up(len(data), alignment) - len(data)))


def build_bes_segment_image(
    elf: Path,
    segments: list[dict[str, object]],
    vector_addr: int,
    reset_vector: int,
    trampoline_addr: int,
    cross_compile: str,
    boot_trace: bool = False,
) -> tuple[bytes, list[dict[str, object]]]:
    elf_data = elf.read_bytes()
    trampoline = padded(build_trampoline(cross_compile, vector_addr, reset_vector, boot_trace))

    payloads: list[tuple[int, bytes, str]] = [(trampoline_addr, trampoline, "m55_vtor_trampoline")]
    for index, segment in enumerate(segments):
        filesz = int(segment["filesz"])
        if filesz == 0:
            continue
        offset = int(segment["offset"])
        if offset < 0 or filesz < 0 or offset + filesz > len(elf_data):
            raise ValueError(f"ELF LOAD {index} exceeds file bounds")
        if filesz > int(segment["memsz"]):
            raise ValueError(f"ELF LOAD {index} filesz exceeds memsz")
        payload = padded(elf_data[offset : offset + filesz])
        # The BES field is named exec_addr, but the loader uses it as the
        # copy destination. Only the first (trampoline) segment is the entry.
        payloads.append((int(segment["paddr"]), payload, f"elf_load_{index}"))

    previous_end = 0
    previous_name = ""
    for address, payload, name in sorted(payloads, key=lambda item: item[0]):
        end = address + len(payload)
        if address < 0 or address % 4 or end > (1 << 32):
            raise ValueError(f"Invalid BES load address for {name}: {address:#x}")
        if previous_name and address < previous_end:
            raise ValueError(f"BES load ranges overlap: {previous_name} and {name}")
        previous_end = end
        previous_name = name

    seg_map_size = len(payloads) * CODE_SEG_MAP_ITEM_SIZE
    code_start_offset = align_up(BOOT_HDR_SIZE + SUBSYS_IMAGE_DESC_SIZE + seg_map_size, 4)
    cursor = code_start_offset
    seg_items: list[dict[str, object]] = []
    image_payload = bytearray()

    for exec_addr, payload, name in payloads:
        cursor = align_up(cursor, 4)
        if len(image_payload) < cursor - code_start_offset:
            image_payload.extend(b"\x00" * (cursor - code_start_offset - len(image_payload)))
        load_offset = cursor
        image_payload.extend(payload)
        seg_items.append(
            {
                "name": name,
                "exec_addr": exec_addr,
                "load_offset": load_offset,
                "size": len(payload),
            }
        )
        cursor += len(payload)

    image_size = code_start_offset + len(image_payload)

    boot_hdr = struct.pack("<IHHII", BOOT_MAGIC_NUMBER, 0, 0, 0, 0)
    desc = struct.pack(
        "<HBBIII",
        SUBSYS_IMAGE_DESC_VERSION,
        SUBSYS_IMAGE_TYPE_SEGMENT,
        0,
        image_size,
        code_start_offset,
        seg_map_size,
    )
    seg_map = b"".join(
        struct.pack("<III", item["exec_addr"], item["load_offset"], item["size"])
        for item in seg_items
    )
    header = padded(boot_hdr + desc + seg_map)
    if len(header) != code_start_offset:
        raise RuntimeError(f"internal header size mismatch: {len(header)} != {code_start_offset}")

    return header + bytes(image_payload), seg_items


def hexify_bes_segments(seg_items: list[dict[str, object]]) -> list[dict[str, str]]:
    return [
        {
            "name": str(item["name"]),
            "exec_addr": f"0x{int(item['exec_addr']):08x}",
            "load_offset": f"0x{int(item['load_offset']):x}",
            "size": f"0x{int(item['size']):x}",
        }
        for item in seg_items
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("elf", type=Path)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--bes-segment-bin", type=Path)
    parser.add_argument("--trampoline-addr", type=lambda value: int(value, 0), default=DEFAULT_TRAMPOLINE_ADDR)
    parser.add_argument("--cross-compile", default="")
    parser.add_argument("--boot-trace", action="store_true", help="V08a1 fixed boot marker at 0x2015e180")
    args = parser.parse_args()

    readelf_output = run_readelf(args.elf)
    segments = parse_load_segments(readelf_output)
    rom_segments = [segment for segment in segments if int(segment["filesz"])]
    if not rom_segments:
        raise RuntimeError("ELF has no file-backed LOAD segments")

    vector_segment = min(rom_segments, key=lambda segment: int(segment["paddr"]))
    elf_data = args.elf.read_bytes()
    vector_offset = int(vector_segment["offset"])
    initial_sp = read_u32_le(elf_data, vector_offset)
    reset_vector = read_u32_le(elf_data, vector_offset + 4)
    vector_addr = int(vector_segment["vaddr"])

    bes_image = None
    bes_segments: list[dict[str, object]] = []
    if args.bes_segment_bin:
        bes_image, bes_segments = build_bes_segment_image(
            args.elf,
            segments,
            vector_addr,
            reset_vector,
            args.trampoline_addr,
            args.cross_compile,
            args.boot_trace,
        )
        if not args.bes_segment_bin.exists() or args.bes_segment_bin.read_bytes() != bes_image:
            args.bes_segment_bin.write_bytes(bes_image)

    payload_map = {
        "elf": str(args.elf),
        "entry": f"0x{parse_entry(readelf_output):08x}",
        "vector_paddr": f"0x{int(vector_segment['paddr']):08x}",
        "vector_vaddr": f"0x{vector_addr:08x}",
        "vector_offset": f"0x{vector_offset:x}",
        "initial_sp": f"0x{initial_sp:08x}",
        "reset_vector": f"0x{reset_vector:08x}",
        "segments": hexify_segments(segments),
    }

    if args.bes_segment_bin:
        payload_map["bes_segment_image"] = {
            "load_address_policy": "ELF p_paddr (LMA); Zephyr startup copies to VMA",
            "path": str(args.bes_segment_bin),
            "size": f"0x{len(bes_image):x}",
            "boot_magic": f"0x{BOOT_MAGIC_NUMBER:08x}",
            "type": "SUBSYS_IMAGE_TYPE_SEGMENT",
            "code_start_offset": f"0x{align_up(BOOT_HDR_SIZE + SUBSYS_IMAGE_DESC_SIZE + len(bes_segments) * CODE_SEG_MAP_ITEM_SIZE, 4):x}",
            "trampoline_addr": f"0x{args.trampoline_addr:08x}",
            "segments": hexify_bes_segments(bes_segments),
        }

    args.output.write_text(json.dumps(payload_map, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
