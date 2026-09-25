#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Strict per-session V02/V03/V04 log acceptance; never joins separate boots."""
import argparse
import json
from pathlib import Path
import re


def analyze(text, mode, count, restarts, build):
    text = re.split(r"CHIP[=:]|zephyr_m55_boot_test_start", text)[-1]
    if re.search(r"HardFault|BusFault|UsageFault|\bASSERT\b|mapping_failure", text, re.I):
        raise ValueError("Firmware fault or MPU mapping failure")
    lines = [line.split("zephyr_ipc ", 1)[1].strip()
             for line in text.splitlines() if "zephyr_ipc " in line]
    expected = [f"begin mode={mode} count={count} restarts={restarts} !", "bth_nc=1 !"]
    for session in range(1, restarts + 2):
        expected.extend([
            f"ready session={session} build={build:08x} nc=1 !",
            f"full session={session} unchanged=1 !",
            f"counts session={session} tx={count} rx={count} !",
            f"checks session={session} crc=1 stale=1 guards=1 !",
            f"quiesced session={session} !",
            f"session={session} pass=1 rc=0 !",
        ])
        if session <= restarts:
            expected.extend([f"off session={session} !", f"on session={session + 1} !"])
    expected.append(f"result pass=1 sessions={restarts + 1} rc=0 !")
    required = []
    current = 0
    progress = -1
    for line in lines:
        ready = re.fullmatch(r"ready session=(\d+) build=[0-9a-f]{8} nc=1 !", line)
        if ready:
            current, progress = int(ready[1]), -1
        match = re.fullmatch(r"progress session=(\d+) data=(\d+) !", line)
        if match:
            s, n = map(int, match.groups())
            if (s != current or not progress < n <= count or not required or
                    required[-1] != f"full session={current} unchanged=1 !"):
                raise ValueError("Invalid progress or session")
            progress = n
            continue
        required.append(line)
    if required != expected:
        index = next((i for i, pair in enumerate(zip(required, expected)) if pair[0] != pair[1]),
                     min(len(required), len(expected)))
        got = required[index] if index < len(required) else "<missing>"
        want = expected[index] if index < len(expected) else "<end>"
        raise ValueError(f"Event {index}: expected {want!r}, got {got!r}")
    return {"pass": True, "mode": mode, "build": f"0x{build:08x}", "sessions": restarts + 1,
            "restarts": restarts, "data_each_direction_per_session": count}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("log", type=Path)
    p.add_argument("--mode", type=int, choices=[2, 3, 4], required=True)
    p.add_argument("--count", type=int, required=True)
    p.add_argument("--restarts", type=int, required=True)
    p.add_argument("--expected-build", type=lambda s: int(s, 16), required=True)
    a = p.parse_args()
    try:
        result = analyze(a.log.read_text(errors="replace"), a.mode, a.count, a.restarts, a.expected_build)
    except ValueError as e:
        print(json.dumps({"pass": False, "reason": str(e)}, ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
