#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Portable local/CI checks and fresh profile builds; no publishing or hardware access."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

from validation_profiles import PROFILES


def main():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument('--workspace', type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--profiles', nargs='*', choices=tuple(PROFILES), default=[])
    parser.add_argument('--cross-compile')
    parser.add_argument('--formal', action='store_true')
    args = parser.parse_args()
    workspace, output = args.workspace.resolve(), args.output.resolve()
    source = workspace / 'bestechnic-zephyr'
    if output.is_relative_to(source) or output.exists():
        parser.error('Use a fresh output directory outside the source repository')
    if args.profiles and not args.cross_compile:
        parser.error('--cross-compile is required when building packages')
    output.mkdir(parents=True)
    env = dict(os.environ, ZEPHYR_BASE=str(workspace / 'zephyr'), CCACHE_DISABLE='1',
               SOURCE_DATE_EPOCH='0', PYTHONDONTWRITEBYTECODE='1', CMAKE_BUILD_PARALLEL_LEVEL='4')
    report = {'status': 'running', 'checks': {}, 'artifacts': {}, 'hardware': 'not_tested'}

    def run(label, command):
        with (output / (label + '.log')).open('w') as stream:
            result = subprocess.run(command, cwd=workspace, env=env, stdout=stream, stderr=subprocess.STDOUT)
        report['checks'][label] = {'exit_code': result.returncode, 'log': label + '.log'}
        result.check_returncode()

    try:
        run('repository', [sys.executable, str(source / 'scripts/check_repo.py')])
        run('host', [sys.executable, str(source / 'scripts/test_host.py')])
        for profile_name in args.profiles:
            build = output / profile_name
            run(profile_name, [sys.executable, '-m', 'west', 'build', '--sysbuild',
                          '-b', 'bes2700yp_devkit/bes2700yp/bth', str(source / 'apps/bes2700yp/bth'),
                          '-d', str(build), '--', '-DZEPHYR_TOOLCHAIN_VARIANT=cross-compile',
                          '-DCROSS_COMPILE=' + args.cross_compile, '-DBES_VALIDATION_PROFILE=' + profile_name,
                          '-DBES_FORMAL_PACKAGE=' + ('ON' if args.formal else 'OFF')])
            release = build / 'release'
            for line in (release / 'SHA256SUMS').read_text().splitlines():
                digest, name = line.split(maxsplit=1)
                if hashlib.sha256((release / name).read_bytes()).hexdigest() != digest:
                    raise ValueError(f'Release checksum mismatch: {profile_name}/{name}')
            run(profile_name + '-resources', [sys.executable, str(source / 'scripts/check_resources.py'),
                '--release', str(release), '--zephyr-base', str(workspace / 'zephyr'),
                '--output', str(output / (profile_name + '-resources.json'))])
            image = release / 'zephyr.bin'
            report['artifacts'][profile_name] = {'bytes': image.stat().st_size,
                                            'sha256': hashlib.sha256(image.read_bytes()).hexdigest()}
        report['status'] = 'pass'
    except Exception as error:
        report['status'] = 'fail'
        report['error'] = str(error)
        raise
    finally:
        (output / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
