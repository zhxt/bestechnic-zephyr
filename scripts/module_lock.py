#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Check or regenerate the module lock from the project's west manifest."""
import argparse
import json
from pathlib import Path
import re
import subprocess

import yaml


def expected_lock(root):
    projects = yaml.safe_load((root / 'west.yml').read_text())['manifest']['projects']
    result = {}
    for project in projects:
        revision = str(project['revision'])
        if not re.fullmatch('[0-9a-f]{40}', revision):
            raise ValueError(f'Pin a full commit for {project["name"]}')
        if project['name'] in result:
            raise ValueError('Duplicate west project')
        result[project['name']] = revision
    return result


def check_lock(root):
    expected = expected_lock(root)
    if json.loads((root / 'module-lock.json').read_text()) != expected:
        raise ValueError('module-lock.json differs from west.yml; run scripts/module_lock.py --write')
    return expected


def check_modules(root, expected=None, *, allow_dirty=()):
    """Verify actual module checkouts both before compilation and packaging."""
    revisions = check_lock(root)
    if expected is not None and revisions != expected:
        raise ValueError('Module lock changed after configuration')
    projects = yaml.safe_load((root / 'west.yml').read_text())['manifest']['projects']
    for project in projects:
        name = project['name']
        relative = Path(project.get('path', name))
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Invalid module path: ' + name)
        path = root.parent / relative
        actual = subprocess.check_output(['git', '-C', str(path), 'rev-parse', 'HEAD'], text=True).strip()
        if actual != revisions[name]:
            raise ValueError('Module revision mismatch: ' + name)
        status = subprocess.check_output(['git', '-C', str(path), 'status', '--porcelain',
                                          '--untracked-files=all'], text=True)
        if status and name not in allow_dirty:
            raise ValueError('Module checkout is dirty: ' + name)
    return revisions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--write', action='store_true')
    args = parser.parse_args()
    if args.write:
        (args.root / 'module-lock.json').write_text(json.dumps(expected_lock(args.root), indent=2) + '\n')
    else:
        check_lock(args.root)
    print('Module lock matches west.yml')


if __name__ == '__main__':
    main()
