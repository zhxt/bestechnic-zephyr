#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""Declared build inputs and development source archives, independent of Git state."""
import fnmatch
import hashlib
import json
import os
from pathlib import Path, PurePosixPath


def relative_path(name):
    path = PurePosixPath(name)
    if not name or path.is_absolute() or '..' in path.parts or '\\' in name or path.as_posix() != name:
        raise ValueError(f'Invalid repository-relative path: {name}')
    return path


def policy(root):
    data = json.loads((Path(root) / 'scripts/project_files.json').read_text())
    if data.get('schema') != 1:
        raise ValueError('Unsupported project file policy')
    return data


def ignored(path, rules):
    return (bool(set(path.parts) & set(rules['ignored_directories'])) or
            any(fnmatch.fnmatchcase(part, pattern) for part in path.parts
                for pattern in rules['ignored_names']))


def checked_file(root, name):
    relative_path(name)
    path = root / name
    for parent in (path, *path.parents):
        if parent == root:
            break
        if parent.is_symlink():
            raise ValueError(f'Source symlinks are not supported: {name}')
    if not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError(f'Missing or external source file: {name}')
    return path


def select_files(root, scope='build'):
    root = Path(root).resolve()
    rules = policy(root)
    section = rules[scope]
    names = set(section['required'])
    for name in names:
        checked_file(root, name)
    for directory in section['directories']:
        relative_path(directory)
        start = root / directory
        if not start.is_dir() or start.is_symlink():
            raise ValueError(f'Missing or symlink source directory: {directory}')
        for folder, directories, files in os.walk(start, followlinks=False):
            directories[:] = [d for d in directories if not ignored((Path(folder) / d).relative_to(root), rules)]
            for name in directories:
                if (Path(folder) / name).is_symlink():
                    raise ValueError(f'Source directory symlink: {Path(folder) / name}')
            for filename in files:
                path = Path(folder) / filename
                rel = path.relative_to(root)
                if ignored(rel, rules):
                    continue
                if path.suffix in rules['source_suffixes'] or any(fnmatch.fnmatchcase(filename, p) for p in rules['source_names']):
                    names.add(rel.as_posix())
    if scope == 'archive':
        names.update(rules['binary_fixtures'])
    return {name: checked_file(root, name) for name in sorted(names)}


def file_hashes(root, scope='build'):
    return {name: hashlib.sha256(path.read_bytes()).hexdigest()
            for name, path in select_files(root, scope).items()}
