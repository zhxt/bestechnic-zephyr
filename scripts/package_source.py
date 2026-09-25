#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Package declared development files or verify and archive a clean Git commit."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile

from project_files import checked_file, select_files
from hal_blobs import FETCH_HINT, blob_metadata

HAL_METADATA = ('manifest.json', 'README.md', 'README.zh-CN.md', 'LICENSE', 'THIRD_PARTY_NOTICES.md',
                'distribution.json', '.gitignore', '.editorconfig', '.gitattributes',
                'CMakeLists.txt', 'Kconfig', 'cmake/import.cmake', 'zephyr/module.yml')


def repository_state(root):
    root = Path(root).resolve()
    # Do not accidentally use a containing workspace's repository.
    if not (root / '.git').exists():
        return {'revision': None, 'dirty': True}
    revision = subprocess.run(['git', '-C', str(root), 'rev-parse', '--verify', 'HEAD'],
                              capture_output=True, text=True)
    if revision.returncode:
        return {'revision': None, 'dirty': True}
    status = subprocess.check_output(['git', '-C', str(root), 'status', '--porcelain',
                                      '--untracked-files=all'], text=True)
    return {'revision': revision.stdout.strip(), 'dirty': bool(status)}


def require_clean(root, expected=None):
    state = repository_state(root)
    if not state['revision'] or state['dirty'] or (expected is not None and state != expected):
        raise ValueError(f'Formal packaging requires the unchanged clean commit: {root}')
    return state


def hal_files(root):
    root = Path(root).resolve()
    manifest = json.loads(checked_file(root, 'manifest.json').read_text())
    blobs = blob_metadata(root, manifest)
    for name in blobs:
        if not (root / name).is_file():
            raise ValueError(f'Missing HAL blob: {name}. {FETCH_HINT}')
    names = (set(HAL_METADATA) | set(manifest['artifacts'])
             | {entry['license-path'] for entry in blobs.values()})
    paths = {name: checked_file(root, name) for name in sorted(names)}
    for name, expected in manifest['artifacts'].items():
        if hashlib.sha256(paths[name].read_bytes()).hexdigest() != expected:
            hint = f'. {FETCH_HINT}' if name in blobs else ''
            raise ValueError(f'HAL artifact checksum mismatch: {name}{hint}')
    for name, entry in blobs.items():
        if 'size' in entry and paths[name].stat().st_size != entry['size']:
            raise ValueError(f'HAL blob size differs from module.yml: {name}')
    return paths


def snapshot(root, output, kind='integration', formal=False, expected_state=None):
    root, output = Path(root).resolve(), Path(output)
    paths = select_files(root, 'archive') if kind == 'integration' else hal_files(root)
    blobs = blob_metadata(root) if kind == 'hal' else {}
    state = require_clean(root, expected_state) if formal else repository_state(root)
    data = {name: path.read_bytes() for name, path in paths.items()}
    hashes = {name: hashlib.sha256(blob).hexdigest() for name, blob in data.items()}
    if formal:
        blob = subprocess.check_output(['git', '-C', str(root), 'archive', '--format=tar', state['revision']])
        with tarfile.open(fileobj=io.BytesIO(blob)) as archive:
            members = [m for m in archive.getmembers() if not m.isdir()]
            if (any(not m.isfile() for m in members)
                    or {m.name for m in members} != set(paths) - set(blobs)):
                raise ValueError('Committed archive differs from the declared package files')
            if any(archive.extractfile(m).read() != data[m.name] for m in members):
                raise ValueError('Committed source differs from the build checkout')
        require_clean(root, state)
    if not formal or kind == 'hal':
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w', format=tarfile.PAX_FORMAT) as archive:
            for name, blob in data.items():
                info = tarfile.TarInfo(name)
                info.size = len(blob)
                info.mode = 0o755 if name not in blobs and paths[name].stat().st_mode & 0o111 else 0o644
                info.mtime = info.uid = info.gid = 0
                archive.addfile(info, io.BytesIO(blob))
        blob = buffer.getvalue()
    current = select_files(root, 'archive') if kind == 'integration' else hal_files(root)
    if set(current) != set(data) or any(p.read_bytes() != data[n] for n, p in current.items()):
        raise ValueError('Source changed while creating the archive')
    if formal:
        require_clean(root, state)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(blob)
    return {'kind': 'formal' if formal else 'development', **state,
            'files': hashes, 'blobs': blobs,
            'archive_sha256': hashlib.sha256(blob).hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--kind', choices=('integration', 'hal'), default='integration')
    parser.add_argument('--formal', action='store_true')
    args = parser.parse_args()
    result = snapshot(args.root, args.output, args.kind, args.formal)
    args.output.with_suffix('.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(f'{result["kind"]} source archive: {len(result["files"])} files')


if __name__ == '__main__':
    main()
