#!/usr/bin/env python3
# Copyright The Zephyr Project Contributors
# SPDX-License-Identifier: Apache-2.0
"""Validate the latest BES2700 doorbell test session in a captured serial log."""

import argparse
import json
from pathlib import Path


def analyze(text, expected_build=None):
    records = [line[line.index("zephyr_db ") + len("zephyr_db "):].strip()
               for line in text.splitlines() if "zephyr_db " in line]
    starts = [i for i, line in enumerate(records) if line.startswith("begin ")]
    errors = []
    if not starts:
        return {"status": "incomplete", "errors": ["Missing begin record"]}
    records = records[starts[-1]:]
    parsed = {}
    for line in records:
        if not line.endswith(" !"):
            errors.append(f"Truncated or unexpected record: {line}")
            continue
        fields = line[:-2].split()
        if fields[0].startswith("phase="):
            key = fields[0]
            fields = fields[1:]
        else:
            key, fields = fields[0], fields[1:]
        data = {}
        for item in fields:
            if "=" not in item:
                errors.append(f"Invalid field: {item}")
                continue
            name, value = item.split("=", 1)
            if name in data:
                errors.append(f"Repeated field: {key}.{name}")
            # CPU registers have unprefixed hexadecimal values.
            try:
                data[name] = int(value, 16 if key == "cpu" else 0)
            except ValueError:
                errors.append(f"Invalid number: {key}.{name}={value}")
        if key in parsed:
            errors.append(f"Duplicate record: {key}")
        parsed[key] = data

    expected = {
        "begin": {"format": 1, "channel": 1, "rounds": 1000},
        "ready": {"hz": 24000000, "channel": 1},
        "phase=bth_initiator": {"rounds": 1000, "pass": 1},
        "phase=m55_initiator": {"rounds": 1000, "pass": 1},
        "phase=rx_pause": {"pass": 1},
        "phase=burst": {"calls": 32, "delivered": 2, "pass": 1},
        "m55": {"rx": 2003, "req": 2033, "kicks": 2003, "done": 2003},
        "state": {"stage": 5, "err": 0, "queued": 31, "spurious": 0},
        "bth": {"tx": 2003, "rx": 2003, "done": 2003},
        "result": {"pass": 1, "rc": 0},
    }
    if expected_build is not None:
        expected["ready"]["build"] = int(str(expected_build), 0)
    complete = "result" in parsed
    for key, values in expected.items():
        if key not in parsed:
            if complete:
                errors.append(f"Missing record: {key}")
            continue
        for field, value in values.items():
            if parsed[key].get(field) != value:
                errors.append(f"{key}.{field}: expected {value}, got {parsed[key].get(field)}")
    if complete:
        for key, fields in {"ready": ["build"], "cpu": ["cpuid", "ictr", "ccr", "mpu"]}.items():
            for field in fields:
                if field not in parsed.get(key, {}):
                    errors.append(f"Missing diagnostic: {key}.{field}")
    return {"status": "fail" if errors else "pass" if complete else "incomplete",
            "errors": errors, "records": parsed,
            "scope": "Doorbell notifications only; no shared-message or BTH Zephyr claim"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--expected-build")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    report = analyze(args.log.read_text(errors="replace"), args.expected_build)
    output = json.dumps(report, indent=2, ensure_ascii=False) + "\n"
    if args.json:
        args.json.write_text(output)
    print(output, end="")
    return {"pass": 0, "fail": 1, "incomplete": 2}[report["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
