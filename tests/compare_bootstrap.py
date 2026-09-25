#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Controlled bootstrap experiment with an explicitly supplied historical payload.

This diagnostic is never an input to the normal dual-Zephyr build.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from firmware import fill_build_info, function_bytes
from check_bth_layout import audit, symbols


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--baseline', type=Path, required=True)
    ap.add_argument('--baseline-image', type=Path, default=Path('zephyr.bin'),
                    help='Baseline image path, relative to --baseline unless absolute (default: zephyr.bin)')
    ap.add_argument('--build-dir', type=Path, required=True)
    ap.add_argument('--cross-compile', required=True)
    a = ap.parse_args()
    baseline, build = a.baseline.resolve(), a.build_dir.resolve()
    if build.exists():
        raise ValueError('experiment needs a fresh build directory')
    baseline_image = (baseline / a.baseline_image).resolve()
    baseline_data = baseline_image.read_bytes()
    generated = build / 'generated'
    generated.mkdir(parents=True)
    layout = json.loads((baseline / 'layout.json').read_text())
    cross = a.cross_compile
    old_elf = baseline / 'adapter.elf'
    old_symbols = symbols(old_elf, cross)
    raw = generated / 'baseline.raw.bin'
    subprocess.run([cross + 'objcopy', '-R', '.trc_str', '-O', 'binary', str(old_elf), str(raw)], check=True)
    data = raw.read_bytes()
    offset = old_symbols['sys_build_info'] - 0x34000000
    info = data[offset:data.index(b'\0', offset)].decode()
    (generated / 'build_info.c').write_text('const char sys_build_info[] __attribute__((section(".build_info"))) = '
                                          + json.dumps(info) + ';\n')
    (generated / 'boot_profile_id.h').write_text(f'#define BOOT_PROFILE_ID {layout["profile_id"]}U\n#define BOOT_PROFILE_VARIANT 2U\n')
    payload = generated / 'bth.payload.bin'
    shutil.copyfile(baseline / 'bth.payload.bin', payload)
    hal = ROOT.parent / 'modules/hal/bestechnic'
    subprocess.run(['cmake', '-S', str(ROOT / 'platforms/bes2700yp/boot/bootstrap'),
                    '-B', str(build / 'bootstrap'), '-GNinja', '-DCROSS_COMPILE=' + cross,
                    '-DHAL_ROOT=' + str(hal), '-DINTEGRATION_ROOT=' + str(ROOT),
                    '-DGENERATED_DIR=' + str(generated),
                    '-DCMSIS_ROOT=' + str(ROOT.parent / 'modules/hal/cmsis_6')], check=True)
    subprocess.run(['cmake', '--build', str(build / 'bootstrap'), '--parallel', '8'], check=True)
    elf = build / 'bootstrap/adapter.elf'
    new_symbols = symbols(elf, cross)
    subprocess.run([cross + 'objcopy', '-R', '.trc_str', '-O', 'binary', str(elf), str(generated / 'new.raw.bin')], check=True)
    binary = build / 'experiment.bin'
    binary.write_bytes(fill_build_info((generated / 'new.raw.bin').read_bytes(), new_symbols))
    report = audit(elf, baseline / 'bth.elf', binary, payload, layout, cross)
    report['purpose'] = 'Controlled comparison only; historical payload is not a normal build input'
    report['same_payload_sha256'] = hashlib.sha256(payload.read_bytes()).hexdigest()
    report['same_build_info_source'] = True
    report['same_profile_id'] = layout['profile_id']
    report['functions'] = {}
    for name in ('bth_crc32', 'bth_copy_bytes'):
        before, after = function_bytes(old_elf, name, cross), function_bytes(elf, name, cross)
        if before != after:
            raise ValueError('T2 function changed: ' + name)
        report['functions'][name] = {'identical': True, 'before': old_symbols[name], 'after': new_symbols[name]}
    for name in ('Boot_Loader', 'BootInit'):
        calls = []
        for target in (old_elf, elf):
            dis = subprocess.check_output([cross + 'objdump', '-d', '--disassemble=' + name, str(target)], text=True)
            calls.append(re.findall(r'\bbl(?:\.w)?\s+[0-9a-f]+ <([^>]+)>', dis))
        if calls[0] != calls[1]:
            raise ValueError('early boot call ordering differs: ' + name)
        report[name + '_calls'] = calls[0]
    report['baseline_image'] = str(baseline_image)
    report['baseline_sha256'] = hashlib.sha256(baseline_data).hexdigest()
    report['baseline_bytes'] = len(baseline_data)
    report['binary_identical'] = binary.read_bytes() == baseline_data
    report['known_changes'] = ['Public HAL facade introduces call boundaries',
                              'Archive grouping changes function placement and relocation targets',
                              'Normalized source/debug paths and linker build ID differ']
    (build / 'comparison.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Controlled bootstrap comparison passed; binary equality is not asserted.')


if __name__ == '__main__':
    main()
