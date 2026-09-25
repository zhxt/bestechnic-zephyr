#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Validate local repository boundaries; publication prerequisites are checked separately."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from urllib.parse import unquote, urlsplit

from module_lock import check_lock
from package_source import hal_files, repository_state
from project_files import ignored, policy, select_files


def check_links(root, paths):
    issues = []
    for name, path in paths.items():
        if path.suffix != '.md':
            continue
        for target in re.findall(r'\]\(([^\s)]+)(?:\s+[^)]*)?\)', path.read_text()):
            url = urlsplit(target.strip('<>'))
            if url.scheme or url.netloc or not url.path:
                continue
            destination = (path.parent / unquote(url.path)).resolve()
            if not destination.is_relative_to(root.resolve()) or not destination.exists():
                issues.append(f'{name}: missing or external document link: {target}')
    return issues


def check(root, hal, publication=False):
    root = root.resolve()
    paths = select_files(root, 'archive')
    inputs = select_files(root, 'build')
    rules = policy(root)
    issues = check_links(root, paths)
    if not set(inputs) <= set(paths):
        issues.append('Build inputs must also be included in the source archive')
    for path in root.rglob('*'):
        relative = path.relative_to(root)
        if ignored(relative, rules):
            continue
        if path.is_symlink():
            issues.append(f'Unapproved symlink: {relative}')
        elif path.is_file() and relative.as_posix() not in paths:
            issues.append(f'Undeclared repository file: {relative}')
    if (root / '.git').exists():
        tracked = subprocess.check_output(['git', '-C', str(root), 'ls-files', '-z']).decode().split('\0')
        for name in filter(None, tracked):
            if name not in paths:
                issues.append(f'Tracked file outside archive policy: {name}')
    for name, path in paths.items():
        if name in rules['binary_fixtures']:
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            issues.append(f'Undeclared binary content: {name}')
            continue
        if re.search(r'/(?:home|Users)/[A-Za-z0-9_.-]+/', text):
            issues.append(f'Personal absolute path: {name}')
        if re.search(r'-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----', text):
            issues.append(f'Private key content: {name}')
        if path.suffix in ('.c', '.h', '.S', '.py', '.cmake') or path.name == 'CMakeLists.txt':
            if 'SPDX-License-Identifier:' not in text[:1500]:
                issues.append(f'Missing source license identifier: {name}')
    check_lock(root)
    artifacts = {}
    try:
        artifacts = hal_files(hal)
        if hashlib.sha256((hal / 'manifest.json').read_bytes()).hexdigest() != (root / 'hal-release.sha256').read_text().strip():
            issues.append('HAL manifest.json SHA256 differs from hal-release.sha256')
    except (ValueError, OSError) as error:
        issues.append(str(error))
    if artifacts:
        for path in hal.rglob('*'):
            relative = path.relative_to(hal)
            if ignored(relative, rules):
                continue
            if path.is_symlink() or (path.is_file() and relative.as_posix() not in artifacts):
                issues.append(f'Undeclared HAL file: {relative}')
    pending = []
    blockers = []
    distribution = json.loads((hal / 'distribution.json').read_text())
    if distribution.get('public_redistribution') != 'confirmed' or not distribution.get('evidence'):
        pending.append('HAL public redistribution evidence is not confirmed')
    if not distribution.get('public_source_url'):
        pending.append('HAL public source/download location is not supplied')
    for label, repository in [('integration', root), ('HAL', hal)]:
        state = repository_state(repository)
        if not state['revision'] or state['dirty']:
            message = f'{label} requires a clean candidate commit'
            pending.append(message)
            blockers.append(message)
        origin = subprocess.run(['git', '-C', str(repository), 'remote', 'get-url', 'origin'],
                                capture_output=True, text=True)
        if origin.returncode or not origin.stdout.strip():
            message = f'{label} publishing remote is not configured'
            pending.append(message)
            blockers.append(message)
    if publication:
        issues.extend(blockers)
    return {'status': 'fail' if issues else 'pass', 'scope': 'publication' if publication else 'local',
            'archive_files': len(paths), 'build_inputs': len(inputs), 'hal_files': len(artifacts),
            'issues': issues, 'publication_pending': pending}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--hal', type=Path)
    parser.add_argument('--for-publication', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    report = check(args.root, args.hal or args.root.parent / 'modules/hal/bestechnic', args.for_publication)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    raise SystemExit(report['status'] != 'pass')


if __name__ == '__main__':
    main()
