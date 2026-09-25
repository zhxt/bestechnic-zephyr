#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Validate V05 boot sessions against the release's layout.json; no inferred cold boots."""
import argparse
import json
import re
from pathlib import Path

STAGES = ["adapter_ready", "handoff", "reset", "early", "main"]


def check_session(lines, manifest):
    errors, missing, stages, samples, seen = [], [], [], [], {}
    stage_index = -1
    for line_number, line in lines:
        if not line.endswith(" !"):
            missing.append(f"line {line_number}: truncated record")
            continue
        words = line[len("zephyr_bth "):-2].split()
        try:
            kind = "stage" if words[0].startswith("stage=") else words.pop(0)
            fields = {}
            for word in words:
                key, value = word.split("=", 1)
                if key in fields:
                    raise ValueError("duplicate field")
                fields[key] = value if key == "stage" else int(value, 0)
        except (ValueError, IndexError):
            errors.append(f"line {line_number}: malformed record")
            continue
        if kind == "stage":
            stage = fields.get("stage")
            if stage not in STAGES:
                errors.append(f"unexpected stage {stage}")
                continue
            index = STAGES.index(stage)
            if index <= stage_index:
                errors.append(f"duplicate/out-of-order stage {stage}")
            stage_index = index
            stages.append(stage)
        elif kind == "progress":
            if stage_index != 4 or "result" in seen:
                errors.append("progress outside main/result interval")
            if set(fields) != {"sample", "timer_ticks"}:
                errors.append("malformed progress")
                continue
            samples.append(fields)
        else:
            if kind in seen:
                errors.append(f"duplicate {kind}")
            if kind == "fault":
                errors.append("CPU fault")
            seen[kind] = fields
            expected_stage = {"begin": -1, "adapter": 0, "image": 0, "uart": 0, "state": 0,
                              "cpu": 3, "regs": 3, "masks": 3, "limits": 3,
                              "clock": 3, "memory": 3, "result": 4}
            if kind not in expected_stage:
                errors.append(f"unknown record {kind}")
            elif stage_index != expected_stage[kind] and kind != "result":
                errors.append(f"{kind} at wrong stage")
    build = int(str(manifest["build"]), 0)
    layout = int(str(manifest["layout"]), 0)
    required = {
        "begin": {"version": 1, "test": 5, "build": build},
        "image": {"layout": layout, "verified": 1},
        "uart": {"ibrd": 1, "fbrd": 19},
        "state": {"cache": 0, "mpu": 0, "systick": 0},
        "memory": {"data": 1, "bss": 1, "guards": 1},
        "clock": {k: manifest[k] for k in ("cpu_hz", "uart_hz", "timer_hz")},
        "masks": {"primask": 0, "basepri": 0, "faultmask": 0},
        "result": {"pass": 1, "samples": 60, "rc": 0},
    }
    for kind, expected in required.items():
        if kind not in seen:
            missing.append(kind)
        elif seen[kind] != expected:
            errors.append(f"{kind} mismatch: {seen[kind]}")
    for kind in ("adapter", "cpu", "regs", "limits"):
        if kind not in seen:
            missing.append(kind)
    for kind, expected_control in (("adapter", 0), ("cpu", 2)):
        if kind in seen:
            f = seen[kind]
            if set(f) != {"cpuid", "ipsr", "control"} or f.get("ipsr") != 0 or \
                    f.get("control") != expected_control or f.get("cpuid", 0) in (0, 0xffffffff):
                errors.append(f"invalid {kind} context")
    if "adapter" in seen and "cpu" in seen and seen["adapter"].get("cpuid") != seen["cpu"].get("cpuid"):
        errors.append("CPUID changed across handoff")
    if "regs" in seen:
        f = seen["regs"]
        low, high = manifest["physical_ranges"]["data"]
        if set(f) != {"vtor", "msp", "psp"} or f.get("vtor") != manifest["vector"] or \
                not all(low < f.get(k, 0) <= high and f[k] % 8 == 0 for k in ("msp", "psp")):
            errors.append("invalid VTOR/stack range/alignment")
    if "limits" in seen and seen["limits"] != {"msplim": 0, "psplim": 0}:
        errors.append("unexpected stack limits for V05 MPU-disabled configuration")
    missing += [f"stage {stage}" for stage in STAGES if stage not in stages]
    ids = [s["sample"] for s in samples]
    if ids != sorted(set(ids)) or any(i < 0 or i >= 60 for i in ids):
        errors.append("duplicate/out-of-order/out-of-range samples")
    if ids != list(range(60)):
        missing.append("60 consecutive samples")
    hz = manifest["timer_hz"]
    for s in samples:
        # Expected elapsed, not Zephyr uptime. Tolerate UART/interrupt overhead,
        # but reject implausible speed, timer stalls and spurious counter jumps.
        if not s["sample"] * hz <= s["timer_ticks"] <= s["sample"] * hz + hz // 4:
            errors.append(f"sample {s['sample']}: timer outside expected window")
    return {"status": "fail" if errors else "incomplete" if missing else "pass",
            "build": f"0x{seen.get('begin', {}).get('build', 0):08x}",
            "stages": stages, "samples": len(samples), "errors": errors, "missing": missing}


def analyze(text, manifest):
    sessions, current = [], None
    for line_number, raw in enumerate(text.splitlines(), 1):
        pos = raw.find("zephyr_bth ")
        if pos < 0:
            continue
        line = raw[pos:]
        if line.startswith("zephyr_bth begin "):
            if current is not None:
                sessions.append(check_session(current, manifest))
            current = []
        if current is not None:
            current.append((line_number, line))
    if current is not None:
        sessions.append(check_session(current, manifest))
    return {"status": sessions[-1]["status"] if sessions else "incomplete",
            "sessions": sessions, "session_count": len(sessions),
            "note": "Status is the latest boot. Cold-boot provenance and V04b rollback require operator records."}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("log", type=Path)
    ap.add_argument("--manifest", type=Path, required=True)
    ap.add_argument("--output", type=Path)
    args = ap.parse_args()
    result = analyze(args.log.read_text(errors="replace"), json.loads(args.manifest.read_text()))
    rendered = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        args.output.write_text(rendered)
    print(rendered, end="")
    return {"pass": 0, "fail": 1, "incomplete": 2}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
