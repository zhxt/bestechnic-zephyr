#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Mutate copies of a built arbitration ELF; every unsafe copy must be rejected."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from audit_arbitration import audit as audit_guard
from audit_resources import audit as audit_resource, file_span
from check_bth_layout import symbols
from pack_m55_payload import parse_load_segments, run_readelf


def run(release, cross):
    elf = release / 'adapter.elf'
    layout = json.loads((release / 'layout.json').read_text())
    probe = layout['arbitration_service']['probe']
    data = elf.read_bytes()
    segments = parse_load_segments(run_readelf(elf))
    syms = symbols(elf, cross)
    cases = []
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        audit_guard(elf, cross, probe)
        audit_resource(elf, release / 'bth.elf', cross, ROOT, root, arbitration=True)

        def reject(name, patches, *, descriptor=False, expected_probe=probe):
            changed = bytearray(data)
            for address, payload in patches:
                offset = file_span(segments, address, len(payload), executable=not descriptor)
                changed[offset:offset + len(payload)] = payload
            target = root / 'mutated.elf'
            target.write_bytes(changed)
            try:
                if descriptor:
                    audit_resource(target, release / 'bth.elf', cross, ROOT, root, arbitration=True)
                else:
                    audit_guard(target, cross, expected_probe)
            except ValueError as error:
                cases.append(dict(case=name, rejected=True, reason=str(error)))
            else:
                raise AssertionError('unsafe ELF accepted: ' + name)

        descriptor = syms['bes_arbitration_service']
        offset = file_span(segments, descriptor, 32)
        for index, value in enumerate(struct.unpack_from('<8I', data, offset)):
            reject(f'descriptor-word-{index}', [(descriptor + index*4, struct.pack('<I', value ^ 1))], descriptor=True)
        reject('readonly-cycle', [(syms['bes_arbitration_dispatch'], b'\xfe\xe7')], descriptor=True)
        for name in ('bes_arbitration_enter', 'bes_arbitration_leave', 'bes_arbitration_busy'):
            reject(name + '-cycle', [(syms[name], b'\xfe\xe7')])

        def instructions(name, pattern):
            text = subprocess.check_output([cross+'objdump', '-d', '--disassemble='+name, str(elf)], text=True)
            found = []
            for line in text.splitlines():
                match = re.match(r'\s*([0-9a-f]+):\s+((?:[0-9a-f]{4,8}\s+)+)\s*(\S+)\s*(.*)', line)
                if match and re.search(pattern, match[3]+' '+match[4], re.I):
                    size = sum(len(word)//2 for word in match[2].split())
                    found.append((int(match[1], 16), b'\x00\xbf' * (size//2)))
            if not found:
                raise AssertionError('mutation target absent: ' + pattern)
            return found

        for register in ('IPSR', 'CONTROL', 'PRIMASK'):
            reject('missing-'+register, instructions('bes_arbitration_enter', r'^mrs\b.*\b'+register+r'\b'))
        reject('missing-mask', instructions('bes_arbitration_enter', r'^cpsid\s+i'))
        reject('missing-restore', instructions('bes_arbitration_enter', r'^msr\s+PRIMASK'))
        for name in ('bes_arbitration_enter', 'bes_arbitration_leave', 'bes_arbitration_busy'):
            reject('bypass-'+name, instructions('dual_dispatch', r'^bl(?:\.w)?\b.*<'+name+r'>'))
        reject('wrong-probe-profile', [], expected_probe=not probe)
    return dict(status='pass', elf_sha256=hashlib.sha256(data).hexdigest(),
                profile=layout['validation_profile'], cases=cases, count=len(cases))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--release', type=Path, required=True)
    parser.add_argument('--cross-compile', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = run(args.release, args.cross_compile)
    args.output.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(dict(status=report['status'], rejected=report['count'])))
