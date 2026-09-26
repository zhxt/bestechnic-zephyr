#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Build twice with the parent workspace/SDK hidden and networking disabled.

Requires unprivileged bubblewrap namespaces. Sources, libraries, and the
selected toolchain are read-only; output and temporary caches are writable.
An optional reference build also checks reproducibility across toolchain paths.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--workspace', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--cross-compile', required=True)
    ap.add_argument('--sdk', type=Path, required=True, help='SDK directory to hide')
    ap.add_argument('--reference-build', type=Path,
                    help='Compare build identity and image with an existing native build')
    a = ap.parse_args()
    workspace, output, sdk = a.workspace.resolve(), a.output.resolve(), a.sdk.resolve()
    cross_prefix = Path(a.cross_compile).expanduser()
    if not cross_prefix.is_absolute() or not Path(str(cross_prefix) + 'gcc').is_file():
        raise ValueError('--cross-compile must be an absolute prefix of an installed toolchain')
    toolchain = cross_prefix.parent.parent.resolve()
    if (toolchain.is_relative_to(sdk) or sdk.is_relative_to(toolchain)
            or workspace.parent.is_relative_to(toolchain)):
        raise ValueError('toolchain must not contain or be contained by a hidden directory')
    isolated_cross = '/tmp/toolchain/bin/' + cross_prefix.name
    reference = None
    if a.reference_build:
        reference_dir = a.reference_build.resolve()
        reference_identity = json.loads((reference_dir / 'generated/identity.json').read_text())
        reference_image = reference_dir / 'zephyr.bin'
        reference = {'directory': str(reference_dir), 'bytes': reference_image.stat().st_size,
                     'sha256': hashlib.sha256(reference_image.read_bytes()).hexdigest()}
    if output.exists():
        raise ValueError('isolation output must be a fresh directory')
    if not workspace.is_relative_to(workspace.parent) or workspace == workspace.parent:
        raise ValueError('invalid workspace')
    # Bubblewrap needs existing mount points beneath the read-only source bind.
    # A fresh west workspace need not have run a build yet.
    (workspace / 'build').mkdir(exist_ok=True)
    (workspace / 'zephyr/.cache').mkdir(exist_ok=True)
    output.mkdir(parents=True)
    common = ['bwrap', '--die-with-parent', '--unshare-net', '--ro-bind', '/', '/',
              '--tmpfs', '/tmp', '--tmpfs', str(workspace.parent), '--tmpfs', str(sdk),
              '--ro-bind', str(workspace), '/tmp/workspace', '--tmpfs', '/tmp/workspace/build',
              '--tmpfs', '/tmp/workspace/zephyr/.cache',
              '--ro-bind', str(toolchain), '/tmp/toolchain', '--bind', str(output), '/tmp/out',
              '--proc', '/proc', '--dev', '/dev', '--chdir', '/tmp/workspace',
              '--setenv', 'ZEPHYR_BASE', '/tmp/workspace/zephyr',
              '--unsetenv', 'TOOLCHAIN_ROOT',
              '--setenv', 'CROSS_COMPILE', isolated_cross,
              '--setenv', 'XDG_CACHE_HOME', '/tmp/cache', '--setenv', 'CCACHE_DISABLE', '1',
              '--setenv', 'SOURCE_DATE_EPOCH', '0', '--setenv', 'PYTHONDONTWRITEBYTECODE', '1']
    results = []
    for run in ('first', 'second'):
        command = common + ['/tmp/workspace/.venv/bin/python', '-m', 'west', 'build', '--sysbuild',
            '-b', 'bes2700yp_devkit/bes2700yp/bth', 'bestechnic-zephyr/apps/bes2700yp/bth',
            '-d', '/tmp/out/' + run, '--', '-DZEPHYR_TOOLCHAIN_VARIANT=cross-compile',
            '-DCROSS_COMPILE=' + isolated_cross, '-DBES_VALIDATION_PROFILE=ipc-backpressure']
        with (output / (run + '.log')).open('w') as log:
            subprocess.run(command, check=True, stdout=log, stderr=subprocess.STDOUT,
                           env=dict(os.environ, CCACHE_DISABLE='1'))
        image = output / run / 'zephyr.bin'
        results.append({'run': run, 'bytes': image.stat().st_size,
                        'sha256': hashlib.sha256(image.read_bytes()).hexdigest()})
        print(results[-1], flush=True)
        if reference:
            identity = json.loads((output / run / 'generated/identity.json').read_text())
            if identity != reference_identity:
                raise ValueError('Reference and isolated builds have different inputs or profiles')
            if results[-1]['sha256'] != reference['sha256']:
                raise ValueError('Reference and isolated images are not bit-for-bit reproducible')
    if results[0]['sha256'] != results[1]['sha256']:
        raise ValueError('clean builds are not bit-for-bit reproducible')
    if reference and (json.loads((reference_dir / 'generated/identity.json').read_text()) != reference_identity
                      or hashlib.sha256(reference_image.read_bytes()).hexdigest() != reference['sha256']):
        raise ValueError('Reference build changed during isolation verification')
    report = {'status': 'pass', 'network': 'unshared', 'compiler_cache': 'disabled',
              'hidden': [str(workspace.parent), str(sdk), '/tmp/workspace/build'],
              'source_mount': 'read-only /tmp/workspace',
              'toolchain_mount': 'read-only /tmp/toolchain', 'results': results,
              'hardware_status': 'not_tested'}
    if reference:
        report['reference'] = reference
        report['reference_comparison'] = 'pass'
    (output / 'isolation-report.json').write_text(json.dumps(report, indent=2) + '\n')
    print('Isolated clean builds are reproducible; SDK and producer were unavailable.')


if __name__ == '__main__':
    main()
