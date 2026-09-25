#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Exercise real source/library changes, restoring all inputs in a finally block.

Run only in an idle migration workspace. This builds test variants, never flashes.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

import yaml


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--workspace', type=Path, required=True)
    ap.add_argument('--build-dir', type=Path, required=True)
    ap.add_argument('--cross-compile', required=True)
    a = ap.parse_args()
    workspace, build = a.workspace.resolve(), a.build_dir.resolve()
    root, hal = workspace / 'bestechnic-zephyr', workspace / 'modules/hal/bestechnic'
    logs = build / 'incremental-evidence'
    logs.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, ZEPHYR_BASE=str(workspace / 'zephyr'), CCACHE_DISABLE='1')

    def run(label, configure=False, failure=False):
        command = ['cmake', '--build', str(build), '--parallel', '8']
        if configure:
            command = [sys.executable, '-m', 'west', 'build', '--sysbuild', '-c',
                       '-b', 'bes2700yp_devkit/bes2700yp/bth', str(root / 'apps/bes2700yp/bth'),
                       '-d', str(build), '--', '-DZEPHYR_TOOLCHAIN_VARIANT=cross-compile',
                       '-DCROSS_COMPILE=' + a.cross_compile, '-DBES_VALIDATION_PROFILE=ipc-backpressure',
                       '-DBES_FORMAL_PACKAGE=OFF']
        log = logs / (label + '.log')
        with log.open('w') as stream:
            result = subprocess.run(command, cwd=workspace, env=env, stdout=stream, stderr=subprocess.STDOUT)
        if failure:
            if result.returncode == 0 or 'checksum mismatch' not in log.read_text():
                raise ValueError('corrupt HAL was not rejected for the expected reason')
            return {'rejected': True}
        result.check_returncode()
        files = ['m55/zephyr/zephyr.elf', 'generated/m55.segment.bin',
                 'bth/zephyr/zephyr.elf', 'generated/bth.payload.bin', 'bootstrap/adapter.elf', 'zephyr.bin']
        hashes = {name: sha(build / name) for name in files}
        if (build / 'generated/m55.segment.bin').read_bytes() not in (build / 'generated/bth.payload.bin').read_bytes():
            raise ValueError('stale M55 payload')
        print(label, hashes['zephyr.bin'], flush=True)
        return hashes

    sources = [root / f'apps/bes2700yp/{core}/src/main.c' for core in ('m55', 'bth')]
    manifest_path, lock = hal / 'manifest.json', root / 'hal-release.sha256'
    module_path = hal / 'zephyr/module.yml'
    metadata = json.loads(manifest_path.read_text())
    module = yaml.safe_load(module_path.read_text())
    libname = next(name for name in metadata['artifacts'] if name.endswith('system.a'))
    library = hal / libname
    originals = {p: p.read_bytes() for p in sources + [manifest_path, module_path, lock, library]}
    results = {}
    try:
        results['baseline'] = run('baseline', configure=True)
        results['noop'] = run('noop')
        if results['baseline'] != results['noop']:
            raise ValueError('no-op rebuild changes artifacts')
        for core, source in zip(('m55', 'bth'), sources):
            before = originals[source]
            needle = b'int main(void)\n{'
            if before.count(needle) != 1:
                raise ValueError('unexpected application entry')
            source.write_bytes(before.replace(needle, needle + b'\n __asm__ volatile ("nop");'))
            results[core] = run(core)
            for name in (['generated/m55.segment.bin'] if core == 'm55' else []) + ['generated/bth.payload.bin', 'zephyr.bin']:
                if results[core][name] == results['baseline'][name]:
                    raise ValueError('missing dependency propagation: ' + core + '/' + name)
            source.write_bytes(before)
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            (temp / 'marker.c').write_text('const unsigned bes_hal_incremental_marker = 0x10203040;\n')
            subprocess.run([a.cross_compile + 'gcc', '-c', '-mthumb', '-mcpu=cortex-m33',
                            '-mfpu=fpv5-sp-d16', '-mfloat-abi=hard', str(temp / 'marker.c'),
                            '-o', str(temp / 'marker.o')], check=True)
            subprocess.run([a.cross_compile + 'ar', 'rcsD', str(library), str(temp / 'marker.o')], check=True)
        metadata['version'] += '+dependency-test-only'
        metadata['artifacts'][libname] = sha(library)
        # Keep the synthetic local variant consistent with the blob contract.
        for blob in module['blobs']:
            blob['version'] = metadata['version']
            if 'zephyr/blobs/' + blob['path'] == libname:
                blob['sha256'] = metadata['artifacts'][libname]
                blob['size'] = library.stat().st_size
        module_path.write_text(yaml.safe_dump(module, sort_keys=False))
        manifest_path.write_text(json.dumps(metadata, indent=2, sort_keys=True) + '\n')
        lock.write_text(sha(manifest_path) + '\n')
        results['hal_update'] = run('hal-update')
        if results['hal_update']['bootstrap/adapter.elf'] == results['baseline']['bootstrap/adapter.elf']:
            raise ValueError('HAL release update did not propagate')
        data = bytearray(library.read_bytes())
        data[-1] ^= 1
        library.write_bytes(data)
        results['hal_corruption'] = run('hal-corruption', failure=True)
    finally:
        for path, data in originals.items():
            path.write_bytes(data)
        results['restored'] = run('restored', configure=True)
    if results['restored'] != results['baseline']:
        raise ValueError('restored source does not reproduce baseline artifacts')
    report = {'status': 'pass', 'changes_restored': True, 'results': results}
    (logs / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Incremental dependency verification passed; original inputs restored.')


if __name__ == '__main__':
    main()
