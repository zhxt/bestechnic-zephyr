#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Validate complete rounds of the continuous doorbell exercise."""

import argparse
import json
from pathlib import Path
import re

from analyze_ipc_doorbell import analyze as analyze_round


def analyze(text, min_seconds=600, min_rounds=100, expected_build=None):
    text = text.rsplit("CHIP=best1600", 1)[-1]
    marker = re.compile(r"^zephyr_db (repeat|repeat_end) round=(\d+) ticks=(\d+) hz=(\d+) !$")
    active = None
    errors = []
    reports = []
    last_end = None
    frequency = None
    elapsed = 0.0
    busy_seconds = 0.0
    for line in text.splitlines():
        index = line.find("zephyr_db ")
        if index < 0:
            continue
        line = line[index:].strip()
        match = marker.fullmatch(line)
        if match:
            kind, number, ticks, hz = match.groups()
            number, ticks, hz = int(number), int(ticks), int(hz)
            if ticks >= 2**32 or hz <= 0:
                errors.append("Invalid clock record")
                continue
            if frequency is None:
                frequency = hz
            if hz != frequency:
                errors.append("Clock frequency changed")
            if kind == "repeat":
                if active is not None:
                    errors.append("Next round started before previous round ended")
                if number != len(reports):
                    errors.append(f"Nonconsecutive round {number}")
                if last_end is not None:
                    gap = ((ticks - last_end) & 0xffffffff) / hz
                    elapsed += gap
                    if gap > 2:
                        errors.append(f"Inter-round gap exceeds 2 seconds: {gap}")
                active = {"number": number, "start": ticks, "hz": hz, "lines": []}
            elif active is None or number != active["number"]:
                errors.append("End record has no matching round")
            else:
                body = "\n".join(active["lines"])
                if body.count("zephyr_db begin ") != 1:
                    errors.append(f"Round {number}: missing or duplicate begin")
                result = analyze_round(body, expected_build)
                if result["status"] != "pass":
                    errors.append(f"Round {number}: {result}")
                duration = ((ticks - active["start"]) & 0xffffffff) / hz
                if duration <= 0:
                    errors.append(f"Round {number}: nonpositive duration")
                elapsed += duration
                busy_seconds += duration
                reports.append({"round": number, "seconds": duration, "status": result["status"]})
                last_end = ticks
                active = None
            continue
        if line.startswith(("zephyr_db repeat", "zephyr_db conflict")):
            errors.append(f"Failure or malformed boundary: {line}")
        elif active is not None:
            active["lines"].append(line)
        else:
            errors.append(f"Unframed doorbell record: {line}")
    incomplete = active is not None or len(reports) < min_rounds or elapsed < min_seconds
    return {"status": "fail" if errors else "incomplete" if incomplete else "pass",
            "errors": errors, "completed_rounds": len(reports), "seconds": elapsed,
            "round_execution_seconds": busy_seconds,
            "single_flight_round_trips_per_direction": len(reports) * 1000,
            "active_round": active["number"] if active else None,
            "clock_hz": frequency, "rounds": reports}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path)
    parser.add_argument("--expected-build", required=True)
    parser.add_argument("--min-seconds", type=int, default=600)
    parser.add_argument("--min-rounds", type=int, default=100)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    result = analyze(args.log.read_text(errors="replace"), args.min_seconds,
                     args.min_rounds, args.expected_build)
    output = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.json:
        args.json.write_text(output)
    print(output, end="")
    return {"pass": 0, "fail": 1, "incomplete": 2}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
