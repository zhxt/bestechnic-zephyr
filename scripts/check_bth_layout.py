#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Audit both ELFs and the combined BES image before release."""
import argparse
import hashlib
import json
import re
import struct
import subprocess
from pathlib import Path
from pack_m55_payload import parse_load_segments, run_readelf
from pack_bth_payload import within


def output(*args):
    return subprocess.check_output(args, text=True)


def symbols(elf, cross):
    result = {}
    for line in output(cross + "nm", "-n", str(elf)).splitlines():
        words = line.split()
        if len(words) == 3:
            result[words[2]] = int(words[0], 16)
    return result


def audit_early_ram(syms):
    """Flash setup must use code/data copied or cleared before hal_cmu_setup."""
    groups = {
        'text': ('__boot_text_sram_start__', '__boot_text_sram_end__',
                 ('memcpy', 'hal_norflash_init', 'norflash_set_mode', 'norflash_match_chip')),
        'data': ('__boot_data_sram_start__', '__boot_data_sram_end__', ('norflash_cfg',)),
        'bss': ('__boot_bss_sram_start__', '__boot_bss_sram_end__', ('norflash_ctx',)),
    }
    result = {}
    for kind, (start, end, names) in groups.items():
        low, high = ((0x00500000, 0x00510000) if kind == 'text' else (0x20500000, 0x20510000))
        if not low <= syms.get(start, -1) < syms.get(end, -1) <= high:
            raise ValueError('Invalid early boot RAM range: ' + kind)
        for name in names:
            if not syms[start] <= syms.get(name, -1) < syms[end]:
                raise ValueError('Early boot symbol outside initialized RAM: ' + name)
            result[name] = syms[name]
    return result


def audit(adapter, zephyr, binary, payload, manifest, cross):
    syms, zsyms = symbols(adapter, cross), symbols(zephyr, cross)
    early_ram = audit_early_ram(syms)
    forbidden = [s for s in syms if re.match(r"(?:osKernel|osThread|osRtx|rtx_|software_init_hook|dsp_m55_open|btdrv_start_bt)", s)]
    if forbidden:
        raise ValueError(f"unexpected RTOS/other core startup dependencies: {forbidden}")
    for name in ("Boot_Loader", "hal_cmu_boot_m55_start_bth", "bth_boot_adapter_main", "bth_enter_zephyr"):
        if name not in syms:
            raise ValueError(f"missing adapter entry {name}")
    if not 0x20500000 < syms["__StackLimit"] < syms["__StackTop"] <= 0x20510000:
        raise ValueError("adapter stack outside its private 64 KiB")
    if not syms["__bss_start__"] <= syms["adapter_bss_probe"] < syms["__bss_end__"] <= syms["__StackLimit"]:
        raise ValueError("adapter BSS is not covered by startup clearing")
    if not syms["__data_start__"] <= syms["adapter_data_probe"] < syms["__data_end__"]:
        raise ValueError("adapter data probe outside data copy")
    # PT_LOADs can overlap: the BES linker emits overlays and a NOLOAD
    # aggregate spanning boot code aliases. Every address must still fit.
    segs = parse_load_segments(run_readelf(adapter))
    for s in segs:
        v, m, p, n = (int(s[k]) for k in ("vaddr", "memsz", "paddr", "filesz"))
        if n > m:
            raise ValueError("adapter filesz > memsz")
        if not any(within(v, m, lo, hi) for lo, hi in (
                (0x20500000, 0x20510000), (0x00500000, 0x00510000),
                (0x34000000, 0x34800000), (0x14000000, 0x14800000),
                (0x30000000, 0x30800000))):
            raise ValueError(f"adapter VMA exceeds allocation: {s}")
        if n and not within(p, n, 0x34000000, 0x34800000):
            raise ValueError(f"adapter LMA outside flash: {s}")
    # Prove that no ordinary BSS orphan escaped the now-fixed linker wildcard.
    sections = output("readelf", "-W", "-S", str(adapter))
    for match in re.finditer(r"\[\s*\d+\]\s+(\.bss\S*)\s+NOBITS\s+([0-9a-f]+)\s+[0-9a-f]+\s+([0-9a-f]+)", sections):
        if not within(int(match[2], 16), int(match[3], 16), syms["__bss_start__"], syms["__bss_end__"]):
            raise ValueError(f"orphan BSS section {match[1]}")
    image = binary.read_bytes()
    packed = payload.read_bytes()
    # Same pre-download format as the validated V04b combined image:
    # MAGIC_NUM_AUTO is off, so the programmer owns boot magic finalization.
    if not 16 <= len(image) <= 0x800000:
        raise ValueError("invalid combined BES boot header/length")
    magic, flags_version, reserved, build_info = struct.unpack_from("<4I", image)
    if (magic, flags_version, reserved) != (0xffffffff, 0x00040000, 0) or \
            not 0x34000000 <= build_info < 0x34000000 + len(image):
        raise ValueError("unexpected SDK v4 pre-download header")
    offset = syms["bth_payload_start"] - 0x34000000
    if image[offset:offset + len(packed)] != packed or syms["bth_payload_end"] - syms["bth_payload_start"] != len(packed):
        raise ValueError("combined image does not contain the exact checked payload")
    if hashlib.sha256(packed).hexdigest() != manifest["payload_sha256"]:
        raise ValueError("payload differs from manifest")
    if hashlib.sha256(zephyr.read_bytes()).hexdigest() != manifest["elf_sha256"]:
        raise ValueError("Zephyr ELF differs from manifest")
    if zsyms.get("_vector_start") != manifest["vector"]:
        raise ValueError("Zephyr vector symbol differs from manifest")
    disasm = output(cross + "objdump", "-d", "--disassemble=Boot_Loader", str(adapter))
    if not all(f"<{name}>" in disasm for name in ("hal_cmu_boot_m55_start_bth", "BootInit", "bth_boot_adapter_main")):
        raise ValueError("adapter boot chain missing from disassembly")
    if re.search(r"\bbl\s+.*<(?:_start|__rt_entry)>", disasm):
        raise ValueError("adapter enters ordinary C runtime")
    return {"status": "pass", "hardware_status": "not_tested", "adapter_segments": segs,
        "early_boot_ram": early_ram,
        "adapter_stack": [syms["__StackLimit"], syms["__StackTop"]],
        "adapter_bss": [syms["__bss_start__"], syms["__bss_end__"]],
        "combined_bytes": len(image), "combined_sha256": hashlib.sha256(image).hexdigest(),
        "boot_header": "SDK v4, magic=0xffffffff before programmer finalization (same as V04b)",
        "embedded_payload_offset": offset, "forbidden_symbols": forbidden,
        "boot_chain": "M55 entry hook -> BTH BootInit -> data/BSS -> adapter -> Zephyr",
        "security_contract": "same current security domain; no CMSE/BLXNS or SAU reconfiguration"}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ("adapter", "zephyr", "binary", "payload", "manifest", "output"):
        ap.add_argument("--" + name, type=Path, required=True)
    ap.add_argument("--cross-compile", required=True)
    a = ap.parse_args()
    report = audit(a.adapter, a.zephyr, a.binary, a.payload, json.loads(a.manifest.read_text()), a.cross_compile)
    a.output.write_text(json.dumps(report, indent=2) + "\n")
    print("BTH dual-ELF/combined-image audit: pass (hardware not tested)")
